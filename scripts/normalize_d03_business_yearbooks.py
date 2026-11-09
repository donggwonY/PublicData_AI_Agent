"""Normalize totals from verified source layouts, retaining edition provenance."""
import json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/d03'
def compact(s):return re.sub(r'\s+','',s)
def number(s):
 s=compact(s).replace(',','')
 return int(s) if re.fullmatch(r'\d+',s) else None
def main():
 annual=[];local=[];checks=[]
 for filename,district in [('business_yearbooks_expanded.json','달성군'),('suseong_business_sources.json','수성구')]:
  for src in json.loads((OUT/filename).read_text(encoding='utf-8'))['sources']:
   if src['status']!='source_table_saved':continue
   table=src['tables'][0]
   yearrows=[r for r in table if r and re.fullmatch(r'(19|20)\d{2}년?',compact(r[0]))]
   assert yearrows
   first=table.index(yearrows[0]);headers=' '.join(compact(c) for r in table[:first] for c in r)
   has_female='여성대표자' in headers;employee_col=3 if has_female else 2
   source_years=[]
   for row in yearrows:
    year=int(compact(row[0]).rstrip('년'));n=number(row[1]);e=number(row[employee_col]);assert n is not None and e is not None and n>0 and e>0
    source_years.append(year)
    annual.append({'district':district,'reference_year':year,'establishments':n,'workers':e,'edition_year':src['edition_year'],'source':src['url']})
   latest=max(source_years)
   loc=[]
   for row in table[table.index(yearrows[-1])+1:]:
    label=compact(row[0]) if row else ''
    if district=='달성군':is_area=label in ['화원','논공','다사','유가','옥포','현풍','가창','하빈','구지']
    else:is_area=bool(re.fullmatch(r'[가-힣0-9·]+동',label)) and src.get('section')=='040603'
    if not is_area:continue
    n,e=number(row[1]),number(row[employee_col]);assert n is not None and e is not None
    r={'district':district,'area_label':label,'reference_year_inferred':latest,'reference_year_verified':False,'establishments':n,'workers':e,'edition_year':src['edition_year'],'source':src['url']};local.append(r);loc.append(r)
   if loc:
    total=next(r for r in reversed(annual) if r['source']==src['url'] and r['reference_year']==latest)
    checks.append({'source':src['url'],'local_rows':len(loc),'establishments_sum_match':sum(r['establishments'] for r in loc)==total['establishments'],'workers_sum_match':sum(r['workers'] for r in loc)==total['workers']})
 grouped={}
 for r in annual:grouped.setdefault((r['district'],r['reference_year']),[]).append(r)
 conflicts=[{'district':k[0],'year':k[1],'values':sorted({(x['establishments'],x['workers']) for x in rs})} for k,rs in grouped.items() if len({(x['establishments'],x['workers']) for x in rs})>1]
 failed={c['source'] for c in checks if not(c['establishments_sum_match'] and c['workers_sum_match'])}
 for r in local:r['quality_hold']=r['source'] in failed
 out={'annual_source_rows':annual,'local_source_rows':local,'sum_checks':checks,'cross_edition_conflicts':conflicts,'unique_district_years':len(grouped),'limitations':['Edition provenance retained; duplicate yearbook observations must not be summed.','Local area year inferred from latest annual row, not independently verified publication date.','2020 census scope change not corrected.','Not model input: publication dates, historical area mapping and revisions need verification.']}
 (OUT/'business_yearbooks_normalized.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 lines=['# 사업체·종사자 표 정규화','','원본별 발간판·출처를 유지한 총사업체수/총종사자수 추출. 여성대표자 수와 종사자 성별 세부열은 총수와 분리.','',f'연간 원문행 {len(annual)}, 고유 지역×연도 {len(grouped)}, 동·읍면 원문행 {len(local)}.',f'지역합계 점검 {len(checks)}개 중 양쪽일치 {sum(x["establishments_sum_match"] and x["workers_sum_match"] for x in checks)}개. 판본 간 총수 충돌 {len(conflicts)}개 지역×연도.','','동·읍면 기준연도는 표 마지막 연간행에서 추정한 값이며 아직 확정하지 않음. 공표일·경계·2020 조사범위 변화 확인 전 과거예측 입력 사용 안 함. 판본 중복행 합산 금지. 상세값과 실패 체크는 JSON.']
 (OUT/'business_yearbooks_normalized.md').write_text('\n'.join(lines)+'\n',encoding='utf-8');print('\n'.join(lines))
if __name__=='__main__':main()
