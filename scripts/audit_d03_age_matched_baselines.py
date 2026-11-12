"""Same-feature age-table baselines against the frozen 96-quarter candidate."""
import json
from pathlib import Path
import pandas as pd,numpy as np
from fit_d03 import metrics
from snapshot_hashes import snapshot_sha256
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/d03'

def main():
 source=OUT/'all_quarters_evaluation.json';r=json.loads(source.read_text(encoding='utf-8'))
 path=ROOT/'service/data/processed/stores.parquet';assert snapshot_sha256(path)==r['hashes']['stores']
 f=pd.read_parquet(path);f['industry']=f.service.replace({'의원':'의원·병원','병원':'의원·병원'})
 bad=f.ld.isna()|(f.closed&f.cd.isna())|(f.cd<f.ld)|(~f.closed&f.cd.notna())|f.industry.isna();f=f[~bad].copy()
 def cohort(t):
  a=f[f.ld.le(t)&(f.cd.isna()|f.cd.gt(t))].copy().reset_index(drop=True)
  a['age_band']=pd.cut((t-a.ld).dt.days,[-1,364,1094,1824,3649,np.inf],labels=['<1','1-3','3-5','5-10','10+']).astype(str)
  a['y']=(a.closed&a.cd.gt(t)&a.cd.le(t+pd.Timedelta(days=365))).astype(int)
  a['gu']=a.gu.fillna('__MISSING__').astype(str)
  return a
 cache={};results=[]
 for w in r['results']:
  if w['cal'] not in cache:
   a=cohort(pd.Timestamp(w['cal']))
   region={(name,gu):(len(g),int(g.y.sum())) for (name,gu),g in a.groupby(['industry','gu'])}
   age={(name,gu,band):(len(g),int(g.y.sum())) for (name,gu,band),g in a.groupby(['industry','gu','age_band'])}
   cache[w['cal']]=(region,age)
  region,age=cache[w['cal']];b=cohort(pd.Timestamp(w['landmark']))
  assert len(b)==w['scores']['candidate']['n'] and int(b.y.sum())==w['scores']['candidate']['events']
  base_by_industry={g['industry']:g['scores']['baseline']['predicted_pct']/100 for g in w['groups']}
  predictions={'region_shrink500':[],'age_shrink500':[],'age_plain':[]}
  missing=0
  for name,gu,band in zip(b.industry,b.gu,b.age_band):
   n,e=region.get((name,gu),(0,0));parent=(e+500*base_by_industry[name])/(n+500)
   an,ae=age.get((name,gu,band),(0,0));missing+=int(an==0)
   predictions['region_shrink500'].append(parent)
   predictions['age_shrink500'].append((ae+500*parent)/(an+500))
   predictions['age_plain'].append(ae/an if an else parent)
  predictions={k:np.array(v) for k,v in predictions.items()};y=b.y.to_numpy()
  scores={k:metrics(y,v) for k,v in predictions.items()};scores['candidate']=w['scores']['candidate']
  groups=[]
  prior={g['industry']:g for g in w['groups']}
  for name,g in b.groupby('industry'):
   ix=g.index.to_numpy();ss={k:metrics(y[ix],v[ix]) for k,v in predictions.items()};ss['candidate']=prior[name]['scores']['candidate']
   groups.append({'industry':name,'small_sample':bool(len(g)<200 or g.y.sum()<20),'scores':ss})
  for name in scores:
   for metric in ['brier','log_loss']:assert abs(sum(g['scores'][name][metric]*g['scores'][name]['n'] for g in groups)/len(b)-scores[name][metric])<1e-12
  results.append({'landmark':w['landmark'],'scores':scores,'groups':groups,'age_cell_fallback_rows':missing})
  if w['landmark'].endswith('10-01'):print('completed',w['landmark'][:4],flush=True)
 out={'protocol':{'primary_baseline':'age_shrink500','parent':'industry-region mean shrunk to industry mean with pseudo-n500','age_cell':'industry-region-ageband rate shrunk to parent with pseudo-n500','secondary':'unshrunk age cell; missing cell uses parent','features':'Same industry,gu,age bands as fixed candidate','calibration':'Same previous calibration year as candidate; no evaluation labels used for predictions','scope':'All existing96quarters, unchanged cohort and candidate, no tuning'},'results':results,'hashes':{'input':snapshot_sha256(source),'stores':snapshot_sha256(path),'script':snapshot_sha256(Path(__file__))},'limitations':['Post-hoc model comparison; not fresh independent test.','Fixed500 may over-shrink small cells; plain age table reported as sensitivity rather than selecting best per period.','Overlapping horizons/current snapshot/historical completeness limitations remain.']}
 (OUT/'age_matched_baselines.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
 lines=['# 운영기간을 포함한 동일 입력 기준선 비교','','모델의 입력인 업종·지역·운영기간을 모두 사용한 단순 신고율 표와 비교했습니다. 이전 보정연도만 사용하고 지역과 운영기간 단계에 가상표본500으로 축소합니다. 축소하지 않은 표도 함께 보고합니다. 설정 변경·재학습은 하지 않았습니다.','','|기간|분기|모델이 지역평균보다 두 오차 개선|모델이 운영기간 축소평균보다 개선|모델이 운영기간 단순평균보다 개선|','|---|---:|---:|---:|---:|']
 summaries=[]
 for label,start in [('전체','2002-01-01'),('2013년 이후','2013-01-01'),('최근3년','2023-01-01')]:
  selected=[w for w in results if w['landmark']>=start]
  wins={base:sum(all(w['scores']['candidate'][k]<w['scores'][base][k] for k in ['brier','log_loss']) for w in selected) for base in predictions}
  summaries.append({'scope':label,'n_quarters':len(selected),'model_wins':wins})
  lines.append(f"|{label}|{len(selected)}|{wins['region_shrink500']}|{wins['age_shrink500']}|{wins['age_plain']}|")
 lines+=['','업종별 상세 점수·미관측 운영기간 조합 수는 JSON에 보존했습니다. 동일한 입력정보를 쓰더라도 함수형태와 축소강도가 달라 특정 기준선이 반드시 강하다고 가정하지 않습니다. 분기별로 유리한 모델을 골라 최종 성능으로 보고하지 않습니다. 기존 실험의 사후 검증이며 서비스 모델은 변경하지 않았습니다.']
 (OUT/'age_matched_baselines.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
 print(json.dumps(summaries,ensure_ascii=False),flush=True)
 print('LATEST',results[-1]['scores'],flush=True)
if __name__=='__main__':main()
