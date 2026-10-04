"""Compare one bounded API update window with the immutable local snapshot."""
import hashlib
import json
import argparse
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import unquote, urlencode
from urllib.request import urlopen
from urllib.error import HTTPError, URLError

import pandas as pd
from probe_restaurants import ROOT, ENDPOINT
from check_restaurant_updates import parse_time, row_key


def normal(value):
    return '' if value is None or pd.isna(value) else str(value).strip()


def day(value):
    text = normal(value)
    if not text: return ''
    return pd.to_datetime(text, errors='raise').strftime('%Y-%m-%d')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--simulate', action='store_true')
    args = parser.parse_args()
    token = unquote(next((line.partition('=')[2].strip() for line in
        (ROOT / '.env.data-go-kr').read_text(encoding='utf-8-sig').splitlines()
        if line.startswith('DATA_GO_KR_SERVICE_KEY=')), ''))
    if not token: raise ValueError('missing key')
    params = {'serviceKey': token, 'pageNo': '1', 'numOfRows': '100', 'returnType': 'JSON',
              'cond[OPN_ATMY_GRP_CD::EQ]': '3410000',
              'cond[DAT_UPDT_PNT::GTE]': '20261003000000',
              'cond[DAT_UPDT_PNT::LT]': '20261004000000'}
    with urlopen(ENDPOINT + '?' + urlencode(params), timeout=30) as resp:
        raw = resp.read(2_000_001)
    if len(raw) > 2_000_000: raise ValueError('large response')
    data = json.loads(raw)['response']
    if str(data['header']['resultCode']) not in ('0','00','0000'): raise ValueError('API failed')
    body = data['body']
    items = body.get('items') or {}
    rows = (items.get('item') or []) if isinstance(items, dict) else items
    if isinstance(rows, dict): rows = [rows]
    if not rows or len(rows) != int(body['totalCount']): raise ValueError('bounded window no longer fits one page')
    if len({row_key(r) for r in rows}) != len(rows): raise ValueError('duplicate API keys')
    for r in rows:
        if not all(row_key(r)) or str(r['OPN_ATMY_GRP_CD']) != '3410000': raise ValueError('bad key/region')
        if not datetime(2026,10,3) <= parse_time(r['DAT_UPDT_PNT']) < datetime(2026,10,4): raise ValueError('bad date')
    source = ROOT.parent / 'daegu_lifecycle_agent/data/processed/stores.parquet'
    manifest = json.loads((ROOT / 'docs/d01/manifest.json').read_text(encoding='utf-8'))
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    if sha != manifest['sha256']['stores.parquet']: raise ValueError('snapshot changed')
    old = pd.read_parquet(source)
    keys = ['org_code','mgmt_no','service']
    if old.duplicated(keys).any() or old[keys].isna().any().any(): raise ValueError('invalid snapshot keys')
    index = {tuple(normal(r[k]) for k in keys): r for r in old.to_dict('records')}
    mapping = {'BPLC_NM':'name','ROAD_NM_ADDR':'road_addr_raw','LOTNO_ADDR':'jibun_addr_raw'}
    observations = []
    batch = []
    for r in rows:
        ident = row_key(r)
        previous = index.get(ident)
        now = {local: normal(r.get(api)) for api,local in mapping.items()}
        now.update(ld=day(r.get('LCPMT_YMD')),cd=day(r.get('CLSBIZ_YMD')),
                   closed=any(w in normal(r.get('SALS_STTS_NM')) for w in ('폐업','취소','말소')))
        batch.append((ident, now))
        changes = []
        if previous is not None:
            for field, new in now.items():
                before = day(previous[field]) if field in ('ld','cd') else bool(previous[field]) if field=='closed' else normal(previous[field])
                if before != new: changes.append({'field':field,'before':before,'after':new})
            category = 'matched_changed' if changes else 'matched_unchanged_in_compared_fields'
        else:
            category = 'absent_from_snapshot'
        observations.append({'key':list(ident),'classification':category,
                             'license_date':now['ld'],'api_status':normal(r.get('SALS_STTS_NM')),
                             'license_after_snapshot_reference':bool(now['ld'] and now['ld'] > manifest['reference_date']),
                             'update_kind':normal(r.get('DAT_UPDT_SE')),
                             'changes':changes})
    report = {'queried_at_utc':datetime.now(timezone.utc).isoformat(),
              'snapshot_reference_date':manifest['reference_date'],'snapshot_sha256':sha,
              'query':{k:v for k,v in params.items() if k!='serviceKey'},
              'api_total':int(body['totalCount']),'classification_counts':dict(Counter(r['classification'] for r in observations)),
              'compared_fields':list(now),'observations':observations,
              'limitations':['Missing from cleaned snapshot does not prove a newly created license.',
                             'Only six normalized fields compared; source update timestamps were not preserved in stores.',
                             'API snapshot can change between executions; this is not a stored historical API response.',
                             'No source or production data modified.']}
    out=json.dumps(report,ensure_ascii=False,indent=2)
    if token in out: raise ValueError('credential echo')
    if args.simulate:
        from simulate_upsert import experiment
        current = {}
        for ident, r in index.items():
            if ident[0] != '3410000' or ident[2] != '일반음식점': continue
            values = {field:normal(r[field]) for field in mapping.values()}
            values.update(ld=day(r['ld']), cd=day(r['cd']), closed=bool(r['closed']))
            current[ident] = values
        simulation = experiment(current, batch)
        simulation['queried_at_utc'] = report['queried_at_utc']
        simulation['snapshot_sha256'] = sha
        simulation['query'] = report['query']
        simulation['source_file_unchanged'] = hashlib.sha256(source.read_bytes()).hexdigest() == sha
        assert simulation['source_file_unchanged']
        output = json.dumps(simulation,ensure_ascii=False,indent=2)
        if token in output: raise ValueError('credential echo')
        (ROOT / 'docs/d01/upsert_simulation.json').write_text(output+'\n',encoding='utf-8')
        print(output)
    else:
        (ROOT / 'docs/d01/update_comparison.json').write_text(out+'\n',encoding='utf-8')
        print(out)


if __name__ == '__main__':
    try: main()
    except HTTPError as e:
        print('HTTP error',e.code,'(details withheld)'); raise SystemExit(2)
    except (OSError,URLError,TimeoutError,ValueError,KeyError,TypeError):
        print('Comparison failed; sensitive exception details withheld.'); raise SystemExit(2)
