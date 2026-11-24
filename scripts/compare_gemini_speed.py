"""AI 상담 응답 속도·답변 비교: 지금 설정 vs 생각 수준을 낮춘 설정 (2026-11-24).

공개 앱 AI 상담이 질문 하나에 3~4분 걸려(2026-11-24 확인, 기존 도구도 같음), 모델의 생각 수준을 낮추면
빨라지는지와 답변 품질이 유지되는지 같은 질문으로 비교한다. 앱 코드는 바꾸지 않고 GeminiAgent 설정만 바꿔 돌린다.

    # 키는 환경변수 GEMINI_API_KEY 또는 저장소 루트 .env (값은 출력하지 않음). 운영 키가 아닌 개발용 키를 쓴다.
    service/.venv/Scripts/python scripts/compare_gemini_speed.py [--variants current low minimal] [--out 경로]

결과: 질문 × 설정별 전체 시간, 모델 호출별 시간, 부른 도구, 답변 전문 → JSON + 사람이 읽는 Markdown.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "service"
sys.path.insert(0, str(SERVICE))
os.chdir(SERVICE)

QUESTIONS = [
    "교촌치킨 대구 매장 줄고 있어?",
    "이디야 전망은?",
    "GS",
    "가장 안 망할 치킨 브랜드 추천해줘",
    "대구 커피숍 생존율 알려줘",
    "수성구 범어동에서 치킨집 하면 어때?",
]
VARIANTS = {"current": None, "low": "LOW", "minimal": "MINIMAL"}   # None = 지금 앱 설정(생각 수준 미지정)
TIMEOUT_S = 120


def api_key() -> str:
    if os.environ.get("GEMINI_API_KEY"):
        return os.environ["GEMINI_API_KEY"]
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8-sig").splitlines():
            k, _, v = line.partition("=")
            if k.strip() == "GEMINI_API_KEY" and v.strip():
                return v.strip().strip("\"'")
    raise SystemExit("GEMINI_API_KEY 가 없습니다(환경변수 또는 저장소 루트 .env). 개발용 키를 넣은 뒤 다시 실행하세요.")


def make_agent(key: str, level: str | None):
    from google import genai
    from google.genai import types
    import agent_gemini as G

    client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=TIMEOUT_S * 1000))
    a = G.GeminiAgent(client=client, models=[G.C.GEMINI_MODELS[0]])   # 모델을 고정해 설정 차이만 본다
    if level:
        a.config.thinking_config = types.ThinkingConfig(thinking_level=getattr(types.ThinkingLevel, level))
    calls = []
    orig = a._generate

    def timed():
        t = time.perf_counter()
        try:
            return orig()
        finally:
            calls.append(round(time.perf_counter() - t, 1))
    a._generate = timed
    return a, calls


def run_one(key: str, level: str | None, q: str) -> dict:
    a, calls = make_agent(key, level)
    t0 = time.perf_counter()
    text, tools, err = [], [], None
    try:
        for ev in a.ask(q):
            if ev["type"] == "text":
                text.append(ev["text"])
            elif ev["type"] == "tool_call":
                tools.append(f"{ev['name']}({json.dumps(ev['input'], ensure_ascii=False)})")
            elif ev["type"] == "error":
                err = ev["message"]
    except Exception as e:  # noqa: BLE001 — 시간 초과 등도 결과로 남긴다
        err = f"{type(e).__name__}: {e}"
    return {"seconds": round(time.perf_counter() - t0, 1), "model_calls": calls, "tools": tools,
            "answer": "".join(text).strip(), "error": err, "model": a.model_used}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", nargs="+", default=list(VARIANTS), choices=list(VARIANTS))
    ap.add_argument("--out", default=str(ROOT / "docs/e04/results/gemini_speed_20261124"))
    a = ap.parse_args(argv)
    key = api_key()
    out = {"run_at": datetime.now().isoformat(timespec="seconds"), "timeout_s": TIMEOUT_S, "results": []}
    for q in QUESTIONS:
        for v in a.variants:
            r = run_one(key, VARIANTS[v], q)
            r.update(question=q, variant=v)
            out["results"].append(r)
            print(f"[{v:8}] {r['seconds']:6.1f}s 호출 {r['model_calls']} 도구 {len(r['tools'])} {'오류 ' + r['error'] if r['error'] else ''} · {q}", flush=True)
            time.sleep(5)   # 무료 등급 분당 한도 여유
    p = Path(a.out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.with_suffix(".json").write_bytes(json.dumps(out, ensure_ascii=False, indent=1).encode("utf-8"))
    md = [f"# AI 상담 속도·답변 비교 ({out['run_at']})", "", "| 질문 | 설정 | 시간(초) | 모델 호출(초) | 도구 |", "| --- | --- | ---: | --- | --- |"]
    for r in out["results"]:
        md.append(f"| {r['question']} | {r['variant']} | {r['seconds']} | {r['model_calls']} | {'; '.join(r['tools']) or '-'} |")
    for r in out["results"]:
        md += ["", f"## {r['question']} · {r['variant']} ({r['seconds']}초)", "", r["answer"] or f"(답변 없음: {r['error']})"]
    p.with_suffix(".md").write_bytes(("\n".join(md) + "\n").encode("utf-8"))
    print("저장:", p.with_suffix(".md"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
