"""참고 글쓴이의 문체를 숫자로 관찰합니다 (표준 라이브러리만 사용).

사용법:
    python tools/style_profile.py 참고글.txt [다른파일.txt ...] [--json]

입력: 글과 글 사이를 `---` 한 줄로 구분한 텍스트 파일. 구분선이 없으면 파일 하나를 글 한 편으로 봅니다.
출력: 문장 길이, 짧은 문단 비율, 연결어·정형 틀의 편당 빈도, 시작·끝 문장 유형.
원문 문장은 출력하지 않습니다. 결과는 따라 할 목표가 아니라 관찰값입니다.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

CONNECTIVES = ("그런데", "하지만", "그래서", "그러니", "결국", "오히려", "어쩌면", "사실", "물론", "다만", "여전히", "이상하게", "솔직히", "무엇보다")
PATTERNS = {
    "A가 아니라 B": r"(?:이|가)?\s?아니라\s",
    "'~것 같다' 끝맺음": r"것 같다[.\n]",
    "'모르겠다/모른다' 끝맺음": r"(?:모르겠다|모른다)[.\n]",
    "수사의문 '~아닐까'": r"아닐까",
    "'~인 것이다' 단정": r"것이다[.\n]",
    "세 가지 나란히 (A고, B고, C고)": r"[가-힣]{2,}고,\s[가-힣]{2,}고,\s[가-힣]{2,}고",
    "숫자가 든 문장": r"\d",
}
_SENTENCE = re.compile(r"(?<=[.?!])\s+|\n+")
_TIME = re.compile(r"(오늘|어제|아까|방금|그날|새벽|아침|점심|저녁|밤|요즘)")


def split_posts(text: str) -> list[str]:
    parts = re.split(r"^\s*---\s*$", text.replace("\r\n", "\n"), flags=re.M)
    return [part.strip() for part in parts if part.strip()]


def sentence_type(sentence: str, closing: bool = False) -> str:
    s = sentence.strip()
    if s.endswith("?"):
        return "질문"
    if closing and re.search(r"(모르겠다|모른다|것 같다|아닐까)\.?$", s):
        return "여운·완충"
    if re.match(r"^(나는|나도|내가|난|저는|제가|우리|저희)\s", s):
        return "1인칭"
    if _TIME.search(s[:20]):
        return "장면"
    if re.search(r"\d", s):
        return "숫자"
    if len(s) <= 20:
        return "짧은 선언"
    return "서술"


def profile(posts: list[str]) -> dict[str, object]:
    sentences = [s.strip() for post in posts for s in _SENTENCE.split(post) if len(s.strip()) > 1]
    lengths = [len(s) for s in sentences] or [0]
    paragraphs = [p.strip() for post in posts for p in post.split("\n") if p.strip()]
    joined = "\n".join(posts)
    count = max(len(posts), 1)
    firsts = Counter(sentence_type(_SENTENCE.split(post)[0]) for post in posts)
    lasts = Counter(sentence_type([s for s in _SENTENCE.split(post) if s.strip()][-1], closing=True) for post in posts)
    return {
        "글 수": len(posts),
        "총 글자": len(joined),
        "문장 수": len(sentences),
        "문장 평균 길이": round(statistics.mean(lengths), 1),
        "문장 중앙 길이": statistics.median(lengths),
        "20자 이하 문장 비율(%)": round(100 * sum(x <= 20 for x in lengths) / len(lengths), 1),
        "60자 이상 문장 비율(%)": round(100 * sum(x >= 60 for x in lengths) / len(lengths), 1),
        "40자 미만 짧은 문단 비율(%)": round(100 * sum(len(p) < 40 for p in paragraphs) / max(len(paragraphs), 1), 1),
        "연결어 편당 빈도": {word: round(joined.count(word) / count, 2) for word in CONNECTIVES if joined.count(word)},
        "정형 틀 편당 빈도": {name: round(len(re.findall(p, joined)) / count, 2) for name, p in PATTERNS.items() if re.search(p, joined)},
        "첫 문장 유형": dict(firsts.most_common()),
        "마지막 문장 유형": dict(lasts.most_common()),
    }


def main(argv: list[str] | None = None) -> int:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="참고 글쓴이 문체 관찰 (원문은 출력하지 않음)")
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    posts: list[str] = []
    for path in args.files:
        try:
            posts += split_posts(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError) as error:
            print(f"읽을 수 없는 파일: {path} ({error})", file=sys.stderr)
            return 2
    if not posts:
        print("분석할 글이 없습니다.", file=sys.stderr)
        return 2
    result = profile(posts)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    else:
        for key, value in result.items():
            print(f"{key}: {value}")
        print("\n※ 관찰값입니다. 이 수치에 맞춰 쓰지 말고, 참고 글의 문장도 옮기지 마세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
