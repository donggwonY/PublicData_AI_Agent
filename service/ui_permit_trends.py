"""User-facing exploration of same-snapshot permit flows and comparable regions."""
import pandas as pd
import streamlit as st
import plotly.express as px
from core.permit_trends import summarize_permit_trends, permit_trends_csv, compare_industry_regions, compare_industry_dongs


def arrow(diff: int) -> str:
    """증감 화살표 방향. 변화값을 '이전 1년보다 …' 문장으로 넘기면 Streamlit 이 항상 ↑로 그리므로 부호로 직접 정한다."""
    return 'up' if diff > 0 else 'down' if diff < 0 else 'off'


def _bar(frame, x, y, key, color=None):
    fig=px.bar(frame,x=x,y=y,color=color,orientation='h',barmode='group',
        color_discrete_map={'개업':'#0f766e','폐업 신고':'#c2410c'},
        color_discrete_sequence=['#0f766e'],text_auto='.1f' if '%' in x else True)
    fig.update_layout(height=max(260,len(frame[y].unique())*48+90),
        margin=dict(l=0,r=30,t=25,b=10),legend=dict(orientation='h',y=1.15,title_text=''),
        paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)')
    fig.update_yaxes(title=None,autorange='reversed')
    fig.update_xaxes(gridcolor='rgba(128,128,128,.12)',rangemode='tozero')
    st.plotly_chart(fig,width='stretch',key=key)


def _remember(key):
    st.session_state["saved_"+key]=st.session_state[key]


def industry_choices(stores):
    """관심 업종 선택지. 사이드바 '내 관심 조건'과 업종 비교 화면이 같은 목록을 쓴다."""
    return ['전체 업종']+sorted(stores.service.dropna().replace({'의원':'의원·병원','병원':'의원·병원'}).unique())


def _sync_industry():
    """업종 비교에서 바꾼 관심 업종을 기억하고 사이드바 '내 관심 조건'에도 반영한다."""
    _remember('dash_trend_industry')
    st.session_state['fav_industry']=st.session_state['dash_trend_industry']


