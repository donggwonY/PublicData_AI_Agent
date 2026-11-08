"""Official Suseong source tables, no historical model adoption."""
import json,re,hashlib,urllib.request
from pathlib import Path
from collect_d03_business_yearbooks import Tables
ROOT=Path(__file__).resolve().parents[1]
def main():
 dest=ROOT/'data/raw/d03/business_yearbooks';dest.mkdir(parents=True,exist_ok=True);results=[]
 for year in [2015,2017,2019,2021,2023]:
  for section in ['040601','040603']:
   url=f'https://stat.suseong.kr/{year}st/{section}.html';r={'district':'수성구','edition_year':year,'section':section,'url':url}
   try:
    raw=urllib.request.urlopen(url,timeout=12).read();s=raw.decode('utf-8-sig');s=re.sub(r'<!--.*?-->','',s,flags=re.S)
    p=Tables();p.feed(s);tables=[t for t in p.tables if any('종사자' in c or '사업체수' in c.replace(' ','') for row in t for c in row)]
    plain=' '.join(re.sub('<[^>]+>',' ',s).split());m=re.search(r'자료기준일\s*[:：]?\s*(.{0,45})',plain)
    r.update(status='source_table_saved' if tables else 'no_matching_table',sha256=hashlib.sha256(raw).hexdigest(),reference_date_text=m[1] if m else None,tables=tables)
    if tables:(dest/f'suseong_{year}_{section}.html').write_bytes(raw)
   except Exception as e:r.update(status='request_error',error_type=type(e).__name__,http_code=getattr(e,'code',None))
   results.append(r);print(year,section,r['status'],flush=True)
 (ROOT/'docs/d03/suseong_business_sources.json').write_text(json.dumps({'retrieved_on':'2026-11-08','status':'source_tables_not_model_ready','limitations':['Edition year is not reference date or publication date.','Merged headers not normalized, census scope changes unverified.','Only successfully returned tables count as acquired.'],'sources':results},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print('saved',sum(r['status']=='source_table_saved' for r in results))
if __name__=='__main__':main()
