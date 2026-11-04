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
 prior=json.loads((out/'no_area_forest.json').read_text(encoding='utf-8'))
 verify_snapshot_hash(ROOT/'scripts/audit_d03_no_area_forest.py',prior['hashes']['script'])
 review=json.loads((out/'event_marker_review.json').read_text(encoding='utf-8'))
 verify_snapshot_hash(out/'event_markers.json',review['hashes']['source'])
 marker=json.loads((out/'event_markers.json').read_text(encoding='utf-8'))
 verify_snapshot_hash(sp,marker['hashes']['stores']);verify_snapshot_hash(rp,marker['hashes']['raw'])
 scope=json.loads((out/'event_sensitivity_scope.json').read_text(encoding='utf-8'));verify_snapshot_hash(out/'event_marker_review.json',scope['hashes']['review'])
 selected={q['key'] for q in review['rows'] if q['review_category'] in ['들안길 푸드페스티벌','세계인의 날','시장 굿페스티벌']};assert len(selected)==61
 assert key.is_unique;f['marked']=key.isin(selected)
 make=lambda:Pipeline([('onehot',OneHotEncoder(handle_unknown='ignore')),('forest',RandomForestClassifier(n_estimators=150,max_depth=8,min_samples_leaf=30,max_features='sqrt',random_state=0,n_jobs=2))])
 windows=[]
 for end,start,stop in [(2015,2017,2018),(2018,2020,2021)]:
  tr=f[f.ld.dt.year.between(2010,end)];va=f[f.ld.dt.year.between(start,stop)]
  assert not set(tr.index)&set(va.index);assert (tr.ld+pd.Timedelta(days=365)).max()<va.ld.min();assert (va.ld+pd.Timedelta(days=365)).le(ref).all()
  expected=(0,50) if start==2017 else (50,0);assert (int(tr.marked.sum()),int(va.marked.sum()))==expected
  y=target(tr);yv=target(va);rf=fit(make(),features(tr),y);pv=rf.predict_proba(features(va))[:,1]
  oldw=next(w for w in prior['windows'] if w['window']==f'{start}-{stop}')
  assert len(tr)==oldw['train_n']
  for name,pred in [('forest',pv),('constant',np.full(len(va),y.mean()))]:
   m=metrics(yv,pred)
   for k in ['n','events','brier','log_loss','predicted_pct']:assert np.isclose(m[k],oldw['scores'][name][k],rtol=1e-6,atol=1e-8)
   for q in oldw['groups']:
    if q['model']!=name:continue
    mask=va[q['field']].astype('string').fillna('__MISSING__').eq(q['group']).to_numpy();gm=metrics(yv[mask],pred[mask])
    for k in ['n','events','brier','log_loss']:assert np.isclose(gm[k],q[k],rtol=1e-6,atol=1e-8)
  rows=[]
  variants={'original':(pv,np.full(len(va),y.mean()),len(tr))}
  if start==2020:
   reduced=tr[~tr.marked];yr=target(reduced);new=fit(make(),features(reduced),yr)
   variants['train_without_marked']=(new.predict_proba(features(va))[:,1],np.full(len(va),yr.mean()),len(reduced))
  masks={'all':np.ones(len(va),dtype=bool),'area_excluded':va.coverage.eq('area_excluded').to_numpy()}
  if start==2017:masks.update({'evaluation_without_marked':~va.marked.to_numpy(),'marked_only':va.marked.to_numpy()})
  for variant,(pred,constant,train_n) in variants.items():
   assert np.isfinite(pred).all() and ((pred>=0)&(pred<=1)).all()
   for group,mask in masks.items():
    for name,p in [('forest',pred),('constant',constant)]:rows.append({'variant':variant,'group':group,'model':name,'train_n':train_n,**metrics(yv[mask],p[mask])})
  if start==2017:
   for name in ['forest','constant']:
    get=lambda g:next(q for q in rows if q['group']==g and q['model']==name)
    a,b,c=get('all'),get('evaluation_without_marked'),get('marked_only')
    assert b['n']+c['n']==a['n'] and b['events']+c['events']==a['events']
    for k in ['brier','log_loss','predicted_pct']:assert np.isclose((b[k]*b['n']+c[k]*c['n'])/a['n'],a[k])
  windows.append({'window':f'{start}-{stop}','train_marked':expected[0],'evaluation_marked':expected[1],'rows':rows})
 first=prior['windows'][0];assert not f[f.ld.dt.year.between(2010,2016)].marked.any()
 report={'scope':'retrospective event-marker sensitivity; not prospective improvement','reused_first_window':first['window'],'reused_first_scores':first['scores'],'windows':windows,'hashes':{'script':snapshot_sha256(Path(__file__)),'plan':snapshot_sha256(out/'event_sensitivity_plan.md'),'baseline':snapshot_sha256(out/'no_area_forest.json'),'review':snapshot_sha256(out/'event_marker_review.json'),'stores':snapshot_sha256(sp),'raw':snapshot_sha256(rp)}}
 (out/'event_sensitivity.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
 lines=['# 행사명 표기50건 민감도 비교','','2015~2016은 학습·평가 모두 해당 기록이 없어 기존 결과 재사용. 2017~2018은 평가 구성 변화, 2020~2021은 학습 구성 변화다. 주소의 행사명 표기는 최신 원본 기반 사후 정보이며 한시허가 확정이 아니다.','','| 기간 | 변경 | 평가집단 | 모델 | n | 실제% | 예측% | Brier | log loss |','| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |']
 for w in windows:
  for q in w['rows']:lines.append(f"| {w['window']} | {q['variant']} | {q['group']} | {q['model']} | {q['n']} | {q['actual_pct']:.2f} | {q['predicted_pct']:.2f} | {q['brier']:.6f} | {q['log_loss']:.6f} |")
 lines+=['','既存'.replace('既存','기존')+' 전체/그룹 점수 재현·입력/규칙 해시·키 유일성·대상50건·시간간격·확률·평가분할 가중합 검사 통과. 원본 삭제/DB/서비스 변경 없음. 2023~2025 재평가 없음. 평가집단을 바꾼 오차 감소는 모델 개선으로 해석하지 않는다.']
 (out/'event_sensitivity.md').write_text('\n'.join(lines)+'\n',encoding='utf-8');print('\n'.join(lines))
if __name__=='__main__':main()
