"""Evidence tiers for 315 unresolved rows, no automatic corrections."""
import json,re
from pathlib import Path
import pandas as pd
from audit_d04_address_evidence import tokens
from snapshot_hashes import snapshot_sha256,verify_snapshot_hash
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/d04'
def main():
 prior=json.loads((OUT/'linkage_preview.json').read_text(encoding='utf-8'));folder=ROOT/'service/data/processed'
 for n,h in prior['hashes'].items():verify_snapshot_hash(folder/f'{n}.parquet',h)
 verify_snapshot_hash(ROOT/prior['local_overlay'],prior['overlay_hash'])
 s=pd.read_parquet(folder/'stores.parquet');o=pd.read_parquet(ROOT/prior['local_overlay']);m=pd.read_parquet(folder/'legal_admin_map.parquet');a=pd.read_parquet(folder/'area_context.parquet')
 key=['service','org_code','mgmt_no'];j=s.merge(o[key+['method']],on=key,validate='one_to_one');f=j[j.method.eq('unresolved')]
 lm={(r.gu,r.legal_dong):r.admin_dong for r in m.itertuples()};ak=set(zip(a.gu,a.admin_dong));known=set(lm)|ak
 rows=[]
 for _,r in f.iterrows():
  if pd.notna(r.gu) and pd.isna(r.dong):kind='missing_dong';expected=None
  elif pd.notna(r.dong) and re.fullmatch(r'[가-힣]+[0-9]+가',r.dong) and (r.gu,re.sub(r'([0-9]+가)$',r'동\1',r.dong)) in lm:kind='omitted_dong';expected=re.sub(r'([0-9]+가)$',r'동\1',r.dong)
  else:continue
  ts=[tokens(r.road_addr_raw),tokens(r.jibun_addr_raw)]
  names={d for g,d in known if g==r.gu and any(g in t and d in t for t in ts)}
  targets=set()
  for name in names:
   if (r.gu,name) in ak:targets.add(name)
   if (r.gu,name) in lm and (r.gu,lm[(r.gu,name)]) in ak:targets.add(lm[(r.gu,name)])
  if kind=='omitted_dong':
   status='normalized_name_address_supported' if expected in names and targets=={lm[(r.gu,expected)]} else ('normalization_only_no_address_support' if not names else 'conflict_or_review')
  else:status='unique_address_target_candidate' if len(targets)==1 else ('multiple_address_targets' if len(targets)>1 else 'no_known_address_target')
  address_positions=[]
  for value in [r.jibun_addr_raw,r.road_addr_raw]:
   if pd.isna(value):continue
   text=str(value)
   match=re.search(r'(?:^|\s)'+re.escape(str(r.gu))+r'\s+([^\s,()]+)',text)
   if match:address_positions.append(match.group(1))
   for bracket in re.findall(r'\(([^)]*)\)',text):
    address_positions.append(re.split(r'[,\s]',bracket.strip())[0])
  supported=names & set(address_positions)
  shares=[float(x.share) for x in m.itertuples() if x.gu==r.gu and x.legal_dong in names]
  rows.append({'position_supported':bool(supported),'mapping_share_below_one':any(x<1 for x in shares),'service':r.service,'kind':kind,'status':status,'address_name_count':len(names),'target_count':len(targets)})
 df=pd.DataFrame(rows);assert len(df)==315 and int(df.kind.eq('missing_dong').sum())==261 and int(df.kind.eq('omitted_dong').sum())==54
 counts=df.groupby(['kind','status']).size().reset_index(name='n').to_dict('records');assert sum(x['n'] for x in counts)==315
 selected=df[df.status.isin(['unique_address_target_candidate','normalized_name_address_supported'])]
 assert len(selected)==193
 position_summary=selected.groupby(['position_supported','mapping_share_below_one']).size().reset_index(name='n').to_dict('records')
 result={'position_summary':position_summary,'n':315,'counts':counts,'groups':df.groupby(['service','kind','status']).size().reset_index(name='n').to_dict('records'),'hashes':prior['hashes'],'script_hash':snapshot_sha256(Path(__file__))}
 (OUT/'recovery_candidates.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 lines=['# 동 추출 누락·생략 후보 대조','','2026-10-30. 보존된주소/현재대표매핑기반의추가후보분류. 원본CSV/지리경계확인이아니며 검토표나운영데이터에연결추가하지않았다.','','| 대상 | 근거 구분 | n |','| --- | --- | ---: |']
 for x in counts:lines.append(f"| {x['kind']} | {x['status']} | {x['n']} |")
 lines+=['','## 193후보 위치/대표성 점검','',str(position_summary),'','position_supported는구군다음주소성분또는괄호첫성분에일치동명이있는지검사한다. 이것도현재/과거경계확인은아니다. share<1은상가표본에서동일법정동의행정동표기가여럿이었다는뜻이며,share=1도전체경계일치를보장하지않는다.','','unique_address_target_candidate는주소내구군과알려진동토큰으로가능한대표행정동이하나인경우다. 행정동과법정동동명충돌은양쪽후보를검토했다. 대표매핑은상가정보에서구한대표값이므로한법정동이여러행정동에걸치는경계정확성을보장하지않는다.','','normalized_name_address_supported는노원3가→노원동3가같이보완한이름이보존주소에도있고대상행정동이일치하는경우다. normalization_only는보완형이연결표에는있으나주소에그이름이없어추가확인이필요하다. 누락동의0후보는주소없음과다르다.','','현재2,518직접행정동후보와근거수준이다르므로합쳐서확정복구로발표하지않는다. 다음은단일대상후보도지번/도로명위치에서추출된값인지확인하고다대행정동법정동의경계불확실성을따로표시하는것이다. 과거동명소속은별도검증.','','315/261/54표본·합계·복합키·해시검증통과. 재현:`python scripts/audit_d04_recovery_candidates.py`. [집계](recovery_candidates.json).']
 (OUT/'recovery_candidates.md').write_text('\n'.join(lines)+'\n',encoding='utf-8');print(json.dumps({'counts':counts,'position_summary':position_summary},ensure_ascii=False))
if __name__=='__main__':main()
