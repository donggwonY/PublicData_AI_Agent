"""Match official popup brands without reading outcome columns."""
import json,re
from pathlib import Path
import pandas as pd
from snapshot_hashes import snapshot_sha256,verify_snapshot_hash
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/d03'
rawpath=ROOT.parent.parent/'상권분석 데이터/식품_일반음식점_대구광역시.csv'
prior=json.loads((OUT/'donggu_concentration.json').read_text(encoding='utf-8'))
verify_snapshot_hash(rawpath,prior['hashes']['raw'])
cols=['개방자치단체코드','관리번호','사업장명','도로명주소','인허가일자']
r=pd.read_csv(rawpath,encoding='cp949',dtype=str,usecols=cols)
r=r[r['도로명주소'].fillna('').str.contains('동부로 149',regex=False)&r['인허가일자'].between('2025-01-01','2025-09-30')]
notice='2025-07-24'
schedule=[('레브슈크레','2025-07-25','2025-07-31'),('롱브르378','2025-07-25','2025-08-07'),('몬트쿠키','2025-08-01','2025-08-07'),('장인한과','2025-08-01','2025-08-04'),('끄네들로','2025-08-08','2025-08-21')]
results=[]
for brand,start,end in schedule:
 m=r[r['사업장명'].str.replace(' ','',regex=False).str.contains(brand,regex=False,na=False)]
 results.append({'brand':brand,'scheduled_start':start,'scheduled_end':end,'matches':[{'name':x['사업장명'],'permit_date':x['인허가일자'],'address':x['도로명주소'],'notice_available_by_permit_date':notice<=x['인허가일자']} for _,x in m.iterrows()]})
result={'source':'https://www.shinsegaegroupnewsroom.com/shinsegae-daegu-sweetpark-anniversary-event/','notice_date':notice,'checked_date':'2026-10-29','read_columns':cols,'matching_scope':'general-restaurant raw CSV, address Dongbu-ro149, permits Jan-Sep2025; substring brand match requires review','results':results,'limitations':['No outcome columns read.','Brand-place-period alignment is evidence, not official management-number permit classification.','No match does not mean no popup; other permit services or operator names may differ.','Notice dates after permit cannot be used as permit-time predictors.'],'hashes':{'raw':snapshot_sha256(rawpath),'script':snapshot_sha256(Path(__file__))}}
(OUT/'popup_evidence.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(results,ensure_ascii=False,indent=2))
