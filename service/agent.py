"""상권 생애주기 추론 에이전트 — Claude API 도구 호출 루프.

CLI 실행:  python agent.py [gemini|claude]

'에이전트'의 실체는 반복문 하나다.
    1. AI 에게 [대화 이력 + Tool 8종 설명]을 보낸다
    2. AI 가 "이 Tool 을 이 인자로 불러 달라"고 답하면(tool_use) 우리가 함수를 실행한다
    3. 실행 결과를 대화에 붙여 다시 보낸다
    4. AI 가 Tool 을 더 부르지 않고 글로 답하면 끝 (최대 MAX_TOOL_ROUNDS 회)
AI 는 데이터에 직접 접근하지 않는다. 숫자는 전부 우리가 실행한 Tool 이 돌려준 값이다.

이 파일은 provider 공통 부분(시스템 프롬프트, Tool 실행기, 팩토리)과 Claude 구현을 담는다.
Gemini 구현은 agent_gemini.py 에 있고, 두 클래스는 같은 이벤트를 내보내 화면 코드가 구분할 필요가 없다.

ask() 가 내보내는 이벤트
    {"type": "text",        "text": ...}                      답변 글자
    {"type": "tool_call",   "name", "input", "id"}            Tool 을 부르기 직전
    {"type": "tool_result", "name", "input", "output", "error"} 실행 결과
    {"type": "done",        "model"}                          정상 종료
    {"type": "error",       "message"}                        사용자에게 보여줄 오류
"""
from __future__ import annotations

import inspect
import json
import os
import sys
from typing import Iterator

import anthropic

import config as C
from core.tool_specs import TOOL_SPECS
from core.tools import TOOL_FUNCTIONS, ToolError, store

MAX_TOOL_ROUNDS = 12  # Tool 호출이 이보다 많아지면 무한 루프로 보고 중단한다(요금·시간 보호)
FALLBACK_BETA = "server-side-fallback-2026-07-01"  # 안전 정책으로 거절될 때 다른 모델로 넘기는 기능


def build_system_prompt() -> str:
    """AI 에게 항상 먼저 주는 지시문. 이 프로젝트의 '환각 방지' 규칙이 여기 담긴다.

    데이터 규모와 기준일을 실제 값으로 채워 넣어, AI 가 데이터의 범위를 알고 답하게 한다.
    """
    s = store()
    meta = s.meta
    rec = meta["records"]["통합"]
    services = ", ".join(k for k in meta["records"] if k != "통합")
    extra = ""
    if s.area_context is not None:
        extra = (f"\n보조 데이터: 소상공인 상가(상권)정보 {len(s.poi):,}개 점포(전 업종, 2026-06 현재 단면) · "
                 f"행정동 {len(s.area_context)}곳의 주민등록 인구 · 도시철도 {0 if s.station is None else len(s.station)}개 역 승하차 · "
                 f"주차장·전통시장. 시간 추세는 인허가, 현재 단면·주변 경쟁·인구는 보조 데이터로 답합니다.")
    return f"""당신은 '대구 상권 생애주기 추론 에이전트'입니다. 대구에서 창업을 준비하는 사람에게 그 자리와 동네의 과거를 공공데이터로 확인시켜 줍니다.

데이터: 행정안전부 지방행정 인허가 — 대구광역시 {services} {rec['total']:,}건(폐업 {rec['closed']:,} / 영업 중 {rec['active']:,}), 기준일 {meta['reference_date']}.{extra}

## 숫자 원칙
- 답변의 모든 수치(생존율, 기간, 건수, 공실률, 비율)는 이번 대화에서 Tool 이 반환한 값만 사용합니다. 기억·상식·추정으로 숫자를 만들지 않습니다.
- 필요한 수치가 Tool 결과에 없으면 Tool 을 더 호출하고, 그래도 없으면 "데이터로 확인되지 않음"이라고 말합니다.
- 수치를 쓸 때 표본 수(n)와 정의(예: 2010년 이후 개업 기준, Kaplan-Meier)를 짧게 함께 밝힙니다.

## 해석 원칙
- 인허가 데이터는 영업 신고 기록입니다. 매출·임대료·유동인구·폐업 사유는 알 수 없으므로 원인을 단정하지 않습니다.
- '공실'은 위 분석 대상 업종의 인허가 공백일 뿐 실제 공실 확정이 아닙니다(분석에 없는 업종으로 전환 가능). 현장 확인을 권합니다.
- 다점포 건물(is_single_unit=false)의 이력은 한 자리의 교체 이력으로 해석하지 않습니다.
- 인허가(시간축)와 상가정보(현재 단면)는 출처가 달라 점포 수가 일치하지 않습니다. 두 숫자를 섞어 비교하지 않고 각각의 출처를 밝힙니다.
- 지하철 승하차는 유동인구의 대리지표일 뿐이며, 역 좌표가 없어 특정 자리와의 거리는 알 수 없습니다.
- 표본이 작거나(대략 n<100) 사이클이 '판정 보류'면 신뢰도가 낮다고 밝힙니다.
- 창업 여부를 대신 결정하거나 투자 조언을 하지 않습니다. 판단 근거와 추가로 확인할 점을 제시합니다.

## 대화 방식
- 한국어로 결론 → 근거 수치 → 주의점 순으로 간결하게 답하고, 이어서 확인해 볼 만한 질문을 1~2개 제안합니다.
- 후속 질문은 앞선 맥락(업태·지역·주소)을 이어받아 필요한 Tool 을 새로 호출합니다. 판단에 여러 관점이 필요하면 Tool 을 여러 개 호출해 교차 확인합니다.
- 여러 지역·업태를 비교할 때는 마크다운 표를 씁니다.
- 주소가 모호하면 normalize_address 로 후보를 확인하고, 후보가 여럿이면 사용자에게 고르게 합니다."""


