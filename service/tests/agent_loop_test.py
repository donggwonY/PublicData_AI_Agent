"""API 키 없이 에이전트 도구 호출 루프를 가짜 클라이언트로 검증.  실행: python -m tests.agent_loop_test"""
import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import LifecycleAgent  # noqa: E402


class FakeStream:
    def __init__(self, message):
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        for b in self.message.content:
            if b.type == "text":
                yield NS(type="content_block_delta", delta=NS(type="text_delta", text=b.text))

    def get_final_message(self):
        return self.message


class FakeClient:
    """1턴: Tool 2개 병렬 호출(하나는 오류) → 2턴: 최종 답변."""

    def __init__(self):
        self.calls = []
        self.beta = NS(messages=NS(stream=self._stream))

    def _stream(self, **kwargs):
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})  # 호출 시점 스냅샷
        if len(self.calls) == 1:
            content = [
                NS(type="text", text="확인해 볼게요."),
                NS(type="tool_use", id="t1", name="get_survival_curve", input={"category": "카페", "gu": "수성구"}),
                NS(type="tool_use", id="t2", name="get_market_cycle", input={"gu": "없는구"}),
            ]
            return FakeStream(NS(content=content, stop_reason="tool_use", usage=None))
        return FakeStream(NS(content=[NS(type="text", text="수성구 카페 중앙생존은 ...")], stop_reason="end_turn", usage=None))


def main():
    client = FakeClient()
    agent = LifecycleAgent(client=client)
    events = list(agent.ask("수성구 카페 어때?"))
    kinds = [e["type"] for e in events]
    print(kinds)

    assert kinds.count("tool_call") == 2 and kinds[-1] == "done"
    results = [e for e in events if e["type"] == "tool_result"]
    assert results[0]["output"]["n"] > 0 and results[0]["error"] is None
    assert results[1]["error"] and "구·군" in results[1]["error"]

    second = client.calls[1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant", "user"]
    tr = second[2]["content"]
    assert len(tr) == 2 and tr[1]["is_error"] is True, "병렬 결과는 한 user 메시지에, 오류는 is_error"
    assert client.calls[0]["fallbacks"] == "default" and client.calls[0]["thinking"] == {"type": "adaptive"}
    assert "Tool 이 반환한 값만" in client.calls[0]["system"]
    print("agent loop OK — system prompt", len(client.calls[0]["system"]), "chars,", len(client.calls[0]["tools"]), "tools")


if __name__ == "__main__":
    main()
