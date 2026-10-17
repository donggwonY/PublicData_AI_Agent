"""Inventory local auxiliary snapshots for historical prediction eligibility."""
import json
from pathlib import Path
import pandas as pd
from snapshot_hashes import snapshot_sha256
ROOT=Path(__file__).resolve().parents[1]

def main():
 data=ROOT/'service/data/processed'; rows=[]
 for name in ['poi','area_context','legal_admin_map','station_traffic','parking','market']:
  path=data/(name+'.parquet');f=pd.read_parquet(path)
  datecols=[c for c in f if any(t in c.lower() for t in ['date','month','year','time','기준','일자','연월'])]
  dates={c:{'distinct':int(f[c].nunique()),'sample':f[c].dropna().astype(str).drop_duplicates().head(12).tolist()} for c in datecols}
  rows.append({'table':name,'rows':len(f),'date_columns':dates,'sha256':snapshot_sha256(path),'historical_features_approved':False})
 out=ROOT/'docs/d03';r={'scope':'local processed snapshots and pipeline only; no remote archive availability claim','tables':rows,
 'decision':'Do not add current auxiliary snapshots to historical opening-time prediction. Need observation date, publication availability date and historical geography.'}
 (out/'auxiliary_audit.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps(r,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
