"""Create a local review-only linkage overlay, never edit processed tables."""
import json
from pathlib import Path
import pandas as pd
from audit_d04_address_evidence import tokens
from snapshot_hashes import snapshot_sha256,verify_snapshot_hash
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/d04'
def allowed(gu,dong,road,jibun,keys):
 if pd.isna(gu) or pd.isna(dong) or (gu,dong) not in keys:return False
 ts=[tokens(road),tokens(jibun)]
 if not any(gu in t and dong in t for t in ts):return False
 return not any(g==gu and d!=dong and any(g in t and d in t for t in ts) for g,d in keys)
def main():
 keys={('남구','대명2동'),('남구','대명3동'),('서구','내당2.3동')}
 assert allowed('서구','내당2.3동',None,'대구광역시 서구 내당2.3동 10',keys)
 assert not allowed('남구','대명2동',None,'대구광역시 남구 대명12동 10',keys)
 assert not allowed('남구','대명2동','남구 대명3동','남구 대명2동',keys)
 assert not allowed('남구','대명2동',None,'서구 대명2동',keys)
 prior=json.loads((OUT/'links.json').read_text(encoding='utf-8'))
 paths={n:ROOT/'service/data/processed'/f'{n}.parquet' for n in ['stores','legal_admin_map','area_context']}
 for n,p in paths.items():verify_snapshot_hash(p,prior['hashes'][n])
 s,m,a=[pd.read_parquet(paths[n]) for n in paths]
 assert not s.duplicated(['service','org_code','mgmt_no']).any() and not m.duplicated(['gu','legal_dong']).any() and not a.duplicated(['gu','admin_dong']).any()
 j=s.merge(m[['gu','legal_dong','admin_dong']],left_on=['gu','dong'],right_on=['gu','legal_dong'],how='left',validate='many_to_one',sort=False)
 keys=set(zip(a.gu,a.admin_dong));old=pd.Series([(g,d) in keys for g,d in zip(j.gu,j.admin_dong)],index=j.index)
 overlay=j[['service','org_code','mgmt_no','uid','gu','dong','admin_dong']].rename(columns={'admin_dong':'original_admin_dong'}).copy()
 overlay['review_admin_dong']=overlay.original_admin_dong;overlay['method']='unresolved';overlay.loc[old,'method']='existing_legal_map'
 candidates=~old&pd.Series([(g,d) in keys for g,d in zip(j.gu,j.dong)],index=j.index)
 accepted=[idx for idx,row in j[candidates].iterrows() if allowed(row.gu,row.dong,row.road_addr_raw,row.jibun_addr_raw,keys)]
 overlay.loc[accepted,'review_admin_dong']=j.loc[accepted,'dong']
 overlay.loc[accepted,'method']='direct_admin_address_candidate'
 new=pd.Series([(g,d) in keys for g,d in zip(overlay.gu,overlay.review_admin_dong)],index=j.index)
 assert len(overlay)==len(s) and not overlay.duplicated(['service','org_code','mgmt_no']).any() and overlay.uid.tolist()==s.uid.tolist()
 assert overlay.loc[old,'review_admin_dong'].equals(overlay.loc[old,'original_admin_dong'])
 assert not (old&~new).any();assert int((~old).sum())==3008 and int((new&~old).sum())==2518 and int((~new).sum())==490
 checked=overlay.merge(a[['gu','admin_dong']],left_on=['gu','review_admin_dong'],right_on=['gu','admin_dong'],how='left',validate='many_to_one');assert len(checked)==len(s)
 local=ROOT/'data/raw/d04_review';local.mkdir(parents=True,exist_ok=True);overlay.to_parquet(local/'linkage_preview.parquet',index=False)
 rows=[]
 for service,g in j.assign(before_failed=~old,after_failed=~new).groupby('service'):
  rows.append({'service':service,'n':len(g),'before_failed':int(g.before_failed.sum()),'after_failed':int(g.after_failed.sum())})
 assert sum(x['after_failed'] for x in rows)==490
 for n,p in paths.items():verify_snapshot_hash(p,prior['hashes'][n])
 result={'n':len(s),'before_failed':3008,'candidate_connections':2518,'after_failed':490,'after_failed_pct':490/len(s)*100,'methods':overlay.method.value_counts().to_dict(),'groups':rows,'review_only':True,'local_overlay':'data/raw/d04_review/linkage_preview.parquet','hashes':{n:snapshot_sha256(p) for n,p in paths.items()},'overlay_hash':snapshot_sha256(local/'linkage_preview.parquet'),'script_hash':snapshot_sha256(Path(__file__))}
 (OUT/'linkage_preview.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