def render_permit_trends(stores, reference_date, gu=None, legal_admin=None):
    result=summarize_permit_trends(stores,reference_date,gu)
    rows=pd.DataFrame(result['rows'])
    choices=industry_choices(stores)
    if st.session_state.get('dash_trend_industry') not in choices:
        saved=st.session_state.get('saved_dash_trend_industry',choices[0])
        st.session_state['dash_trend_industry']=saved if saved in choices else choices[0]
    selected=st.selectbox('관심 업종',choices,key='dash_trend_industry',on_change=_sync_industry,help='업종을 선택하면 다른 구·군과 같은 조건으로 비교할 수 있어요.')
    if rows.empty:
        st.info('선택 지역에 집계 가능한 인허가 기록이 없습니다.')
        return
    shown=rows if selected==choices[0] else rows[rows.industry.eq(selected)]
    title=f"{gu or '대구 전체'} · {selected}"
    st.subheader(title)
    st.caption(f"최근 1년 {result['window_first_day']}~{result['reference_date']} · 인허가 기록 기준")
    active=int(shown.active_permits.sum());opened=int(shown.opened.sum());closed=int(shown.closure_reports.sum())
    previous_opened=int(shown.previous_opened.sum());previous_closed=int(shown.previous_closure_reports.sum())
    left,middle,right=st.columns(3)
    left.metric('영업 중인 인허가',f'{active:,}건',border=True)
    middle.metric('최근 1년 개업',f'{opened:,}건',f'이전 1년보다 {opened-previous_opened:+,}건',delta_color='off',
                  delta_arrow=arrow(opened-previous_opened),border=True)
    right.metric('최근 1년 폐업 신고',f'{closed:,}건',f'이전 1년보다 {closed-previous_closed:+,}건',delta_color='off',
                 delta_arrow=arrow(closed-previous_closed),border=True)
    st.caption('실제 고유 점포 수와 다를 수 있으며, 폐업 신고는 사업 실패를 뜻하지 않습니다.')
    if shown.empty:
        st.info('이 지역의 유효 자료에서는 해당 업종 기록을 찾지 못했어요. 다른 지역 비교는 아래에서 확인할 수 있어요.')
    with st.container(border=True):
        st.markdown('#### 최근 변화 한눈에')
        if len(shown)==1:
            trend=pd.DataFrame({'기간':['이전 1년','최근 1년']*2,'구분':['개업']*2+['폐업 신고']*2,
                                '인허가 기록(건)':[previous_opened,opened,previous_closed,closed]})
            _bar(trend,'인허가 기록(건)','기간','dash-permit-trends','구분')
        elif not shown.empty:
            chart=shown.head(10).melt(id_vars='industry',value_vars=['opened','closure_reports'],var_name='구분',value_name='인허가 기록(건)')
            chart['구분']=chart['구분'].replace({'opened':'개업','closure_reports':'폐업 신고'})
            _bar(chart,'인허가 기록(건)','industry','dash-permit-trends','구분')
            st.caption('현재 영업 인허가 수가 많은 상위 10개 업종입니다. 관심 업종을 선택하면 이전 1년과 직접 비교할 수 있어요.')
        else:
            st.caption('표시할 해당 업종 기록이 없습니다.')
    if selected!=choices[0]:
        from ui_forecast import render_closure_forecast
        render_closure_forecast(stores,selected,gu)
        with st.container(border=True):
            st.markdown('#### 지역별 비교')
            gu_tab,dong_tab=st.tabs(['구·군 비교','동·읍·면 비교'])
            with gu_tab:
                comparison=compare_industry_regions(stores,reference_date,selected)
                if not comparison.empty:
                    regions=comparison.region.tolist()
                    default=regions
                    if not default:default=regions[:3]
                    if 'dash_compare_regions' not in st.session_state:
                        st.session_state['dash_compare_regions']=st.session_state.get('saved_dash_compare_regions',default)
                    st.session_state['dash_compare_regions']=[r for r in st.session_state['dash_compare_regions'] if r in regions]
                    with st.expander(f"비교 지역 선택 · {len(st.session_state['dash_compare_regions'])}곳"):
                        picked=st.multiselect('비교할 구·군',regions,max_selections=9,key='dash_compare_regions',on_change=_remember,args=('dash_compare_regions',))
                    st.caption(f'{selected} · 선택한 구·군을 같은 기준으로 비교합니다.')
                    selected_rows=comparison[comparison.region.isin(picked)].copy()
                    labels={'region':'지역','active_permits':'영업 인허가(건)','active_share_pct':'지역 내 업종 비중(%)',
                            'opened':'최근 1년 개업(건)','closure_reports':'최근 1년 폐업 신고(건)',
                            'opened_change':'개업 증감(건)','closure_change':'폐업 신고 증감(건)'}
                    selected_rows=selected_rows.rename(columns=labels)
                    if selected_rows.empty:
                        st.info('비교할 지역을 한 곳 이상 선택해 주세요.')
                    else:
                        measure=_measure_picker('dash_compare_measure')
                        _comparison_chart(selected_rows,measure,'dash-region-comparison')
                        with st.expander('구·군별 상세 수치'):
                            st.dataframe(selected_rows[list(labels.values())],hide_index=True,width='stretch',
                                column_config={'지역 내 업종 비중(%)':st.column_config.NumberColumn(format='%.1f')})
                    with st.expander('구·군 비교 기준'):
                        st.caption('상단 요약은 선택 지역, 이 그래프는 비교 대상으로 선택한 구·군 기준입니다. 비중의 분모는 각 지역의 수록 업종 전체 영업 인허가입니다. 지역명 미연결은 제외하며 건수·비중은 수요나 창업 성공률을 뜻하지 않습니다.')
            with dong_tab:
                _render_dong_comparison(stores,reference_date,selected,gu,legal_admin)

    else:
        st.info('관심 업종을 선택하면 이전 1년 변화와 구·군별·동별 현황을 비교할 수 있어요.')
    with st.expander('상세 수치 · 다운로드 · 집계 기준'):
        table=shown.rename(columns={'industry':'업종','active_permits':'영업 인허가(건)','opened':'최근 1년 개업(건)',
            'closure_reports':'최근 1년 폐업 신고(건)','previous_opened':'이전 1년 개업(건)','previous_closure_reports':'이전 1년 폐업 신고(건)','active_share_pct':'지역 내 업종 비중(%)'})
        st.dataframe(table,hide_index=True,width='stretch')
        st.download_button('선택한 지역·업종 CSV',data=permit_trends_csv(result,gu,None if selected==choices[0] else selected),
            file_name=f"permit_trends_{result['reference_date']}.csv",mime='text/csv',key='dash_trend_download')
        st.caption(f"이전 1년: {result['previous_window_first_day']}~{result['previous_window_last_day']} · 두 기간 모두 365일입니다.")
        st.caption(f"원천 {result['source_service_count']}개 업종, 의원·병원을 묶어 {result['analysis_group_count']}개 그룹입니다. 전체 상업시설을 포괄하지 않습니다.")
        st.caption('개업과 폐업의 차이는 실제 공실이나 고유 점포 수 변화를 뜻하지 않습니다. 증감은 직전365일 대비 건수 차이입니다. 비중 분모가 없으면 값을 표시하지 않습니다.')
        st.caption(f"선택 지역 제외: 단기 행사·팝업 인허가 {result.get('excluded_short_event_rows',0):,}건 · 날짜 누락·모순 {result['excluded_date_rows']:,}건")


