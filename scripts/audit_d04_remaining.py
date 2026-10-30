"""Describe remaining review rows without correcting production data."""
import json,re
from pathlib import Path
import pandas as pd
from audit_d04_address_evidence import tokens
from snapshot_hashes import snapshot_sha256,verify_snapshot_hash
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/d04'
def main():
 prior=json.loads((OUT/'linkage_preview.json').read_text(encoding='utf-8'));folder=ROOT/'service/data/processed'
 for n,digest in prior['hashes'].items():verify_snapshot_hash(folder/f'{n}.parquet',digest)
 op=ROOT/prior['local_overlay'];verify_snapshot_hash(op,prior['overlay_hash'])
 s=pd.read_parquet(folder/'stores.parquet');o=pd.read_parquet(op);m=pd.read_parquet(folder/'legal_admin_map.parquet');a=pd.read_parquet(folder/'area_context.parquet')
 key=['service','org_code','mgmt_no'];assert not s.duplicated(key).any() and not o.duplicated(key).any()
 f=s.merge(o[key+['method']],on=key,how='left',validate='one_to_one');assert len(f)==len(s);f=f[f.method.eq('unresolved')].copy();assert len(f)==490
 valid_gu=set(a.gu);legal=set(zip(m.gu,m.legal_dong));admin=set(zip(a.gu,a.admin_dong));known=legal|admin
 rows=[]
 for _,r in f.iterrows():
  if pd.isna(r.gu):reason='구군 누락'
  elif r.gu not in valid_gu:reason='구군 목록 불일치'
  elif pd.isna(r.dong):reason='동 추출값 누락'
  elif re.fullmatch(r'[가-힣]+[0-9]+가',str(r.dong)) and (r.gu,re.sub(r'([0-9]+가)$',r'동\1',r.dong)) in legal:reason='동 글자 생략 후보'
  elif re.fullmatch(r'[가-힣]+[0-9.]*[동읍면리]',str(r.dong)):reason='동읍면리 표기 있으나 연결표 미등재'
  else:reason='도로명 또는 복합 표기 등 추가검토'
  def present(x):return pd.notna(x) and bool(str(x).strip())
  ts=[tokens(r.road_addr_raw),tokens(r.jibun_addr_raw)]
  matches=sorted({d for g,d in known if g==r.gu and any(g in t and d in t for t in ts)})
  rows.append({'service':r.service,'reason':reason,'address_present':present(r.road_addr_raw) or present(r.jibun_addr_raw),'known_address_name_count':len(matches)})
 df=pd.DataFrame(rows);groups=df.groupby(['service','reason']).size().reset_index(name='n').to_dict('records');totals=df.reason.value_counts().to_dict();assert sum(totals.values())==490
 result={'n':490,'totals':totals,'groups':groups,'both_address_strings_absent':int((~df.address_present).sum()),'address_known_names':{str(k):int(v) for k,v in df.known_address_name_count.value_counts().items()},'hashes':prior['hashes'],'overlay_hash':snapshot_sha256(op),'script_hash':snapshot_sha256(Path(__file__))}
 (OUT/'remaining.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 lines=['# 残余490건 원인 후보 분류'.replace('残余','잔여'),'','2026-10-30. 검토용 연결 이후 잔여만 점검. 순서대로 상호배타적 분류했으며 원인 확정이나 자동수정 규칙이 아니다.','','| 분류 | 건수 |','| --- | ---: |']
 for k,v in totals.items():lines.append(f'| {k} | {v} |')
 lines += ['',f"도로명·지번 보존문자열 모두 없는 건수: {result['both_address_strings_absent']}.",f"주소 안에 동일구군의 알려진 동명이 나타나는 개수별 행수: {result['address_known_names']}.",'','동 추출값 누락은 원본주소가 없다는 뜻이 아니다. 노원3가→노원동3가 같은 후보는 현재법정동연결표에 보완형이 존재하는 경우만 세었다. 동읍면리 미등재에는 대현1/2동·성당1/2동·유가면·구지읍 등이 포함되며 옛이름/오기/연결표부족 중 무엇인지는 공식변경이력과주소검증전미확정이다. 도로명내동명/법정동명의우연한일치가능성이있어토큰후보만으로연결하지않는다.','','다음 권고: 보존주소가있는동추출누락과동글자생략후보를원주소대조로좁힌후검토표에서만시험. 옛행정구역추정은임의치환하지않는다. 실제원본CSV확보/경계검증/DB대조는아직미완료.','','복합키일대일·490재현·분류합계·입력/검토표해시검증통과. 원본/운영/DB변경없음. 재현:`python scripts/audit_d04_remaining.py`. [집계](remaining.json).']
 (OUT/'remaining.md').write_text('\n'.join(lines)+'\n',encoding='utf-8');print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
