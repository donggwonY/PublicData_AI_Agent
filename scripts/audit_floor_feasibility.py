"""Read-only shared DB floor-data feasibility audit; no model fitting."""
import os,re,json,hashlib
from pathlib import Path
from urllib.parse import urlsplit,unquote
import pandas as pd
import psycopg
ROOT=Path(__file__).resolve().parents[1]
vals={}
for line in (ROOT/'.env').read_text(encoding='utf-8-sig').splitlines():
 m=re.match(r'^\s*(?:export\s+)?(\w+)\s*=\s*(.*)$',line)
 if m: vals[m[1]]=m[2].strip().strip('"').strip("'")
url=os.environ.get('APP_READER_DATABASE_URL') or vals.get('APP_READER_DATABASE_URL','')
u=urlsplit(url); user=unquote(u.username or '')
assert user.split('.')[0]=='app_reader'
assert u.hostname=='db.uoiamnbkzlvlskngataq.supabase.co' or (u.hostname.endswith('.pooler.supabase.com') and user.endswith('.uoiamnbkzlvlskngataq'))
with psycopg.connect(url,sslmode='require',connect_timeout=15) as conn:
 conn.read_only=True
 with conn.cursor() as c:
  c.execute('show transaction_read_only'); assert c.fetchone()[0]=='on'
  c.execute("set local statement_timeout='60s'")
  c.execute('select version_id from app.current_version where singleton');v=c.fetchone()[0]
  c.execute('select count(*) from app.stores where version_id=%s',(v,));raw=c.fetchone()[0]
  c.execute("""select extract(year from ld)::int as year,service,gu,floor,count(*) as n
    from app.stores where version_id=%s and is_primary=true and short_event=false
    and ld is not null and ld <= date '2026-11-06'
    group by 1,2,3,4 order by 1,2,3,4""",(v,))
  rows=c.fetchall()
d=pd.DataFrame(rows,columns=['year','service','gu','floor','n'])
def band(x):
 if pd.isna(x) or not str(x).strip():return 'unknown'
 if re.fullmatch(r'지하[1-9][0-9]*층',x):return 'basement'
 if re.fullmatch(r'[1-9][0-9]*층',x):return 'ground' if x=='1층' else 'upper'
 return 'unparsed'
d['band']=d.floor.map(band)
d['known']=d.n.where(d.band.isin(['basement','ground','upper']),0)
d['upper']=d.n.where(d.band.eq('upper'),0)
def summary(keys,data):
 s=data.groupby(keys,dropna=False)[['n','known','upper']].sum().reset_index()
 s['coverage_pct']=(s.known/s.n*100).round(2)
 s['upper_among_known_pct']=(s.upper/s.known.replace(0,float('nan'))*100).round(2)
 return s
out=ROOT/'docs/d05/feasibility';out.mkdir(parents=True,exist_ok=True)
y=summary(['year'],d);sv=summary(['service'],d[d.year.between(2020,2025)])
cells=summary(['year','gu','service'],d[d.year.between(2020,2025)])
# Screening thresholds are feasibility rules, not proof of adequate precision.
cells['screen_pass']=(cells.known>=30)&(cells.coverage_pct>=80)&cells.gu.notna()
for name,frame in [('annual',y),('services_2020_2025',sv),('cells_2020_2025',cells)]:frame.to_csv(out/(name+'.csv'),index=False,encoding='utf-8-sig')
eligible=cells[cells.screen_pass].groupby(['gu','service']).year.nunique()
result={'source':'shared app.stores read-only','version':v,'reference_date':'2026-11-06','raw_rows':raw,'retained_rows':int(d.n.sum()),'rules':'is_primary=true; short_event=false; valid opening date <=reference; floor unknown retained separately; 2026 incomplete excluded from completed-year screening','bands':{str(k):int(val) for k,val in d.groupby('band').n.sum().items()},'recent_annual':y[y.year>=2015].to_dict('records'),'top_services':sv.sort_values('known',ascending=False).head(15).to_dict('records'),'cell_count':len(cells),'screened_cells':int(cells.screen_pass.sum()),'pairs_passing_all_six_years':int((eligible==6).sum()),'passing_pairs':eligible[eligible==6].reset_index().to_dict('records'),'limitations':['floor extracted from latest address; opening-time floor not verified','missingness and floor parsing can bias upper-floor share','registered stores do not cover all commercial premises','upper-floor entry is not success, demand, suitability, or rent affordability','no forecast evaluated; >=30 and >=80% are screening only']}
(out/'results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
