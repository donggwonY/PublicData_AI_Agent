"""사이드바 남은 질문 수가 질문한 그 화면에서 바로 줄어드는지(2026-11-15). 실제 AI 대신 가짜 에이전트를 쓴다."""
import os
import re
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

import agent


class _FakeAgent:
    def ask(self, prompt):
        yield {"type": "text", "text": "테스트 답변"}
        yield {"type": "done", "model": "fake"}


def _left(app) -> int | None:
    for m in app.sidebar.markdown:
        hit = re.search(r"남은 질문 \*\*(\d+)회\*\*", m.value)
        if hit:
            return int(hit.group(1))
    return None


class SidebarQuotaTests(unittest.TestCase):
    def test_quota_drops_in_same_run(self):
        env = {"APP_DATA_SOURCE": "parquet", "LLM_PROVIDER": "gemini", "GEMINI_API_KEY": "dummy-for-test"}
        with patch.dict(os.environ, env), patch.object(agent, "create_agent", lambda *a, **k: _FakeAgent()):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py")).run(timeout=90)
            self.assertFalse(app.exception)
            self.assertEqual(len(app.chat_input), 0)          # 다른 탭에서는 하단 입력창이 없다
            app.session_state["main_tab"] = "💬 AI 상담"      # AI 상담 탭을 연다
            app.run(timeout=90)
            self.assertEqual(len(app.chat_input), 1)
            start = _left(app)
            self.assertIsNotNone(start)
            app.session_state["main_tab"] = "💬 AI 상담"      # 테스트 도구는 탭 선택을 기억하지 않아 매번 지정
            app.chat_input[0].set_value("수성구 요즘 어때?").run(timeout=90)
            self.assertFalse(app.exception)
            self.assertEqual(_left(app), start - 1)          # 같은 실행에서 바로 반영
            self.assertTrue(any("테스트 답변" in m.value for m in app.markdown))


if __name__ == "__main__":
    unittest.main()
