"""Building-balanced opening context vs permit context; exploratory fixed comparisons."""
import json,sys
from pathlib import Path
import numpy as np,pandas as pd
from scipy.spatial import cKDTree
from scipy.sparse import hstack,csr_matrix
from sklearn.preprocessing import OneHotEncoder,StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss,log_loss,roc_auc_score
from snapshot_hashes import snapshot_sha256
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/d03/opening_neighborhood'

def composition(buildings,industries,own,nindustries):
 if not len(buildings):return (0,0.,0.,1.)
 pairs=np.unique(np.column_stack([buildings,industries]),axis=0)
 unique,inverse=np.unique(pairs[:,0],return_inverse=True)
 k=np.bincount(inverse)
 counts=np.bincount(pairs[:,1],weights=1/k[inverse],minlength=nindustries)
 assert np.isclose(counts.sum(),len(unique))
 shares=counts/len(unique)
 return (len(unique),float(shares[own]),float(1-(shares**2).sum()),0.)

def self_test():
 a=composition(np.array([1,1,1,2]),np.array([0,0,1,1]),0,3)
 b=composition(np.array([1,1,2]),np.array([0,1,1]),0,3)
 assert a==b and np.isclose(a[1],.25) and a[0]==2
 assert composition(np.array([],dtype=int),np.array([],dtype=int),0,3)==(0,0.,0.,1.)
 assert composition(np.array([1,2]),np.array([0,0]),0,3)==(2,1.,0.,0.)
 print('PASS composition duplicate-invariance, mixed building weights, empty and same-only cases',flush=True)

