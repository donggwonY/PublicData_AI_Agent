"""Audit active-record truncation and same-day boundary effects, without changing production."""
import ast
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from audit_d02_units import ROOT, DEMO


def main():
    data = DEMO / 'data/processed'
    manifest = json.loads((ROOT / 'docs/d01/manifest.json').read_text(encoding='utf-8'))
    for name, expected in manifest['sha256'].items():
        assert hashlib.sha256((data / name).read_bytes()).hexdigest() == expected, name
    source = DEMO / 'pipeline/build.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'max_concurrency')
    ns = {'pd': pd, 'np': np, 'DAY': pd.Timedelta(days=1)}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(source), 'exec'), ns)
    calc = ns['max_concurrency']
    st = pd.read_parquet(data / 'stores.parquet')
    units = pd.read_parquet(data / 'units.parquet').set_index('uid')
    ref = pd.Timestamp(manifest['reference_date'])
    def count_with_end(frame, ends):
        events = pd.concat([
            pd.DataFrame({'uid': frame.uid, 't': frame.ld, 'd': 1}),
            pd.DataFrame({'uid': frame.uid, 't': ends, 'd': -1})
        ]).sort_values(['uid', 't', 'd'])
        return events.assign(cum=events.groupby('uid').d.cumsum()).groupby('uid').cum.max()
    raw_end = st.cd.where(st.closed, ref + pd.Timedelta(days=1))
    minimum_end = raw_end.where(raw_end > st.ld, st.ld + pd.Timedelta(days=1))
    raw = calc(st, ref, 0).reindex(units.index)
    baseline = calc(st, ref, 60).reindex(units.index)
    assert raw.equals(units.max_concurrent_naive)
    assert baseline.equals(units.max_concurrent)
    min_day = count_with_end(st, minimum_end).reindex(units.index)
    adjusted_end = pd.Series(np.maximum(raw_end - pd.Timedelta(days=60), st.ld + pd.Timedelta(days=1)), index=st.index)
    # Isolate active-end shortening: keep closed intervals unchanged from production.
    keep_active = count_with_end(st, adjusted_end.where(st.closed, raw_end)).reindex(units.index)
    forward = raw.gt(1) & baseline.le(1)
    reverse = raw.le(1) & baseline.gt(1)
    suspicious = baseline.le(1) & units.n_active.gt(1)
    assert (min_day[reverse] > 1).all()
    assert (keep_active[suspicious] > 1).all()
    cases = []
    for name, records in [
        ('same_day_close', [('2020-01-01','2020-01-01',True)]),
        ('same_day_with_existing', [('2019-01-01',None,False),('2020-01-01','2020-01-01',True)]),
        ('closed_overlap_60', [('2019-01-01','2020-03-01',True),('2020-01-01',None,False)]),
        ('closed_overlap_61', [('2019-01-01','2020-03-02',True),('2020-01-01',None,False)]),
        ('two_active_recent', [('2020-01-01',None,False),('2026-09-01',None,False)]),
    ]:
        frame = pd.DataFrame(records, columns=['ld','cd','closed'])
        frame['uid'] = name
        frame['ld'] = pd.to_datetime(frame.ld)
        frame['cd'] = pd.to_datetime(frame.cd)
        cases.append({'case': name, 'days0': int(calc(frame,ref,0).iloc[0]), 'days60': int(calc(frame,ref,60).iloc[0])})
    expected = [(0,1),(1,2),(2,1),(2,2),(2,1)]
    assert [(c['days0'],c['days60']) for c in cases] == expected
    active = st[st.uid.isin(units.index[suspicious]) & ~st.closed].copy()
    active['days_since_open'] = (ref-active.ld).dt.days
    same_day_ids = set(st.loc[st.closed & st.ld.eq(st.cd),'uid'])
    counts = {
        'multi_to_single': int(forward.sum()), 'single_to_multi': int(reverse.sum()),
        'reverse_with_same_day_record': int(sum(uid in same_day_ids for uid in units.index[reverse])),
        'single_with_multiple_active': int(suspicious.sum()), 'active_records_in_these_units': len(active),
        'flagged_now_multi_when_active_end_preserved': int(keep_active[suspicious].gt(1).sum()),
        'all_single_to_multi_when_active_end_preserved': int((baseline.le(1) & keep_active.gt(1)).sum()),
        'reverse_now_multi_with_minimum_one_day_only': int(min_day[reverse].gt(1).sum()),
    }
    out = ROOT / 'docs/d02'
    payload = {'reference_date': str(ref.date()), 'input_hashes_verified':len(manifest['sha256']),
               'build_sha256':hashlib.sha256(source.read_bytes()).hexdigest(), 'counts':counts,'synthetic_cases':cases}
    (out/'boundary_audit.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines = ['# D-02 자리 판정 경계·실제 이력 점검', '', f'기준일 {ref.date()}. D-01 입력 14개 해시 일치. 기존 0일·60일 동시영업 수 재현.', '',
             '## 분류 변화 원인', '',
             f'- 0일 다점포 → 60일 단일: {counts["multi_to_single"]}곳.',
             f'- 0일 단일 → 60일 다점포: {counts["single_to_multi"]}곳. 이 중 당일 개업·폐업 기록이 있는 곳 {counts["reverse_with_same_day_record"]}곳.',
             f'- 겹침 허용 없이 당일 기록만 최소 1일로 처리해도 역방향 {counts["reverse_now_multi_with_minimum_one_day_only"]}곳이 모두 다점포가 된다. 0일과 60일 비교는 겹침 허용과 당일 기록 처리라는 두 효과가 섞여 있다.',
             '', '## 현재 영업 기록이 여러 개인 31곳', '',
             f'- 해당 {counts["single_with_multiple_active"]}곳의 영업 중 기록은 {len(active)}건이다. 아래 전수 목록은 인허가 기록 기준이며 실제 방문·영업 확인이 아니다.',
             f'- 폐업 기록의 60일 처리 방식은 유지하고 영업 중 기록의 종료만 기준일+1일로 보존하면 해당 {counts["flagged_now_multi_when_active_end_preserved"]}곳 모두 다점포로 바뀐다.',
             f'- 전체에서 이 실험으로 단일→다점포로 바뀌는 곳은 {counts["all_single_to_multi_when_active_end_preserved"]}곳이다.',
             '- 즉 영업 중 관측 구간까지 줄이는 구현이 이 분류에 영향을 준다는 것을 확인했다. 실제 양도양수인지, 신고 지연인지, 주소가 여러 점포를 묶었는지는 이 데이터만으로 확정할 수 없다.', '',
             '## 합성 경계 사례', '', '```text', pd.DataFrame(cases).to_string(index=False), '```', '',
             'days0/60은 최대 동시영업 수다. 단독 당일 개폐업의 0일 결과 0은 반개방 구간의 길이가 0이어서 발생한다. 이 규칙을 실제 점포가 없다는 뜻으로 해석하면 안 된다.', '',
             '## 현재 영업 기록 전수 목록', '', '```text', active[['uid','name','ld','days_since_open']].sort_values(['uid','ld']).to_string(index=False), '```', '',
             '## 역방향 변경 27곳의 당일 기록', '', '```text', st[st.uid.isin(units.index[reverse]) & st.closed & st.ld.eq(st.cd)][['uid','name','ld','cd']].sort_values(['uid','ld']).to_string(index=False), '```', '',
             '## 잠정 사용 제한과 다음 단계', '',
             '- is_single_unit만으로 물리적 단일 점포나 실제 양도양수를 확정하지 않는다. 현재 영업 다중 여부를 함께 표시한다.',
             '- 당일 개폐업 처리와 양도양수 허용 기간은 분리해서 정의한다. 영업 중 기록에 허용 기간을 적용할지도 별도로 결정한다.',
             '- 운영 코드를 수정하거나 31곳을 삭제하지 않았다. 이번 대안은 원인 분리를 위한 실험이다.',
             '- 다음은 폐업 상태·공실 후보 90일~3년·생존 코호트의 정의 검증이다. 자리·층 민감도와 전체 EDA도 남아 있다.', '',
             '재현: `python scripts/audit_d02_boundaries.py` (D-01과 같은 데이터·분석 패키지 사용).', '']
    (out/'boundary_audit.md').write_text('\n'.join(line.rstrip() for line in lines),encoding='utf-8')
    print(json.dumps(payload,ensure_ascii=False,indent=2))

if __name__ == '__main__':
    main()
