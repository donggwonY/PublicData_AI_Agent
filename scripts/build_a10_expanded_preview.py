"""Export all 83 qualified industry comparisons and rebuild the local preview."""

import html
import json
import re

import numpy as np
import pandas as pd

from export_a10_app_comparison import MONTH, ROOT


DOCS = ROOT / "docs/a10"
AREAS = ("대구광역시 중구 성내1동", "대구광역시 수성구 범어3동", "대구광역시 달서구 월성1동")


def main():
    validation = pd.read_csv(DOCS / "expanded_industry_validation.csv")
    if len(validation) != 83 or not validation.industry_code.is_unique:
        raise ValueError("Expected 83 unique qualified industries")
    if int(validation.confirmed_improvement.sum()) != 22:
        raise ValueError("Expected the reviewed 22 improved industry methods")
    validation["active_method"] = validation.selected_method.where(
        validation.confirmed_improvement, "poisson_context"
    )
    original = pd.read_csv(ROOT / f"data/raw/a10/industry_comparison_{MONTH}.csv", dtype={"admin_code": str})
    nearby = pd.read_csv(ROOT / f"data/raw/a10/expanded_nearby_predictions_{MONTH}.csv", dtype={"admin_code": str})
    keys = ["admin_code", "industry_code"]
    data = nearby.merge(validation[["industry_code", "active_method"]], on="industry_code", validate="many_to_one")
    reference = original.loc[original.industry_code.isin(validation.industry_code)]
    if len(data) != 12616 or data.duplicated(keys).any():
        raise ValueError("Expected 152 areas by 83 industries")
    if not data.groupby("industry_code").size().eq(152).all():
        raise ValueError("Each industry must cover 152 areas")
    merged = data.merge(reference[keys + ["actual_shops", "poisson_context"]], on=keys,
                        validate="one_to_one", suffixes=("", "_original"))
    if len(merged) != len(reference):
        raise ValueError("Lookup keys differ from the original evaluations")
    np.testing.assert_array_equal(merged.actual_shops, merged.actual_shops_original)
    np.testing.assert_allclose(merged.poisson_context, merged.poisson_context_original, atol=1e-10)
    data["estimated_shops"] = [row[row.active_method] for _, row in data.iterrows()]
    if not np.isfinite(data.estimated_shops).all() or data.estimated_shops.lt(0).any():
        raise ValueError("Invalid count estimate")
    data["base_month"] = MONTH
    output = data[keys + ["base_month", "actual_shops", "estimated_shops"]].sort_values(keys)
    output.to_csv(DOCS / "industry_comparison_app_83.csv", index=False, encoding="utf-8", lineterminator="\n")
    validation.to_csv(DOCS / "expanded_industry_validation.csv", index=False, encoding="utf-8", lineterminator="\n")
    evidence = {
        month: json.loads((ROOT / f"data/raw/a10/expanded_nearby_{month}.json").read_text(encoding="utf-8"))
        for month in ("2025-06", "2026-09", "2026-06")
    }
    (DOCS / "expanded_validation_summary.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    industries = {}
    for _, row in validation.iterrows():
        group = data.loc[data.industry_code.eq(row.industry_code)].set_index("admin_area")
        cards = group.loc[list(AREAS)]
        industries[row.industry_code] = {
            "name": row.industry_name,
            "uses_nearby": row.active_method != "poisson_context",
            "counts": [[int(card.actual_shops), int(np.floor(card.estimated_shops + 0.5))]
                       for _, card in cards.iterrows()],
        }
    priority = ["I21201", "S20701", "I20101", "P10501"]
    order = priority + sorted(set(industries) - set(priority), key=lambda code: industries[code]["name"])
    options = "\n".join(
        f'      <option value="{code}">{html.escape(industries[code]["name"])}</option>'
        for code in order
    )
    preview = DOCS / "cafe_comparison_preview.html"
    content = preview.read_text(encoding="utf-8")
    content, count = re.subn(r'(<select id="industry">).*?(</select>)',
                           lambda match: match[1] + "\n" + options + "\n    " + match[2],
                           content, flags=re.S)
    if count != 1:
        raise ValueError("Expected one industry selector")
    payload = json.dumps(industries, ensure_ascii=False).replace("<", "\\u003c")
    script = '''  <script id="a10-data" type="application/json">PAYLOAD</script>
  <script>
    const industries = JSON.parse(document.querySelector("#a10-data").textContent);
    const industry = document.querySelector("#industry");
    const cards = document.querySelectorAll(".cards article");
    function updateCards() {
      const selected = industries[industry.value];
      const maximum = Math.max(...selected.counts.flat());
      const scale = Math.max(50, Math.ceil(maximum / 50) * 50);
      cards.forEach((card, index) => {
        const [actual, estimate] = selected.counts[index];
        const [actualValue, estimateValue] = card.querySelectorAll("dd:not(.track)");
        const [actualBar, estimateBar] = card.querySelectorAll(".bar");
        card.querySelector("dt").textContent = `실제 ${selected.name} 점포 수`;
        actualValue.textContent = `${actual}곳`;
        estimateValue.textContent = `약 ${estimate}곳`;
        actualBar.style.width = `${actual / scale * 100}%`;
        estimateBar.style.width = `${estimate / scale * 100}%`;
      });
      document.querySelector("#scale-note").textContent =
        `막대는 세 후보지 모두 0~${scale}곳 기준이에요.`;
      document.querySelector("#nearby-note").textContent = selected.uses_nearby
        ? "이 업종은 가까운 동네의 여건도 반영했어요." : "";
    }
    industry.addEventListener("change", updateCards);
    updateCards();
  </script>'''.replace("PAYLOAD", payload)
    content, count = re.subn(
        r'  <script(?: id="a10-data"[^>]*)?>.*?</script>(?:\s*<script>.*?</script>)?',
        lambda match: script, content, flags=re.S
    )
    if count != 1:
        raise ValueError("Expected one preview script block")
    preview.write_text(content, encoding="utf-8", newline="\n")
    print(f"Exported {len(output)} rows, {len(industries)} selector options, "
          f"{int(validation.confirmed_improvement.sum())} improved methods")


if __name__ == "__main__":
    main()
