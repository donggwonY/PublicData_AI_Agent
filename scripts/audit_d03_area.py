"""Audit floor-area quality and historical availability, without training."""
import json
from pathlib import Path
import numpy as np
import pandas as pd
from snapshot_hashes import snapshot_sha256,verify_snapshot_hash
ROOT=Path(__file__).resolve().parents[1]
def main():
 out=ROOT/'docs/d03';sp=ROOT/'service/data/processed/stores.parquet';old=json.loads((out/'protocol.json').read_text(encoding='utf-8'));verify_snapshot_hash(sp,old['hashes']['service/data/processed/stores.parquet'])
 s=pd.read_parquet(sp);s=s[s.service.eq('일반음식점')&s.ld.dt.year.between(2010,2021)].copy()
 rp=ROOT.parent.parent/'상권분석 데이터/식품_일반음식점_대구광역시.csv'
 cols=['개방자치단체코드','관리번호','소재지면적','시설총규모','인허가일자','최종수정시점','데이터갱신시점']
 r=pd.read_csv(rp,encoding='cp949',dtype=str,usecols=cols)
 r['_key']=r['개방자치단체코드'].str.strip()+'|'+r['관리번호'].str.strip();assert r['_key'].is_unique
 s['_key']=s.org_code.astype(str).str.replace(r'\.0$','',regex=True).str.strip()+'|'+s.mgmt_no.astype(str).str.strip()
 j=s.merge(r,on='_key',how='left',validate='many_to_one',indicator=True);matched=j['_merge'].eq('both')
 a=pd.to_numeric(j['소재지면적'],errors='coerce');facility=pd.to_numeric(j['시설총규모'],errors='coerce')
 equal=np.isclose(j.area_m2,a,equal_nan=True)
 raw_numeric=a.copy()
 a=j.area_m2.copy()
 modified=pd.to_datetime(j['최종수정시점'],errors='coerce');same_day=modified.dt.normalize().eq(j.ld)
 valid=np.isfinite(a)&a.gt(0)
 def stats(ix):
  x=a[ix];v=valid[ix]
  return {'n':int(ix.sum()),'missing':int(x.isna().sum()),'nonpositive':int(x.le(0).sum()),'positive':int(v.sum()),'positive_pct':float(v.mean()*100),'median_positive':float(x[v].median()),'p99_positive':float(x[v].quantile(.99)),'max_positive':float(x[v].max())}
 groups={}
 for end,start,stop in [(2013,2015,2016),(2015,2017,2018),(2018,2020,2021)]:groups[f'validation_{start}_{stop}']=stats(j.ld.dt.year.between(start,stop)&j.lat.between(-90,90)&j.lon.between(-180,180))
 malformed=j['소재지면적'].notna()&raw_numeric.isna()
 comma_fixed=pd.to_numeric(j['소재지면적'].str.replace(',','',regex=False),errors='coerce')
 result={'scope':'general restaurants opened2010-2021; metadata only; no model evaluation','all':stats(pd.Series(True,index=j.index)),'validation':groups,'raw_matches':int(matched.sum()),'raw_unmatched':int((~matched).sum()),'area_matches':int((equal&matched).sum()),'area_mismatches':int((~equal&matched).sum()),'comma_recoverable':int((malformed&comma_fixed.notna()).sum()),'unparseable_nonblank':int(malformed.sum()),'unparseable_examples':j.loc[malformed,'소재지면적'].drop_duplicates().head(10).tolist(),'both_area_fields_present':int((a.notna()&facility.notna()).sum()),'area_fields_disagree':int((a.notna()&facility.notna()&~np.isclose(a,facility,equal_nan=True)).sum()),'modified_after_open_day':int((modified.dt.normalize()>j.ld).sum()),'modified_same_day':int(same_day.sum()),'modified_missing':int(modified.isna().sum()),'opening_time_area_confirmed':False,'hashes':{'stores':snapshot_sha256(sp),'raw':snapshot_sha256(rp),'script':snapshot_sha256(Path(__file__))}}
 (out/'area_availability.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 lines=['# D-03 매장 면적 품질·시점 점검','','## 확인 결과','',f"2010~2021 일반음식점 {len(j):,}건(좌표 없는 행 포함). 양수 면적 {int(valid.sum()):,}건({valid.mean()*100:.2f}%), 누락 {int(a.isna().sum()):,}건, 0이하 {int(a.le(0).sum()):,}건. 양수 중앙값 {a[valid].median():.2f}㎡. 숫자 변환 불가 비어있지 않은 원문 {int(malformed.sum())}건. 이 중 쉼표 제거로 숫자 변환 가능한 값 {int((malformed&comma_fixed.notna()).sum())}건(진단만 수행, 기존 데이터 수정 없음).",f"가공 area_m2는 원본 소재지면적과 {int((equal&matched).sum()):,}건 일치; 원본 미연결 {int((~matched).sum())}건은 비교 불가; 연결 후 값 차이 {int((~equal&matched).sum())}건. 시설총규모와 둘 다 값이 있는 경우 불일치 {result['area_fields_disagree']:,}건이므로 의미 확인 없이 서로 대체하지 않는다.",'',f"레코드 최종수정일이 허가일 이후인 행 {result['modified_after_open_day']:,}건. 이 날짜는 레코드 전체 수정일이며 면적 자체가 바뀌었다는 증거가 아니다. 반대로 허가일과 수정일이 같아도 당시 공개/측정 시점을 증명하지 못한다.",'','## 판단','','현재 파일에 면적 변경 이력·면적 측정일/유효시작일은 없어 개업 당시 면적을 확정할 수 없다. 수치 보유율은 높으나 과거 예측 시점에 알 수 있었는지는 미확인이다. 현재값을 개업 당시값으로 가정해 학습·평가하지 않았다. 기존 모델/운영/DB 변경 없음.','','## 후속 자료 조건','','허가 당시 면적 또는 관리번호별 면적 변경 이력과 적용일이 필요하다. 이미 작성한 한시영업 자료 문의에 이 항목을 함께 요청할 수 있다. 확보 후0/누락을 별도 표시하고 학습기간에서만 대체/변환 규칙을 정하며, 과도한 값은 원본 검토 후 처리한다. 최대값만으로 오류나 정상 여부를 단정하지 않는다. 시설총규모를 자동 보충하거나 허가일 이후 수정된 행을 모두 삭제하지 않는다.','','원본 키 유일성 검사 통과. 연결된 행의 값 차이도 별도 기록했으며 원본 버전 차이/가공 원인을 확정하지 않았다. 미연결 행은 제외/보정하지 않고 별도 집계. 좌표 유효 기존 검증기간별 품질은 [JSON](area_availability.json). 재현: `python scripts/audit_d03_area.py`.']
 (out/'area_availability.md').write_text('\n'.join(lines)+'\n',encoding='utf-8');print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
