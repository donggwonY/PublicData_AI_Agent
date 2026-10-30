"""Post-cleaning date audit; not a raw completeness audit."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from snapshot_hashes import snapshot_sha256,verify_snapshot_hash
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/d04'
def main():
 p=ROOT/'service/data/processed/stores.parquet';meta_path=p.parent/'meta.json'
 prior=json.loads((OUT/'links.json').read_text(encoding='utf-8'));verify_snapshot_hash(p,prior['hashes']['stores'])
 s=pd.read_parquet(p);meta=json.loads(meta_path.read_text(encoding='utf-8'));ref=pd.Timestamp(meta['reference_date'])
 assert len(s)==225858 and not s.duplicated(['service','org_code','mgmt_no']).any()
 old={'일반음식점','휴게음식점','제과점영업','미용업','세탁업','노래연습장업','담배소매업'}
 rows=[]
 for service,g in s.groupby('service'):
  closed=g.closed.fillna(False);days=(g.cd-g.ld).dt.days;expected=(g.cd.where(closed,ref)-g.ld).dt.days.clip(lower=0)
  rows.append({'service':service,'new_service':service not in old,'n':len(g),'closed':int(closed.sum()),'missing_closed_flag':int(g.closed.isna().sum()),'missing_open_date':int(g.ld.isna().sum()),'closed_missing_date':int((closed&g.cd.isna()).sum()),'not_closed_with_date':int((~closed&g.cd.notna()).sum()),'close_before_open':int(g.cd.lt(g.ld).sum()),'open_after_reference':int(g.ld.gt(ref).sum()),'close_after_reference':int(g.cd.gt(ref).sum()),'same_day_closed':int((closed&days.eq(0)).sum()),'closed_within30_days':int((closed&days.between(0,30)).sum()),'duration_mismatch':int((~(g.dur_days.eq(expected)|(g.dur_days.isna()&expected.isna()))).sum())})
 assert sum(r['n'] for r in rows)==len(s)
 result={'scope':'post-cleaning stores only; status code and date fallback provenance unavailable','reference_date':str(ref.date()),'rows':rows,'recorded_build_quality':{k:meta['quality'].get(k) for k in ['raw_rows','duplicates_removed','missing_license_date','license_date_before_1960','closed_without_close_date','date_contradiction','non_daegu_address']},'hashes':{'stores':snapshot_sha256(p),'meta':snapshot_sha256(meta_path),'current_build_script':snapshot_sha256(ROOT/'service/pipeline/build.py'),'script':snapshot_sha256(Path(__file__))}}
 (OUT/'date_quality.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 lines=['# 인허가 종료표시·날짜 품질 점검','','2026-10-30. 현재가공본만검사한결과로원본상태코드의정확성/누락률을입증하지않는다. 기준일 '+str(ref.date())+'.','','| 업종 | 새 업종 | 행수 | 종료표시 | 비종료+종료일 | 기준후허가 | 기준후종료 | 당일종료 | 30일내종료 |','| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
 for r in rows:lines.append(f"| {r['service']} | {r['new_service']} | {r['n']} | {r['closed']} | {r['not_closed_with_date']} | {r['open_after_reference']} | {r['close_after_reference']} | {r['same_day_closed']} | {r['closed_within30_days']} |")
 lines+=['','## 해석','','현재build코드는폐업일을우선사용하고없으면인허가취소일을사용한다. 영업상태명에폐업/취소/말소가있으면closed=True이다. 이불리언은정리된종료표시이며실제사업실패가아니다. 원본날짜출처와상세상태를stores에보존하지않아업종별취소일대체비중은계산할수없다. 현재코드와가공본생성당시코드의동일성까지입증한것은아니다.','','가공전품질기록(meta): '+str(result['recorded_build_quality']), '','현재build코드는폐업표시인데종료일이없거나날짜역전이있는행을제외한다. 가공본에서그문제가0이라고원본에도없었다고해석하면안된다. 제외집계는중복될수있으므로단순합계로탈락행수를계산하지않는다. 업종별탈락수와원인대조는원본확보후별도검증대상이다. 당일/30일내종료는행사성영업등이포함될수있는검토지표이지자동삭제조건이아니다.','','## 검증','','225858행·복합키·업종합계·입력해시검증. 날짜역전/누락/기준일이후/계산기간차이는JSON에각각보존. 운영/DB/원본수정없음. 재현:`python scripts/audit_d04_dates.py`. [전체결과](date_quality.json).']
 (OUT/'date_quality.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
 totals={k:sum(r[k] for r in rows) for k in rows[0] if k not in ['service','new_service']};print(json.dumps({'totals':totals,'new_service_rows':[r for r in rows if r['new_service']],'build_quality':result['recorded_build_quality']},ensure_ascii=False))
if __name__=='__main__':main()
