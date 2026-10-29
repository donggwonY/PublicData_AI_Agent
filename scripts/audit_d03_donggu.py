"""Outcome-informed concentration audit; never a training exclusion rule."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from snapshot_hashes import snapshot_sha256,verify_snapshot_hash
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/d03'
import sys
sys.path.insert(0,str(ROOT/'service'))
from pipeline.numeric import parse_area

def main():
 old=json.loads((OUT/'area_subgroups.json').read_text(encoding='utf-8'))
 sp=ROOT/'service/data/processed/stores.parquet';rp=ROOT.parent.parent/'상권분석 데이터/식품_일반음식점_대구광역시.csv'
 verify_snapshot_hash(sp,old['hashes']['stores']);verify_snapshot_hash(rp,old['hashes']['raw'])
 s=pd.read_parquet(sp)
 f=s[s.service.eq('일반음식점')&s.ld.between('2025-01-01','2025-09-30')&s.lat.between(-90,90)&s.lon.between(-180,180)].copy()
 cols=['개방자치단체코드','관리번호','소재지면적','인허가일자','폐업일자','업태구분명','도로명주소','사업장명','상세영업상태명']
 raw=pd.read_csv(rp,encoding='cp949',dtype=str,usecols=cols);raw['_key']=raw['개방자치단체코드']+'|'+raw['관리번호'];assert raw._key.is_unique
 f['_key']=f.org_code.astype(str).str.replace(r'\.0$','',regex=True)+'|'+f.mgmt_no
 text=f._key.map(raw.set_index('_key')['소재지면적']);parsed=parse_area(text)
 area=f.area_m2.copy();recover=area.isna()&text.str.contains(',',regex=False,na=False)&parsed.notna();area.loc[recover]=parsed[recover].astype(float)
 f['audit_area']=area;f=f[np.isfinite(area)&area.gt(0)].copy();f['days']=(f.cd-f.ld).dt.days;f['event']=f.closed&f.days.between(0,365)
 assert len(f)==1608 and int(f.event.sum())==168
 d=f[f.gu.eq('동구')].copy();assert len(d)==237 and int(d.event.sum())==62
 j=d.merge(raw,on='_key',how='left',validate='one_to_one',indicator=True)
 checks={'matched':int(j._merge.eq('both').sum())}
 for a,b in [('ld','인허가일자'),('cd','폐업일자')]:
  dates=pd.to_datetime(j[b],errors='coerce');checks[a+'_mismatch']=int((~(j[a].eq(dates)|(j[a].isna()&dates.isna()))).sum())
 checks['category_mismatch']=int(j.category.ne(j['업태구분명']).sum());print('Raw comparison',checks,flush=True);assert checks['matched']==237
 mismatch=j[~(j.cd.eq(pd.to_datetime(j['폐업일자'],errors='coerce'))|(j.cd.isna()&pd.to_datetime(j['폐업일자'],errors='coerce').isna()))]
 checks['date_differences']=[{'stored_close':str(x.cd),'raw_close':str(x['폐업일자']),'stored_event':bool(x.event),'raw_status':str(x['상세영업상태명'])} for _,x in mismatch.iterrows()]
 checks['donggu_categories']=d.category.value_counts().to_dict()
 events=d[d.event]
 def dates(frame,col):return {str(k.date()):int(v) for k,v in frame[col].value_counts().items()}
 blocks=[]
 for key,g in d.groupby('building_key',dropna=False):
  e=g[g.event]
  blocks.append({'building':str(key),'n':len(g),'events':len(e),'short_30d_events':int(e.days.le(30).sum()),'categories':g.category.value_counts().to_dict(),'open_dates':dates(g,'ld'),'close_dates':dates(e,'cd'),'duration_days':{str(k):int(v) for k,v in e.days.value_counts().items()},'area_min':float(g.audit_area.min()),'area_max':float(g.audit_area.max()),'addresses':g.road_addr_raw.dropna().value_counts().to_dict()})
 blocks.sort(key=lambda x:(-x['events'],-x['n'],x['building']))
 result={'scope':'post-outcome concentration audit, no model change or exclusion','n':len(d),'events':len(events),'short_7d_events':int(events.days.le(7).sum()),'short_30d_events':int(events.days.le(30).sum()),'short_90d_events':int(events.days.le(90).sum()),'category_events':events.category.value_counts().to_dict(),'closure_dates':dates(events,'cd'),'buildings':blocks,'raw_check':checks,'raw_keyword_count':int(j['사업장명'].fillna('').str.contains('한시|임시|축제|행사',regex=True).sum()),'hashes':{'stores':snapshot_sha256(sp),'raw':snapshot_sha256(rp),'script':snapshot_sha256(Path(__file__))}}
 assert sum(x['n'] for x in blocks)==237 and sum(x['events'] for x in blocks)==62
 (OUT/'donggu_concentration.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({**{k:v for k,v in result.items() if k!='buildings'},'top_buildings':blocks[:5]},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
