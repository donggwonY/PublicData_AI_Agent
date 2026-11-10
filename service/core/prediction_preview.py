"""Frozen historical-model simulation; no sklearn or live DB required."""
import math

def review_cell(cell):
    m=cell['scores']['region_cal'];base=cell['scores']['baseline'];reasons=[]
    if m['n']<200 or m['events']<20:reasons.append('검증 표본 부족')
    if m['roc_auc'] is None or m['roc_auc']<=0.5:reasons.append('폐업 여부 구분 능력 부족')
    if abs(m['predicted_pct']-m['actual_pct'])>5:reasons.append('평균 예측 오차 5%p 초과')
    if not all(m[k]<base[k] for k in ['brier','log_loss']):reasons.append('기본 평균 대비 두 오차 개선 미확인')
    return reasons

def model_probability(model,industry,gu,age_band):
    def sigmoid(z):
        return 1/(1+math.exp(-z)) if z>=0 else math.exp(z)/(1+math.exp(z))
    def shifted(p,delta):
        p=min(1-1e-6,max(1e-6,p))
        return sigmoid(math.log(p/(1-p))+delta)
    raw=sigmoid(model['intercept']+sum(model['weights'][name].get(value,0) for name,value in [('industry',industry),('gu',gu),('age_band',age_band)]))
    p=shifted(raw,model['global_shift'])
    p=shifted(p,model['industry_shifts'].get(industry,0))
    return shifted(p,model['region_shifts'].get(industry+'|'+gu,0))

def preview(model,industry,gu,age_band):
    if model.get('format_version')!=1 or model.get('usage')!='research_input_simulation_only':
        raise ValueError('지원하지 않는 모델')
    for name,value in [('industry',industry),('gu',gu),('age_band',age_band)]:
        if value not in model['weights'][name]:return {'probability':None,'reasons':['학습 범위 밖의 입력']}
    cell=next((x for x in model['evidence'] if x['industry']==industry and x['gu']==gu),None)
    if cell is None:return {'probability':None,'reasons':['지역·업종 검증 자료 없음']}
    reasons=review_cell(cell)
    if not model['training_combinations'].get('|'.join([industry,gu,age_band]),0):reasons.append('해당 운영기간의 학습 기록 없음')
    return {'probability':None if reasons else model_probability(model,industry,gu,age_band),'reasons':reasons,'evidence':cell['scores']['region_cal']}
