"""Independent rerun of fixed E06 G1 only; never tune or overwrite E06 outputs."""
import json,sys
from pathlib import Path
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from snapshot_hashes import snapshot_sha256
src=ROOT/'scripts/e06_competition/models.py';text=src.read_text(encoding='utf-8');prefix=text.split('# ── G2 LightGBM')[0]
assert 'LAST_YEAR, FIRST_TARGET = 2022, 2010' in prefix
prefix=prefix.replace('LAST_YEAR, FIRST_TARGET = 2022, 2010','LAST_YEAR, FIRST_TARGET = 2025, 2010')
ns={'__file__':str(src),'__name__':'e06_readonly_review'};exec(compile(prefix,'e06_g1_fixed_prefix','exec'),ns)
saved=json.loads((ROOT/'docs/e06/results/test.json').read_text(encoding='utf-8'));assert saved['input_sha256']==snapshot_sha256(ns['SRC'])
P=ns['build'](['gu']);rolling=ns['rolling'];mae=ns['mae']
pre,_=rolling(P,'closes',[2020,2021,2022],.3);vm=P.year.isin([2020,2021,2022]);vscore=round(mae(P.loc[vm,'closes'],pre[vm]),4);assert vscore==saved['precheck_val_G1_closes_mae']
pred,_=rolling(P,'closes',[2023,2024,2025],.3);mask=P.year.isin([2023,2024,2025]);y=P.loc[mask,'closes'].to_numpy();mu=pred[mask].to_numpy()
observed={'G1':round(mae(y,mu),4)}
for name,col in [('B1','closes_l1'),('B2','closes_m3'),('B3','closes_m5')]:observed[name]=round(mae(y,P.loc[mask,col]),4)
assert all(observed[k]==saved['tier1_closes']['mae'][k] for k in observed)
assert int(mask.sum())==saved['tier1_closes']['cells']
years={}
for yr in [2023,2024,2025]:
 ix=P.year.eq(yr);years[str(yr)]=round(mae(P.loc[ix,'closes'],pred[ix]),4);assert years[str(yr)]==saved['tier1_closes']['by_year'][str(yr)]['G1']
lo=ns['ppf_counts'](.1,mu);hi=ns['ppf_counts'](.9,mu);cov=round(float(((y>=lo)&(y<=hi)).mean()),3);assert cov==saved['tier1_closes']['cov80_poisson']
ci=ns['boot'](np.abs(y-mu)-np.abs(y-P.loc[mask,'closes_m3'].to_numpy()),(P.loc[mask,'year'].astype(str)+'|'+P.loc[mask,'category']).to_numpy());assert ci==saved['tier1_closes']['improvement_vs_best_ci95']
# Check future-event perturbation leaves <=2022 feature/target rows unchanged.
original=ns['s'];changed=original.copy();changed.loc[changed.oy>2022,'oy']+=50;changed.loc[changed.cy>2022,'cy']+=50
future=changed.ld>pd.Timestamp('2022-12-31');changed.loc[future,'ld']=changed.loc[future,'ld']+pd.DateOffset(years=50)
future=changed.cd>pd.Timestamp('2022-12-31');changed.loc[future,'cd']=changed.loc[future,'cd']+pd.DateOffset(years=50)
ns['s']=changed;Q=ns['build'](['gu']);ns['s']=original
cols=['key','year','closes']+ns['NUM']+['daegu_cat_trend','gu_trend']
x=P[P.year<=2022][cols].sort_values(['key','year']).reset_index(drop=True);z=Q[Q.year<=2022][cols].sort_values(['key','year']).reset_index(drop=True)
pd.testing.assert_frame_equal(x,z)
# Independent Poisson quantile check using scipy, not the custom implementation.
from scipy.stats import poisson
assert np.array_equal(lo,poisson.ppf(.1,mu)) and np.array_equal(hi,poisson.ppf(.9,mu))
quality={'retained_records':len(original),'closed_missing_date':int((original.closed&original.cd.isna()).sum()),'closure_before_open':int((original.cd<original.ld).sum()),'missing_gu':int(original.gu.isna().sum())}
out={'scope':'Read-only replication of fixed G1 validation and test metrics; not a new independent test, no retuning. G2 and other targets not rerun.','validation_mae':vscore,'test_mae':observed,'test_year_G1':years,'test_cells':int(mask.sum()),'interval_coverage':cov,'bootstrap_ci95':ci,'checks':{'saved_input_hash':True,'metrics_match':True,'future_event_perturbation_through2022':True,'poisson_quantiles_scipy_match':True},'quality':quality,'notes':['Historical snapshot category, location and is_primary are not proven point-in-time; future-event perturbation does not remove these limitations.','Feature category levels and panel keys derived from full snapshot; eligibility depends on lagged activity.','Trend denominator in code is years y-2..y-4, numerator y-1; report wording previous3 mean is ambiguous.','Observed80% coverage is aggregate, not guarantee per district/category.','Review reruns fixed published model only; does not create a fresh holdout.'],'hashes':{'source':snapshot_sha256(ns['SRC']),'models_script':snapshot_sha256(src),'saved_test':snapshot_sha256(ROOT/'docs/e06/results/test.json'),'review_script':snapshot_sha256(Path(__file__))}}
dest=ROOT/'docs/d03/e06_closures_crosscheck.json';dest.write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(out,ensure_ascii=False),flush=True)
