"""데이터 점검(pipeline/check_data.py) 규칙 검사 (E-04, 2026-11-20 추가)."""
import unittest

import pandas as pd

from pipeline.check_data import Report, check_frames


def _frames():
    units = pd.DataFrame({"uid": ["A 1층", "B 1층"]})
    stores = pd.DataFrame({"org_code": ["1", "1"], "service": ["s", "s"], "mgmt_no": ["a", "b"],
                           "uid": ["A 1층", "B 1층"], "gu": ["중구", "중구"], "dong": ["삼덕동1가", "삼덕동1가"]})
    transitions = pd.DataFrame({"uid": ["A 1층"]})
    lam = pd.DataFrame({"gu": ["중구"], "legal_dong": ["삼덕동1가"], "admin_dong": ["삼덕동"]})
    ac = pd.DataFrame({"gu": ["중구"], "admin_dong": ["삼덕동"]})
    area = pd.DataFrame({"level": ["구"], "gu": ["중구"], "dong": [None], "year": [2026]})
    probs = {c: [0.5] for c in ("p_food", "p_cafe")} | {c: [0.0] for c in
                                                       ("p_beauty", "p_food_retail", "p_tobacco", "p_entertainment", "p_other")}
    nts = pd.DataFrame({"uid": ["B 1층"], **probs, "data_reference_date": ["2026-11-06"]})
    return {"stores": stores, "units": units, "transitions": transitions, "area_year": area,
            "area_cycle": area.drop(columns="year"), "survival": area.drop(columns="year").assign(service="s", category="c"),
            "vacancy_area": area.drop(columns="year"), "legal_admin_map": lam, "area_context": ac,
            "next_tenant_scores": nts}


def _run(frames):
    rep = Report()
    check_frames(frames, {"reference_date": "2026-11-06"}, "t", rep)
    return {(r[1], r[2]) for r in rep.rows}, rep


class CheckDataTest(unittest.TestCase):
    def test_clean_frames_have_no_failures(self):
        _, rep = _run(_frames())
        self.assertFalse(rep.failed, [r for r in rep.rows if r[1] == "FAIL"])

    def test_duplicate_key_fails(self):
        f = _frames()
        f["units"] = pd.DataFrame({"uid": ["A 1층", "A 1층", "B 1층"]})
        rows, rep = _run(f)
        self.assertIn(("FAIL", "units 키 uid"), rows)

    def test_unknown_uid_fails(self):
        f = _frames()
        f["next_tenant_scores"] = f["next_tenant_scores"].assign(uid="Z 9층")
        rows, _ = _run(f)
        self.assertIn(("FAIL", "next_tenant_scores → units (uid)"), rows)

    def test_probabilities_must_sum_to_one(self):
        f = _frames()
        f["next_tenant_scores"] = f["next_tenant_scores"].assign(p_food=0.6)
        rows, _ = _run(f)
        self.assertIn(("FAIL", "next_tenant_scores 확률 합 = 1"), rows)

    def test_missing_required_table_fails(self):
        f = _frames()
        del f["transitions"]
        rows, _ = _run(f)
        self.assertIn(("FAIL", "transitions 표 있음"), rows)

    def test_admin_unmatched_rate_warns(self):
        f = _frames()
        f["stores"] = f["stores"].assign(dong=None)
        rows, rep = _run(f)
        self.assertIn(("WARN", "행정동 미연결 비율"), rows)
        self.assertFalse(rep.failed)


if __name__ == "__main__":
    unittest.main()
