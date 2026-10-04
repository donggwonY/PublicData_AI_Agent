"""Bounded, read-only pagination/replay/date-filter experiment (5 calls)."""
import hashlib
import json
from datetime import datetime, timezone
from urllib.parse import unquote, urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from probe_restaurants import ROOT, ENDPOINT


def row_key(row):
    return (str(row.get('OPN_ATMY_GRP_CD', '')), str(row.get('MNG_NO', '')), '일반음식점')


def parse_time(value):
    value = str(value)
    if len(value) == 14 and value.isdigit():
        return datetime.strptime(value, '%Y%m%d%H%M%S')
    return datetime.fromisoformat(value)


def digest(row):
    return hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def main():
    contents = (ROOT / '.env.data-go-kr').read_text(encoding='utf-8-sig')
    key = unquote(next((line.partition('=')[2].strip() for line in contents.splitlines()
                       if line.startswith('DATA_GO_KR_SERVICE_KEY=')), ''))
    if not key:
        raise ValueError('missing key')
    audit = []

    def fetch(label, page, start, end):
        params = {'serviceKey': key, 'pageNo': str(page), 'numOfRows': '5', 'returnType': 'JSON',
                  'cond[OPN_ATMY_GRP_CD::EQ]': '3410000',
                  'cond[DAT_UPDT_PNT::GTE]': start, 'cond[DAT_UPDT_PNT::LT]': end}
        with urlopen(Request(ENDPOINT + '?' + urlencode(params), headers={'Accept': 'application/json'}), timeout=30) as resp:
            raw = resp.read(2_000_001)
        if len(raw) > 2_000_000: raise ValueError('oversized response')
        data = json.loads(raw)['response']
        if str(data['header']['resultCode']) not in ('0', '00', '0000'):
            raise ValueError('API error')
        body = data['body']
        items = body.get('items') or {}
        rows = items.get('item') or [] if isinstance(items, dict) else items
        if isinstance(rows, dict): rows = [rows]
        if not isinstance(rows, list): raise ValueError('unexpected rows')
        lo, hi = parse_time(start), parse_time(end)
        parsed = [parse_time(row['DAT_UPDT_PNT']) for row in rows]
        audit.append({'label': label, 'page': page, 'start_inclusive': start, 'end_exclusive': end,
                      'total_reported': int(body['totalCount']), 'received': len(rows),
                      'region_matches': all(str(row.get('OPN_ATMY_GRP_CD')) == '3410000' for row in rows),
                      'date_matches': all(lo <= t < hi for t in parsed),
                      'missing_keys': sum(not all(row_key(r)) for r in rows),
                      'update_times': sorted(set(str(r['DAT_UPDT_PNT']) for r in rows))})
        return rows

    start, end = '20261003000000', '20261004000000'
    first = fetch('page1', 1, start, end)
    second = fetch('page2', 2, start, end)
    repeat = fetch('page1_repeat', 1, start, end)
    if not first: raise ValueError('empty first sample; choose another date')
    boundary = parse_time(first[0]['DAT_UPDT_PNT']).strftime('%Y%m%d%H%M%S')
    upper = fetch('exclude_boundary', 1, start, boundary)
    lower = fetch('include_boundary', 1, boundary, end)
    k1, k2, kr = [{row_key(r) for r in group} for group in (first, second, repeat)]
    merged = {row_key(r): digest(r) for r in first + second}
    before = len(merged)
    merged.update({row_key(r): digest(r) for r in repeat})
    result = {
        'queried_at_utc': datetime.now(timezone.utc).isoformat(), 'endpoint': ENDPOINT,
        'org_code': '3410000', 'region_note': 'Existing snapshot mostly maps this code to 중구; issuing authority need not equal address district.',
        'calls': audit, 'page_overlap_keys': len(k1 & k2),
        'page1_internal_duplicates': len(first)-len(k1), 'page2_internal_duplicates': len(second)-len(k2),
        'repeat_same_keys': k1 == kr,
        'repeat_same_payloads': {row_key(r): digest(r) for r in first} == {row_key(r): digest(r) for r in repeat},
        'unique_before_replay': before, 'unique_after_replay': len(merged),
        'boundary_partition_total_matches': audit[3]['total_reported'] + audit[4]['total_reported'] == audit[0]['total_reported'],
        'sample_contains_boundary': any(parse_time(r['DAT_UPDT_PNT']).strftime('%Y%m%d%H%M%S') == boundary for r in lower),
        'reported_count_covered': len(k1 | k2) == audit[0]['total_reported'] == audit[1]['total_reported'],
        'limitations': ['Coverage is only against API-reported count for this region/time; source completeness is not established.',
                        'No stable ordering guarantee established.', 'No deletion or historical correction behavior tested.',
                        'DAT_UPDT_PNT may reflect bulk publication, not business-level change; not established.'],
    }
    safe = json.dumps(result, ensure_ascii=False, indent=2)
    if key in safe: raise ValueError('credential echo')
    (ROOT / 'docs/d01/update_probe.json').write_text(safe + '\n', encoding='utf-8')
    print(safe)


if __name__ == '__main__':
    try:
        main()
    except HTTPError as exc:
        print('HTTP error:', exc.code, '(URL/body withheld)'); raise SystemExit(2)
    except (URLError, TimeoutError, ValueError, KeyError, TypeError, OSError):
        print('Experiment incomplete; sensitive error details withheld. No success report written.'); raise SystemExit(2)
