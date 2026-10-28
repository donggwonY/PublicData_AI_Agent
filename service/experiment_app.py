"""Local D-03 evidence viewer: streamlit run experiment_app.py."""
from pathlib import Path
import json
import math
import pandas as pd
import streamlit as st

RESULT = Path(__file__).resolve().parents[1] / 'docs/d03/historical_context.json'
LABELS = {'constant': '학습 평균 기준선', 'base': '기존 모델', 'context': '주변 상권 추가 모델'}


def load_results(path=RESULT):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    expected = ['2015-2016', '2017-2018', '2020-2021']
    if [r['window'] for r in data['results']] != expected:
        raise ValueError('검증 기간이 예상 결과와 다릅니다.')
    for row in data['results']:
        scores = row['scores']
        if set(scores) != set(LABELS):
            raise ValueError('비교 모델 구성이 다릅니다.')
        base = scores['base']
        for m in scores.values():
            if m['n'] <= 0 or (m['n'], m['events']) != (base['n'], base['events']):
                raise ValueError('같은 검증 표본끼리 비교해야 합니다.')
            if not 0 <= m['events'] <= m['n']:
                raise ValueError('사건 수가 표본 범위를 벗어났습니다.')
            if not math.isclose(m['actual_pct'], 100*m['events']/m['n'], abs_tol=1e-8):
                raise ValueError('실제 비율과 사건 수가 맞지 않습니다.')
            for key in ['actual_pct', 'predicted_pct', 'brier', 'log_loss', 'roc_auc']:
                if not math.isfinite(m[key]):
                    raise ValueError('유효하지 않은 지표가 있습니다.')
            if not 0 <= m['predicted_pct'] <= 100 or not 0 <= m['brier'] <= 1 or not 0 <= m['roc_auc'] <= 1 or m['log_loss'] < 0:
                raise ValueError('지표 범위를 확인해야 합니다.')
    return data


def main():
    st.set_page_config(page_title='D-03 실험 비교', page_icon='📊', layout='wide')
    st.title('일반음식점 폐업 신고 예측 · 실험 비교')
    st.caption('D-03 후속 실험 · 분석일 2026-10-28 · 인허가 기준일 2026-10-13')
    st.info('팀 검토용 실험 결과입니다. 개별 점포의 미래 폐업 확률이나 창업 추천을 제공하지 않습니다.')
    mode = st.radio('실험 보기', ['면적·확률 보정', '초기 주변 상권'], horizontal=True)
    if mode == '면적·확률 보정':
        from experiment_area import render_area
        render_area()
        return
    try:
        data = load_results()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        st.error('검증 결과를 읽을 수 없습니다. 결과 파일과 형식을 확인해 주세요.')
        st.stop()
    rows = data['results']
    better = sum(all(r['scores']['context'][k] < r['scores']['base'][k] for k in ['brier','log_loss']) for r in rows)
    st.subheader(f'3개 검증 기간 중 {better}개 기간에서 기존 모델보다 확률 오차 감소')
    st.write('과거 주변 정보를 추가해도 여러 시기에 걸쳐 꾸준한 개선을 확인하지 못했습니다. 현재 후보의 공개 확률 안내는 보류합니다.')
    period = st.selectbox('검증 기간', [r['window'] for r in rows], index=2)
    selected = next(r for r in rows if r['window'] == period)
    scores = selected['scores']
    c1,c2,c3 = st.columns(3)
    c1.metric('검증 인허가', f"{scores['base']['n']:,}건")
    c2.metric('실제 365일 이내 신고 비율', f"{scores['base']['actual_pct']:.2f}%")
    c3.metric('좌표 누락으로 제외', f"{selected['validation_without_coordinates']:,}건")
    st.caption('여기서 폐업 신고는 폐업·취소·말소 기록을 뜻합니다. 실제 사업 실패나 현장 공실과 같지 않습니다.')
    chart = pd.DataFrame({'모델':[LABELS[k] for k in LABELS],
        '평균 예측 확률 (%)':[scores[k]['predicted_pct'] for k in LABELS],
        '실제 신고 비율 (%)':[scores[k]['actual_pct'] for k in LABELS]}).set_index('모델')
    st.subheader('평균 예측과 실제 신고 비율')
    st.bar_chart(chart, stack=False)
    st.caption('평균 예측 확률은 정확도가 아닙니다. 두 비율이 가까워도 개별 사례를 잘 구분한다는 뜻은 아닙니다.')
    table = pd.DataFrame([{'모델': LABELS[k], '확률 오차 (Brier)':scores[k]['brier'],
        '확률 오차 (log loss)':scores[k]['log_loss'], '구분 능력 (AUC)':scores[k]['roc_auc']} for k in LABELS])
    st.dataframe(table, hide_index=True, column_config={key:st.column_config.NumberColumn(format='%.5f') for key in table.columns if key != '모델'})
    st.caption('Brier·log loss는 낮을수록 좋습니다. AUC는 높을수록 구분 능력이 좋으며, 상수 예측은 0.5입니다.')
    st.subheader('세 기간의 확률 오차 비교')
    overview = pd.DataFrame([{'검증 기간':r['window'], **{LABELS[k]:r['scores'][k]['brier'] for k in LABELS}} for r in rows])
    st.dataframe(overview, hide_index=True)
    with st.expander('어떤 정보를 추가했나요?', expanded=True):
        st.write('기존 모델: 업태·구군·개업 월. 추가 모델: 개업 60일 전 기준 주변 500m 일반음식점의 관측 영업 수와 직전 365일 개업·폐업일 기록 수.')
        st.write('각 기간에서 같은 표본으로 비교했습니다. 결과를 본 뒤 반경이나 시차를 바꾸지 않았고, 기존 최종 시험(2023~2024년)은 다시 평가하지 않았습니다.')
    with st.expander('해석할 때 주의할 점'):
        st.write('현재 인허가 자료의 날짜와 좌표로 과거를 복원했습니다. 새 외부 과거 자료를 확보한 결과가 아닙니다. 당시 주소·신고 지연·원천 누락을 완전히 확인하지 못했습니다.')
        st.write(f"이웃 원천에서 좌표가 없는 등의 이유로 {data['source_excluded_coordinates']:,}건을 제외했습니다. 주변 경쟁을 적게 집계할 수 있으며, 인허가 건수는 고유 점포 수와 다를 수 있습니다.")
        st.write('기존 결과를 본 뒤 진행한 후속 탐색입니다. 작은 차이의 통계적 유의성이나 미래 성능을 입증하지 않았습니다.')
    st.download_button('집계 결과 JSON 내려받기', json.dumps(data, ensure_ascii=False, indent=2), file_name='d03_historical_context.json', mime='application/json')
    st.caption('저장된 실험 집계 결과를 표시합니다. 이 화면은 DB 조회, 모델 재학습, 개인별 예측을 실행하지 않습니다.')


if __name__ == '__main__':
    main()
