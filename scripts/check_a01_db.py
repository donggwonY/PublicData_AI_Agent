"""Read-only shared DB comparison; no parquet fallback and no DB mutations."""
import io
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import numpy as np
import pandas as pd
import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'service'))
from core.datasource import _read_csv, _restore_dtypes
from join_a01_poi import distances
from snapshot_hashes import snapshot_sha256

OUT = ROOT / 'docs/a01'
TABLES = ['poi', 'station_traffic', 'area_context']


def main():
    local_url = next((s.split('=', 1)[1].strip().strip('"').strip("'")
                      for s in (ROOT / '.env').read_text(encoding='utf-8-sig').splitlines()
                      if s.startswith('APP_DATABASE_URL=')), '')
    url = os.environ.get('APP_DATABASE_URL') or local_url
    target = urlsplit(url)
    if (target.hostname != 'aws-0-ap-southeast-2.pooler.supabase.com'
            or not (target.username or '').endswith('.uoiamnbkzlvlskngataq')
            or target.port != 5432):
        raise ValueError('Unexpected connection target')
    frames, comparisons = {}, []
    with psycopg.connect(url, sslmode='require', connect_timeout=15, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute('BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY')
            cur.execute('SET LOCAL statement_timeout = 120000')
            cur.execute('SET LOCAL extra_float_digits = 3')
            cur.execute('SHOW transaction_read_only')
            if cur.fetchone()[0] != 'on':
                raise RuntimeError('Read-only transaction required')
            cur.execute('SELECT current_user')
            role = cur.fetchone()[0]
            cur.execute('SELECT version_id FROM app.current_version WHERE singleton')
            version = cur.fetchone()[0]
            cur.execute('SELECT status, reference_date, dtypes FROM app.dataset_versions WHERE version_id=%s', (version,))
            status, reference_date, dtypes = cur.fetchone()
            if status != 'current':
                raise ValueError('Expected current dataset')
            for table in TABLES:
                cur.execute('SELECT column_name,data_type FROM information_schema.columns '
                            'WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position', ('app', table))
                spec = [(c, t) for c, t in cur.fetchall() if c not in ('version_id', '_row')]
                query = sql.SQL('COPY (SELECT {} FROM app.{} WHERE version_id={} ORDER BY _row) '
                                "TO STDOUT WITH (FORMAT CSV, HEADER TRUE, NULL '\\N')").format(
                    sql.SQL(',').join(sql.Identifier(c) for c, _ in spec),
                    sql.Identifier(table), sql.Literal(version))
                buf = io.BytesIO()
                with cur.copy(query) as cp:
                    for chunk in cp:
                        buf.write(chunk)
                size = buf.tell()
                buf.seek(0)
                frame = _restore_dtypes(_read_csv(buf, spec), (dtypes or {}).get(table, {}))
                local = pd.read_parquet(ROOT / f'service/data/processed/{table}.parquet')
                equal = True
                try:
                    pd.testing.assert_frame_equal(frame, local, check_exact=True)
                except AssertionError:
                    equal = False
                comparisons.append({'table': table, 'db_rows': len(frame), 'local_rows': len(local),
                                    'exact_values_order_dtypes_equal': equal, 'download_bytes': size,
                                    'local_sha256': snapshot_sha256(ROOT / f'service/data/processed/{table}.parquet')})
                frames[table] = frame
                print(table, len(frame), 'exact_match', equal, flush=True)
            cur.execute('SELECT count(*) FROM app.stores WHERE version_id=%s', (version,))
            stores_count = cur.fetchone()[0]
            cur.execute('ROLLBACK')
    poi = frames['poi']
    loc_path = OUT / 'station_locations.json'
    points = next(g['points'] for g in json.loads(loc_path.read_text(encoding='utf-8'))['station_exit_groups']
                  if g['traffic_station'] == '동대구역')
    d = np.column_stack([distances(poi.lat.to_numpy(), poi.lon.to_numpy(), p['latitude'], p['longitude']) for p in points])
    cafe = poi.cat_s.eq('카페').to_numpy()
    unique = ~poi.duplicated().to_numpy()
    prior = json.loads((OUT / 'refresh_check.json').read_text(encoding='utf-8'))['dongdaegu']
    results = []
    for radius in [300, 500]:
        mask = d.min(axis=1) <= radius
        exits = []
        for i, p in enumerate(points):
            m = mask & cafe & (d.argmin(axis=1) == i)
            exits.append({'exit': p['exit'], 'rows': int(m.sum()), 'deduplicated': int((m & unique).sum())})
        results.append({'radius': radius, 'all_rows': int(mask.sum()), 'all_deduplicated': int((mask & unique).sum()),
                        'cafe_rows': int((mask & cafe).sum()), 'cafe_deduplicated': int((mask & cafe & unique).sum()), 'exits': exits})
    result = {'checked_at_utc': datetime.now(timezone.utc).isoformat(), 'project': 'uoiamnbkzlvlskngataq',
              'schema': 'app', 'db_role': role, 'transaction_read_only': True, 'version': version,
              'status': status, 'reference_date': str(reference_date), 'comparisons': comparisons,
              'stores_count_only': stores_count, 'dongdaegu': results, 'prior_counts_equal': results == prior,
              'location_sha256': snapshot_sha256(loc_path), 'database_written': False}
    (OUT / 'db_verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if not all(c['exact_values_order_dtypes_equal'] for c in comparisons) or results != prior:
        raise ValueError('Comparison differs; inspect saved non-secret result')
    print('PASS: exact input comparison and independent DB cafe recalculation')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Connection exceptions may contain credentials. Never print their text.
        print('FAILED:', type(exc).__name__, 'sqlstate:', getattr(exc, 'sqlstate', None))
        sys.exit(1)
