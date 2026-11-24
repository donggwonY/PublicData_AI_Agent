"""Read-only D06 consultation adapter; no ranking or runtime training."""
from pathlib import Path
import importlib.util
import json
ROOT=Path(__file__).resolve().parents[2]
def get_franchise_outlook(brand: str) -> dict:
    source=ROOT/'scripts/d06_franchise_lookup.py'
    spec=importlib.util.spec_from_file_location('_d06_lookup',source)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    result=module.lookup_franchise(brand)
    if result.get('forecast'):
        base=ROOT/'docs/d06/delivery/revised'
        if result['forecast']['horizon_years']==2:
            metrics=json.loads((base/'permit_missing_latest/results.json').read_text(encoding='utf-8'))['metrics']
            result['evaluation']=[a for a in metrics if a['year']>=2024 and a['model']=='stale_plus_permits']
        else:
            result['evaluation']=json.loads((base/'rebuild_summary.json').read_text(encoding='utf-8'))['validation'][-2:]
        result['evaluation_scope']='과거'+' 자료의 회고적 평가이며 2025년은 잠정 자료임. 2026년 실제 결과 검증이 아님.'
    result['presentation_rules']=['과거 가맹점 수와 기준연도를 먼저 표시','확률은 상담 참고정보이며 성공·계약 추천이 아님','확률순 브랜드 정렬을 하지 않음','1년과 2년 전망을 혼합 비교하지 않음','업종 비교값은 같은 간격의 과거 관측 비율이며 2026년 실측값이 아님']
    return result
