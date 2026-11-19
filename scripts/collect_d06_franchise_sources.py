"""Download three FTC sources for D-06; secrets and personal fields excluded."""
from pathlib import Path
import importlib.util,json,gzip,hashlib,concurrent.futures
from datetime import datetime,timezone

def load(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def main():
 api=load('api','scripts/e08_franchise/download_ftc.py');key=load('key','scripts/collect_franchise_probe.py').KEY
 out=Path('data/raw/d06_franchise');out.mkdir(parents=True,exist_ok=True)
 manifest=Path('docs/d06/decline/acquisition_manifest.json');meta=json.loads(manifest.read_text()) if manifest.exists() else {}
 def one(job):
  name,year=job;f=out/f'{name}_{year}.jsonl.gz';old=meta.get(f.name)
  if old and f.exists() and hashlib.sha256(f.read_bytes()).hexdigest()==old['sha256']:return f.name,old
  path,param=api.APIS[name];first=api.fetch(key,path,param,str(year),1);rows=api.items_of(first);total=int(first.get('totalCount') or 0)
  for page in range(2,(total+api.PAGE-1)//api.PAGE+1):rows+=api.items_of(api.fetch(key,path,param,str(year),page))
  assert len(rows)==total
  body=''.join(json.dumps({k:v for k,v in r.items() if k not in api.DROP},ensure_ascii=False)+'\n' for r in rows)
  f.write_bytes(gzip.compress(body.encode('utf-8'),mtime=0))
  return f.name,dict(api=name,year=year,rows=total,sha256=hashlib.sha256(f.read_bytes()).hexdigest(),downloaded_at=datetime.now(timezone.utc).isoformat())
 jobs=[(a,y) for a in ['brand_list','brand_stats','brand_region'] for y in range(2017,2027) if not(a=='brand_stats' and y==2026)]
 with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
  for f,result in ex.map(one,jobs):
   meta[f]=result;manifest.write_text(json.dumps(meta,indent=2),encoding='utf-8');print(f,result['rows'],flush=True)
 print('Complete:',len(meta),'source files')
if __name__=='__main__':main()
