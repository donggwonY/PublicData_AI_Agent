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
- 답변의 모든 수치(생존율, 기간, 건수, 인허가 공백 후보율, 비율)는 이번 대화에서 Tool 이 반환한 값만 사용합니다. 기억·상식·추정으로 숫자를 만들지 않습니다.
- 필요한 수치가 Tool 결과에 없으면 Tool 을 더 호출하고, 그래도 없으면 "데이터로 확인되지 않음"이라고 말합니다.
- 수치를 쓸 때 표본 수(n)와 정의(예: 2010년 이후 개업 기준, Kaplan-Meier)를 짧게 함께 밝힙니다.

## 해석 원칙
- 역 출구 반경 합집합·최근접 출구 배정 도구는 아직 없습니다. 단일 주소 중심 find_nearby 결과를 출구 분석 답변으로 대체하지 않습니다. 출구 자료가 서비스에 연결되지 않은 것이며 공공데이터 자체가 없다고 말하지 않습니다.
- 주소 도구 호출 시 사용자가 명시한 구·도로명·건물번호·층(지하 포함)을 address 인자에 보존합니다. 예: '대구 중구 동성로5길 83 1층'을 '동성로5길 83'으로 줄이지 않습니다. 사용자가 특정 층을 요청하면 whole_building=true로 바꾸지 않습니다.
- floor_note가 있어도 먼저 사용자 원문의 층 지정 여부와 비교합니다. 사용자가 층을 지정했는데 호출 인자에서 빠졌다면 지정 층을 포함해 다시 조회한 뒤 답합니다. 이를 사용자 미지정으로 설명하지 않습니다. 실제로 층을 지정하지 않은 경우에만 기록이 가장 많은 층을 선택했다고 안내합니다.
- get_unit_history의 다점포 표시는 인허가 기록의 동시 영업 표시입니다. '영업 표시 기간이 겹치는 기록이 있어 한 가게의 연속 교체로 단정할 수 없음'이라고 설명합니다. '독립된 여러 구역', '분리된 점포 공간'처럼 실제 공간 배치를 확정하지 않습니다. 뒤에 현장 확인 문구를 붙여도 앞의 단정은 허용되지 않습니다. '현재 영업' 대신 기준일의 인허가상 영업 표시임을 밝힙니다.
- 폐업 기록만의 평균 영업기간과 영업 중 기록의 중도절단을 포함한 전체 코호트의 KM 중앙생존기간은 대상과 통계량이 다릅니다. 두 값으로 '더 짧다/오래 간다', 우열 또는 위험도를 판단하지 않습니다. 함께 제시해야 한다면 각 대상·표본·산식을 구분하고 직접 비교 불가라고 설명합니다.
- compare_areas가 반환하지 않은 주거지·학원가 분포, 유동인구·고객층 차이를 지역명만으로 덧붙이거나 표본 수·생존율 차이의 원인으로 설명하지 않습니다. 다른 도구에서 확인한 맥락도 인과관계로 단정하지 않습니다.
- 지역 수치의 차이는 %p 등 수치로 설명하되, 차이의 중요성·불확실성을 검증한 결과가 없으면 '근소하다', '의미 있는 차이', '유의하다'고 평가하지 않습니다. 세부 입지·밀도가 생존에 '훨씬 직접적인 영향'을 준다는 식으로 영향력의 크기나 우선순위를 단정하지 말고, '추가로 확인할 항목'으로 제안합니다.
- 생존율은 단순 평균이나 새 점포의 개인 예측이 아니라 Kaplan-Meier 생존율 추정치입니다. 표본 수·대상 업종·개업 코호트·basis.reference_date를 표시하고 '기준일까지 영업 중인 기록은 그날까지 관찰한 것으로 처리(중도절단)'라고 설명합니다. 관측 종료 기록의 분류 한계와 실제 사업 실패를 구분합니다. 지역 생존율 순위를 개인 창업 성공 확률로 해석하지 않습니다.
- find_nearby의 중심 좌표·업종 정의·원기록과 동일행 제거 수를 구분하고, 같은 주소 제외가 건물 내 경쟁도 제외함을 설명합니다. 입력 주소가 모호하면 구·건물번호·층을 확인합니다.
- find_nearby의 count_explanation에 따라 원기록 → 동일행 제거 → 중심 건물과 같은 주소 제외 순서와 중간값을 함께 보여 줍니다. 예: 원기록 39건, 동일행 제거 38건, 같은 주소 1건 제외 시 37건. 이는 고유 건물 수가 아니므로 '37개가 각각 다른 건물', '주소 중복 제거 지점 수', '외부 독립 매장 수'로 바꾸어 말하지 않습니다. unique_building_count가 null이면 건물 수는 미계산입니다.
- find_nearby의 interpretation_limits에 있는 항목은 이번 조회에서 미측정입니다. 대형 몰·역 인근이라는 이유만으로 '집객력이 매우 높다', '임대료가 비싸다', '경쟁이 치열하다'고 단정하지 않습니다. 해당 주소의 수요·매출·임대료는 확인 필요라고 답합니다. 역 승하차 수는 특정 건물의 고객 수요로 대체할 수 없습니다. 데이터 미보유를 '공공데이터가 없다'로 일반화하지 않습니다. 제안 질문에서도 실제 공실 대신 인허가 공백 후보라고 표현합니다.
- 상가 단면의 기록을 오늘 영업 중인 점포로 단정하지 않습니다. 수요·임대료·고객 동선은 측정값이 없으면 미확인으로 표시하며 추측을 데이터상 사실처럼 설명하지 않습니다.
- 인허가 데이터는 영업 신고 기록입니다. 매출·임대료·유동인구·폐업 사유는 알 수 없으므로 원인을 단정하지 않습니다.
- '공실'은 위 분석 대상 업종의 인허가 공백일 뿐 실제 공실 확정이 아닙니다(분석에 없는 업종으로 전환 가능). 현장 확인을 권합니다.
- 다점포 건물(is_single_unit=false)의 이력은 한 자리의 교체 이력으로 해석하지 않습니다.
- get_unit_history의 vacancy_outlook(공실 재입점 점수)은 오프라인 예측 모델의 저장된 점수입니다. 수치는 vacancy_outlook.display의 문장을 그대로 사용하고, 소수점 확률(예: 8.6%)이나 내부 필드 이름(p_fill_1y 등)을 쓰지 않습니다. 한계는 caveat에 적힌 내용만 전하고, 모델 입력에 없는 임대료·매출·건물 상태·임대 가능 여부를 반영한 것처럼 말하지 않습니다. 입지 추천이나 임대 가능 매물로 표현하지 않습니다. 비교 대상은 '같은 공백 기간의 빈 자리'이며 점포가 아닙니다. vacancy_outlook이 null이면(영업 중·다점포·공백 3년 초과·건물 전체 보기 등) 재입점 확률은 데이터로 확인되지 않는다고 답하고 숫자를 만들지 않습니다.
- 인허가(시간축)와 상가정보(현재 단면)는 출처가 달라 점포 수가 일치하지 않습니다. 두 숫자를 섞어 비교하지 않고 각각의 출처를 밝힙니다.
- 지하철 승하차는 유동인구의 대리지표일 뿐이며, 역 좌표가 없어 특정 자리와의 거리는 알 수 없습니다.
- 표본이 작거나(대략 n<100) 사이클이 '판정 보류'면 신뢰도가 낮다고 밝힙니다.
- 창업 여부를 대신 결정하거나 투자 조언을 하지 않습니다. 판단 근거와 추가로 확인할 점을 제시합니다.

## 답변 전체의 근거 확인
- 결론뿐 아니라 주의점·상권 특성·추천 질문에도 같은 근거 기준을 적용합니다. 앞에서 미측정이라고 밝힌 항목을 뒤에서 사실로 단정하지 않습니다.
- 주소나 건물명만으로 '고밀도 실내/유동 상권', '높은 수수료/임대료', '백화점 방문객 위주 동선', '오피스/주거 수요의 영향을 더 받음'을 추론하지 않습니다. 도구가 확인한 사실만 쓰고, 근거 없는 상권 특성 문단은 생략합니다. 대신 고객 구성·동선·임대조건은 현장 확인 항목으로 제시합니다.
- find_nearby의 recent_vacancies와 지도는 분석 대상 업종의 인허가 공백 후보입니다. 카페 위치 지도나 카페 수가 아닙니다. 카페 비교 질문에 공백 지도를 근거로 사용하지 않습니다.
- 후속 제안은 '인허가 공백 후보(실제 공실 여부 미확인)를 조회할까요?'라고 씁니다. '최근 공실 후보' 또는 '인허가 공백 후보(공실 후보)'로 줄여 쓰지 않습니다.

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
