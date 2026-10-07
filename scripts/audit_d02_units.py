"""Read-only D-02 concurrency sensitivity using the demo's actual function."""
import ast
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT.parent / 'daegu_lifecycle_agent'

def main():
    source = DEMO / 'pipeline/build.py'
    data = DEMO / 'data/processed'
    manifest = json.loads((ROOT / 'docs/d01/manifest.json').read_text(encoding='utf-8'))
    for name, expected in manifest['sha256'].items():
        assert hashlib.sha256((data / name).read_bytes()).hexdigest() == expected, name
    st = pd.read_parquet(data / 'stores.parquet')
    units = pd.read_parquet(data / 'units.parquet').set_index('uid')
    ref = pd.Timestamp(manifest['reference_date'])
    # Extract the unchanged production function without loading unrelated API dependencies.
    tree = ast.parse(source.read_text(encoding='utf-8'))
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'max_concurrency')
    namespace = {'pd': pd, 'np': np, 'DAY': pd.Timedelta(days=1)}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), namespace)
    calculate = namespace['max_concurrency']
    results = {days: calculate(st, ref, days).reindex(units.index) for days in (0, 30, 60, 90)}
    assert results[0].equals(units['max_concurrent_naive']), '0-day baseline mismatch'
    assert results[60].equals(units['max_concurrent']), '60-day baseline mismatch'
    assert (results[60].le(1) == units['is_single_unit']).all()
    rows = []
    for days, counts in results.items():
        single = counts.le(1)
        rows.append({'tolerance_days': days, 'single_units': int(single.sum()),
                     'multi_units': int((~single).sum()),
                     'changed_from_60': int((single != units['is_single_unit']).sum()),
                     'single_but_multiple_active': int((single & units['n_active'].gt(1)).sum())})
    changed = results[0].gt(1) & results[60].le(1)
    sample_ids = units.index[changed][:5]
    examples = st[st.uid.isin(sample_ids)][['uid', 'name', 'ld', 'cd', 'closed']].sort_values(['uid', 'ld'])
    regional = pd.DataFrame({'gu': units.gu, 'changed': changed, 'single60': results[60].le(1)}).groupby('gu', dropna=False).agg(units=('changed', 'size'), changed=('changed', 'sum'), single60=('single60', 'sum'))
    regional['changed_pct'] = (100 * regional.changed / regional.units).round(2)
    output = ROOT / 'docs/d02'
    output.mkdir(exist_ok=True)
    payload = {'reference_date': str(ref.date()), 'source_commit': manifest['commit'],
               'build_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
               'input_hashes_verified': len(manifest['sha256']), 'unit_count': len(units),
               'baseline_checks_passed': 3, 'sensitivity': rows,
               'regions': json.loads(regional.reset_index().to_json(orient='records', force_ascii=False))}
    (output / 'unit_sensitivity.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    lines = ['# D-02 첫 점검: 자리 판정과 60일 허용', '',
             f'기준일: {ref.date()}. 입력은 D-01의 가공본이며 원본 데이터와 데모 코드는 수정하지 않았다.',
             f'입력 {len(manifest["sha256"])}개 해시 일치. 실제 max_concurrency 함수를 AST로 추출해 실행했다. 0일·60일 동시영업 수와 단일 자리 플래그를 기존 결과와 대조해 3개 검사 통과.', '',
             '| 허용 일수 | 단일 자리 | 다점포 자리 | 60일 대비 분류 변경 | 단일이나 현재 영업 기록 2개 이상 |',
             '| --- | --- | --- | --- | --- |']
    for r in rows:
        lines.append('| ' + ' | '.join(str(v) for v in r.values()) + ' |')
    lines += ['', '## 해석 범위', '',
              '- 위 숫자는 알고리즘의 분류 민감도이며 실제 양도양수·물리적 점포 수의 정답 검증은 아니다.',
              '- 60일은 종료일에서 일수를 빼는 방식이며, 영업 중인 기록의 관측 종료에도 적용된다. 현재 영업 기록이 여러 개인데 단일 자리로 분류되는 사례를 별도 검토해야 한다.',
              '- 0일 계산은 당일 개업·폐업 기록의 종료 이벤트를 시작보다 먼저 처리한다. 반면 양수 허용을 적용하면 최소 1일 길이를 보장하므로 0일과 양수 결과의 차이는 순수한 겹침 허용 효과만은 아니다.',
              '- 주소 정규화 함수의 모듈 설명은 층을 제외한다고 적혀 있지만 최종 build_address는 건물+층 및 80% 층 보충을 적용한다. 최종 실행 코드를 정의 근거로 삼는다.',
              '- 층 보충과 도로명→지번 최빈 매핑은 전체 기록을 이용한다. 과거 시점 예측에 그대로 사용하면 미래 정보 사용 가능성을 별도 검토해야 한다.',
              '', '## 지역별 0일 다점포 → 60일 단일 변경', '', '```text', regional.to_string(), '```', '',
              '## 표본 이력', '', '0일 다점포→60일 단일로 바뀐 uid 정렬 순서의 앞 5곳. 대표 표본이나 실제 양도양수 확인 사례가 아니다.', '', '```text', examples.to_string(index=False), '```', '',
              '## 남은 작업', '',
              '- 경계일 합성 사례와 실제 다중 영업 표본으로 판정 원인을 확인한다.',
              '- 주소·층·업종 별칭, 폐업 상태, 공실 90일~3년, 생존 2010년 코호트 정의를 추가 검증한다.',
              '- 구·동·업종·개업연도 EDA와 작은 집단·관측 기간·누락률을 정리한다.',
              '- 학생의 해석, 정의별 민감도 표, 사용 금지 조건과 키·기준일 전달 문서를 마무리한다.', '',
              '재현: `python scripts/audit_d02_units.py` (pandas·numpy·pyarrow 필요).', '']
    (output / 'unit_sensitivity.md').write_text('\n'.join(line.rstrip() for line in '\n'.join(lines).splitlines()) + '\n', encoding='utf-8')
    print(json.dumps(payload, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
