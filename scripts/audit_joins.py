"""D-01 snapshot join audit; never modifies source tables."""
import hashlib
import json
from pathlib import Path
import pandas as pd
from profile_data import table

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = ROOT.parent / 'daegu_lifecycle_agent/data/processed'
    manifest = json.loads((ROOT/'docs/d01/manifest.json').read_text(encoding='utf-8'))
    frames = {}
    for name in ('stores','units','transitions','legal_admin_map','area_context'):
        path=source/f'{name}.parquet'
        if hashlib.sha256(path.read_bytes()).hexdigest()!=manifest['sha256'][path.name]:
            raise ValueError('Snapshot differs from manifest')
        frames[name]=pd.read_parquet(path)
    st,un,tr,mp,ctx=[frames[n] for n in frames]
    checks=[]
    def record(name,missing,total):
        checks.append({'join':name,'unmatched':int(missing),'denominator':int(total),
                       'unmatched_pct':round(missing/total*100,3) if total else None})
    # Missing keys are never matched to other missing keys.
    u=un.loc[un.uid.notna(),['uid']]
    for name,frame in [('stores',st),('transitions',tr)]:
        merged=frame[['uid']].merge(u,on='uid',how='left',validate='many_to_one',indicator=True)
        record(f'{name}.uid → units.uid',(merged['_merge']=='left_only').sum(),len(frame))
    mp=mp.dropna(subset=['gu','legal_dong'])
    linked=st[['org_code','mgmt_no','service','gu','dong']].merge(mp[['gu','legal_dong','admin_dong','share']],
        left_on=['gu','dong'],right_on=['gu','legal_dong'],how='left',validate='many_to_one',indicator='map_match')
    linked['unmapped']=linked.map_match.eq('left_only')
    record('stores.(gu,dong) → legal_admin_map',linked.unmapped.sum(),len(st))
    valid_ctx=ctx.dropna(subset=['gu','admin_dong'])[['gu','admin_dong','pop_total']]
    linked=linked.merge(valid_ctx,on=['gu','admin_dong'],how='left',validate='many_to_one',indicator='context_match')
    record('stores → mapping → area_context',linked.context_match.eq('left_only').sum(),len(st))
    mapped=linked[~linked.unmapped]
    record('mapped stores → area_context',mapped.context_match.eq('left_only').sum(),len(mapped))
    linked['ambiguous_mapping']=linked.share.lt(1) & ~linked.unmapped
    by_gu=linked.groupby('gu',dropna=False).agg(rows=('service','size'),unmapped=('unmapped','sum'),
                                              ambiguous_mapping=('ambiguous_mapping','sum')).reset_index()
    by_gu['unmapped_pct']=(by_gu.unmapped/by_gu.rows*100).round(2)
    by_service=linked.groupby('service').agg(rows=('service','size'),unmapped=('unmapped','sum')).reset_index()
    by_service['unmapped_pct']=(by_service.unmapped/by_service.rows*100).round(2)
    summary={'snapshot_reference_date':manifest['reference_date'],'checks':checks,
             'missing_gu_or_dong':int(st[['gu','dong']].isna().any(axis=1).sum()),
             'mapped_to_nonunanimous_admin':int(linked.ambiguous_mapping.sum()),
             'context_matched_but_population_missing':int((linked.context_match.eq('both') & linked.pop_total.isna()).sum())}
    (ROOT/'docs/d01/join_audit.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    parts=['# D-01 조인 품질 점검',f"스냅샷 기준일 {manifest['reference_date']}. 입력 SHA-256을 기존 manifest와 대조했다.",
           '## 연결 실패율',table(pd.DataFrame(checks)),
           '모든 연결은 many_to_one 검증을 적용했다. 우측 키 결측은 제외해 결측끼리 연결되는 일을 막았다. 전체 인허가 행 기준이며 고유 점포/자리 비율과 다르다.',
           f"gu 또는 dong 결측: {summary['missing_gu_or_dong']:,}행. 대표 행정동 점유율이 1 미만인 매핑에 연결된 인허가: {summary['mapped_to_nonunanimous_admin']:,}행. 맥락표 연결 후 인구 결측: {summary['context_matched_but_population_missing']:,}행.",
           '## 구군별',table(by_gu),'## 업종별',table(by_service),
           '## 연결 실패 표본',table(linked.loc[linked.unmapped,['org_code','mgmt_no','service','gu','dong']].head(10)),
           '처음 10행이며 대표 무작위 표본이 아니다. 동/읍/면 이름의 단위 차이, 상가정보의 지역 범위, 주소 파싱 실패가 원인 후보다. 실패만으로 원인을 확정하지 않는다. 연결 성공도 행정 경계의 정확성을 보장하지 않는다.',
           '## 재현', '`python scripts/audit_joins.py` (pandas·pyarrow 필요). 원본을 수정하지 않고 이 보고서와 JSON만 생성한다.']
    (ROOT/'docs/d01/join_audit.md').write_text('\n\n'.join(parts)+'\n',encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))
    print(table(by_gu))


if __name__=='__main__': main()
