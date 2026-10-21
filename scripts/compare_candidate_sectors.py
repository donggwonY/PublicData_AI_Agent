"""Meeting draft: explicit category crosswalks, not matched establishments."""
from pathlib import Path
import json
import hashlib
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/a01'
# Label, license service, exact categories (None = service), POI field/values, caveat.
SPECS=[
 ('카페(좁은 정의)', ['일반음식점','휴게음식점'],['커피숍','까페'],'cat_s',['카페'],'부분 대응: 다방·전통찻집·키즈/라이브카페 제외. 기존 서비스 카페 별칭보다 좁음.'),
 ('베이커리',['제과점영업'],None,'cat_s',['빵/도넛'],'부분 대응: 인허가는 푸드트럭 포함; 상가 빵 판매점과 제과점 허가 범위가 다를 수 있음.'),
 ('분식·김밥',['일반음식점','휴게음식점'],['분식','김밥(도시락)'],'cat_s',['김밥/만두/분식'],'부분 대응: 도시락·만두 포함 범위 및 일반조리판매 누락 여부 합의 필요.'),
 ('치킨(좁은 정의)',['일반음식점'],['통닭(치킨)'],'cat_s',['치킨'],'부분 대응: 호프/통닭 제외. 포함하면 술집과 겹침; 기존 치킨 별칭과 다름.'),
 ('중식',['일반음식점'],['중국식'],'cat_m',['중식'],'분류상 대응 후보: 중국집·마라탕/훠궈 포함. 개별 점포 매칭은 미검증.'),
 ('한식(넓은 정의)',['일반음식점'],['한식','식육(숯불구이)','냉면집','탕류(보신용)','복어취급','횟집'],'cat_m',['한식'],'부분 대응: 한식 중분류의 고기·횟집 등을 반영한 제안. 인허가 한식만과 비교하면 범위 불일치.'),
 ('미용실(헤어)',['미용업'],['일반미용업'],'cat_s',['미용실'],'분류상 대응 후보: 피부·네일·메이크업·기타 제외. 기존 미용업 키워드는 더 넓음.'),
 ('네일숍',['미용업'],['네일아트업'],'cat_s',['네일숍'],'분류상 대응 후보: 종합 미용실의 네일 겸업은 별도 확인 필요.'),
 ('피부관리',['미용업'],['피부미용업'],'cat_s',['피부 관리실'],'분류상 대응 후보: 마사지·체형관리 제외; 겸업은 별도 확인 필요.'),
 ('세탁',['세탁업'],None,'cat_s',['세탁소','셀프 빨래방'],'부분 대응: 무인 셀프 빨래방의 허가 포괄 여부 불확실. 일반세탁/빨래방 분리 논의 필요.'),
 ('노래방',['노래연습장업'],None,'cat_s',['노래방'],'분류상 대응 후보: 유흥주점 제외. 기존 서비스 키워드의 유흥주점 포함은 검토 필요.'),
 ('담배 소매',['담배소매업'],None,'cat_s',['담배/전자담배 소매업'],'직접 대응 부적합: 담배 판매 허가는 편의점·슈퍼에도 있으나 상가 분류는 전문 소매업임.'),
]

def stats(d):
    missing=d[['lat','lon']].isna().any(axis=1)
    invalid=~missing & ~(d.lat.between(35.4,36.5,inclusive='neither') & d.lon.between(128.1,129.1,inclusive='neither'))
    return {'rows':len(d),'coord_missing':int(missing.sum()),'coord_missing_pct':round(float(missing.mean()*100),2) if len(d) else None,'coord_outside_pipeline_bbox':int(invalid.sum())}

