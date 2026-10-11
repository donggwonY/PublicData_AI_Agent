"""Bounded historical-state inspection of one previously matched license."""
import hashlib
import json
from datetime import datetime, timezone
from urllib.parse import unquote, urlencode
from urllib.request import urlopen
from urllib.error import HTTPError, URLError
import pandas as pd
from probe_restaurants import ROOT, ENDPOINT


def main():
    source=ROOT/'service/data/processed/stores.parquet'
    manifest=json.loads((ROOT/'docs/d01/manifest.json').read_text(encoding='utf-8'))
    if hashlib.sha256(source.read_bytes()).hexdigest()!=manifest['sha256']['stores.parquet']:
        raise ValueError('snapshot changed')
    stores=pd.read_parquet(source)
    mgmt='3410000-101-2026-00161'
    old=stores[(stores.org_code.astype(str)=='3410000') & (stores.mgmt_no==mgmt) & (stores.service=='일반음식점')]
    if len(old)!=1: raise ValueError('not unique')
    old=old.iloc[0]
    name=str(old['name']).strip()
    if not name: raise ValueError('missing search name')
    token=unquote(next((line.partition('=')[2].strip() for line in
        (ROOT/'.env.data-go-kr').read_text(encoding='utf-8-sig').splitlines()
        if line.startswith('DATA_GO_KR_SERVICE_KEY=')),''))
    if not token: raise ValueError('missing key')
    results=[]
    for date in ('20260923','20261001','20261002','20261003',None):
        params={'serviceKey':token,'pageNo':'1','numOfRows':'100','returnType':'JSON',
                'cond[OPN_ATMY_GRP_CD::EQ]':'3410000','cond[BPLC_NM::LIKE]':name}
        if date: params['cond[BASE_DATE::EQ]']=date
        endpoint=ENDPOINT.removesuffix('/info')+('/history' if date else '/info')
        with urlopen(endpoint+'?'+urlencode(params),timeout=30) as response:
            raw=response.read(2_000_001)
        if len(raw)>2_000_000: raise ValueError('large response')
        data=json.loads(raw)['response']
        if str(data['header']['resultCode']) not in ('0','00','0000'): raise ValueError('API error')
        body=data['body']
        items=body.get('items') or {}
        rows=(items.get('item') or []) if isinstance(items,dict) else items
        if isinstance(rows,dict): rows=[rows]
        if len(rows)!=int(body['totalCount']): raise ValueError('incomplete name search')
        matched=[r for r in rows if str(r.get('OPN_ATMY_GRP_CD'))=='3410000' and str(r.get('MNG_NO'))==mgmt]
        results.append({'requested_base_date':date,'operation':'history' if date else 'info',
                        'search_total':int(body['totalCount']),'matching_key_count':len(matched),
                        'matched_rows':[{field:r.get(field) for field in ('BASE_DATE','SALS_STTS_NM','CLSBIZ_YMD','LCPMT_YMD','DAT_UPDT_PNT','LAST_MDFCN_PNT','DAT_UPDT_SE')} for r in matched]})
    report={'queried_at_utc':datetime.now(timezone.utc).isoformat(),'key':['3410000',mgmt,'일반음식점'],
            'baseline_reference_date':manifest['reference_date'],'baseline_closed':bool(old['closed']),
            'queries':results,'limitations':['One license only; not a boundary contract proof.',
                'Name filter could miss renamed historical records; no match does not prove deletion.',
                'No source data or production state updated.']}
    output=json.dumps(report,ensure_ascii=False,indent=2)
    if token in output: raise ValueError('credential echo')
    (ROOT/'docs/d01/history_probe.json').write_text(output+'\n',encoding='utf-8')
    print(output)


if __name__=='__main__':
    try: main()
    except HTTPError as e:
        print('HTTP error:',e.code,'(details withheld)'); raise SystemExit(2)
    except (OSError,URLError,TimeoutError,ValueError,KeyError,TypeError):
        print('History probe incomplete; sensitive details withheld.'); raise SystemExit(2)
