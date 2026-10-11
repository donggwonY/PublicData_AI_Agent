"""API 키 없이 Gemini 에이전트 루프 검증 (실제 google-genai 타입 + 가짜 클라이언트).  실행: python -m tests.gemini_loop_test"""
import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from google.genai import errors, types  # noqa: E402

from agent_gemini import GeminiAgent  # noqa: E402


def reply(*parts):
    return NS(candidates=[NS(content=types.Content(role="model", parts=list(parts)), finish_reason="STOP")],
              prompt_feedback=None)


class FakeModels:
    def __init__(self, script):
        self.script, self.calls = script, []

    def generate_content(self, model, contents, config):
        self.calls.append({"model": model, "n_contents": len(contents), "config": config})
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def test_tool_loop_and_model_fallback():
    script = [
        errors.ClientError(429, {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}}),
        reply(types.Part(function_call=types.FunctionCall(id="c1", name="get_survival_curve", args={"category": "카페", "gu": "수성구"})),
              types.Part(function_call=types.FunctionCall(id="c2", name="get_market_cycle", args={"gu": "없는구"}))),
        reply(types.Part(text="수성구 카페 중앙생존기간은 ...")),
    ]
    fake = FakeModels(script)
    agent = GeminiAgent(client=NS(models=fake), models=["model-a", "model-b"])
    events = list(agent.ask("수성구 카페 어때?"))
    kinds = [e["type"] for e in events]
    print(kinds)
    assert [c["model"] for c in fake.calls] == ["model-a", "model-b", "model-b"], "429 → 다음 모델, 이후 그 모델 유지"
    assert kinds.count("tool_call") == 2 and kinds[-1] == "done" and events[-1]["model"] == "model-b"
    results = [e for e in events if e["type"] == "tool_result"]
    assert results[0]["output"]["n"] > 0 and results[1]["error"]
    # user, model(함수호출), user(함수응답 2개 한 메시지), model(최종)
    assert [c.role for c in agent.contents] == ["user", "model", "user", "model"]
    fr = agent.contents[2].parts
    assert len(fr) == 2 and fr[0].function_response.id == "c1" and "result" in fr[0].function_response.response
    assert "error" in fr[1].function_response.response
    cfg = fake.calls[0]["config"]
    from core.tool_specs import TOOL_SPECS
    assert len(cfg.tools[0].function_declarations) == len(TOOL_SPECS) and cfg.automatic_function_calling.disable
    assert "Tool 이 반환한 값만" in cfg.system_instruction


def test_server_error_retries_then_switches_model():
    """503(과부하)은 같은 모델로 재시도하고, 그래도 안 되면 다음 모델로 넘어간다."""
    overloaded = errors.ServerError(503, {"error": {"code": 503, "message": "The model is overloaded.",
                                                    "status": "UNAVAILABLE"}})
    fake = FakeModels([overloaded, overloaded, overloaded,   # model-a: 최초 + 재시도 2회 모두 실패
                       reply(types.Part(text="수성구 카페 중앙생존은 ..."))])  # model-b 에서 성공
    agent = GeminiAgent(client=NS(models=fake), models=["model-a", "model-b"], server_retry_delays=(0, 0))
    events = list(agent.ask("수성구 카페 어때?"))
    assert [c["model"] for c in fake.calls] == ["model-a", "model-a", "model-a", "model-b"]
    assert events[-1]["type"] == "done" and events[-1]["model"] == "model-b"


def test_server_error_all_models_fail():
    """모든 모델이 503이면 사용자에게 안내하고 이력을 되돌린다."""
    overloaded = errors.ServerError(503, {"error": {"code": 503, "message": "overloaded", "status": "UNAVAILABLE"}})
    fake = FakeModels([overloaded] * 6)
    agent = GeminiAgent(client=NS(models=fake), models=["model-a", "model-b"], server_retry_delays=(0, 0))
    events = list(agent.ask("질문"))
    assert events[-1]["type"] == "error" and "혼잡" in events[-1]["message"], events
    assert agent.contents == []


def test_error_rolls_back_history():
    fake = FakeModels([errors.ClientError(400, {"error": {"code": 400, "message": "API key not valid", "status": "INVALID_ARGUMENT"}})])
    agent = GeminiAgent(client=NS(models=fake), models=["model-a"])
    events = list(agent.ask("아무 질문"))
    assert events[-1]["type"] == "error" and "키" in events[-1]["message"], events
    assert agent.contents == [], "실패한 턴은 이력에서 제거"


if __name__ == "__main__":
    test_tool_loop_and_model_fallback()
    test_server_error_retries_then_switches_model()
    test_server_error_all_models_fail()
    test_error_rolls_back_history()
    print("gemini loop OK")
