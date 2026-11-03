"""Frozen full-coverage baseline audit; no 2023-2025 scoring."""
import json,sys
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
 results=[]
 for end,start,stop in [(2013,2015,2016),(2015,2017,2018),(2018,2020,2021)]:
  tr=f[f.ld.dt.year.between(2010,end)];va=f[f.ld.dt.year.between(start,stop)]
  assert not set(tr.index)&set(va.index);assert (tr.ld+pd.Timedelta(days=365)).max()<va.ld.min();assert (va.ld+pd.Timedelta(days=365)).le(ref).all()
  y,yv=target(tr),target(va)
  m=fit(Pipeline([('onehot',OneHotEncoder(handle_unknown='ignore')),('logistic',LogisticRegression(C=1,solver='lbfgs',max_iter=2000,random_state=0))]),features(tr),y)
  pred={'constant':np.full(len(va),y.mean()),'logistic':m.predict_proba(features(va))[:,1]}
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
   for name in scores:
    for k in ['n','events','brier','log_loss','predicted_pct']:assert np.isclose(scores[name][k],old['validation'][name][k],atol=1e-8,rtol=1e-6),(name,k)
  results.append({'window':f'{start}-{stop}','train_n':len(tr),'scores':scores,'groups':groups})
 passed=all(w['scores']['logistic'][k]<w['scores']['constant'][k] for w in results for k in ['brier','log_loss'])
 report={'scope':'reused historical full population and missing-input groups; no new independent validation','windows':results,'passed':passed,'hashes':{'stores':snapshot_sha256(sp),'raw':snapshot_sha256(rp),'script':snapshot_sha256(Path(__file__)),'plan':snapshot_sha256(out/'full_coverage_plan.md')}}
 (out/'full_coverage.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
 lines=['# 누락 포함 전체 대상 평가','','면적·좌표 누락 행을 포함하되 입력은 업태·구군·개업 월만 사용했다. 기존2020~2021 전체 점수 재현 통과. 신규 독립 시험이 아니며2023~2025 재채점 없음.','','| 기간 | 그룹 | n | 신고 | 실제% | 예측% | Brier(기준선→모델) | log loss(기준선→모델) |','| --- | --- | ---: | ---: | ---: | ---: | --- | --- |']
 for w in results:
  pairs=[('전체',w['scores']['constant'],w['scores']['logistic'])]
  for g in [r for r in w['groups'] if r['field']=='coverage' and r['model']=='logistic']:
   b=next(r for r in w['groups'] if r['field']=='coverage' and r['model']=='constant' and r['group']==g['group']);pairs.append((g['group'],b,g))
  for group,b,m in pairs:lines.append(f"| {w['window']} | {group} | {m['n']} | {m['events']} | {m['actual_pct']:.2f} | {m['predicted_pct']:.2f} | {b['brier']:.6f} → {m['brier']:.6f} | {b['log_loss']:.6f} → {m['log_loss']:.6f} |")
 lines+=['',f'세기간 전체표본에서 두 오차 모두 기준선보다 개선: {passed}.','', '과거 주소/업태 시점·최신 스냅샷 누락 한계 유지. 가공 전 제외 원천까지 포함한 모집단은 아니다. 누락 여부는 진단에만 사용했고 결과를 보고 대체/모델 분기하지 않았다. 과거 그룹 결과를2025 제외293건의 성능으로 해석하지 않는다. 입력 해시·날짜간격·비중복·확률·수렴·합계 검사 통과. [계획](full_coverage_plan.md), [결과](full_coverage.json).']
 (out/'full_coverage.md').write_text('\n'.join(lines)+'\n',encoding='utf-8');print('\n'.join(lines),flush=True)
if __name__=='__main__':main()
