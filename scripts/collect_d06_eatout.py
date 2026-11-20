from pathlib import Path
import importlib.util,json,gzip,hashlib,concurrent.futures

def load(n,p):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def main():
 api=load('api','scripts/e08_franchise/download_ftc.py');key=load('key','scripts/collect_franchise_probe.py').KEY;P=Path('data/raw/d06_franchise');manifest=Path('docs/d06/decline/additional/eatout_manifest.json');meta={}
 def one(y):
  path,param=api.APIS['eatout'];j=api.fetch(key,path,param,str(y),1);rows=api.items_of(j);total=int(j.get('totalCount') or 0)
  for page in range(2,(total+api.PAGE-1)//api.PAGE+1):rows+=api.items_of(api.fetch(key,path,param,str(y),page))
  assert len(rows)==total;f=P/f'eatout_{y}.jsonl.gz';f.write_bytes(gzip.compress(('\n'.join(json.dumps(r,ensure_ascii=False) for r in rows)+'\n').encode('utf-8'),mtime=0));return str(y),dict(rows=total,sha256=hashlib.sha256(f.read_bytes()).hexdigest())
 with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
  for y,r in ex.map(one,range(2017,2027)):meta[y]=r;manifest.write_text(json.dumps(meta,indent=2),encoding='utf-8')
 print('eatout years',len(meta),'total rows',sum(r['rows'] for r in meta.values()))
if __name__=='__main__':main()
