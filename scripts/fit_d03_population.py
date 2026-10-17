"""Predeclared population comparison on identical eight-district validation rows."""
from fit_d03 import *
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import StandardScaler
from join_d03_population import join_population
import hashlib

def main():
 out=ROOT/'docs/d03';audit=json.loads((out/'population_join.json').read_text(encoding='utf-8'))
 verify_snapshot_hash(out/'population_monthly.json',audit['hashes']['population_monthly'])
 verify_snapshot_hash(ROOT/'scripts/join_d03_population.py',audit['hashes']['script'])
 raw=json.loads((out/'population_monthly.json').read_text(encoding='utf-8'))
 for src in raw['sources']:assert hashlib.sha256((ROOT/'data/raw/d03_population'/src['file']).read_bytes()).hexdigest()==src['sha256']
 protocol=json.loads((out/'protocol.json').read_text(encoding='utf-8'))
 for name,digest in protocol['hashes'].items():verify_snapshot_hash(ROOT/name,digest)
 pop=pd.DataFrame(raw['rows']);st=pd.read_parquet(ROOT/'service/data/processed/stores.parquet')
 districts=['중구','동구','서구','남구','북구','수성구','달서구','달성군']
 f=st[st.service.eq('일반음식점') & st.gu.isin(districts) & (st.ld.dt.year.between(2010,2018)|st.ld.dt.year.between(2020,2021))].copy()
 f['row_id']=np.arange(len(f))
 cats=['category','gu','open_month'];nums=['log_population','log_households'];results={};regions=[];calibration={};identities=None
 for lag in [2,3]:
  linked=join_population(f,pop,lag)
  assert linked.population.notna().all() and linked.households.notna().all()
  linked['open_month']=linked.ld.dt.month.astype(str)
  for c in cats:linked[c]=linked[c].astype('string').fillna('__MISSING__').astype(str)
  linked['log_population']=np.log1p(linked.population.astype(float));linked['log_households']=np.log1p(linked.households.astype(float))
  tr=linked[linked.ld.dt.year.between(2010,2018)].copy();va=linked[linked.ld.dt.year.between(2020,2021)].copy().reset_index(drop=True)
  assert len(tr)==22800 and len(va)==5643
  ids=(tr.row_id.tolist(),va.row_id.tolist())
  if identities is None:identities=ids
  else:assert identities==ids
  target=lambda a:(a.closed & (a.cd-a.ld).dt.days.le(365)).astype(int).to_numpy()
  y=target(tr);yv=target(va)
  if lag==2:
   results['constant']=metrics(yv,np.full(len(va),y.mean()))
  for label,extra in ([('base',False),('population_2m',True)] if lag==2 else [('population_3m',True)]):
   transforms=[('categories',OneHotEncoder(handle_unknown='ignore'),cats)]
   if extra:transforms.append(('numeric',StandardScaler(),nums))
   model=Pipeline([('features',ColumnTransformer(transforms)),('logistic',LogisticRegression(C=1,class_weight=None,solver='lbfgs',max_iter=2000,random_state=0))])
   columns=cats+nums if extra else cats
   with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter('always');model.fit(tr[columns],y)
   assert not any(issubclass(w.category,ConvergenceWarning) for w in caught)
   p=model.predict_proba(va[columns])[:,1];assert np.isfinite(p).all() and ((p>=0)&(p<=1)).all()
   results[label]=metrics(yv,p)
   for gu,idx in va.groupby('gu').groups.items():
    ix=np.asarray(list(idx));regions.append({'model':label,'gu':gu,**metrics(yv[ix],p[ix])})
   c=pd.DataFrame({'bin':pd.cut(p,[-.000001,.05,.1,.15,.2,.3,.5,1],include_lowest=True),'prediction':p,'event':yv}).groupby('bin',observed=True).agg(n=('event','size'),predicted=('prediction','mean'),actual=('event','mean')).reset_index()
   c['bin']=c['bin'].astype(str);calibration[label]=json.loads(c.to_json(orient='records'))
 result={'scope':'follow-up exploratory validation only; prior test untouched; historical release dates not verified','train_n':22800,'validation_n':5643,'results':results,'regions':regions,'calibration':calibration,
 'versions':{'python':platform.python_version(),'numpy':np.__version__,'pandas':pd.__version__,'scikit-learn':sklearn.__version__,'scipy':scipy.__version__},
 'hashes':{'script':snapshot_sha256(Path(__file__)),'plan':snapshot_sha256(out/'population_join.md'),'population':snapshot_sha256(out/'population_monthly.json'),'stores':protocol['hashes']['service/data/processed/stores.parquet']}}
 (out/'population_validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 lines=['# D-03 인구 추가 후속 탐색 결과','','학습 2010~2018년 22,800건, 검증 2020~2021년 5,643건. 군위군 제외 8개 구군의 동일 인허가 표본에서 비교했다. 기존 전체 지역 결과와 모집단이 다르다. 2023~2024년은 예측·채점하지 않았다.','','```text',pd.DataFrame(results).T.to_string(),'```','',
 'base는 업태·구군·개업 월, population_2m/3m은 여기에 각각 개업 2/3개월 전 총인구·세대수의 log1p와 학습자료로 적합한 표준화를 추가했다. C=1 등 설정은 고정했다. constant는 이번 학습 표본의 사건 비율이다.','','## 구군별 결과','','```text',pd.DataFrame(regions).to_string(index=False),'```','',
 '## 제한','','기존 검증 결과를 본 뒤 설계한 후속 탐색이며 독립적인 성능 입증이 아니다. 2개월·3개월 시차는 당시 공개일 확인을 대신하는 가정이다. 과거 수정 이력·인구 정의 변화·행정경계 한계가 남는다. 군위군·전체 대구·실제 미래 성능으로 일반화하지 않는다. 확률구간별 실제 사건 비율은 population_validation.json에 보존했다.', '',
 '동일 표본·연결 후 누락 없음·입력 해시·수렴·확률 범위 검사를 통과했다. 원본·DB·운영 모델은 변경하지 않았다.','','재현: `python scripts/fit_d03_population.py` (기존 분석 가상환경).','']
 (out/'population_validation.md').write_text('\n'.join(l.rstrip() for l in '\n'.join(lines).splitlines())+'\n',encoding='utf-8')
 print(json.dumps(results,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
