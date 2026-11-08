"""Acquire official yearbook source tables; no model-ready claims."""
import json,hashlib,re,urllib.request
from pathlib import Path
from html.parser import HTMLParser
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/d03'
class Tables(HTMLParser):
 def __init__(self):super().__init__();self.tables=[];self.table=None;self.row=None;self.cell=None
 def handle_starttag(self,t,a):
  if t=='table':self.table=[]
  elif t=='tr' and self.table is not None:self.row=[]
  elif t in ('td','th') and self.row is not None:self.cell=[]
 def handle_data(self,d):
  if self.cell is not None:self.cell.append(d)
 def handle_endtag(self,t):
  if t in ('td','th') and self.cell is not None:self.row.append(' '.join(''.join(self.cell).split()));self.cell=None
  elif t=='tr' and self.row is not None:
   if self.table is not None:self.table.append(self.row)
   self.row=None
  elif t=='table' and self.table is not None:self.tables.append(self.table);self.table=None
def main():
 path=OUT/'business_yearbooks_expanded.json';sources=[]
 rawdir=ROOT/'data/raw/d03/business_yearbooks';rawdir.mkdir(parents=True,exist_ok=True)
 for year in [2013,2015,2017,2018,2019,2020,2021,2022,2023,2024]:
  url=f'https://dalseong.daegu.kr/tong{year}/040603.html';r={'edition_year':year,'url':url}
  try:
   raw=urllib.request.urlopen(url,timeout=12).read();s=raw.decode('utf-8-sig');p=Tables();p.feed(s)
   tables=[t for t in p.tables if any('종사자수' in c.replace(' ','') for row in t for c in row)]
   plain=' '.join(re.sub('<[^>]+>',' ',s).split());m=re.search(r'자료기준일\s*[:：]?\s*(.{0,50})',plain)
   r.update(status='source_table_saved' if tables else 'no_matching_table',source_sha256=hashlib.sha256(raw).hexdigest(),reference_date_text=m[1] if m else None,tables=tables)
   if tables:(rawdir/f'dalseong_{year}.html').write_bytes(raw)
  except Exception as e:r.update(status='request_error',error_type=type(e).__name__,http_code=getattr(e,'code',None))
  sources.append(r);path.write_text(json.dumps({'retrieved_on':'2026-11-08','scope':'Dalseong only, official yearbook candidate URLs verified by actual table response','limitations':['Publication edition differs from reference year.','Merged headers preserved as text cells; normalization pending.','Publication date and census definition changes must be verified before historical modeling.','No province-wide coverage or model training.'],'sources':sources},ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(year,r['status'],flush=True)
 print('saved_editions',sum(r['status']=='source_table_saved' for r in sources))
if __name__=='__main__':main()
