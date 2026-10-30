"""Audit preserved address strings; do not claim independent raw verification."""
import json,re
from pathlib import Path
import pandas as pd
from snapshot_hashes import snapshot_sha256,verify_snapshot_hash
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/d04'
def tokens(value):return set(re.findall(r'[가-힣]+[0-9]+(?:\.[0-9]+)+동|[가-힣0-9]+',str(value))) if pd.notna(value) else set()
def main():
 prior=json.loads((OUT/'links.json').read_text(encoding='utf-8'));paths={n:ROOT/'service/data/processed'/f'{n}.parquet' for n in ['stores','legal_admin_map','area_context']}
 for n,p in paths.items():verify_snapshot_hash(p,prior['hashes'][n])
 s,m,a=[pd.read_parquet(paths[n]) for n in paths]
 assert not m.duplicated(['gu','legal_dong']).any() and not a.duplicated(['gu','admin_dong']).any()
 j=s.merge(m[['gu','legal_dong','admin_dong']],left_on=['gu','dong'],right_on=['gu','legal_dong'],how='left',validate='many_to_one');assert len(j)==len(s)
 keys=set(zip(a.gu,a.admin_dong));candidate=j[j.admin_dong.isna()&pd.Series([(g,d) in keys for g,d in zip(j.gu,j.dong)],index=j.index)].copy();assert len(candidate)==2518
 statuses=[]
 for _,row in candidate.iterrows():
  jt,rt=tokens(row.jibun_addr_raw),tokens(row.road_addr_raw)
  def supports(t):return row.gu in t and row.dong in t
  direct=supports(jt) or supports(rt)
  alternatives={(g,d) for g,d in keys if g==row.gu and d!=row.dong and (supports(set()) or (g in jt and d in jt) or (g in rt and d in rt))}
  statuses.append('conflicting_admin_names' if alternatives else ('exact_address_support' if direct else 'no_exact_address_support'))
 candidate['evidence']=statuses
 rows=[]
 for (service,status),g in candidate.groupby(['service','evidence']):rows.append({'service':service,'status':status,'n':len(g)})
 totals=candidate.evidence.value_counts().to_dict();assert sum(totals.values())==2518
 assert '대명2동' not in tokens('대명12동');assert '남구' not in tokens('님구')
 assert '내당2.3동' in tokens('대구광역시 서구 내당2.3동 899-6번지')
 assert '내당2동' not in tokens('내당2.3동') and '신천1.2동' in tokens('(신천1.2동)')
 assert '비산2.3동' not in tokens('비산12.3동')
 result={'candidate_n':2518,'totals':totals,'groups':rows,'limitations':['preserved source strings, not independent raw CSV comparison','current admin name agreement does not validate historical boundaries','no source/DB/production edits'],'hashes':{n:snapshot_sha256(p) for n,p in paths.items()},'script_hash':snapshot_sha256(Path(__file__))}
 (OUT/'address_evidence.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 lines=['# 행정동 후보의 보존 주소 대조','','2026-10-30. 확인한 로컬폴더에서 대상4업종 원본CSV를 찾지 못해 stores의 road_addr_raw/jibun_addr_raw만 대조했다. 독립 원본파일 검증이 아니다.','',str(totals),'','| 업종 | 구분 | 건수 |','| --- | --- | ---: |']
 for r in rows:lines.append(f"| {r['service']} | {r['status']} | {r['n']} |")
 lines+=['','exact_address_support: 같은 주소 문자열 안에 구군과 후보행정동이 토큰 단위로 일치하고 다른 현재행정동 토큰은 없음. conflicting_admin_names: 동일 구군의 다른현재행정동토큰도있어검토필요. no_exact_address_support: 정확문자열근거부족. 이 검사는 철자·표기차이/과거행정구역을 해결하지 않는다.','','행정동표기와법정동입력혼입 가능성을 확인하는 자료이며,현재경계소속·과거소속·대표행정동매핑의정확성을 증명하지 않는다. 자동연결/삭제/운영DB수정없음. 다음은 근거충분후보의현재맥락조회용보정정책과충돌/불일치별주소점검이다. 역사적모델입력은별도검증해야한다.','','입력해시/키유일성/다대일연결/행수/후보2518재현/집계합계/부분문자열오탐방지검사통과. 재현:`python scripts/audit_d04_address_evidence.py`. [결과](address_evidence.json).']
 (OUT/'address_evidence.md').write_text('\n'.join(lines)+'\n',encoding='utf-8');print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
