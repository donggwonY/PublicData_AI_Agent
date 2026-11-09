"""Read-only permit flows from the same snapshot used by the app."""
from __future__ import annotations
import pandas as pd

def summarize_permit_trends(stores: pd.DataFrame, reference_date, gu: str | None = None) -> dict:
    ref = pd.Timestamp(reference_date).normalize()
    start = ref - pd.Timedelta(days=365)
    f = stores.copy()
    if gu is not None:
        f = f[f['gu'].eq(gu)].copy()
    # 단기 행사 등록(다점포·30일 이내 폐업)은 개폐업 현황에서 뺀다(2026-11-09). 열이 없는 이전 버전은 그대로.
    short = f['short_event'].astype(bool) if 'short_event' in f.columns else pd.Series(False, index=f.index)
    excluded_short = int(short.sum())
    f = f[~short].copy()
    bad = f.ld.isna() | (f.closed & f.cd.isna()) | (f.cd < f.ld) | (~f.closed & f.cd.notna())
    excluded = int(bad.sum())
    f = f[~bad].copy()
    f['industry'] = f.service.fillna('업종 미상').replace({'의원': '의원·병원', '병원': '의원·병원'})
    f['active_permits'] = (f.ld.le(ref) & (f.cd.isna() | f.cd.gt(ref))).astype(int)
    f['opened'] = (f.ld.gt(start) & f.ld.le(ref)).astype(int)
    f['closure_reports'] = (f.closed & f.cd.gt(start) & f.cd.le(ref)).astype(int)
    previous_start = start - pd.Timedelta(days=365)
    f['previous_opened'] = (f.ld.gt(previous_start) & f.ld.le(start)).astype(int)
    f['previous_closure_reports'] = (f.closed & f.cd.gt(previous_start) & f.cd.le(start)).astype(int)
    counts = f.groupby('industry')[['active_permits', 'opened', 'closure_reports', 'previous_opened', 'previous_closure_reports']].sum()
    total = int(counts.active_permits.sum())
    counts['active_share_pct'] = counts.active_permits / total * 100 if total else 0.0
    counts = counts.reset_index().sort_values(['active_permits', 'industry'], ascending=[False, True])
    return {'reference_date': str(ref.date()), 'window_start_exclusive': str(start.date()),
            'previous_window_first_day': str((previous_start + pd.Timedelta(days=1)).date()),
            'previous_window_last_day': str(start.date()),
            'window_first_day': str((start + pd.Timedelta(days=1)).date()),
            'excluded_date_rows': excluded, 'excluded_short_event_rows': excluded_short, 'source_service_count': int(stores.service.nunique()),
            'analysis_group_count': int(stores.service.replace({'의원':'의원·병원','병원':'의원·병원'}).nunique()),
            'rows': counts.to_dict('records')}


def permit_trends_csv(result: dict, gu: str | None = None, industry: str | None = None) -> bytes:
    """Export exactly the selected scope, including dating and count definitions."""
    rows = pd.DataFrame(result['rows'])
    if industry is not None and not rows.empty:
        rows = rows[rows.industry.eq(industry)].copy()
    rows['reference_date'] = result['reference_date']
    rows['region'] = gu or '대구 전체'
    rows['current_period_start'] = result['window_first_day']
    rows['current_period_end'] = result['reference_date']
    rows['previous_period_start'] = result['previous_window_first_day']
    rows['previous_period_end'] = result['previous_window_last_day']
    rows['covered_source_industries'] = result['source_service_count']
    rows['covered_analysis_groups'] = result['analysis_group_count']
    rows['excluded_date_rows_region'] = result['excluded_date_rows']
    rows['definition'] = '인허가 기록 기준; 의원·병원 통합; 실제 점포수·사업실패·공실과 다름; 각 기간365일'
    # Treat source labels as text when opened in spreadsheet applications.
    for col in rows.select_dtypes(include=['object','string']).columns:
        rows[col] = rows[col].map(lambda value: "'"+value if isinstance(value,str) and value.startswith(('=','+','-','@','\t','\r','\n')) else value)
    return rows.to_csv(index=False).encode('utf-8-sig')
