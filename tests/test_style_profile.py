from __future__ import annotations

from tools.style_profile import profile, sentences_of


def test_single_line_wrap_does_not_change_sentence_metrics() -> None:
    original = "오늘은 갓 구운 빵을 준비했어요."
    wrapped = "오늘은 갓 구운\n빵을 준비했어요."

    assert sentences_of(original) == sentences_of(wrapped)
    assert profile([original])["문장 평균 길이"] == profile([wrapped])["문장 평균 길이"]
    assert profile([original])["말투(문장 끝) 비율(%)"] == profile([wrapped])["말투(문장 끝) 비율(%)"]


def test_blank_line_keeps_unpunctuated_paragraphs_separate() -> None:
    text = "첫 번째 기록\n\n두 번째 기록"

    assert sentences_of(text) == ["첫 번째 기록", "두 번째 기록"]
