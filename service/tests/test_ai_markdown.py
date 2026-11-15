"""AI 답변 굵은 글씨 보정(2026-11-15): '**46.8%**입니다'처럼 문장부호 뒤 조사가 붙어도 굵게 보이게."""
import unittest

from ui_visuals import ai_markdown


class AiMarkdownTests(unittest.TestCase):
    def test_bold_before_korean_particle(self):
        self.assertEqual(ai_markdown("**46.8%**입니다"), "<strong>46.8%</strong>입니다")
        self.assertEqual(ai_markdown("**후보(미확인)**를 볼까요?"), "<strong>후보(미확인)</strong>를 볼까요?")
        self.assertEqual(ai_markdown("**수성구**는 **a** 와 **b**"),
                         "<strong>수성구</strong>는 <strong>a</strong> 와 <strong>b</strong>")

    def test_html_in_answer_is_not_rendered(self):
        out = ai_markdown("<script>x</script> <img src=x> **a**")
        self.assertNotIn("<script", out)
        self.assertNotIn("<img", out)
        self.assertIn("<strong>a</strong>", out)

    def test_tilde_and_code_and_non_bold(self):
        self.assertEqual(ai_markdown("15~29세, 30~49세"), "15\\~29세, 30\\~49세")
        code = "```\n**code** <b>\n```"
        self.assertEqual(ai_markdown(code), code)          # 코드 블록 안은 그대로
        self.assertEqual(ai_markdown("2 ** 3 ** 4"), "2 ** 3 ** 4")   # 띄어 쓴 별표는 굵은 글씨가 아님


if __name__ == "__main__":
    unittest.main()