def main():
 self_test()
 source=ROOT/'service/data/processed/stores.parquet';features=ROOT/'data/raw/d03/opening_neighborhood.parquet'
 previous=json.loads((OUT/'reproduced_checks.json').read_text(encoding='utf-8'))
 assert snapshot_sha256(source)==previous['hashes']['stores']
 assert snapshot_sha256(features)==previous['hashes']['features']
 protocol={'scope':'Fixed exploratory building representation follow-up, no outcome-driven parameter search.','primary':'Building-weighted same-cohort comparison; old permit context vs fractional building context and context excluding focal building.','composition':'One unit per unique building; split equally among unique eligible industries present in that building. Repeated building-industry records contribute once.','same_building':'included and excluded variants both reported','models':'LR C1 max_iter1500; industry-region-year baseline plus industry interactions with context; no calibration tuning','years':[2022,2023,2024],'radii':[300,500],'train':'five opening cohorts y-6 through y-2, fully observed365day outcomes','subtype':'separate exploratory sensitivity using current recorded category, historical availability unverified','limitations':['Building is not a unique storefront. Different floors/shops remain distinct real businesses.','Building keys and coordinates are current snapshot values; historical relocation unknown.','Fractional industry shares reflect building occupancy mix, not store market shares.','Same outcomes inspected in previous experiments; not an untouched test.','Building sample weights change estimand and do not establish causal effects.']}
 (OUT/'building_context_protocol.json').write_text(json.dumps(protocol,ensure_ascii=False,indent=2),encoding='utf-8')
 f=pd.read_parquet(source);f['industry']=f.service.replace({'의원':'의원·병원','병원':'의원·병원'})
 bad=f.ld.isna()|(f.closed&f.cd.isna())|(f.cd<f.ld)|(~f.closed&f.cd.notna())|f.industry.isna();coord=f.lat.between(-90,90)&f.lon.between(-180,180)&np.isfinite(f.lat)&np.isfinite(f.lon)&~((f.lat==0)&(f.lon==0))
 f=f[~bad&coord&~f.short_event.fillna(False).astype(bool)].copy().reset_index(drop=True)
 f['building']=f.building_key.astype('string').replace('',pd.NA).fillna(f.index.to_series().astype(str));bc,_=pd.factorize(f.building);ic,names=pd.factorize(f.industry)
 a=pd.read_parquet(features);a=a[a.year.between(2016,2024)].copy().join(f[['building','category','ld','cd']],on='source_index')
 assert np.array_equal(a.closure_365.to_numpy(),(a.cd-a.ld).dt.days.le(365).astype(int).to_numpy())
 a['density']=np.log1p(a.nearby_total);a['same']=a.same_share.fillna(0);a['mix']=1-a.hhi.fillna(1);a['empty']=a.nearby_total.eq(0).astype(float)
 lat,lon=np.radians(f[['lat','lon']].to_numpy()).T;pts=np.column_stack([np.cos(lat)*np.cos(lon),np.cos(lat)*np.sin(lon),np.sin(lat)]);tree=cKDTree(pts)
 ld=f.ld.to_numpy(dtype='datetime64[D]').astype('int64');cd=f.cd.to_numpy(dtype='datetime64[D]').astype('int64');cd[f.cd.isna()]=10**9
 ids=a.source_index.unique();counts={}
 for start in range(0,len(ids),500):
  batch=ids[start:start+500];neighbors=tree.query_ball_point(pts[batch],2*np.sin(500/6371008.8/2),workers=2)
  for idx,nb in zip(batch,neighbors):
   nb=np.asarray(nb);nb=nb[(ld[nb]<ld[idx])&(cd[nb]>=ld[idx])];distance=np.linalg.norm(pts[nb]-pts[idx],axis=1)
   for radius in [300,500]:
    use=nb[distance<=2*np.sin(radius/6371008.8/2)]
    full=composition(bc[use],ic[use],ic[idx],len(names));off=use[bc[use]!=bc[idx]];outside=composition(bc[off],ic[off],ic[idx],len(names))
    assert outside[0]<=full[0]<=len(use)
    counts[(idx,radius)]=full+outside
  if start%20000==0:print('building features',start,'/',len(ids),flush=True)
 values=np.array([counts[(i,r)] for i,r in zip(a.source_index,a.radius)])
 for k,col in enumerate(['building_total','building_same','building_mix','building_empty','offsite_total','offsite_same','offsite_mix','offsite_empty']):a[col]=values[:,k]
 a['building_density']=np.log1p(a.building_total);a['offsite_density']=np.log1p(a.offsite_total)
 dest=ROOT/'data/raw/d03/building_opening_context.parquet';a.to_parquet(dest,index=False)
 variants={'permit_density':['density','empty'],'permit_summary':['density','same','mix','empty'],'building_density':['building_density','building_empty'],'building_summary':['building_density','building_same','building_mix','building_empty'],'offsite_density':['offsite_density','offsite_empty'],'offsite_summary':['offsite_density','offsite_same','offsite_mix','offsite_empty'],'subtype_control':['density','same','mix','empty'],'subtype_building':['building_density','building_same','building_mix','building_empty']}
 results=[]
 for radius in [300,500]:
  for year in [2022,2023,2024]:
   tr=a[(a.radius==radius)&a.year.between(year-6,year-2)].copy();te=a[(a.radius==radius)&a.year.eq(year)].copy()
   assert (tr.ld+pd.Timedelta(days=365)).max()<pd.Timestamp(year,1,1)
   wt=1/tr.groupby(['year','building']).building.transform('size').to_numpy();wt*=len(wt)/wt.sum();we=1/te.groupby('building').building.transform('size').to_numpy()
   ie=OneHotEncoder(handle_unknown='ignore');i=ie.fit_transform(tr[['industry']]);j=ie.transform(te[['industry']]);scores={};groups={}
   for name,cols in variants.items():
    cats=['industry','gu']+(['category'] if name.startswith('subtype') else [])
    enc=OneHotEncoder(handle_unknown='ignore');x=enc.fit_transform(tr[cats].fillna('__MISSING__'));z=enc.transform(te[cats].fillna('__MISSING__'))
    ss=StandardScaler();x=hstack([x,csr_matrix(ss.fit_transform(tr[['year']]))]);z=hstack([z,csr_matrix(ss.transform(te[['year']]))])
    sc=StandardScaler();v=sc.fit_transform(tr[cols]);w=sc.transform(te[cols]);xx=hstack([x,*[i.multiply(v[:,k,None]) for k in range(len(cols))]],format='csr');zz=hstack([z,*[j.multiply(w[:,k,None]) for k in range(len(cols))]],format='csr')
    model=LogisticRegression(C=1,max_iter=1500);model.fit(xx,tr.closure_365,sample_weight=wt);assert model.n_iter_[0]<1500
    pred=model.predict_proba(zz)[:,1];y=te.closure_365.to_numpy()
    def metric(mask):
     yy=y[mask];pp=pred[mask];ww=we[mask]
     return dict(n=int(mask.sum()),events=int(yy.sum()),brier=float(brier_score_loss(yy,pp,sample_weight=ww)),log_loss=float(log_loss(yy,pp,sample_weight=ww,labels=[0,1])),auc=float(roc_auc_score(yy,pp,sample_weight=ww)) if len(np.unique(yy))==2 else None,actual_pct=float(np.average(yy,weights=ww)*100),predicted_pct=float(np.average(pp,weights=ww)*100))
    scores[name]=metric(np.ones(len(te),dtype=bool));groups[name]={str(ind):metric(te.industry.eq(ind).to_numpy()) for ind in sorted(te.industry.unique())}
   old=next(r for r in previous['model_results'] if r['mode']=='building_weight' and r['year']==year and r['radius']==radius and r['horizon_days']==365)
   assert abs(scores['permit_summary']['brier']-old['scores']['summary']['brier'])<1e-10
   results.append(dict(radius=radius,year=year,train_n=len(tr),test_n=len(te),scores=scores,groups=groups))
   print('evaluated',radius,year,flush=True)
 out=dict(protocol=protocol,hashes={'source':snapshot_sha256(source),'previous':snapshot_sha256(OUT/'reproduced_checks.json'),'features':snapshot_sha256(dest),'script':snapshot_sha256(Path(__file__)),'protocol':snapshot_sha256(OUT/'building_context_protocol.json')},results=results,quality={'targets':len(ids),'feature_rows':len(a),'building_count_exceeds_permit_count':int(a.building_total.gt(a.nearby_total).sum()),'focal_building_present_rows':int(a.building_total.gt(a.offsite_total).sum())})
 (OUT/'building_context_results.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
 lines=['# 周辺建物基準検証'.replace('周辺建物基準検証','周辺建物基準検証'),'','Building-normalized context; exploratory, not an untouched test.','', '|radius|year|comparison|Brier relative gain %|log loss difference|','|---|---|---|---:|---:|']
 comparisons=[('permit_summary','building_summary'),('building_density','building_summary'),('offsite_density','offsite_summary'),('permit_summary','offsite_summary'),('permit_summary','subtype_control'),('subtype_control','subtype_building')]
 summary=[]
 for base,new in comparisons:
  pairs=[]
  for r in results:
   b=r['scores'][base];n=r['scores'][new];gain=100*(b['brier']-n['brier'])/b['brier'];ldiff=n['log_loss']-b['log_loss'];pairs.append((gain,ldiff));lines.append(f"|{r['radius']}|{r['year']}|{base} → {new}|{gain:.4f}|{ldiff:.6f}|")
  summary.append(dict(base=base,new=new,both_better=sum(g>0 and d<0 for g,d in pairs),brier_gain_min=min(g for g,d in pairs),brier_gain_max=max(g for g,d in pairs)))
 lines[0]='# 建物単位の周辺業種構成'.replace('建物単位の周辺業種構成','건물 단위 주변 업종 구성 검증')
 lines+=['','건물당1의 기여를 해당 건물에서 관측된 서로 다른 업종에 균등 배분한다. 따라서 비중은 점포 점유율이 아닌 건물 내 업종 구성의 요약값이다. 건물 내부의 실제 여러 점포를 하나의 가게로 간주하지 않는다. 동일 건물 포함·제외 조건을 모두 보고한다.','', '평가 표본·가중·학습기간·C값을 고정해 기존 결과와 비교했고 기존 permit_summary Brier 재현을 확인했다. category를 쓴 두 조건은 현재 기록의 세부 업태를 사용하므로 과거 입력 가능성을 확인한 것으로 해석하지 않는다.','', '상세 업종별 점수·해시·한계는 building_context_results.json. 원본 특성은 data/raw/d03/building_opening_context.parquet에 로컬 보관한다. 공개 앱·공유DB 변경 없음.']
 (OUT/'building_context_review.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
 print(json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=='__main__':
 if '--self-test' in sys.argv:self_test()
 else:main()
