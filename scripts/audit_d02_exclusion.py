"""Reproduce the 31 flagged-unit exclusion sensitivity; never edit input data."""
import hashlib
import json
import pandas as pd
from audit_d02_units import ROOT, DEMO


def main():
    data=DEMO/'data/processed'
    manifest=json.loads((ROOT/'docs/d01/manifest.json').read_text(encoding='utf-8'))
    for name,digest in manifest['sha256'].items():
        assert hashlib.sha256((data/name).read_bytes()).hexdigest()==digest,name
    u=pd.read_parquet(data/'units.parquet');s=pd.read_parquet(data/'stores.parquet')
    flagged=u.is_single_unit & u.n_active.gt(1)
    assert int(flagged.sum())==31
    ids=set(u.loc[flagged,'uid']);rows=[]
    for label,us,ss in [('include',u,s),('exclude',u[~flagged],s[~s.uid.isin(ids)])]:
        live=(~us.vacant)|(us.vacant_days<=1095)
        rows.append({'case':label,'units':len(us),'stores':len(ss),'vacancy_denominator':int(live.sum()),'vacancy_candidates':int(us.recent_vacancy.sum()),'vacancy_candidate_pct':round(100*us.recent_vacancy.sum()/live.sum(),4)})
    assert rows[0]['vacancy_candidates']==rows[1]['vacancy_candidates']
    result={'reference_date':manifest['reference_date'],'input_hashes_verified':len(manifest['sha256']),
            'scope':'Excludes all permit histories belonging to the 31 flagged uids; no source edits. Descriptive vacancy sensitivity only; not all downstream analyses.','results':rows}
    (ROOT/'docs/d02/flagged_exclusion.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
