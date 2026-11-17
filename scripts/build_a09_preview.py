"""Render an offline preview from the A-09 recommendation results."""

import json
from html import escape
from pathlib import Path

from evaluate_a08_spatial_units import ROOT


HTML = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>대구 유사 상권 찾기</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f5f7f1;color:#243328;
font-family:Inter,"Malgun Gothic",sans-serif;line-height:1.55}
main{width:min(1040px,92vw);margin:42px auto}h1{margin:0;font-size:clamp(1.8rem,4vw,2.6rem);letter-spacing:-.05em}
p{margin:.4rem 0;color:#465b50}label{display:block;font-weight:700;margin:20px 0 6px}
select{width:min(100%,420px);font:inherit;background:white;border:1px solid #758a7d;border-radius:8px;padding:10px}
article{background:white;border:1px solid #dce5da;border-radius:12px;padding:18px;margin:12px 0}
h2,h3{margin:0}h2{font-size:1.2rem}h3{font-size:1rem;margin:10px 0 4px}.columns{display:grid;grid-template-columns:1fr 1fr;gap:14px}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}td,th{padding:4px;border-bottom:1px solid #e3e9df;text-align:right}
th:first-child,td:first-child{text-align:left}footer{margin-top:16px;color:#465b50;font-size:.9rem}
@media(max-width:670px){.columns{grid-template-columns:1fr}main{margin:22px auto}}
</style></head><body><main>
<h1>대구 유사 상권 찾기</h1>
<p id="scope"></p>
<label for="source">기준 상권</label><select id="source"></select>
<label for="mode">추천에서 우선할 기준</label>
<select id="mode">
<option value="basic">업종과 연령 분포를 함께</option>
<option value="size">상가 수와 거주자 수</option>
<optgroup label="업종 대분류">BUSINESS_OPTIONS</optgroup>
<optgroup label="거주자 연령대">POPULATION_OPTIONS</optgroup>
</select>
<p id="count" aria-live="polite"></p>
<section id="results" aria-label="유사 상권 추천" aria-live="polite"></section>
<footer>소진공 상가업소와 행안부 주민등록 거주자 기준. 업종과 연령의 구성 비율로 비교합니다.
점포 수와 거주자 수는 각 상권의 규모를 파악할 수 있도록 함께 표시합니다.</footer>
</main><script>
const data = PAYLOAD;
const get = id => document.getElementById(id);
const format = new Intl.NumberFormat("ko-KR");
const percent = value => (value * 100).toFixed(1) + "%";
const count = row => "상가 " + format.format(row.shops) + "개 · 거주자 " + format.format(row.residents) + "명";
const node = (tag, title, parent) => {
  const element = document.createElement(tag);
  element.textContent = title;
  parent.append(element);
  return element;
};
function ageLabel(key){
  if (key === "age_100_plus") return "100세 이상";
  const [start,end] = key.split("_").slice(1).map(Number);
  return start + "~" + end + "세";
}
const featureLabel = (group,key) => group === "population" ? ageLabel(key) : (key === "음식" ? "음식업" : key);
const majorKeys = (base,other) => Object.keys(base)
  .sort((a,b) => (base[b]+other[b])-(base[a]+other[a])).slice(0,4);
function comparison(parent, title, base, other, label){
  const section = node("section","",parent);
  node("h3",title,section);
  const table = node("table","",section);
  const header = node("tr","",node("thead","",table));
  ["주요 항목", "기준 상권", "추천 상권"].forEach(name => node("th",name,header));
  const tbody = node("tbody","",table);
  majorKeys(base,other).forEach(key => {
    const row = node("tr","",tbody);
    [label(key),percent(base[key]),percent(other[key])].forEach(value => node("td",value,row));
  });
}
function explain(article, source, other, mode){
  const features = ["business","population"].flatMap(group => {
    return majorKeys(source[group],other[group]).map(key => ({
      name: group === "business" ? key : ageLabel(key),
      base: source[group][key], other: other[group][key]
    }));
  });
  const gap = row => Math.abs(row.base - row.other);
  features.sort((a,b) => gap(a)-gap(b));
  const summary = item => item.name + " " + percent(item.base) + " / " + percent(item.other)
    + " (차이 " + (gap(item)*100).toFixed(1) + "%p)";
  const option = data.options[mode];
  if (option) {
    const {group,key} = option;
    const item = {name:featureLabel(group,key),base:source[group][key],other:other[group][key]};
    node("p","우선 비교 · " + summary(item),article);
  }
  if (mode === "size") node("p","우선 비교 · 상가 수 " + format.format(source.shops) + " / "
    + format.format(other.shops) + "개 · 거주자 수 " + format.format(source.residents) + " / "
    + format.format(other.residents) + "명",article);
  node("p","비슷한 점 · " + summary(features[0]),article);
  node("p","차이가 큰 점 · " + summary(features[features.length - 1]),article);
}
const select = get("source");
const modeSelect = get("mode");
const codes = Object.keys(data.recommendations).sort((a,b) =>
  data.profiles[a].name.localeCompare(data.profiles[b].name,"ko"));
codes.forEach(code => select.add(new Option(data.profiles[code].name,code)));
const example = codes.find(code => data.profiles[code].name === "중구 성내1동");
if(example) select.value = example;
get("scope").textContent = data.month + " 기준 · 상가 " + data.minimum + "개 이상인 "
  + codes.length + "개 읍·면·동";
function render(){
  const source = data.profiles[select.value];
  const mode = modeSelect.value;
  get("count").textContent = count(source);
  const container = get("results");
  container.replaceChildren();
  const recommendations = mode === "basic" ? data.recommendations : data.scenarios[mode];
  recommendations[select.value].forEach(code => {
    const other = data.profiles[code];
    const article = node("article","",container);
    node("h2",other.name,article);
    node("p",count(other),article);
    explain(article,source,other,mode);
    const columns = node("div","",article);
    columns.className = "columns";
    comparison(columns,"업종 구성",source.business,other.business,key=>key);
    comparison(columns,"거주 연령 분포",source.population,other.population,ageLabel);
  });
}
select.addEventListener("change",render);
modeSelect.addEventListener("change",render);
render();
</script></body></html>"""


def option_markup(options, group):
    elements = []
    for mode, option in options.items():
        if option["group"] != group:
            continue
        key = option["key"]
        if group == "population":
            if key == "age_100_plus":
                name = "100세 이상"
            else:
                start, end = map(int, key.split("_")[1:])
                name = f"{start}~{end}세"
            label = f"{name} 거주자 비중"
        else:
            label = f"{'음식업' if key == '음식' else key} 비중"
        elements.append(f'<option value="{escape(mode, quote=True)}">{escape(label)}</option>')
    return "\n".join(elements)


if __name__ == "__main__":
    result = json.loads((ROOT / "a09/similar_areas.json").read_text(encoding="utf-8"))
    payload = {
        "month": result["months"][-1], "minimum": result["minimum_shops"],
        "profiles": result["profiles"], "recommendations": result["recommendations"],
        "scenarios": result["scenarios"]["recommendations"],
        "options": result["scenarios"]["options"],
    }
    path = Path(__file__).resolve().parents[1] / "output/a09_similar_areas_preview.html"
    path.parent.mkdir(exist_ok=True)
    page = HTML.replace("BUSINESS_OPTIONS", option_markup(payload["options"], "business"))
    page = page.replace("POPULATION_OPTIONS", option_markup(payload["options"], "population"))
    page = page.replace("PAYLOAD", json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c"))
    path.write_text(page, encoding="utf-8")
    versioned = path.with_name("a09_similar_areas_preview_v2.html")
    versioned.write_text(page, encoding="utf-8")
    print(versioned)
