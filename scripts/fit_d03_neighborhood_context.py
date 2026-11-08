"""Fixed matched-sample ablation for all-industry neighborhood context."""
import json,warnings
from pathlib import Path
import pandas as pd,numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder,StandardScaler
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.exceptions import ConvergenceWarning
from fit_d03 import metrics
from snapshot_hashes import snapshot_sha256
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/d03'
def main():
 warnings.simplefilter('error',ConvergenceWarning)
 sp=ROOT/'service/data/processed/stores.parquet';fp=ROOT/'data/raw/d03/neighborhood_context.parquet'
 manifest=json.loads((OUT/'neighborhood_context.json').read_text(encoding='utf-8'))
 assert snapshot_sha256(sp)==manifest['hashes']['stores'] and snapshot_sha256(fp)==manifest['hashes']['features']
 f=pd.read_parquet(sp);f['source_row_id']=np.arange(len(f));ctx=pd.read_parquet(fp)
 ids=['source_row_id','uid','service','building_key','industry','gu','as_of'];numeric=[c for c in ctx if c not in ids];assert len(numeric)==52
 for c in numeric:
  if c!='concentration_hhi':ctx[c]=np.sign(ctx[c])*np.log1p(np.abs(ctx[c]))
 def cohort(year):
  t=pd.Timestamp(year,1,1);a=ctx[ctx.as_of.eq(t)].merge(f[['source_row_id','ld','cd','closed']],on='source_row_id',validate='one_to_one')
  assert a.ld.le(t).all() and (a.cd.isna()|a.cd.gt(t)).all()
  a['age_band']=pd.cut((t-a.ld).dt.days,[-1,364,1094,1824,3649,np.inf],labels=['<1','1-3','3-5','5-10','10+']).astype(str)
  a['y']=(a.closed&a.cd.gt(t)&a.cd.le(t+pd.Timedelta(days=365))).astype(int)
  for c in ['industry','gu','age_band']:a[c]=a[c].astype('string').fillna('__MISSING__').astype(str)
  return a
 a,b=cohort(2021),cohort(2023);assert pd.Timestamp(2022,1,1)<pd.Timestamp(2023,1,1)
 preds={'industry_mean':b.industry.map(a.groupby('industry').y.mean()).to_numpy()};assert np.isfinite(preds['industry_mean']).all()
 for family in ['lr','rf']:
  for extra in [False,True]:
   transforms=[('categorical',OneHotEncoder(handle_unknown='ignore'),['industry','gu','age_band'])]
   if extra:transforms.append(('context',make_pipeline(SimpleImputer(strategy='median',add_indicator=True),StandardScaler()),numeric))
   clf=LogisticRegression(C=1,max_iter=3000,random_state=7) if family=='lr' else RandomForestClassifier(n_estimators=150,max_depth=8,min_samples_leaf=30,max_features='sqrt',random_state=7,n_jobs=2)
   m=make_pipeline(ColumnTransformer(transforms),clf);m.fit(a,a.y)
   name=family+('_context' if extra else '_base');preds[name]=m.predict_proba(b)[:,1];print('fit',name,flush=True)
 groups=[]
 for industry,g in b.groupby('industry'):
  ix=g.index.to_numpy();scores={n:metrics(g.y.to_numpy(),p[ix]) for n,p in preds.items()}
  groups.append({'industry':industry,'small_sample':len(g)<200 or int(g.y.sum())<20,'scores':scores})
 overall={n:metrics(b.y.to_numpy(),p) for n,p in preds.items()}
 for name in overall:assert abs(sum(g['scores'][name]['brier']*g['scores'][name]['n'] for g in groups)/len(b)-overall[name]['brier'])<1e-12
 out={'train_year':2021,'test_year':2023,'train_n':len(a),'context_features':numeric,'overall':overall,'groups':groups,'hashes':{'stores':snapshot_sha256(sp),'context':snapshot_sha256(fp),'script':snapshot_sha256(Path(__file__))},'limitations':['Single reused evaluation year, exploratory; not definitive model selection.','Matched geocoded subset, not identical to earlier all-record evaluation.','Latest location reconstructs historical neighbors; permits are not unique shops.','Current industry/gu and permit reporting definitions may differ historically.','Spatial neighborhoods overlap and same permits repeat across years.','No 2025 outcomes or current-date future outcomes used; no deployment.']}
 (OUT/'neighborhood_experiment.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
 lines=['# 전체 업종 주변 상권 정보 추가 비교','','2021학습→2023평가. 좌표 연결 동일표본에서 LR/RF의 주변52특성 추가 비교. 사전고정 LR C1, RF150/깊이8/잎30/sqrt. 숫자변환 signed log1p(집중도 제외), 결측대체·표준화 학습자료만.','','|모델|n|실제%|예측%|Brier|log loss|AUC|','|---|---:|---:|---:|---:|---:|---:|']
 for n,s in overall.items():lines.append(f"|{n}|{s['n']}|{s['actual_pct']:.2f}|{s['predicted_pct']:.2f}|{s['brier']:.6f}|{s['log_loss']:.6f}|{s['roc_auc']:.3f}|")
 lines+=['','|업종|LR추가 전→후 Brier|RF추가 전→후 Brier|','|---|---:|---:|']
 for g in groups:
  s=g['scores'];lines.append(f"|{g['industry']}|{s['lr_base']['brier']:.6f}→{s['lr_context']['brier']:.6f}|{s['rf_base']['brier']:.6f}→{s['rf_context']['brier']:.6f}|")
 lines+=['','단일 기존평가연도 탐색. 최신좌표·인허가건수·현재업종구군·좌표미연결 제외 한계. 서비스 채택 아님. 상세 표본수와 두 오차·AUC는 JSON.']
 (OUT/'neighborhood_experiment.md').write_text('\n'.join(lines)+'\n',encoding='utf-8');print(json.dumps(overall))
if __name__=='__main__':main()
