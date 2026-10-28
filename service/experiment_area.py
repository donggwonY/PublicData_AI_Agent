"""Saved retrospective area and calibration evidence for the local viewer."""
import json,math
from pathlib import Path
import pandas as pd
import streamlit as st
ROOT=Path(__file__).resolve().parents[1]/'docs/d03'
NAMES={'full_training_constant':'학습 평균 기준선','full_training_rf':'면적 모델 · 2010~2023 학습','calibration_base_rf':'보정 전 · 2010~2021 학습','sigmoid_rf':'보정 후 · 2023년으로 보정'}

def load_area(path=ROOT/'area_calibration.json'):
 data=json.loads(Path(path).read_text(encoding='utf-8'))
 scores=data['scores']
 if set(scores)!=set(NAMES):raise ValueError('모델 구성이 다릅니다.')
 first=next(iter(scores.values()))
 for m in scores.values():
  if m['n']<=0 or not 0<=m['events']<=m['n'] or (m['n'],m['events'])!=(first['n'],first['events']):raise ValueError('평가 표본이 다릅니다.')
  if not math.isclose(m['actual_pct'],100*m['events']/m['n'],abs_tol=1e-8):raise ValueError('실제 비율 불일치')
  for k in ['actual_pct','predicted_pct','brier','log_loss','roc_auc']:
   if not math.isfinite(m[k]):raise ValueError('유효하지 않은 지표')
  if not 0<=m['predicted_pct']<=100 or not 0<=m['brier']<=1 or m['log_loss']<0 or not 0<=m['roc_auc']<=1:raise ValueError('지표 범위 오류')
 for name in ['calibration_base_rf','sigmoid_rf']:
  bins=[b for b in data['bins'] if b['model']==name]
  if sum(b['n'] for b in bins)!=first['n'] or sum(b['events'] for b in bins)!=first['events']:raise ValueError('구간 표본 불일치')
  for b in bins:
   if b['n']<=0 or not 0<=b['events']<=b['n'] or not 0<=b['lower']<b['upper']<=1:raise ValueError('구간 오류')
   if not math.isfinite(b['predicted_pct']) or not 0<=b['predicted_pct']<=100 or not math.isclose(b['actual_pct'],100*b['events']/b['n'],abs_tol=1e-8):raise ValueError('구간 비율 오류')
 for m in data['bootstrap_vs_same_base']['metrics'].values():
  if not all(math.isfinite(m[k]) for k in ['lower95','upper95','difference']) or m['lower95']>m['upper95']:raise ValueError('불확실성 구간 오류')
 return data

def render_area():
 try:data=load_area()
 except (OSError,ValueError,KeyError,TypeError):
  st.error('면적 실험 결과를 읽을 수 없습니다. 결과 파일과 형식을 확인해 주세요.');st.stop()
 scores=data['scores'];before=scores['calibration_base_rf'];after=scores['sigmoid_rf']
 st.subheader('면적 추가와 확률 보정 · 2025년 1~9월 개업 표본')
 st.warning('현재 면적이 개업 당시와 같다는 가정의 탐색입니다. 2025년 결과를 본 뒤 추가한 보정 비교이며, 독립 검증이나 개인별 미래 예측이 아닙니다.')
 a,b,c=st.columns(3);a.metric('평가 인허가',f"{after['n']:,}건");b.metric('실제 1년 이내 신고 비율',f"{after['actual_pct']:.2f}%");c.metric('보정 후 평균 예측',f"{after['predicted_pct']:.2f}%")
 st.write('면적이 양수이고 위치가 있는 가게만 비교했습니다. 보정 계수는 2023년 자료로 학습했고, 2025년 결과에 맞춰 계수를 조정하지 않았습니다.')
 chart=pd.DataFrame([{'모델':NAMES[n],'평균 예측 (%)':m['predicted_pct'],'실제 신고 (%)':m['actual_pct']} for n,m in scores.items()]).set_index('모델')
 st.bar_chart(chart,stack=False)
 st.caption('평균 예측이 실제 비율에 가까워도 개별 가게의 확률이 정확하다는 뜻은 아닙니다. 신고 기록은 실제 사업 실패와 다릅니다.')
 table=pd.DataFrame([{'모델':NAMES[n],'Brier':m['brier'],'log loss':m['log_loss'],'AUC':m['roc_auc']} for n,m in scores.items()])
 st.dataframe(table,hide_index=True)
 st.caption('Brier·log loss는 낮을수록 좋습니다. 보정 효과는 같은 기초 모델의 보정 전·후로 비교합니다. 전체 학습 모델과는 학습량이 다릅니다.')
 drop=100*(before['brier']-after['brier'])/before['brier']
 st.write(f"같은 모델의 보정 전보다 Brier가 {drop:.2f}% 감소했습니다. AUC는 {after['roc_auc']:.3f}로 보정 전후 같습니다.")
 ci=data['bootstrap_vs_same_base']['metrics']['brier']
 st.write(f"건물 단위 재표집의 Brier 차이 95% 구간: {ci['lower95']:+.6f} ~ {ci['upper95']:+.6f} (음수는 개선).")
 if ci['lower95']<=0<=ci['upper95']:st.info('이 구간은 0을 포함합니다. 이번 표본의 개선이 안정적으로 이어진다고 확정할 수 없습니다.')
 st.subheader('예측 확률 구간별 실제 신고 비율')
 selected=st.selectbox('구간을 볼 모델',['보정 후','보정 전'])
 name='sigmoid_rf' if selected=='보정 후' else 'calibration_base_rf'
 bins=[b for b in data['bins'] if b['model']==name]
 st.dataframe(pd.DataFrame([{'예측 구간':f"{b['lower']*100:g}~{b['upper']*100:g}%",'인허가 수':b['n'],'평균 예측 (%)':b['predicted_pct'],'실제 신고 (%)':b['actual_pct']} for b in bins]),hide_index=True)
 st.caption('보정하면 각 구간에 속하는 가게가 바뀝니다. 두 표의 같은 구간이 같은 가게를 뜻하지 않습니다.')
 with st.expander('회의에서 설명할 문장',expanded=True):
  st.write('면적을 넣은 모델에서 개선을 확인했고, 과거 자료로 확률을 보정하니 평균 예측은 실제 비율에 가까워졌습니다. 다만 일부 구간의 오차와 과거 면적의 정확성 문제가 남아 연구용 비교 결과로 정리했습니다.')
 with st.expander('실험 범위와 남은 한계'):
  st.write('기초 모델 학습: 2010~2021년. 보정: 2023년. 비교: 2025년 1~9월. 단계 사이에는 1년 관찰 간격을 뒀습니다. 2025년 자료는 이미 본 후속 탐색이므로 새 독립 시험으로 부르지 않습니다.')
  st.write('면적 누락 가게는 제외됐고, 최신 기록의 면적·주소가 개업 당시와 같은지는 미확인입니다. 행사성 한시 영업도 섞였을 수 있습니다. 재표집 구간에는 모델 선택과 재학습 불확실성이 포함되지 않습니다.')
 st.download_button('면적·보정 집계 JSON 내려받기',json.dumps(data,ensure_ascii=False,indent=2),file_name='d03_area_calibration.json',mime='application/json')
 st.caption('저장된 집계만 보여줍니다. DB 접속·재학습·개인별 예측은 실행하지 않습니다.')
