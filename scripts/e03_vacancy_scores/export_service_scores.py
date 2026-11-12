"""E-03: 고정 점수표 → 앱용 service/data/processed/vacancy_scores.parquet (필요한 열만).

- 입력 파일 SHA-256 을 기록값과 대조하고, 데이터 기준일이 service/data/processed/meta.json 과 같은지 확인한다.
- 앱 parquet 모드에서만 읽힌다. 공개 앱(DB 모드)은 app 스키마에 이 표를 올리는 운영 반영 전까지 카드를 보이지 않는다.
실행: python scripts/e03_vacancy_scores/export_service_scores.py <점수표 parquet> <기대 SHA-256>
"""
import hashlib, json, os, sys
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROC = os.path.join(ROOT, 'service', 'data', 'processed')
path, expected = sys.argv[1], sys.argv[2]
sha = hashlib.sha256(open(path, 'rb').read()).hexdigest()
if sha != expected:
    sys.exit(f'파일 해시 불일치: {sha}')
s = pd.read_parquet(path)
ref = json.load(open(os.path.join(PROC, 'meta.json'), encoding='utf-8'))['reference_date']
if set(s.data_reference_date) != {ref}:
    sys.exit(f'점수 기준일 {set(s.data_reference_date)} ≠ 앱 데이터 기준일 {ref}')
out = s[['uid', 'vacant_days', 'vacant_band', 'p_fill_1y', 'thin_evidence', 'data_reference_date', 'generated',
         'model_version']].copy()
out['uid'] = out.uid.astype(str)
out['source_sha256'] = sha
out.to_parquet(os.path.join(PROC, 'vacancy_scores.parquet'), index=False)
print({'rows': len(out), 'reference_date': ref, 'generated': out.generated.iloc[0], 'model_version': out.model_version.iloc[0]})
