"""Offline prototype: stage a complete window before returning a new state.

No network, disk commit, production integration, or deletion handling.
Dates use one caller-defined timezone; naive/aware mixing is rejected by Python.
"""
from copy import deepcopy
from datetime import datetime
from simulate_upsert import merge_batch


def timestamp(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('missing version timestamp')
    return datetime.strptime(value, '%Y%m%d%H%M%S') if len(value) == 14 and value.isdigit() else datetime.fromisoformat(value)


def collect_window(state, start, end, fetch_page, page_size=2, max_pages=100):
    """fetch_page(n) -> {page, total, rows:[{key, updated_at, values}]}.

    state: {scope:(authority,service), watermark: exclusive upper bound,
            records: {key:{updated_at,values}}}. Return a new state only on success.
    Existing records must have trusted source timestamps; no fabricated baseline.
    """
    lo, hi, watermark = map(timestamp, (start, end, state['watermark']))
    if not lo < hi or lo > watermark or hi < watermark:
        raise ValueError('invalid or gapped window')
    if page_size < 1 or max_pages < 1:
        raise ValueError('invalid bounds')
    candidate = deepcopy(state)
    seen = set()
    expected = None
    stats = dict(inserted=0, updated=0, identical=0, stale=0)
    page = 1
    while True:
        if page > max_pages:
            raise ValueError('page limit exceeded')
        response = fetch_page(page)  # Exceptions propagate; input state untouched.
        total = response['total']
        if type(total) is not int or total < 0 or response['page'] != page:
            raise ValueError('bad pagination metadata')
        if expected is None: expected = total
        if expected != total:
            raise ValueError('total changed during fetch')
        rows = response['rows']
        remaining = max(0, expected - (page - 1) * page_size)
        if not isinstance(rows, list) or len(rows) != min(page_size, remaining):
            raise ValueError('incomplete page')
        for row in rows:
            key = tuple(row['key'])
            # Reuse six-field/key/date validation from the previous experiment.
            merge_batch({}, [(key, row['values'])])
            if (key[0], key[2]) != tuple(state['scope']):
                raise ValueError('wrong scope')
            if key in seen: raise ValueError('duplicate across pages')
            seen.add(key)
            version = timestamp(row['updated_at'])
            if not lo <= version < hi: raise ValueError('outside requested window')
            previous = candidate['records'].get(key)
            if previous is None:
                stats['inserted'] += 1
            else:
                old_version = timestamp(previous['updated_at'])
                if version < old_version:
                    stats['stale'] += 1
                    continue
                if version == old_version:
                    if row['values'] != previous['values']:
                        raise ValueError('conflicting payload at same timestamp')
                    stats['identical'] += 1
                    continue
                stats['updated'] += 1
            candidate['records'][key] = {'updated_at': row['updated_at'], 'values': deepcopy(row['values'])}
        if page * page_size >= expected: break
        page += 1
    if len(seen) != expected: raise ValueError('unique count mismatch')
    candidate['watermark'] = end
    return candidate, stats
