"""상가정보 변수 생성 → $E05_WORK/sangga_features.parquet + 연결률 보고 $E05_WORK/sangga_report.json"""
import json, os, sys, time
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths as E5P
import sangga as G

VF = E5P.VF
t = time.time()
d = G.load_quarters(os.path.join(E5P.AUX, 'sangga'),
                    E5P.SANGGA_MAP)
d.to_parquet(os.path.join(VF, 'sangga_quarters.parquet'), index=False)
print('loaded', len(d), f'{time.time()-t:.0f}s', flush=True)
sg = G.SG(d)
X = pd.read_parquet(os.path.join(VF, 'asof_episodes.parquet'))
F = pd.concat([sg.features(X, X.t0, 's1_'), sg.features(X, X.t0 + pd.Timedelta(days=90), 's2_')], axis=1)
F.insert(0, 'occupant_id', X.occupant_id.to_numpy())
F.to_parquet(os.path.join(VF, 'sangga_features.parquet'), index=False)
m16 = X.close_year >= 2016
eb = X.building_key.isin(set(d.bkey.dropna()))
rep = {'store_quarters': len(d), 'quarters': len(sg.qs), 'unknown_code_rows': int(d.unknown_code.sum()),
       'bkey_parsed_pct': round(float(d.bkey.notna().mean() * 100), 1),
       'floor_parsed_pct': round(float(d.floor.notna().mean() * 100), 1),
       'other_share_pct': round(float(d.other.mean() * 100), 1),
       'episodes_2016plus': int(m16.sum()),
       'episode_building_in_sangga_pct_2016plus': round(float(eb[m16].mean() * 100), 1),
       'episode_has_floor_pct_2016plus': round(float(X.floor[m16].notna().mean() * 100), 1),
       's2_missing_pct_2016plus': (F.loc[m16.to_numpy(), [c for c in F.columns if c.startswith('s2_')]].isna().mean() * 100).round(1).to_dict(),
       's2_floor_other_gt0_pct_2016plus': round(float((F.loc[m16.to_numpy(), 's2_sg_floor_other'] > 0).mean() * 100), 1),
       'seconds': round(time.time() - t)}
json.dump(rep, open(os.path.join(VF, 'sangga_report.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(json.dumps(rep, ensure_ascii=False, indent=1))
