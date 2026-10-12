"""Descriptive test of the student's cafe/quick-food composition hypothesis."""
from pathlib import Path
import json
import hashlib
import os
import numpy as np
import pandas as pd
os.environ.setdefault('MPLCONFIGDIR', str(Path(__file__).resolve().parents[1]/'.venv/matplotlib-cache'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager

OUT = Path(__file__).resolve().parents[1]/'docs/a01'
QUICK = ['김밥/만두/분식','버거','토스트/샌드위치/샐러드','빵/도넛']


def correlation(x,y):
    if len(x)<3 or x.nunique()<2 or y.nunique()<2:
        return None
    return float(x.rank(method='average').corr(y.rank(method='average')))


def main():
    source=OUT/'poi_join.json'
    data=json.loads(source.read_text(encoding='utf-8'))
    rows=[]
    for r in data['station_results']:
        for mode in ['raw','exact_deduplicated']:
            key='category_counts' if mode=='raw' else 'category_counts_exact_deduplicated'
            denominator=r['poi_rows'] if mode=='raw' else r['poi_rows_exact_deduplicated']
            counts=r[key]
            assert sum(counts.values())==denominator
            cafe=counts.get('카페',0);quick=sum(counts.get(k,0) for k in QUICK)
            assert 0<=cafe+quick<=denominator
            rows.append({'station':r['station'],'radius_m':r['radius_m'],'mode':mode,
                         'denominator':denominator,'cafe_rows':cafe,'quick_rows':quick,
                         'cafe_pct':cafe/denominator*100 if denominator else None,
                         'quick_pct':quick/denominator*100 if denominator else None,
                         'combined_pct':(cafe+quick)/denominator*100 if denominator else None,
                         'daily_total':r['daily_boarding_alighting_sum'],
                         'transfer':r['transfer_group'],'coverage':r['coverage_status']})
    df=pd.DataFrame(rows)
    # Do not treat missing external-city shops as zero; border station is sensitivity-only.
    base=(df.coverage!='exclude_outside_daegu') & (df.coverage!='border_review') & (df.denominator>0)
    stats=[]
    for radius in [300,500]:
        for mode in ['raw','exact_deduplicated']:
            for scenario in ['primary','exclude_transfer','min_30_rows','include_border']:
                mask=base & (df.radius_m==radius) & (df['mode']==mode)
                if scenario=='exclude_transfer':mask &= ~df.transfer
                if scenario=='min_30_rows':mask &= df.denominator>=30
                if scenario=='include_border':mask=(df.coverage!='exclude_outside_daegu') & (df.denominator>0) & (df.radius_m==radius) & (df['mode']==mode)
                part=df[mask]
                stats.append({'radius_m':radius,'mode':mode,'scenario':scenario,'n':len(part),
                              **{name+'_spearman':correlation(part.daily_total,part[name+'_pct']) for name in ['cafe','quick','combined']}})
    primary=df[base & (df.radius_m==300) & (df['mode']=='raw')].copy()
    median=primary.daily_total.median()
    groups=[]
    for label,part in [('lower_or_equal',primary[primary.daily_total<=median]),('higher',primary[primary.daily_total>median])]:
        groups.append({'group':label,'n':len(part),'median_combined_pct':float(part.combined_pct.median()),
                       'median_cafe_pct':float(part.cafe_pct.median()),'median_quick_pct':float(part.quick_pct.median())})
    result={'checked_date':'2026-10-12','hypothesis':'역 이용량이 많을수록 주변 전체 상가 중 카페·간편식 비중이 높다',
            'denominator':'POI rows in union of exit buffers, all shop categories',
            'cafe_categories':['카페'],'quick_categories':QUICK,
            'input_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
            'primary_excluded_stations':['정평','임당','영남대','사월'],
            'missing_exit_stations':data['missing_exit_stations'],
            'primary_small_denominators':primary[primary.denominator<30][['station','denominator']].to_dict('records'),
            'statistics':stats,'traffic_median_split':float(median),'median_split_groups':groups,
            'station_results':rows,'inference':'descriptive only; overlapping catchments, unmatched time periods, datum and boundary uncertainty; no causal or significance claim'}
    (OUT/'hypothesis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    selected=[s for s in stats if s['scenario']=='primary']
    lines=['# A-01 첫 가설 비교: 역 이용량과 카페·간편식 비중','','2026-10-12 · 김선경 · 탐색 결과(최종 검증 아님)', '',
           '학생 가설: 오가는 사람이 많으니 카페/간편식 비중이 높을 것 같다.', '',
           '## 확정한 정의','',
           '- 주 분석: 각 역 출구 300m 합집합. 500m는 반경 민감도 비교. 도보거리 아님.',
           '- 분모: 범위 안 전체 상가 POI 행. 분자: 카페 + 김밥/만두/분식 + 버거 + 토스트/샌드위치/샐러드 + 빵/도넛.',
           '- 환승역 호선은 하나의 역으로 묶고 승하차 합계를 더했다. 고유 이용객 수가 아니다.',
           '- 정평·임당·영남대는 대구 POI 범위 밖이므로 제외. 사월은 경계 완전성 미확인으로 주 분석에서 제외하고 포함 결과를 별도 계산.',
           '- 출구 미연결 4항목은 누락 처리. 포함 역도 경계·출구 최신성 확인이 완결된 것은 아니다.', '',
           '## 순위 상관계수(Spearman)','',
           '양수면 이용량 순위가 높은 역에서 비중도 높은 경향, 0 근처면 뚜렷한 단조 경향이 약하다는 뜻이다. p값·인과효과를 제시하지 않는다.', '',
           '| 반경 | 중복 처리 | 역 수 | 카페 | 간편식 | 합계 |','| --- | --- | ---: | ---: | ---: | ---: |']
    for s in selected:
        lines.append(f"| {s['radius_m']}m | {s['mode']} | {s['n']} | {s['cafe_spearman']:.3f} | {s['quick_spearman']:.3f} | {s['combined_spearman']:.3f} |")
    main_stat=next(s for s in selected if s['radius_m']==300 and s['mode']=='raw')
    lines += ['', '첫 해석: 300m에서 카페 순위 상관은 '+f"{main_stat['cafe_spearman']:.3f}"+'으로 거의 0에 가깝고, 간편식은 '+f"{main_stat['quick_spearman']:.3f}"+'으로 양의 관계를 보인다. 카페와 간편식을 묶은 가설은 업종을 나누어 해석해야 한다. 이는 이번 표본의 탐색적 관찰이며 확정 결론이 아니다.', '', '## 300m 이용량 상·하위 절반 비교', '', f'이용량 중앙값 {median:,.0f}회/일을 기준으로 구분한 기술통계다. 경계값 동률은 하위 그룹에 포함한다.', '',
              '| 그룹 | 역 수 | 카페·간편식 합계 비중 중앙값 |','| --- | ---: | ---: |']
    for g in groups:lines.append(f"| {g['group']} | {g['n']} | {g['median_combined_pct']:.2f}% |")
    lines += ['', '## 추가 민감도(300m 원본 행)', '', '| 조건 | 역 수 | 합계 비중 순위 상관 |','| --- | ---: | ---: |']
    for s in stats:
        if s['radius_m']==300 and s['mode']=='raw':lines.append(f"| {s['scenario']} | {s['n']} | {s['combined_spearman']:.3f} |")
    lines += ['', '## 해석 제한', '',
              '- 양의 관계가 있어도 역 이용객이 업종 구성을 변화시켰다는 인과 해석은 할 수 없다. 도심·지가·상권 크기 등은 통제하지 않았다.',
              '- 반경별 범위가 달라지고 역 사이 상가가 중복되어 표본이 독립적이지 않다. 유의확률·신뢰구간을 임의로 붙이지 않는다.',
              '- POI 원천 식별자가 없어 전체 동일 행 제거는 중복 민감도 점검일 뿐 고유 점포 수를 확정하지 못한다.',
              '- 승하차 period는 01~07월, 원천 파일명은 20260731이다. POI 설정은 202606이며 원천 관측기간 검증 전 동일 시점 또는 현재 상황이라고 하지 않는다.',
              '- 공식 출구 좌표의 datum·최신 운영 여부·경계 완전성 미확인. 이 결과는 선택한 자료와 공간 가정에 한정된다.',
              '- 학생의 식사 수요 해석과 후속 시간대 비교는 time_slots.md에 기록했다. A-01 완료 처리하지 않는다.', '',
              '재현: `.venv/Scripts/python scripts/join_a01_poi.py` 후 `.venv/Scripts/python scripts/analyze_a01_hypothesis.py`.', '',
              '상세 역별 비중·정의·입력 해시: hypothesis.json. 산점도: hypothesis.png. 원본과 서비스 파일은 변경하지 않았다.']
    (OUT/'hypothesis.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    font=Path('C:/Windows/Fonts/malgun.ttf')
    if font.exists():font_manager.fontManager.addfont(str(font));plt.rcParams['font.family']='Malgun Gothic'
    plt.rcParams['axes.unicode_minus']=False
    fig,axes=plt.subplots(1,2,figsize=(12,5.5),sharey=True)
    for ax,radius in zip(axes,[300,500]):
        part=df[base & (df.radius_m==radius) & (df['mode']=='raw')]
        stat=next(s for s in selected if s['radius_m']==radius and s['mode']=='raw')
        ax.scatter(part.daily_total,part.combined_pct,s=32,alpha=.75,color='#146b81',edgecolors='white',linewidths=.4)
        ax.set_xscale('log');ax.set_xlabel('일평균 승차+하차 합계 (로그 눈금)')
        ax.set_title(f"출구 {radius}m · n={len(part)}\n순위 상관 {stat['combined_spearman']:.3f}")
        ax.grid(alpha=.18);ax.set_axisbelow(True)
        for name in ['반월당','동대구역','중앙로']:
            row=part[part.station==name]
            if len(row):ax.annotate(name,(row.daily_total.iat[0],row.combined_pct.iat[0]),xytext=(-5,7) if name=='반월당' else (4,5),ha='right' if name=='반월당' else 'left',textcoords='offset points',fontsize=8)
    axes[0].set_ylabel('전체 상가 중 카페·간편식 비중 (%)')
    fig.suptitle('이용량이 많은 역에서 카페·간편식 비중도 높을까?',fontsize=15)
    fig.text(.5,.015,'출처: 공식 출구 좌표 + 프로젝트 POI·승하차 스냅샷 | 탐색 결과 · 시점/좌표계 확인 미완료 · 인과 해석 불가',ha='center',fontsize=9,color='#555555')
    fig.tight_layout(rect=[0,.05,1,.94]);fig.savefig(OUT/'hypothesis.png',dpi=160);plt.close(fig)
    print(json.dumps({'primary':selected,'median_split_groups':groups,'small_denominators':result['primary_small_denominators']},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
