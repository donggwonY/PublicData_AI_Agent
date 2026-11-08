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
 for family in ['lr']:
  for block in ['base','composition','flow','compact']:
   extra=block!='base'
   selected={'base':[],'composition':['active_total','same_industry_active','industry_variety','concentration_hhi'],'flow':['opened_total','closed_total','net_permit_flow'],'compact':['active_total','same_industry_active','industry_variety','concentration_hhi','opened_total','closed_total','net_permit_flow']}[block]
   transforms=[('categorical',OneHotEncoder(handle_unknown='ignore'),['industry','gu','age_band'])]
   if extra:transforms.append(('context',make_pipeline(SimpleImputer(strategy='median',add_indicator=True),StandardScaler()),selected))
   clf=LogisticRegression(C=1,max_iter=3000,random_state=7) if family=='lr' else RandomForestClassifier(n_estimators=150,max_depth=8,min_samples_leaf=30,max_features='sqrt',random_state=7,n_jobs=2)
   m=make_pipeline(ColumnTransformer(transforms),clf);m.fit(a,a.y)
   name=family+'_'+block;preds[name]=m.predict_proba(b)[:,1];print('fit',name,flush=True)
 groups=[]
 for industry,g in b.groupby('industry'):
  ix=g.index.to_numpy();scores={n:metrics(g.y.to_numpy(),p[ix]) for n,p in preds.items()}
  groups.append({'industry':industry,'small_sample':len(g)<200 or int(g.y.sum())<20,'scores':scores})
 overall={n:metrics(b.y.to_numpy(),p) for n,p in preds.items()}
 for name in overall:assert abs(sum(g['scores'][name]['brier']*g['scores'][name]['n'] for g in groups)/len(b)-overall[name]['brier'])<1e-12
 out={'train_year':2021,'test_year':2023,'train_n':len(a),'context_features_available':numeric,'blocks':{'composition':['active_total','same_industry_active','industry_variety','concentration_hhi'],'flow':['opened_total','closed_total','net_permit_flow'],'compact':'union of composition and flow'},'overall':overall,'groups':groups,'hashes':{'stores':snapshot_sha256(sp),'context':snapshot_sha256(fp),'script':snapshot_sha256(Path(__file__))},'limitations':['Single reused evaluation year, exploratory; not definitive model selection.','Matched geocoded subset, not identical to earlier all-record evaluation.','Latest location reconstructs historical neighbors; permits are not unique shops.','Current industry/gu and permit reporting definitions may differ historically.','Spatial neighborhoods overlap and same permits repeat across years.','No 2025 outcomes or current-date future outcomes used; no deployment.']}
 (OUT/'neighborhood_blocks.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
 lines=['# 주변 업종 구성과 개폐업 흐름 분리 비교','','2021학습→2023평가. 기존52특성 실험을 본 뒤 진행한 탐색. 새 독립평가가 아님. LR C1/seed7, 동일표본, 학습자료만 변환. 구성4개/흐름3개/합계7개 고정, 결과후 튜닝 없음.','','|후보|n|Brier|log loss|AUC|','|---|---:|---:|---:|---:|']
 for n,s in overall.items():lines.append(f"|{n}|{s['n']}|{s['brier']:.6f}|{s['log_loss']:.6f}|{s['roc_auc']:.3f}|")
 lines+=['','|업종|구성 Brier차이|흐름 Brier차이|둘다 Brier차이|','|---|---:|---:|---:|']
 for g in groups:
  s=g['scores'];base=s['lr_base']['brier'];lines.append(f"|{g['industry']}|{s['lr_composition']['brier']-base:+.6f}|{s['lr_flow']['brier']-base:+.6f}|{s['lr_compact']['brier']-base:+.6f}|")
 lines+=['','차이는 기존모델 대비, 음수가 개선. 전체지표·업종별 두 오차는 JSON. 최신좌표·누락좌표 제외·인허가건수·시간지연가정·반복인허가 한계 동일. 서비스 채택 없음.']
 (OUT/'neighborhood_blocks.md').write_text('\n'.join(lines)+'\n',encoding='utf-8');print(json.dumps(overall))
if __name__=='__main__':main()
