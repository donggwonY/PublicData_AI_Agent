"""Read-only audit of potential temporary-business fields; no model filtering."""
import json
from pathlib import Path
import pandas as pd
from snapshot_hashes import snapshot_sha256
ROOT=Path(__file__).resolve().parents[1]
def main():
 p=ROOT.parent.parent/'상권분석 데이터/식품_일반음식점_대구광역시.csv'
 d=pd.read_csv(p,encoding='cp949',dtype=str)
 d['ld']=pd.to_datetime(d['인허가일자'],errors='coerce');d['cd']=pd.to_datetime(d['폐업일자'],errors='coerce')
 d=d[d.ld.dt.year.between(2010,2021)].copy()
 # Only schema is inspected across the file; no 2023-2024 target evaluations.
 cols=['사업장명','도로명주소','지번주소'];pattern='한시|축제|임시|행사'
 text=d[cols].fillna('').agg(' '.join,axis=1);d['explicit_text_candidate']=text.str.contains(pattern,regex=True)
 candidate=d['업태구분명'].eq('호프/통닭')&d.ld.dt.year.between(2017,2018)&d.ld.dt.month.eq(7)&d['도로명주소'].fillna('').str.contains('공원순환로',regex=False)&d.cd.isin(pd.to_datetime(['2017-07-23','2017-07-26','2018-07-23']))
 assert candidate.sum()==65
 report={'scope':'2010-2021 metadata identification audit; no model training or exclusion','columns':list(d.columns),'raw_rows_in_scope':len(d),'dedicated_temporary_flag_present':False,'permitted_end_date_present':False,'candidate65_text_hits':int((candidate&d.explicit_text_candidate).sum()),'all_text_candidates':int(d.explicit_text_candidate.sum()),'name_chimac_hits':int(d['사업장명'].fillna('').str.contains('치맥',regex=False).sum()),'warning':'치맥 is also an ordinary brand/name; keywords are review flags, not confirmed temporary permits. Current names/addresses not proven historical at opening.','annual_text_counts':{str(k):int(v) for k,v in d.groupby(d.ld.dt.year).explicit_text_candidate.sum().items()},'hashes':{'raw':snapshot_sha256(p),'script':snapshot_sha256(Path(__file__))}}
 out=ROOT/'docs/d03';(out/'temporary_business_fields.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 lines=['# 한시 영업 식별 가능성 점검','','원본 일반음식점 CSV에는 한시영업 여부·허가 종료일 전용 항목이 없다. 상세영업상태는 영업/폐업이어서 한시 여부를 판정하지 못한다.', '',f"2010~2021 허가 {len(d):,}건의 이름/주소에 한시·축제·임시·행사 문구가 있는 후보 {int(d.explicit_text_candidate.sum())}건. 기존65건 중 이 문구로 포착되는 건은 {report['candidate65_text_hits']}건이다. 키워드는 상호 오탐과 누락 가능성이 있어 자동 제외에 쓰지 않는다. 치맥이라는 문자열은 일반 브랜드에도 나타나므로 후보 기준에서 제외했다.",'','현재 이름/주소가 허가 당시에 같았는지도 확인되지 않았다. 주소+행사 일정으로 검토 후보를 만들 수 있지만 정상 상설 업소를 함께 포함할 수 있어 확정 필터가 아니다. 이번에는 모델·표본을 변경하지 않았다.','','## 공개 경로 확인','','[공식 축제 연혁](https://www.chimacfestival.com/page/info_history.php)에는 연도별 참여 브랜드가 있으나 관리번호별 허가 유형과 대응하는 명부는 이번 검색에서 확보하지 못했다. 브랜드명 일치만으로 개별 사업장을 행사 부스로 확정하지 않는다. [공식 공지](https://chimacfestival.com/bbs/board.php?bo_table=notice)는 추가 참가 자료 검색 경로다.','','## 문의 초안 (발송하지 않음)','','대구 음식점 인허가를 이용한 대학 분석 프로젝트를 진행하고 있습니다. 2017·2018년 치맥페스티벌 관련 음식점의 한시 영업 여부를 구분하고자 합니다. 개인정보를 제외한 관리번호·개방자치단체코드·행사명·한시영업 여부·허가 시작/종료일 자료 또는 이를 확인할 수 있는 공개자료가 있는지 문의드립니다. 가능하면 같은 기준의2010~2021년 자료 제공 범위와 열 정의도 안내 부탁드립니다. 폐업일을 이용해 한시영업을 추정하지 않고 허가 당시 자료로 구분하려는 목적입니다.','','문의 대상 후보는 달서구 식품위생 인허가 담당 또는 축제 주최기관이며 정확한 담당 창구는 발송 전 확인한다. 문의/신청/외부 발송은 수행하지 않았다.','','## 판단','','현재 파일만으로65건을 확정 분류하는 것은 불가능하다. 이를 자동 삭제해 예측 성능이 개선됐다고 주장하지 않는다. 확보 전에는 기존 사건 정의를 유지하고 잠정 한시영업 혼입이라는 해석 한계만 표시한다. 이미 본 검증기간의 분류 기준을 정한 뒤에도 독립 평가가 필요하다. 원본/운영/DB 변경 없음. [상세 점검](temporary_business_fields.json). 재현: `python scripts/audit_d03_temporary_fields.py`.']
 (out/'temporary_business_fields.md').write_text('\n'.join(lines)+'\n',encoding='utf-8');print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':main()
