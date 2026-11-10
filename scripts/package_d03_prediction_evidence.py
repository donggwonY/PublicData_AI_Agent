"""Package historical evidence inside service so deployment needs no docs directory."""
import json
from pathlib import Path
from snapshot_hashes import snapshot_sha256
ROOT=Path(__file__).resolve().parents[1]
annual_path=ROOT/'docs/d03/continuous_year_evaluation.json';quarter_path=ROOT/'docs/d03/all_quarters_evaluation.json'
a=json.loads(annual_path.read_text(encoding='utf-8'));q=json.loads(quarter_path.read_text(encoding='utf-8'))
assert a['hashes']['stores']==q['hashes']['stores']
windows=[]
for w in a['windows']:
 windows.append({k:w[k] for k in ['train','cal','test']}|{'regions':[{'industry':r['industry'],'gu':r['gu'],'scores':{k:r['scores'][k] for k in ['baseline','region_cal']}} for r in w['regions']]})
quarterly={}
for w in q['results']:
 for r in w['regions']:
  m=r['scores']['candidate'];b=r['scores']['baseline'];key=r['industry']+'|'+r['gu']
  quarterly.setdefault(key,[]).append({'기준일':w['landmark'],'표본':m['n'],'폐업 신고':m['events'],'실제 신고(%)':m['actual_pct'],'과거 평균 예측(%)':m['predicted_pct'],'평균 오차(%p)':m['predicted_pct']-m['actual_pct'],'기준선 Brier':b['brier'],'모델 Brier':m['brier'],'두 오차 개선':all(m[x]<b[x] for x in ['brier','log_loss']),'소표본':r['small_sample']})
result={'windows':windows,'quarterly':quarterly,'reference_date':q['reference_date'],'quarterly_range':[q['results'][0]['landmark'],q['results'][-1]['landmark']],'coverage_quarters':len(q['coverage']),'evaluated_quarters':len(q['results']),'source_hashes':{'annual':snapshot_sha256(annual_path),'quarterly':snapshot_sha256(quarter_path),'stores':a['hashes']['stores']}}
p=ROOT/'service/data/research/closure_validation.json';p.write_text(json.dumps(result,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n',encoding='utf-8')
print('Packaged',len(windows),'annual landmarks and',len(q['results']),'quarterly landmarks;',p.stat().st_size,'bytes')
