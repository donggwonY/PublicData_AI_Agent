"""Exploratory building-cluster bootstrap, fixed pooled opening-year weights."""
import json
from pathlib import Path
import numpy as np,pandas as pd
from snapshot_hashes import snapshot_sha256
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/d03/opening_neighborhood'
previous=json.loads((OUT/'reproduced_checks.json').read_text(encoding='utf-8'))
p=ROOT/'service/data/processed/stores.parquet';assert snapshot_sha256(p)==previous['hashes']['stores']
f=pd.read_parquet(p);f['industry']=f.service.replace({'의원':'의원·병원','병원':'의원·병원'})
bad=f.ld.isna()|(f.closed&f.cd.isna())|(f.cd<f.ld)|(~f.closed&f.cd.notna())|f.industry.isna()
regions=['중구','동구','서구','남구','북구','수성구','달서구','달성군','군위군']
a=f[~bad&~f.short_event.fillna(False).astype(bool)&f.gu.isin(regions)].copy();a['year']=a.ld.dt.year;a=a[a.year.between(2018,2022)].copy();a['survive']=~(a.cd.notna()&a.cd.le(a.ld+pd.Timedelta(days=1095)));a['building']=a.building_key.astype('string').fillna(a.index.to_series().astype(str))
assert len(a)==previous['regional_records']
rng=np.random.default_rng(20261115);B=1000;rows=[]
for industry,g in a.groupby('industry',sort=True):
 eligible=[x for x in previous['regional'] if x['industry']==industry and x['display_flag']]
 if not eligible:continue
 weights=g.year.value_counts(normalize=True).reindex(range(2018,2023),fill_value=0).to_numpy()
 boot={};totals={};cluster_counts={}
 for gu,z in g.groupby('gu',sort=True):
  ns=pd.crosstab(z.building,z.year).reindex(columns=range(2018,2023),fill_value=0)
  es=z.pivot_table(index='building',columns='year',values='survive',aggfunc='sum',fill_value=0).reindex(index=ns.index,columns=range(2018,2023),fill_value=0)
  n=ns.to_numpy(dtype=float);e=es.to_numpy(dtype=float);k=len(n);cluster_counts[gu]=k
  bn=[];be=[]
  for start in range(0,B,100):
   draws=rng.multinomial(k,np.full(k,1/k),size=min(100,B-start));bn.append(draws@n);be.append(draws@e)
  boot[gu]=(np.vstack(bn),np.vstack(be));totals[gu]=(n.sum(axis=0),e.sum(axis=0))
 totaln=sum(v[0] for v in boot.values());totale=sum(v[1] for v in boot.values())
 pn=sum(v[0] for v in totals.values());pe=sum(v[1] for v in totals.values())
 for prior in eligible:
  gu=prior['gu'];bn,be=boot[gu];on=totaln-bn;oe=totale-be
  good=(bn>0).all(axis=1)&(on>0).all(axis=1)
  rates=100*((be[good]/bn[good])*weights).sum(axis=1);other=100*((oe[good]/on[good])*weights).sum(axis=1);diff=rates-other
  n,e=totals[gu];rate=float(100*((e/n)*weights).sum());delta=float(rate-100*(((pe-e)/(pn-n))*weights).sum())
  assert abs(rate-prior['three_standardized_pct'])<1e-9
  rlo,rhi=np.quantile(rates,[.025,.975]);dlo,dhi=np.quantile(diff,[.025,.975])
  rows.append(dict(industry=industry,gu=gu,n=prior['n'],buildings=cluster_counts[gu],valid_bootstraps=int(good.sum()),rate_pct=rate,rate_lo=float(rlo),rate_hi=float(rhi),difference_pp=delta,difference_lo=float(dlo),difference_hi=float(dhi),interval_excludes_zero=bool(dlo>0 or dhi<0),same_direction_5years=bool(prior['positive_years']==5 or prior['negative_years']==5)))
 print('bootstrap',industry,flush=True)
assert len(rows)==44
out={'method':'1000 bootstrap resamples of buildings within industry and district; all records/years for sampled building retained. Fixed pooled industry opening-year weights. Percentile95 intervals. Seed20261115.','scope':'2018-2022 opening cohorts,1095day no-closure-report proportion. All44 cells with >=30 records in each year; not selected by effect.','limitations':['Exploratory pointwise intervals; 44 comparisons, no multiplicity adjustment, not confirmatory significance.','Nearby buildings may be correlated; clustering by building does not capture broader spatial dependence.','Bootstrap does not fix record errors, administrative boundary changes, relocation or reporting delays.','Same-building dependence across industries/districts is not modeled jointly.','Historical comparisons are not individual forecasts or causal effects.'],'hashes':{'source':snapshot_sha256(p),'previous':snapshot_sha256(OUT/'reproduced_checks.json'),'script':snapshot_sha256(Path(__file__))},'results':rows}
(OUT/'regional_uncertainty.json').write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
pd.DataFrame(rows).to_csv(OUT/'regional_uncertainty.csv',index=False,encoding='utf-8-sig')
lines=['# 지역별 3년 기록 비교의 불확실성','','2018–2022년 개업연도 구성을 맞춘 1095일 이내 폐업 신고 미관측 비율. 같은 건물의 기록을 묶어1000회 재추출했다. 구간은 개별 가게의 예측 범위가 아니라 과거 집단 비율 추정의 흔들림을 나타낸다.','','다른 지역 비교는 같은 업종의 해당 구군 외 지역이며 개업연도 비중을 동일하게 맞췄다. 95% 구간은 각 비교별 탐색용으로44개 동시 비교를 보정하지 않았으므로 확정적 차이나 순위로 해석하지 않는다.','','|업종|지역|기록|건물|비율(%)|95% 구간|다른 지역과 차이(%p)|차이95% 구간|','|---|---|---:|---:|---:|---|---:|---|']
for r in rows:lines.append(f"|{r['industry']}|{r['gu']}|{r['n']}|{r['buildings']}|{r['rate_pct']:.2f}|{r['rate_lo']:.2f}–{r['rate_hi']:.2f}|{r['difference_pp']:.2f}|{r['difference_lo']:.2f}–{r['difference_hi']:.2f}|")
lines+=['','상세 방법·한계·입력 해시는 regional_uncertainty.json. 재실행: service/.venv/Scripts/python.exe scripts/check_regional_cohort_uncertainty.py.']
(OUT/'regional_uncertainty.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print('DONE',len(rows),'interval excludes zero',sum(r['interval_excludes_zero'] for r in rows),'and stable5years',sum(r['interval_excludes_zero'] and r['same_direction_5years'] for r in rows),flush=True)
for r in rows:
 if r['industry']=='미용업' and r['gu'] in ['동구','남구','북구']:print(json.dumps(r,ensure_ascii=False),flush=True)
