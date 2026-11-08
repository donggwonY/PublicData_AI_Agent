"""Index explicitly labeled table years, not inferred publication dates."""
import json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/d03'
def main():
 rows=[]
 for filename,district in [('business_yearbooks_expanded.json','달성군'),('suseong_business_sources.json','수성구')]:
  for source in json.loads((OUT/filename).read_text(encoding='utf-8'))['sources']:
   if source['status']!='source_table_saved':continue
   years=set()
   for table in source['tables']:
    for row in table:
     label=re.sub(r'\s+','',row[0]) if row else ''
     if re.fullmatch(r'(19|20)\d{2}년?',label):years.add(int(label.rstrip('년')))
   assert years
   rows.append({'district':district,'edition_year':source['edition_year'],'url':source['url'],'explicit_table_years':sorted(years),'latest_explicit_year':max(years),'publication_date_verified':False,'local_area_rows_reference_year_verified':False})
 report={'checked_on':'2026-11-08','sources':rows,'limitations':['Years extracted only from explicit first-column labels, not from HTML comments.','Latest annual total does not alone verify every local-area row reference date.','Publication date and 2020 census coverage changes remain unverified.','Overlapping yearbooks must not double-count observations.']}
 (OUT/'yearbook_coverage.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 lines=['# 확보 연보의 명시 연도 점검','','표 첫 열에 직접 적힌 연도만 추출. HTML 주석의 기준일을 사용하지 않음. 발간연도≠자료연도≠공표일.','','|지역|발간판|표에 명시된 연도|','|---|---:|---|']
 for r in rows:lines.append(f"|{r['district']}|{r['edition_year']}|{', '.join(map(str,r['explicit_table_years']))}|")
 lines+=['','읍면동별 행의 기준연도와 실제 공표일은 별도확인 필요. 동일연도 중복판본을 독립관측으로 합산하지 않음. 2020년 전후 조사범위 변경 검토 전 단순증가율 계산 금지. 모델 입력 미채택.']
 (OUT/'yearbook_coverage.md').write_text('\n'.join(lines)+'\n',encoding='utf-8');print('indexed',len(rows),'tables')
if __name__=='__main__':main()
