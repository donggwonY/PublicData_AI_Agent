"""Collect public FTC source pages, never log credentials."""
from pathlib import Path
import json,urllib.request,urllib.parse,urllib.error,concurrent.futures
P=Path("data/raw/franchise");P.mkdir(parents=True,exist_ok=True)
spec=json.loads(Path("docs/d06/api_schema.json").read_text(encoding="utf-8"))
BASE="https://"+spec["host"]+spec.get("basePath","")+next(iter(spec["paths"]))
keys=[]
for f in Path(".").glob(".env*"):
 if not f.is_file():continue
 for l in f.read_text(encoding="utf-8-sig",errors="replace").splitlines():
  if "=" in l and not l.lstrip().startswith("#"):
   k,v=l.split("=",1)
   if any(z in k.upper() for z in ["DATA_GO","DATA_PORTAL","SERVICE_KEY","SERVICEKEY"]): keys.append(v.strip().strip("\"'"))
KEY=urllib.parse.unquote(keys[0])
def fetch(year,page=1,size=10000):
 q=urllib.parse.urlencode(dict(serviceKey=KEY,pageNo=page,numOfRows=size,resultType="json",jngBizCrtraYr=str(year)))
 try:
  b=urllib.request.urlopen(BASE+"?"+q,timeout=30).read();j=json.loads(b)
  if j.get("resultCode")!="00":return {"year":year,"status":j.get("resultCode")}
  (P/f"source_{year}_{page}.json").write_bytes(b)
  items=j.get("items",[])
  return dict(year=year,status="ok",total=j.get("totalCount"),returned=len(items),daegu=sum(x.get("areaNm")=="대구" for x in items),accounting_years=sorted(set(x.get("acntgYr","") for x in items)))
 except urllib.error.HTTPError as e:return dict(year=year,status=f"HTTP {e.code}")
 except Exception as e:return dict(year=year,status=type(e).__name__)
if __name__=="__main__":
 with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(fetch,range(2017,2027)))
 Path("docs/d06/year_probe.json").write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding="utf-8")
 print(json.dumps(results,ensure_ascii=False,indent=2))
