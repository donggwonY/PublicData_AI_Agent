"""Review explicit address markers only; no outcomes or fitting."""
import json,re
from collections import Counter
from pathlib import Path
from snapshot_hashes import snapshot_sha256
ROOT=Path(__file__).resolve().parents[1]
def main():
 out=ROOT/'docs/d03';source=out/'event_markers.json';data=json.loads(source.read_text(encoding='utf-8'))
 rows=[]
 rules=[('들안길 푸드페스티벌','들안길푸드페스티벌'),('세계인의 날','세계인의날'),('시장 굿페스티벌','굿페스티벌'),('경기장 행사장','DGB대구은행파크'),('백화점 행사장','롯데백화점')]
 for r in data['candidates']:
  if r['marker']!='explicit_address':continue
  text=re.sub(r'\s+','',' '.join([r['지번주소'],r['도로명주소']]))
  labels=[name for name,term in rules if term in text]
  assert len(labels)<=1
  rows.append({**r,'review_category':labels[0] if labels else '미분류'})
 assert len(rows)==data['totals']['explicit_address']==69
 assert len({r['key'] for r in rows})==len(rows)
 counts=dict(Counter(r['review_category'] for r in rows));assert sum(counts.values())==69
 report={'method':'AI-assisted literal address review; not human verification or legal permit classification','counts':counts,'rows':rows,'hashes':{'source':snapshot_sha256(source),'script':snapshot_sha256(Path(__file__))}}
 (out/'event_marker_review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 lines=['# 행사장 명시69건 주소 검토 — 2026-11-04','','기존 JSON만 읽어 AI 보조로 주소 문구를 검토했다. 상태·폐업일·기간·모델 점수를 사용하지 않았다. 사람이 허가자료를 대조한 검토는 아니다.','','| 주소 표기 | 건수 |','| --- | ---: |']
 for k,v in counts.items():lines.append(f'| {k} | {v} |')
 lines+=['','행사명이 특정된 축제/행사59+2=61건과 시설 행사장8건을 구분한다. 경기장7건·백화점1건은 상설 매장인지 단기 판매인지 주소만으로 알 수 없다. 축제명 명시61건도 법적 한시허가 유형·당시 입력 시점 미확인이다.','','69건을 일괄 삭제하지 않는다. 전체 후보391건에는 상호 오탐이 포함되어 별도 유지한다. 행사 표기가 없는 기록을 상설점포로 확정하지 않는다. 분류는 설명용 검토이며 현재 예측 모델 입력이나 운영 제외 규칙으로 적용하지 않는다. 다음 모델 비교에는 후보 범위와 평가계획을 먼저 고정해야 한다.','','기존69건·키 유일성·합계 확인 및 입력/스크립트 해시 저장. 원본 재처리·재학습·DB 변경 없음.']
 (out/'event_marker_review.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
 print(counts)
if __name__=='__main__':main()
