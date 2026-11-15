"""Reproduce exploratory comparisons, sensitivity analyses and cohort descriptions."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from scipy.sparse import hstack,csr_matrix
from sklearn.preprocessing import OneHotEncoder,StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss,log_loss,roc_auc_score
from snapshot_hashes import snapshot_sha256
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/d03/opening_neighborhood'
source=ROOT/'service/data/processed/stores.parquet';features=ROOT/'data/raw/d03/opening_neighborhood.parquet'
initial=json.loads((OUT/'initial_results.json').read_text(encoding='utf-8'))
assert initial['hashes']['source']==snapshot_sha256(source)
assert initial['hashes']['script']==snapshot_sha256(ROOT/'scripts/analyze_opening_neighborhood.py')
f=pd.read_parquet(source);f['industry']=f.service.replace({'의원':'의원·병원','병원':'의원·병원'})
bad=f.ld.isna()|(f.closed&f.cd.isna())|(f.cd<f.ld)|(~f.closed&f.cd.notna())|f.industry.isna()
short=f.short_event.fillna(False).astype(bool)
coord=f.lat.between(-90,90)&f.lon.between(-180,180)&np.isfinite(f.lat)&np.isfinite(f.lon)&~((f.lat==0)&(f.lon==0))
valid=f[~bad&coord&~short].reset_index(drop=True)
a=pd.read_parquet(features).join(valid[['building_key','ld','cd']],on='source_index')
assert len(a)==initial['quality']['full_365_day_targets']*2
assert not a.duplicated(['source_index','radius']).any()
a['duration']=(a.cd-a.ld).dt.days
assert np.array_equal(a.closure_365.to_numpy(),a.duration.le(365).astype(int).to_numpy())
a['building']=a.building_key.astype('string').fillna(a.source_index.astype(str))
a['density']=np.log1p(a.nearby_total);a['same']=a.same_share.fillna(0);a['mix']=1-a.hhi.fillna(1);a['empty']=a.nearby_total.eq(0).astype(float)
# Fixed additional named exposures; historical opening/closure dates only.
exposures=['일반음식점','휴게음식점','미용업','의원·병원']
lat,lon=np.radians(valid[['lat','lon']].to_numpy()).T
pts=np.column_stack([np.cos(lat)*np.cos(lon),np.cos(lat)*np.sin(lon),np.sin(lat)])
tree=cKDTree(pts);ld=valid.ld.to_numpy(dtype='datetime64[D]').astype('int64');cd=valid.cd.to_numpy(dtype='datetime64[D]').astype('int64');cd[valid.cd.isna()]=10**9;names=valid.industry.to_numpy()
ids=a.loc[a.year.between(2016,2024),'source_index'].unique();counts={}
for start in range(0,len(ids),500):
 batch=ids[start:start+500];near=tree.query_ball_point(pts[batch],2*np.sin(500/6371008.8/2),workers=2)
 for idx,nb in zip(batch,near):
  nb=np.asarray(nb);nb=nb[(ld[nb]<ld[idx])&(cd[nb]>=ld[idx])];dist=np.linalg.norm(pts[nb]-pts[idx],axis=1)
  for radius in [300,500]:
   use=nb[dist<=2*np.sin(radius/6371008.8/2)];counts[(idx,radius)]=[int((names[use]==name).sum()) for name in exposures]
 if start%20000==0:print('named exposures',start,'/',len(ids),flush=True)
for j,exposure in enumerate(exposures):
 a['near_'+str(j)]=[counts.get((i,r),[0]*4)[j]/n if n else 0 for i,r,n in zip(a.source_index,a.radius,a.nearby_total)]
 a.loc[a.industry.eq(exposure),'near_'+str(j)]=0
results=[]
variants={'base':[],'density':['density','empty'],'composition':['same','mix','empty'],'summary':['density','same','mix','empty'],'specific':['density','same','mix','empty','near_0','near_1','near_2','near_3']}
def fit_compare(data,year,radius,mode,horizon,chosen):
 end=year-2 if horizon==365 else year-4
 tr=data[data.year.between(end-4,end)].copy();te=data[data.year.eq(year)].copy();before=len(te)
 if mode=='unseen_building':te=te[~te.building.isin(tr.building)]
 assert (tr.ld+pd.Timedelta(days=horizon)).max()<pd.Timestamp(year,1,1)
 assert (te.ld+pd.Timedelta(days=horizon)).max()<=pd.Timestamp(initial['reference_date'])
 y=tr.duration.le(horizon).astype(int);yt=te.duration.le(horizon).astype(int)
 weighted=mode in ['building_weight','unseen_building','joint_sensitivity']
 wt=1/tr.groupby(['year','building']).building.transform('size').to_numpy() if weighted else np.ones(len(tr));wt*=len(wt)/wt.sum()
 we=1/te.groupby('building').building.transform('size').to_numpy() if weighted else np.ones(len(te))
 enc=OneHotEncoder(handle_unknown='ignore');x=enc.fit_transform(tr[['industry','gu']].fillna('__MISSING__'));z=enc.transform(te[['industry','gu']].fillna('__MISSING__'))
 ss=StandardScaler();x=hstack([x,csr_matrix(ss.fit_transform(tr[['year']]))]);z=hstack([z,csr_matrix(ss.transform(te[['year']]))]);ie=OneHotEncoder(handle_unknown='ignore');i=ie.fit_transform(tr[['industry']]);j=ie.transform(te[['industry']])
 scores={};groups={}
 for name in chosen:
  cols=variants[name];xx=x.tocsr();zz=z.tocsr()
  if cols:
   sc=StandardScaler();v=sc.fit_transform(tr[cols]);w=sc.transform(te[cols]);xx=hstack([x,*[i.multiply(v[:,k,None]) for k in range(len(cols))]],format='csr');zz=hstack([z,*[j.multiply(w[:,k,None]) for k in range(len(cols))]],format='csr')
  m=LogisticRegression(C=1,max_iter=1500);m.fit(xx,y,sample_weight=wt);assert m.n_iter_[0]<1500
  pp=m.predict_proba(zz)[:,1]
  def score(mask):
   yy=yt.to_numpy()[mask];ww=we[mask];p=pp[mask]
   return dict(n=int(mask.sum()),events=int(yy.sum()),brier=float(brier_score_loss(yy,p,sample_weight=ww)),log_loss=float(log_loss(yy,p,sample_weight=ww,labels=[0,1])),auc=float(roc_auc_score(yy,p,sample_weight=ww)) if len(np.unique(yy))==2 else None,predicted_pct=float(np.average(p,weights=ww)*100),actual_pct=float(np.average(yy,weights=ww)*100))
  scores[name]=score(np.ones(len(te),dtype=bool));groups[name]={str(ind):score(te.industry.eq(ind).to_numpy()) for ind in sorted(te.industry.unique())}
 results.append(dict(mode=mode,horizon_days=horizon,radius=radius,year=year,train_n=len(tr),test_n=len(te),retained_fraction=len(te)/before,test_buildings=int(te.building.nunique()),weighted=weighted,scores=scores,groups=groups))
 print('evaluated',horizon,radius,mode,year,flush=True)
for radius in [300,500]:
 for mode in ['unweighted','exclude_30day','building_weight','exclude_instant_food','unseen_building','joint_sensitivity']:
  data=a[a.radius==radius]
  if mode in ['exclude_30day','joint_sensitivity']:data=data[data.duration.isna()|data.duration.gt(30)]
  if mode=='exclude_instant_food':data=data[data.industry.ne('즉석판매제조가공업')]
  chosen=list(variants) if mode=='unweighted' else (['density','summary','specific'] if mode=='building_weight' else ['density','summary'])
  for year in [2022,2023,2024]:fit_compare(data,year,radius,mode,365,chosen)
 for year in [2020,2021,2022]:fit_compare(a[a.radius==radius],year,radius,'building_weight',1095,['density','summary'])
# Annual descriptive low/high exposure contrasts, no ranking or causal inference.
contrasts=[]
for (industry,year,radius),g in a[a.year.le(2024)&a.nearby_total.gt(0)].groupby(['industry','year','radius']):
 q1,q2=g.same_share.quantile([1/3,2/3])
 if q1>=q2:continue
 z=g[g.same_share.le(q1)|g.same_share.ge(q2)].copy();z['high']=z.same_share.ge(q2);lo=z[~z.high];hi=z[z.high]
 if min(len(lo),len(hi))<200 or min(lo.closure_365.sum(),hi.closure_365.sum(),len(lo)-lo.closure_365.sum(),len(hi)-hi.closure_365.sum())<20:continue
 z['density_bin']=pd.qcut(z.nearby_total,4,labels=False,duplicates='drop');pairs=[]
 for _,cell in z.groupby(['gu','density_bin']):
  l=cell[~cell.high];h=cell[cell.high]
  if min(len(l),len(h))>=20:pairs.append((len(cell),100*(l.closure_365.mean()-h.closure_365.mean())))
 contrasts.append(dict(industry=industry,year=int(year),radius=int(radius),low_n=len(lo),high_n=len(hi),low_cut=float(q1),high_cut=float(q2),raw_gap_pp=float(100*(lo.closure_365.mean()-hi.closure_365.mean())),matched_gap_pp=float(np.average([d for n,d in pairs],weights=[n for n,d in pairs])) if pairs else None,matched_coverage=sum(n for n,d in pairs)/len(z)))
# Region comparison includes records without coordinates, unlike spatial analyses.
regions=['중구','동구','서구','남구','북구','수성구','달서구','달성군','군위군']
r=f[~bad&~short&f.gu.isin(regions)].copy();r['year']=r.ld.dt.year;r=r[r.year.between(2018,2022)];r['duration']=(r.cd-r.ld).dt.days;r['one']=~r.duration.le(365);r['three']=~r.duration.le(1095);r['building']=r.building_key.astype('string').fillna(r.index.to_series().astype(str));assert (r.three<=r.one).all()
regional=[]
for industry,g in r.groupby('industry'):
 weights=g.year.value_counts(normalize=True).reindex(range(2018,2023),fill_value=0)
 for gu in regions:
  local=g[g.gu==gu].copy();n=local.year.value_counts().reindex(range(2018,2023),fill_value=0)
  out=dict(industry=industry,gu=gu,n=len(local),min_year_n=int(n.min()),complete_years=bool(n.gt(0).all()),display_flag=bool(n.ge(30).all()))
  for col in ['one','three']:
   out[col+'_pct']=float(local[col].mean()*100) if len(local) else None
   out[col+'_standardized_pct']=float((local.groupby('year')[col].mean()*weights).sum()*100) if n.gt(0).all() else None
  if n.gt(0).all():
   delta=100*(local.groupby('year').three.mean()-g[g.gu!=gu].groupby('year').three.mean());out.update(positive_years=int(delta.gt(0).sum()),negative_years=int(delta.lt(0).sum()))
   local['w']=1/local.groupby(['year','building']).building.transform('size')
   wr=local.groupby('year').apply(lambda z:np.average(z.three,weights=z.w),include_groups=False)
   clean=local[local.duration.isna()|local.duration.gt(30)];cr=clean.groupby('year').three.mean()
   out['building_weighted_pct']=float((wr*weights).sum()*100);out['exclude30_pct']=float((cr*weights).sum()*100) if len(cr)==5 else None
  regional.append(out)
protocol={'status':'Exploratory post-hoc analyses, reused evaluation years; not independent final validation.','model':'LogisticRegression C1 max_iter1500; industry/region onehot + scaled opening year; neighborhood variables interact with industry.','exposures':exposures,'train':'365day: year-6 through year-2; 1095day: year-8 through year-4. All training outcomes mature before Jan1 evaluation year.','weights':'building modes: inverse records per building-year for training, normalized to training n; inverse records per building for evaluation. Changes estimand, not deduplication.','region_period':'2018-2022, complete1095days; pooled industry opening-year distribution standardizes each region.','limitations':['Current snapshot coordinates and region reconstruct history; relocation/reporting availability unknown.','Permits are not unique businesses; missing building IDs fall back to record IDs.','Removing <=30day outcomes is sensitivity only, changes target population, not deployable filtering.','All spatial features count raw eligible permits, including same-building neighbors; outcome weighting does not remove feature duplication.','No spatial cluster confidence intervals, multiple-testing adjustment or causal claim.','Regional n30/year display flag and spatial n200/events20 screening are not statistical significance.','Specific exposure fits only use 2016-2024 generated named counts; 3year models do not use these columns.']}
out=dict(protocol=protocol,hashes={'stores':snapshot_sha256(source),'features':snapshot_sha256(features),'script':snapshot_sha256(Path(__file__))},model_results=results,regional_records=len(r),regional=regional,relative_share_contrasts=contrasts)
(OUT/'reproduced_checks.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
pd.DataFrame(regional).to_csv(OUT/'regional_cohort_comparison.csv',index=False,encoding='utf-8-sig')
pd.DataFrame(contrasts).to_csv(OUT/'relative_share_comparison.csv',index=False,encoding='utf-8-sig')
lines=['# 周辺業種 구성 및 영업 지속 분석 검증'.replace('周辺業種','주변 업종'),'','기준일 '+initial['reference_date']+'. 기존 결과를 재실행한 탐색 분석이며 새로운 독립 최종평가가 아니다. 인과관계·창업 추천·개별 폐업 확률의 서비스 적용을 검증한 결과가 아니다.','','## 모델 비교','','아래는 주변 가게 수를 포함한 모델(density)에 동종 업종 비중·다양성을 추가한 모델(summary)의 Brier 오차 상대 감소율이다. 양수는 감소, 음수는 증가이며 정확도 증가율이 아니다.','','|추적일|거리|검사|개업연도|평가행|Brier 상대 감소(%)|log loss 변화(추가−기준)|','|---|---|---|---|---:|---:|---:|']
for row in results:
 b=row['scores']['density'];c=row['scores']['summary'];lines.append(f"|{row['horizon_days']}|{row['radius']}|{row['mode']}|{row['year']}|{row['test_n']}|{100*(b['brier']-c['brier'])/b['brier']:.4f}|{c['log_loss']-b['log_loss']:.6f}|")
lines+=['','## 해석','주변 정보 추가의 초기 개선은 반복 건물 가중·단기 운영 제외 후 크게 줄었다. 구체 업종 추가는 두 오차가 함께 안정적으로 개선되는 결과를 보이지 않았다. 3년 결과도 연도에 따라 혼재한다. 모든 조건을 함께 보고하며 유리한 실험만 대표 결과로 선택하지 않는다.','', '## 지역별 기록 비교','2018–2022년 개업 '+str(len(r))+'건을 같은 업종의 개업연도 비중으로 맞췄다. 지역별 수치와 반복 건물·30일 이하 제외 민감도는 regional_cohort_comparison.csv에 있다. 좌표 없는 기록도 지역 비교에는 포함되므로 공간 분석과 표본이 다르다. 3년은1095일, 1년은365일이며 폐업 신고 미관측 비율을 실제 사업 성공률로 해석하지 않는다.','', '## 재실행','저장소 루트에서 service/.venv/Scripts/python.exe scripts/analyze_opening_neighborhood.py 로 기초 특성을 생성한 뒤 service/.venv/Scripts/python.exe scripts/reproduce_opening_neighborhood_checks.py 실행. 원본·특성·스크립트 해시는 JSON에 기록한다.','', '## 한계']+['- '+s for s in protocol['limitations']]
(OUT/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print('SAVED',len(results),'model comparisons',len(contrasts),'annual contrasts',len(regional),'regional cells',flush=True)
