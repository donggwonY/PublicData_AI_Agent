"""Build a standalone, local comparison screen from the validated A-07 model."""

import argparse
import csv
import hashlib
import io
import json
from collections import Counter
from datetime import date
from pathlib import Path

from threadpoolctl import threadpool_limits

from evaluate_a07_baselines import DATA
from evaluate_a07_models import CANDIDATES, load_examples
from prepare_a07_population import shift_month


def freeze_forecast(issue_date, month, target, entries, training_rows, cutoff, evaluation):
    if cutoff is None:
        raise ValueError("A comparison rule must be selected before freezing forecasts")
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(entries[0]))
    writer.writeheader()
    writer.writerows(sorted(entries, key=lambda entry: entry["admin_code"]))
    forecast_bytes = buffer.getvalue().encode("utf-8-sig")
    manifest = {
        "frozen_on_kst": issue_date.isoformat(),
        "base_month": month, "target_month": target,
        "series": "Daegu MOIS registered residents aged 0–9",
        "area_rows": len(entries),
        "forecast_rows": sum(entry["model_population"] is not None for entry in entries),
        "model": evaluation["selected_model"], "sklearn_version": evaluation["sklearn_version"],
        "training_rows": training_rows,
        "training_max_target_month": month,
        "input_panel_sha256": evaluation["panel_sha256"],
        "model_evaluation_sha256": hashlib.sha256((DATA / "model_evaluation.json").read_bytes()).hexdigest(),
        "comparison_evaluation_sha256": hashlib.sha256(
            (DATA / "comparison_evaluation.json").read_bytes()
        ).hexdigest(),
        "forecast_sha256": hashlib.sha256(forecast_bytes).hexdigest(),
        "evaluation": {
            "match": "Use official target-month counts with the same resident definition and administrative code. Exclude missing or noncomparable areas, including changes affecting comparability, and report every exclusion.",
            "population": "Evaluate mean absolute error and three-way change direction on the same eligible areas for both methods.",
            "comparison": "Take all unordered pairs of eligible areas. Compare predicted changes from the base month. Actual ties count as incorrect if a direction is displayed.",
            "display_gap_at_least_people": cutoff,
            "report": "For both methods report number shown, fraction of all eligible pairs shown and order accuracy among shown pairs.",
            "equal_coverage": "Use the number shown by the model at the fixed gap as the common budget. Rank each method by absolute forecast gap descending, breaking ties by ascending administrative code pair.",
        },
    }
    destination = DATA / f"frozen_{month}_to_{target}"
    destination.mkdir()
    (destination / "forecast.csv").write_bytes(forecast_bytes)
    (destination / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freeze-date", type=date.fromisoformat, help="Archive the forecast using this KST date")
    args = parser.parse_args()
    panel = DATA / "monthly_panel.csv"
    evaluation = json.loads((DATA / "model_evaluation.json").read_text(encoding="utf-8"))
    if evaluation["panel_sha256"] != hashlib.sha256(panel.read_bytes()).hexdigest():
        raise ValueError("The validation results and population panel must use the same input")
    with panel.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    month = max(row["base_month"] for row in rows)
    target = shift_month(month, 12)
    history = {(row["admin_code"], row["base_month"]): int(row["population_0_9"]) for row in rows}
    training = [
        example
        for base, examples in load_examples(panel).items()
        if shift_month(base, 12) <= month
        for example in examples
    ]
    model = CANDIDATES[evaluation["selected_model"]]()
    entries = []
    forecasts = []
    with threadpool_limits(limits=2):
        model.fit([row[1] for row in training], [row[2] for row in training])
        for row in rows:
            if row["base_month"] != month:
                continue
            code = row["admin_code"]
            current = history[code, month]
            estimate = None
            baseline = None
            if row["history_12m_usable"] == "1":
                features = [
                    current,
                    *(current - history[code, shift_month(month, -lag)] for lag in (3, 6, 12)),
                ]
                estimate = max(0, round(current + float(model.predict([features])[0])))
                baseline = max(0, current + features[-1])
            forecasts.append({
                "admin_code": code, "admin_area": row["admin_area"],
                "base_month": month, "target_month": target, "current_population": current,
                "model_population": estimate, "baseline_population": baseline,
                "withheld_reason": "" if estimate is not None else "incomparable_12_month_history",
            })
            entries.append({
                "name": row["admin_area"].removeprefix("대구광역시 "),
                "current": current, "estimate": estimate,
            })
    example_areas = {"중구 성내1동": 0, "수성구 범어3동": 1}
    entries.sort(key=lambda row: (
        row["estimate"] is None, example_areas.get(row["name"], 2), row["name"],
    ))
    if len(entries) < 2 or entries[1]["estimate"] is None:
        raise ValueError("At least two areas with estimates are required")
    final = evaluation["final"]
    comparison = json.loads((DATA / "comparison_evaluation.json").read_text(encoding="utf-8"))
    for split, digest in comparison["prediction_sha256"].items():
        predictions = DATA / f"model_predictions_{split}.csv"
        if hashlib.sha256(predictions.read_bytes()).hexdigest() != digest:
            raise ValueError("Re-run the comparison evaluation for the current predictions")
    cutoff = comparison["selection"]["cutoff"]
    if args.freeze_date:
        freeze_forecast(args.freeze_date, month, target, forecasts, len(training), cutoff, evaluation)
    payload = {
        "entries": entries, "month": month, "target": target,
        "mae": final["model"]["mae_people"], "baselineMae": final["repeat_change"]["mae_people"],
        "pairs": final["model"]["pair_accuracy"], "baselinePairs": final["repeat_change"]["pair_accuracy"],
        "direction": final["model"]["direction_accuracy"],
        "baselineDirection": final["repeat_change"]["direction_accuracy"],
        "sample": final["rows"],
        "cutoff": cutoff,
        "comparisonMetrics": comparison["final"]["model_change"]["cutoffs"].get(str(cutoff)),
    }
    output = Path(__file__).resolve().parents[1] / "output/a07_population_preview.html"
    output.parent.mkdir(exist_ok=True)
    output.write_text(HTML.replace("PAYLOAD", json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")),
                      encoding="utf-8")
    print(f"{month} -> {target}; training rows: {len(training)}")
    print(dict(Counter("estimated" if e["estimate"] is not None else "unavailable" for e in entries)))
    print(entries[0], entries[1])
    print(output)


HTML = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>대구 창업 후보지 인구 비교</title>
<style>
:root{color-scheme:light;--ink:#152b29;--green:#00644f;--line:#d9e5df;--muted:#455c56}
*{box-sizing:border-box}body{margin:0;background:#f3f7f4;color:var(--ink);
font-family:Inter,"Malgun Gothic",sans-serif;line-height:1.55}
main{width:min(940px,92vw);margin:48px auto}header{border-bottom:1px solid var(--line);padding-bottom:24px}
h1{font-size:clamp(1.75rem,4vw,2.65rem);letter-spacing:-.055em;margin:0}
p{margin:.4rem 0;color:var(--muted)}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;margin:22px 0}
article,details{background:white;border:1px solid var(--line);border-radius:14px;padding:20px}
label{display:block;font-weight:700;margin-bottom:8px}
select{width:100%;padding:10px;font:inherit;border:1px solid #93afa5;border-radius:8px;background:white;color:var(--ink)}
select:focus-visible,summary:focus-visible{outline:3px solid var(--green);outline-offset:3px}
dl{margin:18px 0 0}dl div{display:flex;justify-content:space-between;gap:8px;padding:10px 0;border-bottom:1px solid var(--line)}
dt{color:var(--muted)}dd{margin:0;font-weight:700;text-align:right;font-variant-numeric:tabular-nums}
dd[data-role=estimate]{color:var(--green)}#comparison{margin:0 0 16px;padding:14px;background:#e1efe8;border-radius:8px;color:var(--ink)}
summary{cursor:pointer;font-weight:700}details p{margin-top:10px}.foot{font-size:.875rem;margin-top:14px}
@media(max-width:600px){main{margin:24px auto}.grid{grid-template-columns:1fr}}
</style></head><body>
<main>
<header><h1>대구 창업 후보지 인구 비교</h1>
<p id="dates"></p></header>
<section class="grid" aria-label="후보지 선택과 결과">
<article><label for="area-a">후보지 A</label><select id="area-a"></select>
<dl id="result-a" aria-live="polite"></dl></article>
<article><label for="area-b">후보지 B</label><select id="area-b"></select>
<dl id="result-b" aria-live="polite"></dl></article>
</section>
<p id="comparison" role="status"></p>
<details><summary>예측 검증 결과</summary><p id="validation"></p><p id="ranking"></p><p id="direction"></p><p id="comparison-validation"></p></details>
<p class="foot">행정안전부 주민등록 거주자 자료를 사용한 로컬 시안입니다. 창업 후보지는 읍·면·동 단위입니다.</p>
</main>
<script>
const data = PAYLOAD;
const fmt = new Intl.NumberFormat("ko-KR");
const pct = value => (value * 100).toFixed(2) + "%";
const signed = value => (value > 0 ? "+" : "") + fmt.format(value) + "명";
const get = id => document.getElementById(id);
get("dates").textContent = "0~9세 주민등록 거주자 · " + data.month + " 기준 · " + data.target + " 추정";
get("validation").textContent = "과거 평가 " + fmt.format(data.sample) + "개 지역·월에서 평균 절대오차 "
  + data.mae.toFixed(2) + "명 · 단순 기준선 " + data.baselineMae.toFixed(2) + "명";
get("ranking").textContent = "후보지 증감 순서 적중률 " + pct(data.pairs) + " · 단순 기준선 " + pct(data.baselinePairs);
get("direction").textContent = "증감 방향 적중률 " + pct(data.direction) + " · 단순 기준선 " + pct(data.baselineDirection)
  + ". 신규 입주 등으로 인구가 갑자기 변하는 지역에서는 오차가 커질 수 있습니다.";
if (data.comparisonMetrics) {
  get("comparison-validation").textContent = "예상 증감 차이 " + data.cutoff + "명 이상만 비교 문구를 표시했을 때, "
    + "과거 평가에서 표시한 쌍의 증감 순서 적중률은 " + pct(data.comparisonMetrics.accuracy)
    + ", 전체 쌍 중 표시 비율은 " + pct(data.comparisonMetrics.coverage) + "였습니다.";
}
const selectors = [get("area-a"), get("area-b")];
selectors.forEach((select, index) => {
  data.entries.forEach((row, i) => select.add(new Option(row.name, i)));
  select.selectedIndex = index;
  select.addEventListener("change", render);
});
function render() {
  const selected = selectors.map(select => data.entries[Number(select.value)]);
  selected.forEach((row, index) => {
    const values = [
      ["현재 인구", fmt.format(row.current) + "명"],
      ["1년 뒤 추정", row.estimate === null ? "산출 보류" : fmt.format(row.estimate) + "명"],
      ["예상 증감", row.estimate === null ? "—" : signed(row.estimate - row.current)],
      ["예상 증감률", row.estimate === null || row.current === 0
        ? "—" : pct((row.estimate - row.current) / row.current)]
    ];
    const result = get(index === 0 ? "result-a" : "result-b");
    result.replaceChildren(...values.map(([label, value], i) => {
      const line = document.createElement("div");
      const title = document.createElement("dt");
      const amount = document.createElement("dd");
      title.textContent = label;
      amount.textContent = value;
      if (i === 1) amount.dataset.role = "estimate";
      line.append(title, amount);
      return line;
    }));
  });
  const [a, b] = selected;
  const comparison = get("comparison");
  if (a === b) comparison.textContent = "다른 후보지를 선택하면 두 지역을 비교할 수 있어요.";
  else if (a.estimate === null || b.estimate === null) {
    comparison.textContent = "선택한 후보지 중 비교 가능한 최근 12개월 인구 이력이 부족한 곳이 있어요.";
  } else {
    const changeA = a.estimate - a.current;
    const changeB = b.estimate - b.current;
    const gap = Math.abs(changeA - changeB);
    const difference = "1년 뒤 추정 인구 차이 " + fmt.format(Math.abs(a.estimate - b.estimate))
      + "명 · 예상 증감 차이 " + fmt.format(gap) + "명. ";
    if (data.cutoff === null || gap < data.cutoff || gap === 0) {
      comparison.textContent = difference + "어느 후보지의 증감이 더 클지는 불확실해요.";
    } else {
      const area = changeA > changeB ? a : b;
      const wording = changeA < 0 && changeB < 0 ? "감소폭이 더 작을 것으로 추정돼요."
        : "증감 인원이 더 클 것으로 추정돼요.";
      comparison.textContent = difference + area.name + "의 " + wording;
    }
  }
}
render();
</script></body></html>"""


if __name__ == "__main__":
    main()