def main():
    files=[ROOT/'service/data/processed'/n for n in ('stores.parquet','poi.parquet','meta.json')]
    st,poi=pd.read_parquet(files[0]),pd.read_parquet(files[1]);meta=json.loads(files[2].read_text(encoding='utf-8'))
    assert st.closed.notna().all()
    assert len(st)==meta['records']['통합']['total']
    assert not st.duplicated(['org_code','mgmt_no','service']).any()
    rows=[]
    for name,sv,cats,pfield,pcats,note in SPECS:
        mask=st.service.isin(sv)
        if cats is not None:
            assert set(cats)<=set(st.loc[mask,'category'])
            mask &= st.category.isin(cats)
        assert set(pcats)<=set(poi[pfield])
        s=st.loc[mask];p=poi.loc[poi[pfield].isin(pcats)];active=s.loc[~s.closed]
        row={'candidate':name,'license_definition':{'service':sv,'category':cats or 'ALL'},'poi_definition':{pfield:pcats},'mapping_note':note,
             'license_all':stats(s),'license_not_closed':stats(active),'license_closed':int(s.closed.sum()),
             'license_opened_2010plus':int((s.ld.dt.year>=2010).sum()),'poi':stats(p),'poi_exact_deduplicated':len(p.drop_duplicates()),
             'actual_license_categories':s.groupby(['service','category']).size().rename('rows').reset_index().to_dict('records'),
             'actual_poi_categories':p.groupby(['cat_m','cat_s']).size().rename('rows').reset_index().to_dict('records')}
        assert len(s)==len(active)+row['license_closed']
        assert len(p.drop_duplicates())<=len(p)
        rows.append(row)
    # Sensitivities resolve the most likely meeting questions without silently changing definitions.
    sensitivities={}
    for label,sv,cats in [('카페_서비스별칭',['일반음식점','휴게음식점'],['커피숍','까페','다방','전통찻집','라이브카페','키즈카페']),('치킨_호프통닭포함',['일반음식점'],['통닭(치킨)','호프/통닭']),('한식_인허가한식만',['일반음식점'],['한식'])]:
        s=st.loc[st.service.isin(sv)&st.category.isin(cats)]
        sensitivities[label]={'all':len(s),'not_closed':int((~s.closed).sum()),'categories':cats}
    result={'analysis_date':'2026-10-13','scope':'local processed Daegu snapshots, not live Supabase','reference_date':meta['reference_date'],'poi_configured_vintage':'202606','input_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files},'total_license':stats(st),'total_poi':stats(poi),'candidates':rows,'sensitivities':sensitivities}
    (OUT/'candidate_sectors.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines=['# 업종 선정 회의용 비교표','', '작성: 김선경 · 2026-10-13 · 후보/대응 규칙은 제안이며 최종 선정 아님.', '',
           '## 읽는 기준','',f"대구 전체 로컬 가공 스냅샷: 인허가 {len(st):,}행, 상가 {len(poi):,}행. Supabase를 직접 조회한 결과가 아니다. 인허가 기준일은 {meta['reference_date']}, 상가 설정 기준은 2026년 6월이며 실제 원본 관측일은 미확인이다.", '',
           '- 인허가 전체 = 과거 개·폐업 이력을 포함한 허가 기록. 점포 수나 현재 경쟁업체 수가 아니다.',
           '- 비폐업 = closed=False인 기록. 생성 코드에서 폐업/취소/말소 외 상태를 포함하므로 실제 정상 영업 확인과 다르다.',
           '- 좌표 누락 = lat 또는 lon이 없는 행. 괄호는 해당 열의 기록 수를 분모로 한 누락률이다.',
           '- 상가 가공 과정에서 좌표 결측행을 이미 제외했다. 아래 상가 누락 0은 원본 품질 100%를 뜻하지 않으며 원본 누락률은 확인 불가다.',
           '- 분류 대응은 업종 이름/범위를 비교한 제안이며 주소·상호를 이용한 점포 단위 연결률이 아니다. 두 자료 건수의 비율을 포괄률로 해석하지 않는다.', '',
           '## 후보별 건수와 좌표','',
           '| 후보 | 인허가 전체 | 비폐업 | 전체 좌표 누락 | 비폐업 좌표 누락 | 상가 기록 | 상가 동일행 제거 | 가공 상가 좌표 누락 |',
           '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    for r in rows:
        a,b,p=r['license_all'],r['license_not_closed'],r['poi']
        lines.append(f"| {r['candidate']} | {a['rows']:,} | {b['rows']:,} | {a['coord_missing']:,} ({a['coord_missing_pct']}%) | {b['coord_missing']:,} ({b['coord_missing_pct']}%) | {p['rows']:,} | {r['poi_exact_deduplicated']:,} | {p['coord_missing']} |")
    lines+=['','범위 밖 좌표는 인허가 생성 코드의 대구 점검 범위(35.4<위도<36.5, 128.1<경도<129.1)로 추가 검사했다. 법정 경계 판정이 아니며 상세 건수는 JSON에 있다. 동일행 제거도 고유 점포 수를 확정하지 않는다.','','## 분류 대응안과 회의 쟁점','','| 후보 | 인허가 포함 기준 | 상가 포함 기준 | 대응 판단 / 결정할 사항 |','| --- | --- | --- | --- |']
    for r in rows:
        d=r['license_definition'];cats=d['category'];definition='·'.join(d['service'])+' / '+('전 업태' if cats=='ALL' else '·'.join(cats))
        pdsc='; '.join(k+' = '+ '·'.join(v) for k,v in r['poi_definition'].items())
        lines.append(f"| {r['candidate']} | {definition} | {pdsc} | {r['mapping_note']} |")
    lines+=['','## 범위를 바꾸면 달라지는 인허가 건수','','| 대안 정의 | 전체 | 비폐업 |','| --- | ---: | ---: |']
    for k,v in sensitivities.items():lines.append(f"| {k} | {v['all']:,} | {v['not_closed']:,} |")
    lines+=['','## 회의에 제안할 선택지','','- 기존 지도를 활용하려면 카페(좁은 정의)를 우선 논의한다. 다방·키즈카페·베이커리 포함 여부부터 합의한다.',
            '- 음식 외 비교 후보는 미용실(헤어)이다. 네일·피부를 분리한 정의로 시작하면 범위가 명확해진다. 중식도 분류상 대응 후보로 함께 검토할 수 있다.',
            '- 담배 소매는 두 분류의 관측 대상 차이가 커 첫 직접 비교 대상에서 보류하는 편이 좋다. 노래방에 유흥주점을 포함하는 기존 키워드도 그대로 쓰지 않는다.',
            '- 확정할 항목: 대상 1~2개, 포함/제외 분류 목록, 기준 시점, 지도 대상과 생존분석 대상의 구분. 선택 후 주소·상호 표본을 직접 대조해 실제 대응을 검증한다.', '',
            '후보 추천은 이번 자료의 범위 명확성과 기존 작업 활용성을 기준으로 한 분석 제안이다. 매출·성공 가능성이나 ML 적합성을 확인한 결론이 아니다. 후보별 지역·기간 분포와 시간 분리 평가 가능성은 별도 검토가 필요하다.', '',
            '## 재현과 근거','','`.venv/Scripts/python.exe scripts/compare_candidate_sectors.py`', '',
            '입력: `service/data/processed/stores.parquet`, `poi.parquet`, `meta.json`. 정의 확인: `service/pipeline/build.py`, `service/pipeline/external.py`, `service/config.py`. 입력 해시·실제 세부분류별 건수·2010년 이후 개업 표본 수는 [JSON](candidate_sectors.json)에 저장한다. 서비스 분류나 DB는 변경하지 않았다.','']
    (OUT/'candidate_sectors.md').write_text('\n'.join(lines),encoding='utf-8')
    print('\n'.join(lines[lines.index('## 후보별 건수와 좌표'):lines.index('## 분류 대응안과 회의 쟁점')]))

if __name__=='__main__':main()
