"""User-facing exploration of same-snapshot permit flows and comparable regions."""
import pandas as pd
import streamlit as st
import plotly.express as px
from core.permit_trends import summarize_permit_trends, permit_trends_csv, compare_industry_regions


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


def render_permit_trends(stores, reference_date, gu=None):
    result=summarize_permit_trends(stores,reference_date,gu)
    rows=pd.DataFrame(result['rows'])
    choices=['전체 업종']+sorted(stores.service.dropna().replace({'의원':'의원·병원','병원':'의원·병원'}).unique())
    if st.session_state.get('dash_trend_industry') not in choices:
        saved=st.session_state.get('saved_dash_trend_industry',choices[0])
        st.session_state['dash_trend_industry']=saved if saved in choices else choices[0]
    selected=st.selectbox('관심 업종',choices,key='dash_trend_industry',on_change=_remember,args=('dash_trend_industry',),help='업종을 선택하면 다른 구·군과 같은 조건으로 비교할 수 있어요.')
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
        with st.container(border=True):
            st.markdown('#### 어디를 함께 살펴볼까요?')
            comparison=compare_industry_regions(stores,reference_date,selected)
            if not comparison.empty:
                regions=comparison.region.tolist()
                default=([gu] if gu in regions else [])+[r for r in ['중구','수성구','달서구'] if r in regions and r!=gu]
                if not default:default=regions[:3]
                if 'dash_compare_regions' not in st.session_state:
                    st.session_state['dash_compare_regions']=st.session_state.get('saved_dash_compare_regions',default[:3])
                st.session_state['dash_compare_regions']=[r for r in st.session_state['dash_compare_regions'] if r in regions]
                picked=st.multiselect('비교할 지역 (최대 4곳)',regions,max_selections=4,key='dash_compare_regions',on_change=_remember,args=('dash_compare_regions',))
                st.caption('이 비교표는 위 지역 선택과 별개로 선택한 구·군을 보여줍니다. 지역명 누락·오기는 제외합니다.')
                selected_rows=comparison[comparison.region.isin(picked)].copy()
                labels={'region':'지역','active_permits':'영업 인허가(건)','active_share_pct':'지역 내 업종 비중(%)',
                        'opened':'최근 1년 개업(건)','closure_reports':'최근 1년 폐업 신고(건)',
                        'opened_change':'개업 증감(건)','closure_change':'폐업 신고 증감(건)'}
                selected_rows=selected_rows.rename(columns=labels)
                if selected_rows.empty:
                    st.info('비교할 지역을 한 곳 이상 선택해 주세요.')
                else:
                    measure=st.radio('비교 기준',['영업 인허가(건)','지역 내 업종 비중(%)','최근 1년 개업(건)','최근 1년 폐업 신고(건)'],horizontal=True,key='dash_compare_measure')
                    plot=selected_rows[['지역',measure]].dropna()
                    if plot.empty:st.info('비중을 계산할 영업 기록이 없습니다.')
                    else:_bar(plot,measure,'지역','dash-region-comparison')
                    st.dataframe(selected_rows[list(labels.values())],hide_index=True,width='stretch',
                        column_config={'지역 내 업종 비중(%)':st.column_config.NumberColumn(format='%.1f')})
                st.caption('비중은 지역 내 수록 업종 전체 영업 인허가 중 해당 업종의 비율입니다. 건수는 상권 규모에 영향을 받으며, 비중도 수요·수익성·창업 성공률을 뜻하지 않습니다.')
                st.caption('다음 확인: ‘동네·자리’에서 인구·집객시설을 살펴보고, ‘자리 이력’에서 관심 자리의 과거 이력을 확인하세요.')
    else:
        st.info('관심 업종을 선택하면 이전 1년 변화와 최대 4개 지역을 비교할 수 있어요.')
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
