"""Frozen full-coverage baseline audit; no 2023-2025 scoring."""
import json,sys
from sklearn.ensemble import RandomForestClassifier
from pathlib import Path
import numpy as np,pandas as pd
from fit_d03 import ROOT,metrics,verify_snapshot_hash,snapshot_sha256,Pipeline,OneHotEncoder,LogisticRegression
from fit_d03_expanded import fit
sys.path.insert(0,str(ROOT/'service'))
from pipeline.numeric import parse_area
def main():
 out=ROOT/'docs/d03';old=json.loads((out/'validation.json').read_text(encoding='utf-8'));area_ref=json.loads((out/'area_complete.json').read_text(encoding='utf-8'))
 sp=ROOT/'service/data/processed/stores.parquet';rp=ROOT.parent.parent/'상권분석 데이터/식품_일반음식점_대구광역시.csv'
 verify_snapshot_hash(sp,old['hashes']['stores']);verify_snapshot_hash(rp,area_ref['hashes']['raw']);verify_snapshot_hash(ROOT/'service/pipeline/numeric.py',area_ref['hashes']['parser'])
 st=pd.read_parquet(sp);f=st[st.service.eq('일반음식점')&st.ld.dt.year.between(2010,2021)].copy().reset_index(drop=True)
 assert not (f.cd.notna()&f.cd.lt(f.ld)).any()
 r=pd.read_csv(rp,encoding='cp949',dtype=str,usecols=['개방자치단체코드','관리번호','소재지면적']);r['key']=r['개방자치단체코드']+'|'+r['관리번호'];assert r.key.is_unique
 key=f.org_code.astype(str).str.replace(r'\.0$','',regex=True)+'|'+f.mgmt_no
 raw=key.map(r.set_index('key')['소재지면적']);parsed=parse_area(raw);area=f.area_m2.copy();recover=area.isna()&raw.str.contains(',',regex=False,na=False)&parsed.notna();area.loc[recover]=parsed[recover].astype(float)
 coord=f.lat.between(-90,90)&f.lon.between(-180,180);valid=np.isfinite(area)&area.gt(0)
 f['coverage']=np.where(~coord,'coordinate_excluded',np.where(~valid,'area_excluded','included'))
 cols=['category','gu','open_month']
 features=lambda a:a.assign(open_month=a.ld.dt.month)[cols].astype('string').fillna('__MISSING__').astype(str)
 target=lambda a:(a.closed&(a.cd-a.ld).dt.days.between(0,365)).astype(int).to_numpy()
 ref=pd.Timestamp(json.loads((ROOT/'service/data/processed/meta.json').read_text(encoding='utf-8'))['reference_date'])
 previous=json.loads((out/'full_coverage.json').read_text(encoding='utf-8'))
 verify_snapshot_hash(Path(__file__).with_name('audit_d03_full_coverage.py'),previous['hashes']['script'])
 results=[]
 for end,start,stop in [(2013,2015,2016),(2015,2017,2018),(2018,2020,2021)]:
  tr=f[f.ld.dt.year.between(2010,end)];va=f[f.ld.dt.year.between(start,stop)]
  assert not set(tr.index)&set(va.index);assert (tr.ld+pd.Timedelta(days=365)).max()<va.ld.min();assert (va.ld+pd.Timedelta(days=365)).le(ref).all()
  y,yv=target(tr),target(va)
  m=fit(Pipeline([('onehot',OneHotEncoder(handle_unknown='ignore')),('logistic',LogisticRegression(C=1,solver='lbfgs',max_iter=2000,random_state=0))]),features(tr),y)
  pred={'constant':np.full(len(va),y.mean()),'logistic':m.predict_proba(features(va))[:,1]}
  rf=fit(Pipeline([('onehot',OneHotEncoder(handle_unknown='ignore')),('forest',RandomForestClassifier(n_estimators=150,max_depth=8,min_samples_leaf=30,max_features='sqrt',random_state=0,n_jobs=2))]),features(tr),y)
  pred['forest']=rf.predict_proba(features(va))[:,1]
  scores={n:metrics(yv,p) for n,p in pred.items()};groups=[]
  for name,p in pred.items():
   assert np.isfinite(p).all() and ((p>=0)&(p<=1)).all()
   for field in ['coverage','gu','category']:
    local=[]
    for group in va[field].astype('string').fillna('__MISSING__').unique():
     mask=va[field].astype('string').fillna('__MISSING__').eq(group).to_numpy();g=metrics(yv[mask],p[mask]);local.append(g);groups.append({'model':name,'field':field,'group':str(group),**g})
    assert sum(g['n'] for g in local)==len(va) and sum(g['events'] for g in local)==int(yv.sum())
    for k in ['brier','log_loss','predicted_pct','actual_pct']:assert np.isclose(sum(g[k]*g['n'] for g in local)/len(va),scores[name][k])
  if start==2020:
   assert len(tr)==old['train_n']
   for name in ['constant','logistic']:
    for k in ['n','events','brier','log_loss','predicted_pct']:assert np.isclose(scores[name][k],old['validation'][name][k],atol=1e-8,rtol=1e-6),(name,k)
  prev=next(w for w in previous['windows'] if w['window']==f'{start}-{stop}')
  assert len(tr)==prev['train_n']
  for name in ['constant','logistic']:
   for k in ['n','events','brier','log_loss','predicted_pct']:assert np.isclose(scores[name][k],prev['scores'][name][k],rtol=1e-6,atol=1e-8)
  for g in groups:
   if g['model']=='forest':continue
   oldg=next(q for q in prev['groups'] if all(q[k]==g[k] for k in ['model','field','group']))
   for k in ['n','events','brier','log_loss']:assert np.isclose(g[k],oldg[k])
  results.append({'window':f'{start}-{stop}','train_n':len(tr),'scores':scores,'groups':groups})
 passed=all(w['scores']['forest'][k]<w['scores'][b][k] for w in results for b in ['constant','logistic'] for k in ['brier','log_loss'])
 area_pass=True
 lines=['# 면적 없는 전체대상 RF 비교','','입력: 업태·구군·개업 월. 누락 여부는 사후 진단에만 사용. 주변 이력 모델은 이번에 실험하지 않았다.','','| 기간 | 대상 | 모델 | n | 실제% | 예측% | Brier | log loss |','| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |']
 for w in results:
  for group in ['all','area_excluded']:
   scores=w['scores'] if group=='all' else {g['model']:g for g in w['groups'] if g['field']=='coverage' and g['group']==group}
   if group=='area_excluded':area_pass &= all(scores['forest'][k]<scores[b][k] for b in ['constant','logistic'] for k in ['brier','log_loss'])
   for name,m in scores.items():lines.append(f"| {w['window']} | {group} | {name} | {m['n']} | {m['actual_pct']:.2f} | {m['predicted_pct']:.2f} | {m['brier']:.6f} | {m['log_loss']:.6f} |")
 report={'windows':results,'overall_pass':passed,'area_excluded_pass':bool(area_pass),'hashes':{'stores':snapshot_sha256(sp),'raw':snapshot_sha256(rp),'script':snapshot_sha256(Path(__file__)),'plan':snapshot_sha256(out/'no_area_forest_plan.md'),'baseline':snapshot_sha256(out/'full_coverage.json')}}
 (out/'no_area_forest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
 lines+=['',f'三期間通過: overall={passed}, area_excluded={area_pass}'.replace('三期間通過','三期間通過'.replace('三期間通過','세 기간 두 기준선 대비 두 오차 개선')),'','기존 기준선과 그룹 점수 재현·해시·시간 간격·그룹 가중 합계 검사 통과. 누락 원인/시점은 미확인. 새로운 독립 시험이 아니며 2023~2025 및 DB/서비스 변경 없음.']
 (out/'no_area_forest.md').write_text('\n'.join(lines)+'\n',encoding='utf-8');print('\n'.join(lines))
if __name__=='__main__':main()
