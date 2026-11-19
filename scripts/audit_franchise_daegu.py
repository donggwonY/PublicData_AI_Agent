from pathlib import Path
import json,re,hashlib
import pandas as pd
P=Path("docs/d06")
f=Path("data/raw/franchise/daegu_all.json");d=pd.DataFrame(json.loads(f.read_text(encoding="utf-8")))
keys=["jngBizCrtraYr","acntgYr","brandMnno","areaNm"]
duplicates=int(d.duplicated(keys).sum());conflicts=int(d.drop_duplicates().duplicated(keys).sum())
assert conflicts==0,"Conflicting brand/year rows require inspection"
d=d.drop_duplicates(keys).copy()
def bounds(v):
 m=re.fullmatch(r"([0-9,.]+)~([0-9,.]+)",str(v).strip())
 if not m:return (None,None)
 lo,hi=[float(x.replace(",","")) for x in m.groups()]
 return (lo,hi) if 0<lo<=hi else (None,None)
d[["sales_lo","sales_hi"]]=pd.DataFrame(d.fyerAvrgSlsAmtScopeVal.map(bounds).tolist(),index=d.index)
d["year"]=pd.to_numeric(d.acntgYr);d["report_year"]=pd.to_numeric(d.jngBizCrtraYr);d["stores"]=pd.to_numeric(d.frcsCnt,errors="coerce")
d["valid_sales"]=d.sales_lo.notna();d["midpoint_proxy"]=(d.sales_lo+d.sales_hi)/2
annual=d.groupby("year").agg(rows=("brandMnno","size"),brands=("brandMnno","nunique"),positive_ranges=("valid_sales","sum"),active_brands=("stores",lambda s:int((s>0).sum())))
v=d[d.valid_sales];coverage=v.groupby("brandMnno").year.nunique()
result=dict(source_sha256=hashlib.sha256(f.read_bytes()).hexdigest(),rows=len(d),exact_duplicate_keys=duplicates,conflicting_keys=conflicts,brands=int(d.brandMnno.nunique()),positive_sales_rows=len(v),positive_brands=int(v.brandMnno.nunique()),brands_with_at_least_5_years=int((coverage>=5).sum()),brands_with_all_10_years=int((coverage>=10).sum()),report_minus_accounting_year=sorted((d.report_year-d.year).unique().tolist()),zero_sales_field=int(d.fyerAvrgSlsAmtScopeVal.eq("0").sum()),annual=annual.reset_index().to_dict("records"))
annual.to_csv(P/"availability_by_year.csv",index=True)
d.to_parquet("data/raw/franchise/daegu_panel.parquet",index=False)
(P/"availability.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(result,ensure_ascii=False,indent=2))