def run_tool(name: str, args: dict) -> tuple[dict | None, str, bool]:
    """AI 가 요청한 Tool 을 실제로 실행한다. 반환: (원본 결과, tool_result 문자열, is_error).

    원본 dict 는 화면에서 차트를 그리는 데 쓰고, 문자열은 AI 에게 보낸다.
    어떤 오류가 나든 예외를 밖으로 던지지 않는다 — 오류도 AI 에게 알려 주면
    AI 가 인자를 고쳐 다시 부르거나 사용자에게 되물을 수 있기 때문이다.
    """
    fn = TOOL_FUNCTIONS.get(name)
    if fn is None:
        return None, f"알 수 없는 Tool: {name}", True
    # AI 가 함수에 없는 인자나 null 을 보내는 일이 있다. 시그니처에 있는 이름만 남기고 None 은 버려
    # 함수의 기본값이 쓰이게 한다(그대로 넘기면 TypeError 로 죽는다).
    params = inspect.signature(fn).parameters
    kwargs = {k: v for k, v in (args or {}).items() if k in params and v is not None}
    try:
        out = fn(**kwargs)
        return out, json.dumps(out, ensure_ascii=False), False
    except ToolError as e:
        return None, str(e), True
    except Exception as e:  # Tool 내부 버그도 대화를 끊지 않고 모델에 알린다
        return None, f"Tool 실행 중 오류: {type(e).__name__}: {e}", True


