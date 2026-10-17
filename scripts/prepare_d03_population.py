"""Normalize verified MOIS downloads; retain raw bytes and structural missingness."""
import csv,io,json,re,hashlib,shutil,calendar
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
FILES=['200901_200912_주민등록인구및세대현황_월간.csv','201001_201412_주민등록인구및세대현황_월간.csv','201501_201912_주민등록인구및세대현황_월간 (1).csv','202001_202412_주민등록인구및세대현황_월간 (1).csv']

def main():
 rawdir=ROOT/'data/raw/d03_population';rawdir.mkdir(parents=True,exist_ok=True)
 out=ROOT/'docs/d03';records=[];sources=[];months_seen=set();checks=0
 for filename in FILES:
  local=rawdir/filename
  if not local.exists():shutil.copyfile(Path.home()/'Downloads'/filename,local)
  b=local.read_bytes();digest=hashlib.sha256(b).hexdigest()
  rows=list(csv.DictReader(io.StringIO(b.decode('cp949'))))
  assert len({r['행정구역'] for r in rows})==len(rows)
  assert rows[0]['행정구역'].startswith('대구광역시  ')
  months=sorted({m.group(0) for c in rows[0] if (m:=re.match(r'\d{4}년\d{2}월_',c))})
  assert not months_seen.intersection(months);months_seen.update(months)
  def n(row,col):return int(row[col].strip().replace(',',''))
  for prefix in months:
   year,month=map(int,re.findall(r'\d+',prefix))
   for row in rows:
    assert n(row,prefix+'총인구수')==n(row,prefix+'남자 인구수')+n(row,prefix+'여자 인구수');checks+=1
   for col in ['총인구수','세대수','남자 인구수','여자 인구수']:
    assert n(rows[0],prefix+col)==sum(n(r,prefix+col) for r in rows[1:]);checks+=1
   for row in rows[1:]:
    m=re.fullmatch(r'대구광역시\s+(\S+)\s+\((\d+)\)',row['행정구역']);assert m
    gu,code=m.groups();structural=gu=='군위군' and (year,month)<(2023,7)
    vals={k:n(row,prefix+v) for k,v in [('population','총인구수'),('households','세대수'),('male','남자 인구수'),('female','여자 인구수')]}
    if structural:assert all(v==0 for v in vals.values())
    records.append({'gu':gu,'region_code':code,'reference_month':f'{year}-{month:02d}','reference_date':f'{year}-{month:02d}-{calendar.monthrange(year,month)[1]}',
     **{k:None if structural else v for k,v in vals.items()},'status':'not_covered_before_transfer' if structural else 'observed',
     'source_file':filename,'historical_release_date':None})
  sources.append({'file':filename,'sha256':digest,'encoding':'cp949','rows':len(rows),'months':len(months),'source_url':'https://jumin.mois.go.kr/statMonth.do','received_date':'2026-10-17'})
 expected={f'{y}년{m:02d}월_' for y in range(2009,2025) for m in range(1,13)}
 assert months_seen==expected
 assert len({(r['region_code'],r['reference_month']) for r in records})==len(records)
 regular=[r for r in records if r['gu']!='군위군'];assert len(regular)==8*192
 valid=[r for r in records if r['status']=='observed']
 assert len(valid)==1554
 result={'source':'MOIS resident population and households, user downloads','sources':sources,'checks':{'months':192,'unique_key':True,'arithmetic_checks':checks,'rows':len(records),'observed_rows':len(valid),'structural_missing_rows':len(records)-len(valid)},'rows':sorted(records,key=lambda r:(r['gu'],r['reference_month']))}
 (out/'population_monthly.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps(result['checks'],ensure_ascii=False))
if __name__=='__main__':main()
