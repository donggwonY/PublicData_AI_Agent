"""Compare local source version and snapshot; dry-run comma parser only."""
import json,sys
from pathlib import Path
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'service'))
from pipeline.numeric import parse_area
from snapshot_hashes import snapshot_sha256,verify_snapshot_hash

def main():
 out=ROOT/'docs/d03';sp=ROOT/'service/data/processed/stores.parquet'
 verify_snapshot_hash(sp,json.loads((out/'protocol.json').read_text(encoding='utf-8'))['hashes']['service/data/processed/stores.parquet'])
 s=pd.read_parquet(sp);s=s[s.service.eq('일반음식점')&s.ld.dt.year.between(2010,2021)].copy()
 rp=ROOT.parent.parent/'상권분석 데이터/식품_일반음식점_대구광역시.csv';r=pd.read_csv(rp,encoding='cp949',dtype=str)
 s['key']=s.org_code.astype(str).str.replace(r'\.0$','',regex=True)+'|'+s.mgmt_no
 r['key']=r['개방자치단체코드']+'|'+r['관리번호'];assert r.key.is_unique
 j=s.merge(r,on='key',how='left',validate='many_to_one',indicator=True)
 old=pd.to_numeric(j['소재지면적'],errors='coerce');new=parse_area(j['소재지면적']);matched=j['_merge'].eq('both')
 recovered=old.isna()&new.notna();unchanged=old.notna();assert np.allclose(old[unchanged],new[unchanged]);assert recovered.sum()==55
 mismatch=matched&~np.isclose(j.area_m2,old,equal_nan=True);assert mismatch.sum()==16
 details=[]
 for _,row in j[mismatch].iterrows():
  details.append({'key':row['key'],'snapshot_area':float(row.area_m2),'local_raw_text':row['소재지면적'],'local_raw_parsed':float(pd.to_numeric(row['소재지면적'])),'local_record_modified':row['최종수정시점'],'cause':'not a comma parsing issue; source version/record history unresolved'})
 report={'scope':'2010-2021 source-only dry run; processed snapshot unchanged','recovered_values':int(recovered.sum()),'recovered_min':float(new[recovered].min()),'recovered_max':float(new[recovered].max()),'previous_numeric_unchanged':int(unchanged.sum()),'mismatches':details,'raw_unmatched_keys':j.loc[~matched,'key'].tolist(),'hashes':{'raw':snapshot_sha256(rp),'stores':snapshot_sha256(sp),'parser':snapshot_sha256(ROOT/'service/pipeline/numeric.py'),'script':snapshot_sha256(Path(__file__))}}
 (out/'area_parser_fix.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 lines=['# 面積 숫자 변환 수정과16건 대조'.replace('面積','면적'),'','## 수정과 실제 자료 검증','','배치의 면적 변환을 엄격한 천 단위 구분 처리로 수정했다. 1,048.35는1048.35로 읽고 12,34 같은 잘못된 쉼표는 결측을 유지한다. 일반 숫자·0·음수·누락의 기존 의미는 보존한다.',f"2010~2021 로컬 원본 대응 범위에서55개 값을 복구 가능함을 dry-run으로 확인했다. 복구 범위 {report['recovered_min']:,.2f}~{report['recovered_max']:,.2f}㎡. 기존 숫자 {report['previous_numeric_unchanged']:,}건은 동일. 값이 크다는 이유만으로 상한을 두거나 삭제하지 않았다.",'','## 16건과 미연결1건','','16건은 원본 값 자체가 숫자로 잘 읽히므로 쉼표 오류로 설명되지 않는다. 예: 가공99.24㎡/현재원본64.88㎡. 현재 보유 CSV와 기존 Parquet는 동일 원본 버전이라고 확인되지 않았으며, 실제 면적 변경/원본 정정/당시 가공 차이 중 무엇인지는 미확정이다. 당시 배치 입력 원본과 변경 이력이 없으므로 자동 덮어쓰기하지 않는다. 상세 관리키·양쪽 값·현재 수정일과 원본 미연결1건은 JSON에 기록했다. 원본 수정일만으로 면적 변경 시점/정답을 추정하지 않는다.','','## 영향 범위와 검증','','파서3개+core14개 총17개 단위검사, 서비스 smoke ALL PASSED0. 기존 D-03 stores 해시 유지 확인. 기존 로컬 분석 패키지 환경에서 검사했으며 배포 고정 환경 재현은 별도다. 전체 배치 재생성·DB 적재·공개 배포·푸시는 미수행. 다음 배치부터 새 파서가 적용되며 현재 앱의 면적 값은 아직 바뀌지 않았다.','','개업 당시 면적임을 확인한 것은 아니어서 예측 모델에는 추가하지 않았다. [세부 대조](area_parser_fix.json). 재현: `python scripts/verify_d03_area_fix.py`.']
 (out/'area_parser_fix.md').write_text('\n'.join(lines)+'\n',encoding='utf-8');print(json.dumps({k:report[k] for k in ['recovered_values','recovered_min','recovered_max','previous_numeric_unchanged','raw_unmatched_keys']},ensure_ascii=False))
if __name__=='__main__':main()
