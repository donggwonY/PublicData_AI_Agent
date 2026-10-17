"""Audit lagged population joins; lag is an explicit assumption, not release verification."""
import json,hashlib
from pathlib import Path
import pandas as pd
from snapshot_hashes import snapshot_sha256,verify_snapshot_hash
ROOT=Path(__file__).resolve().parents[1]

def join_population(frame,pop,lag):
    f=frame.copy()
    f['population_month']=(f.ld.dt.to_period('M')-lag).astype(str)
    before=len(f)
    f=f.merge(pop[['gu','reference_month','reference_date','population','households','status']],left_on=['gu','population_month'],right_on=['gu','reference_month'],how='left',validate='many_to_one',indicator=True)
    assert len(f)==before
    found=f.population.notna()
    assert (pd.to_datetime(f.loc[found,'reference_date'])<f.loc[found,'ld']).all()
    f['population_join_status']='matched_under_lag_assumption'
    f.loc[~found,'population_join_status']='missing'
    f.loc[~found & f.gu.eq('군위군'),'population_join_status']='gunwi_history_unavailable'
    f.loc[f.gu.isna(),'population_join_status']='missing_region'
    return f

def main():
    out=ROOT/'docs/d03';p=out/'population_monthly.json';meta=json.loads(p.read_text(encoding='utf-8'))
    for src in meta['sources']:
        assert hashlib.sha256((ROOT/'data/raw/d03_population'/src['file']).read_bytes()).hexdigest()==src['sha256']
    protocol=json.loads((out/'protocol.json').read_text(encoding='utf-8'))
    for name,digest in protocol['hashes'].items():verify_snapshot_hash(ROOT/name,digest)
    pop=pd.DataFrame(meta['rows']);assert not pop.duplicated(['gu','reference_month']).any()
    st=pd.read_parquet(ROOT/'service/data/processed/stores.parquet')
    f=st[st.service.eq('일반음식점') & st.ld.dt.year.between(2010,2024)].copy()
    f['split']='unused_gap'
    for label,lo,hi in [('train',2010,2018),('validation',2020,2021),('previous_test',2023,2024)]:f.loc[f.ld.dt.year.between(lo,hi),'split']=label
    results=[]
    for lag in [2,3]:
        linked=join_population(f,pop,lag)
        for name,g in linked.groupby('split'):
            results.append({'lag_months':lag,'split':name,'n':len(g),'matched':int(g.population.notna().sum()),'missing':int(g.population.isna().sum()),'statuses':g.population_join_status.value_counts().to_dict()})
    # Calendar-year boundary and structural 0 handling, independent tiny samples.
    tiny=pd.DataFrame({'gu':['중구','군위군'],'ld':pd.to_datetime(['2010-01-01','2023-08-01'])})
    check=join_population(tiny,pop,2)
    assert check.population_month.tolist()==['2009-11','2023-06']
    assert pd.notna(check.population.iloc[0]) and pd.isna(check.population.iloc[1])
    result={'scope':'retrospective join feasibility only, not proof of historical availability','default_lag_months':2,'sensitivity_lag_months':3,
            'release_evidence':{'url':'https://jumin.mois.go.kr/statMonth.do','checked':'2026-10-17','current_rule':'Month-end reference, next-month day 1 after noon; next weekday for weekends/holidays','historical_release_dates_verified':False,'historical_vintages_verified':False},
            'results':results,'checks':['raw byte hashes','input snapshot hash','unique gu/month','many-to-one no row increase','reference date precedes opening','year-boundary example','Gunwi zero is missing'],
            'hashes':{'population_monthly':snapshot_sha256(p),'script':snapshot_sha256(Path(__file__))}}
    (out/'population_join.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result['results'],ensure_ascii=False,indent=2))
if __name__=='__main__':main()