def _render_dong_comparison(stores,reference_date,industry,gu,legal_admin):
    regions=sorted(set(stores.gu.dropna()) & {'중구','동구','서구','남구','북구','수성구','달서구','달성군','군위군'})
    if not regions:
        st.info('비교할 구·군 자료가 없습니다.');return
    if gu in regions:
        chosen=gu
        st.markdown(f'**{chosen} · {industry}**')
    else:
        if st.session_state.get('dash_dong_compare_gu') not in regions:
            st.session_state['dash_dong_compare_gu']='중구' if '중구' in regions else regions[0]
        chosen=st.selectbox('어느 구·군의 동을 볼까요?',regions,key='dash_dong_compare_gu')
    st.caption('법정동 기준 · 동명이 연결되지 않은 기록은 제외됩니다.')
    result=compare_industry_dongs(stores,reference_date,industry,chosen,legal_admin)
    if not result['available']:
        st.info('동명 확인 자료가 없어 동 비교를 제공할 수 없습니다. 구·군 비교를 이용해 주세요.');return
    rows=pd.DataFrame(result['rows'])
    if rows.empty:
        st.info('이 구·군에서 동명을 확인할 수 있는 인허가 기록이 없습니다.');return
    names=rows.region.tolist();key='dash_dong_compare_names_'+chosen
    if key not in st.session_state:
        defaults=rows.sort_values(['active_permits','region'],ascending=[False,True]).head(3).region.tolist()
        st.session_state[key]=[x for x in st.session_state.get('saved_'+key,defaults) if x in names]
    picked=st.multiselect('비교할 동',names,max_selections=4,key=key,on_change=_remember,args=(key,),placeholder='동 이름 검색 · 최대 4곳',help='처음에는 해당 업종 영업 기록이 많은 최대 3곳을 표시합니다. 원하는 동으로 바꿀 수 있으며 추천 순위는 아닙니다.')
    table=rows[rows.region.isin(picked)].rename(columns={'region':'지역','active_permits':'영업 인허가(건)',
        'active_share_pct':'지역 내 업종 비중(%)','opened':'최근 1년 개업(건)','closure_reports':'최근 1년 폐업 신고(건)',
        'opened_change':'개업 증감(건)','closure_change':'폐업 신고 증감(건)'})
    if table.empty:
        st.info('비교할 동을 한 곳 이상 선택해 주세요.');return
    measure=_measure_picker('dash_dong_compare_measure')
    _comparison_chart(table,measure,'dash-dong-comparison')
    with st.expander('동별 상세 수치'):
        st.dataframe(table.drop(columns=['region_active_total']),hide_index=True,width='stretch',column_config={'지역 내 업종 비중(%)':st.column_config.NumberColumn(format='%.1f')})
    with st.expander('집계 기준 · 제외 기록'):
        st.caption(f"{chosen} 전체 원기록 {result['source_rows']:,}건 중 동명 연결 {result['source_rows']-result['unmatched_rows']:,}건, 미연결 {result['unmatched_rows']:,}건입니다. 이 수치는 선택 업종만의 건수가 아닙니다.")
        st.caption('보유 상가정보의 법정동명과 정확히 일치하는 인허가만 집계합니다. 행정동 인구 통계와 범위가 다르며, 명칭이 다른 기록을 임의로 합치지 않습니다. 동별 합계와 구·군 전체는 다를 수 있습니다.')
        st.caption('비중의 분모는 해당 동의 수록 업종 전체 영업 인허가입니다. 표본이 적으면 몇 건으로 수치가 크게 달라질 수 있고, 건수나 비중은 창업 성공률이 아닙니다.')


def _measure_picker(key):
    labels={'영업 인허가(건)':'영업 규모', '지역 내 업종 비중(%)':'업종 비중',
            '최근 1년 개업(건)':'최근 1년 개업', '최근 1년 폐업 신고(건)':'최근 1년 폐업 신고'}
    return st.selectbox('무엇을 비교할까요?',list(labels),format_func=labels.get,key=key)


def _comparison_chart(table,measure,key):
    plot=table[['지역',measure]].dropna()
    missing=table.loc[table[measure].isna(),'지역'].tolist()
    if plot.empty:
        st.info('선택한 지역의 전체 영업 인허가가 0건이어서 업종 비중을 계산할 수 없습니다. 다른 지역이나 비교 항목을 선택해 주세요.')
        return
    if missing:
        st.caption('비중 계산 불가: '+', '.join(missing)+' · 전체 영업 인허가가 0건인 지역은 그래프에서 제외했습니다.')
    if plot[measure].eq(0).all():
        messages={
            '영업 인허가(건)':'해당 업종의 영업 중인 인허가 기록이 없습니다.',
            '지역 내 업종 비중(%)':'해당 업종의 영업 중인 인허가 기록이 없습니다.',
            '최근 1년 개업(건)':'해당 업종의 최근 1년 개업 기록이 없습니다.',
            '최근 1년 폐업 신고(건)':'해당 업종의 최근 1년 폐업 신고 기록이 없습니다.'}
        st.info('집계 가능한 선택 지역에는 '+messages[measure]+' 다른 지역·업종이나 비교 항목을 선택해 주세요.')
        return
    _bar(plot,measure,'지역',key)
