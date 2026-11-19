from collect_franchise_probe import fetch,P
from pathlib import Path
import json,math,concurrent.futures,hashlib
probes=json.loads(Path("docs/d06/year_probe.json").read_text(encoding="utf-8"))
jobs=[(v["year"],page) for v in probes if v["status"]=="ok" for page in range(2,math.ceil(int(v["total"])/10000)+1)]
def run(job):
 y,p=job;f=P/f"source_{y}_{p}.json"
 if f.exists():return dict(year=y,page=p,status="cached")
 r=fetch(y,p);r["page"]=p;return r
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:results=list(ex.map(run,jobs))
failed=[r for r in results if r["status"] not in ["ok","cached"]]
if failed:print(json.dumps(failed));raise SystemExit("Incomplete acquisition; rerun cached collector")
records=[];manifest=[]
for v in probes:
 y=v["year"];n=0;dy=[];pages=[]
 for p in range(1,math.ceil(int(v["total"])/10000)+1):
  f=P/f"source_{y}_{p}.json";b=f.read_bytes();j=json.loads(b);items=j["items"];n+=len(items)
  assert int(j["totalCount"])==int(v["total"]),(y,"total changed")
  dy.extend(x for x in items if x.get("areaNm")=="대구")
  pages.append(dict(page=p,rows=len(items),sha256=hashlib.sha256(b).hexdigest()))
 assert n==int(v["total"]),(y,n,v["total"])
 records.extend(dy);manifest.append(dict(year=y,total=n,daegu=len(dy),pages=pages))
(P/"daegu_all.json").write_text(json.dumps(records,ensure_ascii=False),encoding="utf-8")
Path("docs/d06/acquisition_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps([dict(year=x["year"],total=x["total"],daegu=x["daegu"]) for x in manifest],ensure_ascii=False));print("daegu_total",len(records))
