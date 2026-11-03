"""Frozen full-coverage baseline audit; no 2023-2025 scoring."""
import json,sys
from pathlib import Path
import numpy as np,pandas as pd
from fit_d03 import ROOT,metrics,verify_snapshot_hash,snapshot_sha256,Pipeline,OneHotEncoder,LogisticRegression
from fit_d03_expanded import fit
sys.path.insert(0,str(ROOT/'service'))
from pipeline.numeric import parse_area
def main():
 out=ROOT/'docs/d03';old=json.loads((out/'validation.json').read_text(encoding='utf-8'));area_ref=json.loads((out/'area_complete.json').read_text(encoding='utf-8'))
 sp=ROOT/'service/data/processed/stores.parquet';rp=ROOT.parent.parent/'상권분석 데이터/식품_일반음식점_대구광역시.csv'
 verify_snapshot_hash(sp,old['hashes']['stores']);verify_snapshot_hash(rp,area_ref['hashes']['raw']);verify_snapshot_hash(ROOT/'service/pipeline/numeric.py',area_ref['hashes']['parser'])
 st=pd.read_parquet(sp);f=st[st.service.eq('일반음식점')&st.ld.dt.year.between(2010,2021)].copy().reset_index(drop=True)
 assert not (f.cd.notna()&f.cd.lt(f.ld)).any()
 r=pd.read_csv(rp,encoding='cp949',dtype=str,usecols=['개방자치단체코드','관리번호','소재지면적','최종수정시점','데이터갱신시점','영업상태명','상세영업상태명','폐업일자','지번주소','인허가일자']);r['key']=r['개방자치단체코드']+'|'+r['관리번호'];assert r.key.is_unique
 key=f.org_code.astype(str).str.replace(r'\.0$','',regex=True)+'|'+f.mgmt_no
 raw=key.map(r.set_index('key')['소재지면적']);parsed=parse_area(raw);area=f.area_m2.copy();recover=area.isna()&raw.str.contains(',',regex=False,na=False)&parsed.notna();area.loc[recover]=parsed[recover].astype(float)
 coord=f.lat.between(-90,90)&f.lon.between(-180,180);valid=np.isfinite(area)&area.gt(0)
 f['coverage']=np.where(~coord,'coordinate_excluded',np.where(~valid,'area_excluded','included'))
 f['event']=(f.closed&(f.cd-f.ld).dt.days.between(0,365)).astype(int)
 f['duration']=(f.cd-f.ld).dt.days
 f['raw_area_kind']=np.where(raw.isna()|raw.fillna('').str.strip().eq(''),'blank',np.where(parsed.le(0).fillna(False),'nonpositive',np.where(parsed.gt(0).fillna(False),'positive','unparsed')))
 rr=r.set_index('key')
 for col in ['최종수정시점','데이터갱신시점','영업상태명','상세영업상태명','폐업일자','지번주소','인허가일자']:f[col]=key.map(rr[col])
 f['close_month']=f.cd.dt.strftime('%Y-%m').fillna('__MISSING__')
 f['duration_band']=pd.cut(f.duration,[-1,0,7,30,90,180,365,float('inf')],labels=['0','1-7','8-30','31-90','91-180','181-365','366+']).astype('string').fillna('no_date')
 selected=[]
 for place,opens,close,expected in [('대구광역시 달서구 두류동 560',['2016-07-26','2016-07-27'],'2016-08-01',46),('대구광역시 수성구 두산동 152-1',['2018-09-07'],'2018-09-08',50)]:
  g=f[f.coverage.eq('area_excluded')&f.event.eq(1)&f.building_key.eq(place)&f.ld.dt.strftime('%Y-%m-%d').isin(opens)&f.cd.eq(pd.Timestamp(close))]
  assert len(g)==expected
  # Preserve unmatched raw rows explicitly; do not infer their addresses.
  selected.append({'place':place,'n':len(g),'raw_address_available':int(g['지번주소'].notna().sum()),'raw_addresses':g['지번주소'].value_counts().to_dict(),'raw_open_dates':g['인허가일자'].value_counts().to_dict(),'festival_address_n':int(g['지번주소'].str.contains('들안길.*푸드페스티벌',regex=True,na=False).sum())})
 result={'groups':selected,'hashes':{'raw':snapshot_sha256(rp),'stores':snapshot_sha256(sp),'script':snapshot_sha256(Path(__file__))},'limitation':'address identifies festival context, not legal temporary permit type or historical availability'}
 (out/'historical_event_evidence.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
 print(json.dumps(selected,ensure_ascii=False))
if __name__=='__main__':main()
