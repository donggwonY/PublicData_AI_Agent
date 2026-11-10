"""District/industry permit overview, without interpreting flows as vacancy."""
import pandas as pd
import streamlit as st
import plotly.express as px
from core.permit_trends import summarize_permit_trends, permit_trends_csv

def render_permit_trends(stores, reference_date, gu=None):
    st.subheader('최근 1년 업종별 개업·폐업 신고')
    result = summarize_permit_trends(stores, reference_date, gu)
    rows = pd.DataFrame(result['rows'])
    st.caption(f"자료 기준일 {result['reference_date']} · 집계기간 {result['window_first_day']}~{result['reference_date']} · 지역: {gu or '대구 전체'}")
    st.caption(f"수록 원천 업종 {result['source_service_count']}개, 의원·병원을 묶은 분석 그룹 {result['analysis_group_count']}개 기준입니다. 전체 상업시설을 포괄하지 않습니다.")
    if rows.empty:
        st.info('선택 지역에 집계 가능한 인허가 기록이 없습니다.')
        return
    choices = ['전체 업종'] + sorted(rows.industry.tolist())
    if st.session_state.get('dash_trend_industry') not in choices:
        st.session_state['dash_trend_industry'] = choices[0]
    selected = st.selectbox('개폐업 현황 업종', choices, key='dash_trend_industry')
    shown = rows if selected == choices[0] else rows[rows.industry.eq(selected)]
    left, middle, right = st.columns(3)
    left.metric('기록상 영업 인허가', f"{int(shown.active_permits.sum()):,}건", border=True)
    middle.metric('최근 1년 개업', f"{int(shown.opened.sum()):,}건", f"직전 365일 대비 {int(shown.opened.sum()-shown.previous_opened.sum()):+,}건", delta_color='off', border=True)
    right.metric('최근 1년 폐업 신고', f"{int(shown.closure_reports.sum()):,}건", f"직전 365일 대비 {int(shown.closure_reports.sum()-shown.previous_closure_reports.sum()):+,}건", delta_color='off', border=True)
    st.caption(f"비교기간 {result['previous_window_first_day']}~{result['previous_window_last_day']} · 두 기간 모두 365일입니다. 윤년에는 전년 같은 날짜 구간과 다를 수 있습니다.")
    st.caption('인허가 기록 건수이며 실제 고유 점포 수와 다를 수 있습니다. 폐업 신고에는 취소·말소 등이 포함되며, 개업과 폐업의 차이는 실제 공실이나 점포 수 증감을 뜻하지 않습니다.')
    chart_rows = shown.head(10)
    chart = chart_rows.melt(id_vars='industry', value_vars=['opened', 'closure_reports'], var_name='구분', value_name='건수')
    chart['구분'] = chart['구분'].replace({'opened': '개업', 'closure_reports': '폐업 신고'})
    fig = px.bar(chart, x='건수', y='industry', color='구분', orientation='h', barmode='group',
                 color_discrete_map={'개업': '#0f766e', '폐업 신고': '#ea580c'},
                 category_orders={'industry': chart_rows.industry.tolist()},
                 labels={'industry': '업종'})
    fig.update_layout(height=max(240, len(chart_rows) * 55 + 85),
                      margin=dict(l=0, r=16, t=15, b=0),
                      legend=dict(orientation='h', y=1.12, title_text=''),
                      paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    fig.update_xaxes(title_text='인허가 기록 (건)', separatethousands=True, gridcolor='rgba(128,128,128,0.15)')
    fig.update_yaxes(title_text=None)
    st.plotly_chart(fig, width='stretch', key='dash-permit-trends')
    if len(shown) > 10:
        st.caption('기록상 영업 인허가 수 상위 10개 업종입니다. 전체 결과는 아래 상세 표에서 확인하세요.')
    table = shown.rename(columns={'industry':'업종', 'active_permits':'기록상 영업 인허가(건)', 'opened':'최근 1년 개업(건)', 'closure_reports':'최근 1년 폐업 신고(건)', 'previous_opened':'직전 365일 개업(건)', 'previous_closure_reports':'직전 365일 폐업 신고(건)', 'active_share_pct':'선택 지역 내 영업 인허가 비중(%)'})
    with st.expander('업종별 상세 수치 보기', expanded=len(shown) == 1):
        st.dataframe(table, hide_index=True, width='stretch')
    st.download_button('선택 결과 CSV 다운로드', data=permit_trends_csv(result, gu, None if selected == choices[0] else selected), file_name=f"permit_trends_{result['reference_date']}.csv", mime='text/csv', key='dash_trend_download')
    if result.get('excluded_short_event_rows'):
        st.caption(f"백화점·마트 식품관 등 다점포 자리에서 30일 이내 폐업한 단기 행사·팝업 등록 {result['excluded_short_event_rows']:,}건은 이 집계에서 제외했습니다.")
    if result['excluded_date_rows']:
        st.caption(f"개업·폐업 날짜가 없거나 일관되지 않은 기록 {result['excluded_date_rows']:,}건은 이 집계에서 제외했습니다.")
