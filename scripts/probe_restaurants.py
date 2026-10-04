"""Fetch five Daegu restaurant records. Never print credentials, URLs or raw errors."""
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = 'https://apis.data.go.kr/1741000/general_restaurants/info'


def main():
    text = (ROOT / '.env.data-go-kr').read_text(encoding='utf-8-sig')
    key = next((line.partition('=')[2].strip() for line in text.splitlines()
                if line.startswith('DATA_GO_KR_SERVICE_KEY=')), '')
    if not key:
        print('Missing local DATA_GO_KR_SERVICE_KEY.'); return 2
    key = unquote(key)
    params = {'serviceKey': key, 'pageNo': '1', 'numOfRows': '5',
              'returnType': 'JSON', 'cond[ROAD_NM_ADDR::LIKE]': '대구광역시'}
    request = Request(ENDPOINT + '?' + urlencode(params), headers={'Accept': 'application/json'})
    try:
        with urlopen(request, timeout=45) as response:
            raw = response.read(2_000_001)
            status = response.status
    except HTTPError as exc:
        print(f'API HTTP error {exc.code}; response body and URL withheld.'); return 2
    except (URLError, TimeoutError):
        print('API connection failed; details withheld to protect key.'); return 2
    if len(raw) > 2_000_000:
        print('Unexpected response size.'); return 2
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        try:
            xml = ET.fromstring(raw)
            code = xml.findtext('.//returnReasonCode') or xml.findtext('.//resultCode')
        except ET.ParseError:
            code = None
        print('Non-JSON response; numeric error code:', code if code and code.isdigit() else 'unavailable')
        return 2
    response = payload.get('response', {})
    header, body = response.get('header', {}), response.get('body', {})
    code = str(header.get('resultCode', ''))
    if code not in ('00', '0', '0000', 'INFO-000'):
        print('API did not report success; numeric code:', code if code.isdigit() else 'unavailable')
        print('Top-level field names:', [k for k in payload if k in ('response','header','body','resultCode','resultMsg')])
        return 2
    container = body.get('items', {})
    rows = container.get('item', []) if isinstance(container, dict) else container
    if isinstance(rows, dict): rows = [rows]
    if not isinstance(rows, list) or not rows or not all(isinstance(r, dict) for r in rows):
        print('No sample rows or unexpected items shape.'); return 2
    fields = sorted(set().union(*(row.keys() for row in rows)))
    required = ['OPN_ATMY_GRP_CD','MNG_NO','LCPMT_YMD','SALS_STTS_NM','DAT_UPDT_PNT']
    summary = {
        'queried_at_utc': datetime.now(timezone.utc).isoformat(), 'endpoint': ENDPOINT,
        'filter': {'ROAD_NM_ADDR contains': '대구광역시'},
        'http_status': status, 'result_code': code, 'page': body.get('pageNo'),
        'total_count_reported': body.get('totalCount'), 'sample_rows': len(rows),
        'required_fields_present': all(k in fields for k in required),
        'fields': fields,
        'org_codes': sorted({str(row.get('OPN_ATMY_GRP_CD', '')) for row in rows}),
        'status_counts': dict(Counter(str(row.get('SALS_STTS_NM', '')) for row in rows)),
        'update_times': sorted({str(row.get('DAT_UPDT_PNT', '')) for row in rows}),
        'limitations': 'First 5 road-address matches only; not all Daegu, no population estimate or incremental completeness verification.',
    }
    # Do not persist a credential if the upstream service unexpectedly echoes it.
    serialized = json.dumps(summary, ensure_ascii=False, indent=2)
    if key in serialized or params['serviceKey'] in serialized:
        print('Unexpected credential echo detected; output not saved.'); return 2
    target = ROOT / 'docs/d01/api_probe.json'
    target.write_text(serialized + '\n', encoding='utf-8')
    print(serialized)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
