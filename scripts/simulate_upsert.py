"""Validate and merge projected records without mutating input state."""
from copy import deepcopy
from datetime import datetime
import hashlib
import json

FIELDS = {'name', 'road_addr_raw', 'jibun_addr_raw', 'ld', 'cd', 'closed'}


def merge_batch(current, batch):
    seen = set()
    for key, values in batch:
        if len(key) != 3 or any(not isinstance(k, str) or not k.strip() for k in key):
            raise ValueError('invalid key')
        if key in seen:
            raise ValueError('duplicate batch key')
        seen.add(key)
        if set(values) != FIELDS or not isinstance(values['closed'], bool):
            raise ValueError('invalid fields')
        start = datetime.strptime(values['ld'], '%Y-%m-%d')
        end = datetime.strptime(values['cd'], '%Y-%m-%d') if values['cd'] else None
        if (values['closed'] and end is None) or (end and end < start):
            raise ValueError('invalid dates')
    candidate = deepcopy(current)
    inserted = updated = unchanged = 0
    for key, values in batch:
        if key not in candidate: inserted += 1
        elif candidate[key] != values: updated += 1
        else: unchanged += 1
        candidate[key] = deepcopy(values)
    return candidate, {'inserted': inserted, 'updated': updated, 'unchanged': unchanged}


def fingerprint(state):
    serial = [[list(k), v] for k,v in sorted(state.items())]
    return hashlib.sha256(json.dumps(serial, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def experiment(current, batch):
    original = fingerprint(current)
    first, first_counts = merge_batch(current, batch)
    second, second_counts = merge_batch(first, batch)
    reversed_result, _ = merge_batch(current, list(reversed(batch)))
    failures = {}
    bad_key = deepcopy(batch)
    bad_key[-1] = (('', 'invalid', '일반음식점'), bad_key[-1][1])
    duplicate = deepcopy(batch) + [deepcopy(batch[0])]
    bad_date = deepcopy(batch)
    bad_date[-1][1]['closed'] = True
    bad_date[-1][1]['cd'] = ''
    for label, bad in [('missing_key',bad_key),('duplicate_key',duplicate),('closed_without_date',bad_date)]:
        rejected = False
        try: merge_batch(current, bad)
        except ValueError: rejected = True
        failures[label] = {'rejected':rejected, 'original_unchanged':fingerprint(current)==original}
    result = {
        'scope':'In-memory six-field projection only; not raw-data ingestion or production transaction.',
        'before_rows':len(current),'after_first_rows':len(first),'after_second_rows':len(second),
        'first_apply':first_counts,'second_apply':second_counts,
        'same_after_replay':first==second,'same_after_reversed_batch':first==reversed_result,
        'input_unchanged':fingerprint(current)==original,'failure_cases':failures,
        'before_sha256':original,'after_sha256':fingerprint(first),
    }
    assert result['same_after_replay'] and result['same_after_reversed_batch'] and result['input_unchanged']
    assert second_counts['inserted']==second_counts['updated']==0
    assert all(v['rejected'] and v['original_unchanged'] for v in failures.values())
    return result
