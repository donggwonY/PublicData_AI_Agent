"""Bounded peer review of A01 Dongdaegu joins, without modifying A01 outputs."""
import json,sys
from pathlib import Path
import numpy as np
import pandas as pd
from snapshot_hashes import snapshot_sha256,verify_snapshot_hash
ROOT=Path(__file__).resolve().parents[1]
def main():
 out=ROOT/'docs/d04';a=ROOT/'docs/a01'
 ref=json.loads((a/'dongdaegu_exit_cafes.json').read_text(encoding='utf-8'))
 fixture=json.loads((a/'consultation_case.json').read_text(encoding='utf-8'))
 paths={'poi.parquet':ROOT/'service/data/processed/poi.parquet','station_locations.json':a/'station_locations.json'}
 for name,p in paths.items():verify_snapshot_hash(p,ref['input_hashes'][name]);verify_snapshot_hash(p,fixture['input_hashes'][name])
 locations=json.loads(paths['station_locations.json'].read_text(encoding='utf-8'))
 points=next(g['points'] for g in locations['station_exit_groups'] if g['traffic_station']=='동대구역')
 assert points==ref['exit_points'] and len(points)==3
 p=pd.read_parquet(paths['poi.parquet']);assert p[['lat','lon']].notna().all().all()
 assert p.lat.between(-90,90).all() and p.lon.between(-180,180).all()
 # Independent atan2 implementation; do not import A01 distance helper.
 lat=np.deg2rad(p.lat.to_numpy());lon=np.deg2rad(p.lon.to_numpy());ds=[]
 for point in points:
  a1,b1=np.deg2rad([point['latitude'],point['longitude']]);h=np.sin((lat-a1)/2)**2+np.cos(lat)*np.cos(a1)*np.sin((lon-b1)/2)**2;h=np.clip(h,0,1)
  ds.append(2*6371008.8*np.arctan2(np.sqrt(h),np.sqrt(1-h)))
 d=np.column_stack(ds);near=d.argmin(axis=1);ordered=np.sort(d,axis=1);ties=np.isclose(ordered[:,0],ordered[:,1],rtol=0,atol=1e-6)
 cafe=p.cat_s.eq('카페').to_numpy();unique=~p.duplicated().to_numpy();results=[]
 expected={300:(732,724,42,41),500:(1294,1272,72,70)}
 for radius in (300,500):
  inside=d.min(axis=1)<=radius
  counts=(int(inside.sum()),int((inside&unique).sum()),int((inside&cafe).sum()),int((inside&cafe&unique).sum()))
  assert counts==expected[radius]
  r=next(x for x in ref['results'] if x['radius_m']==radius);exits=[]
  for i,point in enumerate(points):
   assigned=inside&cafe&(near==i)&~ties
   values={'exit':point['exit'],'buffer_count':int(((d[:,i]<=radius)&cafe).sum()),'buffer_deduplicated':int(((d[:,i]<=radius)&cafe&unique).sum()),'nearest_count':int(assigned.sum()),'nearest_deduplicated':int((assigned&unique).sum())}
   old=next(e for e in r['exits'] if e['exit']==point['exit'])
   assert all(values[k]==old[k] for k in values)
   exits.append(values)
  assert int((inside&cafe&ties).sum())==r['exact_ties']==0
  assert sum(e['nearest_count'] for e in exits)==counts[2]
  assert sum(e['nearest_deduplicated'] for e in exits)==counts[3]
  # Dedup before/after radius filtering agrees for identical complete rows.
  assert len(p.loc[inside].drop_duplicates())==counts[1]
  assert len(p.loc[inside&cafe].drop_duplicates())==counts[3]
  results.append({'radius_m':radius,'all_rows':counts[0],'dedup_all':counts[1],'cafe_rows':counts[2],'dedup_cafe':counts[3],'exits':exits,'ties':0})
 assert np.all(~(d.min(axis=1)<=300)|(d.min(axis=1)<=500))
 report={'date':'2026-11-03','scope':'local snapshot independent distance recomputation and code review; not live DB or full A01 validation','results':results,'input_hashes':{k:snapshot_sha256(v) for k,v in paths.items()},'script_hash':snapshot_sha256(Path(__file__)),'limitations':['degree datum not independently verified','records not unique live shops','nearest exit not pedestrian flow','station overlap retained in original all-station analysis','only Dongdaegu recomputed']}
 (out/'a01_cross_review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps(results,ensure_ascii=False))
if __name__=='__main__':main()
