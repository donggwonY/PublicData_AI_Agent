"""Fixed nonlinear baseline/context comparison; no hyperparameter search."""
import json
from pathlib import Path
import numpy as np,pandas as pd
from sklearn.preprocessing import OrdinalEncoder
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import brier_score_loss,log_loss,roc_auc_score
from snapshot_hashes import snapshot_sha256
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/d03/opening_neighborhood'
source=ROOT/'data/raw/d03/building_opening_context.parquet'
previous=json.loads((OUT/'building_context_results.json').read_text(encoding='utf-8'));assert snapshot_sha256(source)==previous['hashes']['features']
a=pd.read_parquet(source)
config=dict(max_iter=200,learning_rate=.05,max_leaf_nodes=15,min_samples_leaf=100,l2_regularization=10,early_stopping=False,random_state=20261116)
protocol={'model':'HistGradientBoostingClassifier','config':config,'comparisons':'Within-tree density vs permit composition; building density vs building composition. Also report tree vs prior linear, not attributed to context.','weighted':'same inverse building training/evaluation weights as previous','years':[2022,2023,2024],'radii':[300,500],'validation':'Previously inspected evaluation years; exploratory, no tuning. No subtype features, unverified historical subtype deliberately omitted.'}
(OUT/'nonlinear_protocol.json').write_text(json.dumps(protocol,indent=2),encoding='utf-8')
variants={'permit_density':['density','empty'],'permit_summary':['density','same','mix','empty'],'building_density':['building_density','building_empty'],'building_summary':['building_density','building_same','building_mix','building_empty']}
results=[];predictions=[]
for radius in [300,500]:
 for year in [2022,2023,2024]:
  tr=a[(a.radius==radius)&a.year.between(year-6,year-2)].copy();te=a[(a.radius==radius)&a.year.eq(year)].copy()
  assert (tr.ld+pd.Timedelta(days=365)).max()<pd.Timestamp(year,1,1)
  wt=1/tr.groupby(['year','building']).building.transform('size').to_numpy();wt*=len(wt)/wt.sum();we=1/te.groupby('building').building.transform('size').to_numpy()
  enc=OrdinalEncoder(handle_unknown='use_encoded_value',unknown_value=np.nan)
  cats=enc.fit_transform(tr[['industry','gu']].fillna('__MISSING__'));tcats=enc.transform(te[['industry','gu']].fillna('__MISSING__'))
  assert all(len(c)<255 for c in enc.categories_)
  scores={};groups={};record=te[['source_index','building','industry','closure_365']].copy();record['radius']=radius;record['year']=year;record['weight']=we
  for name,cols in variants.items():
   x=np.column_stack([cats,tr[['year']+cols].to_numpy()]);z=np.column_stack([tcats,te[['year']+cols].to_numpy()])
   model=HistGradientBoostingClassifier(categorical_features=[0,1],**config);model.fit(x,tr.closure_365,sample_weight=wt);pp=model.predict_proba(z)[:,1];record[name]=pp;y=te.closure_365.to_numpy()
   def metric(mask):
    yy=y[mask];p=pp[mask];w=we[mask]
    return dict(n=int(mask.sum()),events=int(yy.sum()),brier=float(brier_score_loss(yy,p,sample_weight=w)),log_loss=float(log_loss(yy,p,sample_weight=w,labels=[0,1])),auc=float(roc_auc_score(yy,p,sample_weight=w)) if len(np.unique(yy))==2 else None,actual_pct=float(np.average(yy,weights=w)*100),predicted_pct=float(np.average(p,weights=w)*100))
   scores[name]=metric(np.ones(len(te),dtype=bool));groups[name]={str(ind):metric(te.industry.eq(ind).to_numpy()) for ind in sorted(te.industry.unique())}
  old=next(r for r in previous['results'] if r['radius']==radius and r['year']==year)
  assert all(scores[k]['n']==old['scores'][k]['n'] for k in scores)
  results.append(dict(radius=radius,year=year,train_n=len(tr),test_n=len(te),scores=scores,groups=groups,linear_scores=old['scores']))
  predictions.append(record)
  print('evaluated nonlinear',radius,year,flush=True)
predfile=ROOT/'data/raw/d03/nonlinear_neighborhood_predictions.parquet';pd.concat(predictions,ignore_index=True).to_parquet(predfile,index=False)
output=dict(protocol=protocol,results=results,hashes={'features':snapshot_sha256(source),'script':snapshot_sha256(Path(__file__)),'previous':snapshot_sha256(OUT/'building_context_results.json'),'predictions':snapshot_sha256(predfile),'protocol':snapshot_sha256(OUT/'nonlinear_protocol.json')})
(OUT/'nonlinear_results.json').write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
summary=[];lines=['# 주변 업종 구성의 비선형 비교','','고정 설정의 트리 모델로 가게 수만 포함한 경우와 업종 구성까지 추가한 경우를 비교했다. 같은 결과를 반복 확인한 탐색 분석이며 독립 최종평가가 아니다. 세부 업태는 제외했다.','','|반경|연도|기준|추가|Brier 상대 감소(%)|log loss 차이|','|---|---|---|---|---:|---:|']
for base,new in [('permit_density','permit_summary'),('building_density','building_summary')]:
 pairs=[]
 for r in results:
  b=r['scores'][base];n=r['scores'][new];gain=100*(b['brier']-n['brier'])/b['brier'];diff=n['log_loss']-b['log_loss'];pairs.append((gain,diff));lines.append(f"|{r['radius']}|{r['year']}|{base}|{new}|{gain:.4f}|{diff:.6f}|")
 summary.append(dict(base=base,new=new,both_better=sum(g>0 and d<0 for g,d in pairs),min_gain=min(g for g,d in pairs),max_gain=max(g for g,d in pairs)))
lines+=['','건물 가중은 기록이 많은 건물의 영향을 줄이는 목적이며 표본의 의미를 바꾼다. 공간적 상관·과거 좌표·신고 지연·반복 평가 한계는 유지된다. 선형 대비 개선이 있더라도 주변 정보의 효과는 같은 트리 모델 내 비교로 따로 판단한다. 공개 서비스 변경 없음.']
(OUT/'nonlinear_review.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps(summary),flush=True)
