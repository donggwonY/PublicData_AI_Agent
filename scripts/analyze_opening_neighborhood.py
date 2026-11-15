"""Descriptive opening-time neighborhood analysis; not individual prediction."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from snapshot_hashes import snapshot_sha256
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/d03/opening_neighborhood';OUT.mkdir(exist_ok=True)
p=ROOT/'service/data/processed/stores.parquet'
f=pd.read_parquet(p)
ref=pd.Timestamp(json.loads((p.parent/'meta.json').read_text(encoding='utf-8'))['reference_date'])
bad=f.ld.isna()|(f.closed&f.cd.isna())|(f.cd<f.ld)|(~f.closed&f.cd.notna())|f.service.isna()
coord=f.lat.between(-90,90)&f.lon.between(-180,180)&np.isfinite(f.lat)&np.isfinite(f.lon)&~((f.lat==0)&(f.lon==0))
short=f.short_event.fillna(False).astype(bool)
quality={'raw':len(f),'invalid_dates_or_industry':int(bad.sum()),'invalid_coordinates':int((~coord).sum()),'short_event':int(short.sum()),'excluded_union':int((bad|~coord|short).sum())}
f=f[~bad&coord&~short].copy().reset_index(drop=True)
f['industry']=f.service.replace({'의원':'의원·병원','병원':'의원·병원'})
lat,lon=np.radians(f[['lat','lon']].to_numpy()).T
points=np.column_stack([np.cos(lat)*np.cos(lon),np.cos(lat)*np.sin(lon),np.sin(lat)])
tree=cKDTree(points)
ld=f.ld.to_numpy(dtype='datetime64[D]').astype('int64')
cd=f.cd.to_numpy(dtype='datetime64[D]').astype('int64');cd[f.cd.isna()]=10**9
codes,names=pd.factorize(f.industry)
ids=np.flatnonzero((f.ld+pd.Timedelta(days=365)).le(ref))
quality['valid_records']=len(f);quality['full_365_day_targets']=len(ids);quality['incomplete_followup']=len(f)-len(ids)
industry_values=f.industry.to_numpy();gu_values=f.gu.astype(str).to_numpy();years=f.ld.dt.year.to_numpy()
rows=[]
for start in range(0,len(ids),250):
 batch=ids[start:start+250]
 near=tree.query_ball_point(points[batch],2*np.sin(500/6371008.8/2),workers=2)
 for idx,neighbors in zip(batch,near):
  neighbors=np.asarray(neighbors,dtype=int)
  # Strictly prior openings excludes target and all same-day openings.
  active=neighbors[(ld[neighbors]<ld[idx])&(cd[neighbors]>=ld[idx])]
  distance=np.linalg.norm(points[active]-points[idx],axis=1)
  for radius in [300,500]:
   use=active[distance<=2*np.sin(radius/6371008.8/2)]
   counts=np.bincount(codes[use],minlength=len(names));total=len(use);same=int(counts[codes[idx]])
   share=same/total if total else np.nan
   hhi=float(((counts/total)**2).sum()) if total else None
   group='no_neighbors' if not total else ('zero_same' if same==0 else ('below_10pct' if share<.1 else 'at_least_10pct'))
   rows.append((int(idx),str(industry_values[idx]),str(gu_values[idx]),int(years[idx]),radius,total,same,share,hhi,group,int(cd[idx]<=ld[idx]+365)))
 if start%25000==0:print('processed',start,'/',len(ids),flush=True)
a=pd.DataFrame(rows,columns=['source_index','industry','gu','year','radius','nearby_total','nearby_same','same_share','hhi','group','closure_365'])
assert len(a)==len(ids)*2 and not a.duplicated(['source_index','radius']).any()
assert (a.nearby_same<=a.nearby_total).all()
local=ROOT/'data/raw/d03/opening_neighborhood.parquet';local.parent.mkdir(parents=True,exist_ok=True);a.to_parquet(local,index=False)
def aggregate(keys):
 g=a.groupby(keys,dropna=False).agg(n=('closure_365','size'),events=('closure_365','sum'),median_neighbors=('nearby_total','median')).reset_index()
 g['no_closure_365_pct']=100*(1-g.events/g.n)
 g['small_group']=(g.n<200)|(g.events<20)|((g.n-g.events)<20)
 return g
annual=aggregate(['year','industry','radius','group']);annual.to_csv(OUT/'annual_groups.csv',index=False,encoding='utf-8-sig')
regional=aggregate(['year','gu','industry','radius','group']);regional.to_csv(OUT/'regional_groups.csv',index=False,encoding='utf-8-sig')
coverage=a[a.radius==500].groupby('year').agg(n=('closure_365','size'),events=('closure_365','sum'),without_neighbors=('nearby_total',lambda s:int((s==0).sum()))).reset_index()
coverage.to_csv(OUT/'year_coverage.csv',index=False,encoding='utf-8-sig')
# Full recent calendar years only, chosen by follow-up completeness, not outcomes.
last_full=(ref-pd.Timedelta(days=365)).year-1
recent=annual[annual.year.between(last_full-2,last_full)]
pairs=[]
for (industry,year,radius),g in recent.groupby(['industry','year','radius']):
 g=g.set_index('group')
 if not {'below_10pct','at_least_10pct'}.issubset(g.index):continue
 lo=g.loc['below_10pct'];hi=g.loc['at_least_10pct']
 pairs.append(dict(industry=industry,year=int(year),radius=int(radius),low_n=int(lo.n),high_n=int(hi.n),low_events=int(lo.events),high_events=int(hi.events),gap_pp=float(hi.no_closure_365_pct-lo.no_closure_365_pct),eligible=bool(not lo.small_group and not hi.small_group)))
result={'reference_date':str(ref.date()),'quality':quality,'recent_full_years':[last_full-2,last_full],'comparisons':pairs,'hashes':{'source':snapshot_sha256(p),'script':snapshot_sha256(Path(__file__))},'limitations':['Descriptive association, not causal or model performance.','Latest recorded coordinates; relocation history and reporting availability unknown.','Counts are permits, not unique shops; same building neighbors retained.','Same-day openings excluded; same-day closures treated as active immediately before opening.','Only complete365-day cohorts; no claim about long-term survival.','10 percent groups fixed before computation; not optimized or recommendation thresholds.','Sample flag n200/events20/non-events20 is screening, not statistical certainty.','No adjustment yet for region, opening month, density or spatial dependence.','Historical record coverage may vary; all annual cohorts are reported.','No DB or service changes.']}
(OUT/'initial_results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(quality));print('recent comparisons',len(pairs),'eligible',sum(x['eligible'] for x in pairs),flush=True)
