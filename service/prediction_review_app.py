"""Local service-readiness review. Historical evaluation, not live inference."""
import json
from pathlib import Path
import pandas as pd
import streamlit as st

RESULT=Path(__file__).parent/'data/research/closure_validation.json'

from core.prediction_preview import review_cell, preview

@st.cache_data(show_spinner=False)
def load_results(path=RESULT):
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    if [w['test'] for w in data['windows']]!=list(range(2013,2026)):
        raise ValueError('연속 평가기간 불일치')
    for w in data['windows']:
        if (w['train'],w['cal'])!=(w['test']-4,w['test']-2):
            raise ValueError('평가 규칙 불일치')
    return data

def render_review():
    st.subheader('폐업 신고 예측 · 연구용')
    st.info('과거 검증 결과와 고정 모델의 입력 시뮬레이션입니다. 현재 점포의 검증된 미래 확률이나 창업 추천이 아닙니다.')
    try:
        data=load_results()
    except (OSError,ValueError,KeyError,TypeError):
        st.error('검증 결과 파일을 확인해 주세요.')
        return
    industry=st.selectbox('업종',sorted({r['industry'] for w in data['windows'] for r in w['regions']}),key='review_industry')
    areas=sorted({r['gu'] for w in data['windows'] for r in w['regions'] if r['industry']==industry})
    if st.session_state.get('review_gu') not in areas:
        st.session_state['review_gu']=areas[0]
    gu=st.selectbox('지역',areas,key='review_gu')
    rows=[]
    for w in data['windows']:
        cell=next((r for r in w['regions'] if r['industry']==industry and r['gu']==gu),None)
        if cell is None:
            rows.append({'연도':w['test'],'검토 결과':'평가 기록 없음'})
            continue
        m=cell['scores']['region_cal'];reasons=review_cell(cell)
        rows.append({'연도':w['test'],'표본':m['n'],'폐업 신고':m['events'],'과거 평균 예측(%)':m['predicted_pct'],'실제 신고(%)':m['actual_pct'],'평균 오차(%p)':m['predicted_pct']-m['actual_pct'],'AUC':m['roc_auc'],'검토 결과':' / '.join(reasons) if reasons else '추가 검증 후보 · 적용 승인 아님'})
    latest=rows[-1]
    st.subheader('2025년 검토 결과')
    st.write(latest['검토 결과'])
    st.caption('예측 대상: 해당 연도 1월 1일 영업 중인 인허가의 이후 365일 폐업 신고. 신규 창업 실패 확률이 아닙니다.')
    with st.expander('연구용 입력 시뮬레이션'):
        st.caption('2021년 학습·2023년 보정·2025년 평가 모델입니다. 운영기간은 예측 기준일 당시를 가정합니다. 현재 시점용 갱신 모델이 아닙니다.')
        band=st.selectbox('기준일 당시 운영기간 구간',['<1','1-3','3-5','5-10','10+'],format_func=lambda x:{'<1':'365일 미만','1-3':'365~1,094일','3-5':'1,095~1,824일','5-10':'1,825~3,649일','10+':'3,650일 이상'}[x])
        if st.button('모델 계산 확인',key='preview_calculate'):
            try:
                artifact=json.loads((Path(__file__).parent/'data/research/closure_preview_model.json').read_text(encoding='utf-8'))
                result=preview(artifact,industry,gu,band)
            except (OSError,ValueError,KeyError,TypeError):
                st.error('모델 파일을 확인할 수 없습니다.')
            else:
                if result['probability'] is None:
                    st.warning('표시 보류: '+' / '.join(result['reasons']))
                else:
                    st.metric('고정 모델 계산값 · 연구용',f"{result['probability']*100:.2f}%")
                    ev=result['evidence']
                    st.caption(f"2025년 같은 업종·지역 검증 {ev['n']:,}건 · 실제 신고율 {ev['actual_pct']:.2f}% · 평균 예측 {ev['predicted_pct']:.2f}%")
                    st.caption('선택한 조건의 모델 계산값이며 특정 가게의 실제 위험을 검증한 수치가 아닙니다. 사후 표시 기준은 서비스 허용 기준으로 검증되지 않았습니다.')
    st.subheader('연초별 상세 검증 · 2013~2025')
    frame=pd.DataFrame(rows)
    st.dataframe(frame,hide_index=True,width='stretch')
    st.download_button('선택 결과 CSV',frame.to_csv(index=False).encode('utf-8-sig'),file_name='historical_prediction_review.csv',mime='text/csv')
    with st.expander('전체 분기 검증 · 2002~2025'):
        st.caption(f"자료 기준일 {data['reference_date']} · 전체 {data['coverage_quarters']}개 분기 시작일 중 학습·보정 조건을 충족한 {data['evaluated_quarters']}개 분기 평가. 2013년 이전도 포함합니다.")
        records=data['quarterly'].get(industry+'|'+gu,[])
        if records:
            quarters=pd.DataFrame(records)
            st.dataframe(quarters,hide_index=True,width='stretch')
            st.download_button('분기별 결과 CSV',quarters.to_csv(index=False).encode('utf-8-sig'),file_name='quarterly_prediction_review.csv',mime='text/csv',key='review_quarter_csv')
        else:
            st.info('선택 조건의 분기 평가 기록이 없습니다.')
        st.caption('과거 폐업 이력의 완전성은 확인되지 않았으며 초기 구간은 해석에 주의가 필요합니다. 분기 간 추적기간과 점포가 겹치므로 독립 시험으로 볼 수 없습니다.')
    with st.expander('검토 기준과 한계'):
        st.write('표본200건·신고20건, AUC>0.5, 평균오차≤5%p, 기본 평균 대비 Brier·log loss 모두 감소를 확인합니다. 기존 진단 기준을 묶은 사후 검토안으로, 운영 허용 기준이 검증된 것은 아닙니다.')
        st.write('조건을 충족해도 이후 기간 성능은 보장되지 않습니다. 연도별 선택적 모델 교체나 실패 집단 제외 후 성능 재계산은 하지 않습니다. 실제 도입 전 대상·보류 기준, 데이터 갱신 주기, 예측 시점과 결과 추적 방식을 팀과 확정해야 합니다.')
        st.write('현재 자료로 과거를 복원했으며 단기 행사와 같은 자리의 여러 인허가가 포함됩니다. 공개 앱 통계와 제외 기준이 다릅니다.')

def main():
    st.set_page_config(page_title='폐업 신고 예측 검증',layout='wide')
    render_review()

if __name__=='__main__':main()