class ClaudeAgent:
    """Claude API 로 도구 호출 루프를 도는 에이전트. 대화 이력은 인스턴스가 들고 있다."""

    provider = "claude"

    def __init__(self, api_key: str | None = None, client: anthropic.Anthropic | None = None,
                 model: str = C.CLAUDE_MODEL):
        # client 를 밖에서 받을 수 있게 열어 둔 것이 '의존성 주입'이다.
        # 테스트에서 가짜 클라이언트를 넣어 API 키 없이 루프를 검증할 수 있다(tests/agent_loop_test.py).
        # api_key 를 명시적으로 넘긴다 — 공개 서버에서 os.environ 에 넣으면 모든 방문자가 공유하게 됨
        self.client = client or (anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic())
        self.model = model
        self.system = build_system_prompt()
        self.messages: list[dict] = []

    def reset(self) -> None:
        self.messages = []

    def ask(self, user_text: str) -> Iterator[dict]:
        """이벤트 스트림: text / tool_call / tool_result / done / error."""
        checkpoint = len(self.messages)
        self.messages.append({"role": "user", "content": user_text})
        try:
            yield from self._loop()
        except anthropic.AuthenticationError:
            yield self._fail(checkpoint, "Claude API 인증 실패 — API 키를 확인하세요.")
        except anthropic.RateLimitError:
            yield self._fail(checkpoint, "Claude API 요청 한도 초과 — 잠시 후 다시 시도하세요.")
        except anthropic.APIConnectionError:
            yield self._fail(checkpoint, "Claude API 네트워크 연결 실패.")
        except anthropic.APIStatusError as e:
            yield self._fail(checkpoint, f"Claude API 오류 {e.status_code}: {e.message}")

    def _fail(self, checkpoint: int, message: str) -> dict:
        # 반쯤 진행된 턴은 버려 다음 질문이 깨진 이력으로 시작하지 않게.
        # (Tool 요청만 있고 결과가 없는 이력은 API 가 거부해서, 안 지우면 이후 모든 질문이 실패한다)
        del self.messages[checkpoint:]
        return {"type": "error", "message": message}

    def _loop(self) -> Iterator[dict]:
        """Tool 요청이 없을 때까지 AI 에게 되묻는 본체."""
        for _ in range(MAX_TOOL_ROUNDS):
            # stream = 글자가 생성되는 대로 받기. 사용자가 완성까지 기다리지 않아도 된다.
            with self.client.beta.messages.stream(
                model=self.model,
                max_tokens=16000,
                system=self.system,          # 숫자·해석 원칙 (build_system_prompt)
                tools=TOOL_SPECS,            # AI 가 고를 수 있는 Tool 8종의 설명
                messages=self.messages,      # 지금까지의 대화 전체 (API 는 이력을 기억하지 않는다)
                thinking={"type": "adaptive"},       # 필요할 때 더 오래 생각하게
                cache_control={"type": "ephemeral"},  # 앞부분(시스템·Tool 설명) 캐시 → 비용·지연 절감
                betas=[FALLBACK_BETA],
                fallbacks="default",
            ) as stream:
                for event in stream:
                    if event.type == "content_block_delta" and event.delta.type == "text_delta":
                        yield {"type": "text", "text": event.delta.text}
                response = stream.get_final_message()

            # 사고·도구 호출 블록까지 원형 그대로 이어 붙인다
            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "refusal":
                yield {"type": "error", "message": "요청이 안전 정책에 의해 거절되었습니다."}
                return
            if response.stop_reason == "max_tokens":
                yield {"type": "error", "message": "응답이 최대 길이에서 잘렸습니다. 질문을 나눠 주세요."}
                return

            # Tool 요청이 없으면 = AI 가 답을 다 썼다는 뜻 → 루프 종료
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                yield {"type": "done", "model": self.model}
                return

            results = []
            for tu in tool_uses:
                yield {"type": "tool_call", "id": tu.id, "name": tu.name, "input": tu.input}
                out, content, is_error = run_tool(tu.name, tu.input)
                block = {"type": "tool_result", "tool_use_id": tu.id, "content": content}
                if is_error:
                    block["is_error"] = True
                results.append(block)
                yield {"type": "tool_result", "id": tu.id, "name": tu.name, "input": tu.input,
                       "output": out, "error": content if is_error else None}
            # 병렬 호출 결과는 하나의 user 메시지로 함께 반환.
            # 나눠 보내면 형식이 어긋나고, AI 가 다음부터 병렬 호출을 덜 하게 된다.
            self.messages.append({"role": "user", "content": results})
            yield {"type": "text", "text": "\n\n"}

        yield {"type": "error", "message": f"Tool 호출이 {MAX_TOOL_ROUNDS}회를 넘어 중단했습니다."}


LifecycleAgent = ClaudeAgent  # 이전 이름 호환

API_KEY_ENV = {"gemini": "GEMINI_API_KEY", "claude": "ANTHROPIC_API_KEY"}


def create_agent(provider: str = C.LLM_PROVIDER, api_key: str | None = None):
    """설정값에 맞는 에이전트를 만들어 주는 팩토리 함수.

    화면 코드(app.py)는 이 함수만 부르면 되고, 어느 회사 AI 를 쓰는지 몰라도 된다.
    Gemini 는 여기서만 import 한다 — Claude 만 쓰는 환경에서 google-genai 가 없어도 동작하도록.
    """
    provider = (provider or C.LLM_PROVIDER).lower()
    if provider == "gemini":
        from agent_gemini import GeminiAgent
        return GeminiAgent(api_key=api_key)
    if provider == "claude":
        return ClaudeAgent(api_key=api_key)
    raise ValueError(f"지원하지 않는 LLM_PROVIDER: {provider} (gemini | claude)")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    provider = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("LLM_PROVIDER", C.LLM_PROVIDER)).lower()
    agent = create_agent(provider, os.environ.get(API_KEY_ENV.get(provider, "")))
    print(f"대구 상권 생애주기 에이전트 [{provider}] (종료: exit, 초기화: reset)\n")
    while True:
        try:
            q = input("\n질문> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if q in ("exit", "quit"):
            break
        if q == "reset":
            agent.reset()
            continue
        if not q:
            continue
        for ev in agent.ask(q):
            if ev["type"] == "text":
                print(ev["text"], end="", flush=True)
            elif ev["type"] == "tool_call":
                print(f"\n  🔧 {ev['name']}({json.dumps(ev['input'], ensure_ascii=False)})", flush=True)
            elif ev["type"] == "tool_result" and ev["error"]:
                print(f"  ⚠️ {ev['error']}", flush=True)
            elif ev["type"] == "error":
                print(f"\n[오류] {ev['message']}")
        print()


if __name__ == "__main__":
    main()
