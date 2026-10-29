import json
from pathlib import Path
import pandas as pd
from snapshot_hashes import snapshot_sha256
ROOT=Path(__file__).resolve().parents[1]
def main():
 folder=ROOT/'service/data/processed';out=ROOT/'docs/d04';out.mkdir(exist_ok=True)
 paths={n:folder/(n+'.parquet') for n in ['stores','legal_admin_map','area_context']}
 s,m,a=[pd.read_parquet(paths[n]) for n in paths]
 assert not m.duplicated(['gu','legal_dong']).any() and not a.duplicated(['gu','admin_dong']).any()
 j=s.merge(m[['gu','legal_dong','admin_dong']],left_on=['gu','dong'],right_on=['gu','legal_dong'],how='left',validate='many_to_one')
 j=j.merge(a[['gu','admin_dong']].assign(context_exists=True),on=['gu','admin_dong'],how='left',validate='many_to_one')
 assert len(j)==len(s);j['failed']=j.context_exists.isna();j['analysis_service']=j.service.replace({'의원':'의원+병원','병원':'의원+병원'})
 rows=[]
 for field in ['analysis_service','gu']:
  for key,g in j.groupby(field,dropna=False):rows.append({'field':field,'group':str(key),'n':len(g),'failed':int(g.failed.sum()),'failed_pct':float(g.failed.mean()*100)})
  assert sum(x['n'] for x in rows if x['field']==field)==len(s)
  assert sum(x['failed'] for x in rows if x['field']==field)==int(j.failed.sum())
 reasons={'missing_gu_or_dong':int((j.failed&(j.gu.isna()|j.dong.isna())).sum()),'no_mapping_with_keys':int((j.failed&j.gu.notna()&j.dong.notna()&j.admin_dong.isna()).sum()),'mapped_but_no_context':int((j.failed&j.admin_dong.notna()).sum())}
 assert sum(reasons.values())==int(j.failed.sum())
 result={'n':len(s),'failed':int(j.failed.sum()),'failed_pct':float(j.failed.mean()*100),'raw_services':s.service.nunique(),'analysis_services':j.analysis_service.nunique(),'reasons':reasons,'groups':rows,'hashes':{n:snapshot_sha256(p) for n,p in paths.items()},'script_hash':snapshot_sha256(Path(__file__))}
 (out/'links.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 lines=['# D-04 初回 연결 점검'.replace('初回','첫'),'','2026-10-29. 로컬 Parquet 점검이며 Supabase 직접 검증이 아니다. 의원·병원을 묶어15분석업종으로 표시. 미연결을 삭제하지 않았다.','',f"전체 {len(s):,}건 / 미연결 {int(j.failed.sum()):,}건 ({j.failed.mean()*100:.2f}%).",'',str(reasons),'','| 분류 | 집단 | 전체 | 미연결 | 비율% |','| --- | --- | ---: | ---: | ---: |']
 for x in rows:lines.append(f"| {x['field']} | {x['group']} | {x['n']} | {x['failed']} | {x['failed_pct']:.2f} |")
 lines+=['','연결단계의 실패 분류이며 원본 주소의 오류 원인을 확정한 것이 아니다. 다음은 실패가 많은 업종/지역의 원본 주소·법정동/행정동 매핑 확인. 기존7업종과의 증가 원인 분해 및DB대조는 미완료. 키유일성·다대일연결·행수보존·집단별합계·원인합계 검사통과.','', '재현: `python scripts/audit_d04_links.py`. [집계](links.json).']
 (out/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8');print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
