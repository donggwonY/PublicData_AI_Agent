"""E-05 실험 경로. 작업 폴더·보조 자료 폴더는 환경변수로 지정한다(저장소에 원본·중간 산출물을 두지 않음).

- E05_WORK: 작업 폴더. `input/`(고정 빌드 8개 파일 + 법정동 대응표)을 두고, 중간 parquet·결과 json이 여기에 생긴다.
- E05_AUX: 보조 자료 폴더. `subway/subway_monthly.csv`, `station/daegu_station_location.xlsx`,
  `population/pop_*.csv`, `sangga/sangga_daegu_YYYYMMDD.csv`.
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))


def _need(name):
    v = os.environ.get(name)
    if not v:
        raise SystemExit(f'{name} 환경변수가 필요합니다 (scripts/e05_vacancy/README.md 참고)')
    return v


VF = _need('E05_WORK')
IN = os.path.join(VF, 'input')
AUX = _need('E05_AUX')
# 법정동→행정동 대응표: 실험 당시 저장소 버전(커밋 3fea4ca)을 고정 입력에 둔다.
# service/data/processed 의 현재 파일은 637fc00에서 다시 만들어져 인구 변수 579건이 달라진다(2026-11-10 확인).
LMAP = os.path.join(IN, 'legal_admin_map.parquet')
SANGGA_MAP = os.path.join(REPO, 'docs', 'e05', 'sangga_category_map.csv')
