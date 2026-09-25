"""참고 글쓴이의 문체를 숫자로 관찰하고, 내 초안과 비교합니다 (표준 라이브러리만 사용).

사용법:
    python tools/style_profile.py 참고글.txt                       # 참고 글 문체 분석
    python tools/style_profile.py 참고글.txt --compare 내초안.txt  # 초안과 비교 + 베낀 구간 검사
    python tools/style_profile.py 참고글.txt --json                # 결과를 JSON으로

입력: 글과 글 사이를 `---` 한 줄로 구분한 텍스트 파일. 구분선이 없으면 파일 하나를 글 한 편으로 봅니다.
분석 결과에는 참고 글의 문장을 출력하지 않습니다. 비교할 때만 내 초안에서 참고 글과 겹치는 구간을 보여 줍니다.
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
}
_SENTENCE = re.compile(r"(?<=[.?!])\s+|\n+")
_TIME = re.compile(r"(오늘|어제|아까|방금|그날|새벽|아침|점심|저녁|밤|요즘)")
_EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")
DEFAULT_COPY_CHARS = 12


def split_posts(text: str) -> list[str]:
    parts = re.split(r"^\s*---\s*$", text.replace("\r\n", "\n"), flags=re.M)
    return [part.strip() for part in parts if part.strip()]


def sentences_of(post: str) -> list[str]:
    return [s.strip() for s in _SENTENCE.split(post) if len(s.strip()) > 1]


def ending(sentence: str) -> str:
    """문장 끝 말투: 합쇼체 / 해요체 / 평서(-다) / 반말 / 명사·음슴 / 질문 / 기타."""
    s = re.sub(r"[\s\"'”’)\]]+$", "", sentence)
    s = re.sub(r"[.!~…ㅋㅎ^;:)]+$", "", s)
    if sentence.rstrip().endswith("?"):
        return "질문"
    if re.search(r"(니다|니까|습니다|십시오)$", s):
        return "합쇼체(-니다)"
    if re.search(r"요$", s):
        return "해요체(-요)"
    if re.search(r"다$", s):
        return "평서(-다)"
    if re.search(r"(어|아|야|지|게|네|래|걸|거든|잖아|자)$", s):
        return "반말(-어/-지)"
    if re.search(r"(음|함|임|됨|중|것)$", s) or re.search(r"[가-힣]$", s):
        return "명사·음슴"
    return "기타"


def opening_type(sentence: str, closing: bool = False) -> str:
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


def _pct(part: int, whole: int) -> float:
    return round(100 * part / whole, 1) if whole else 0.0


def profile(posts: list[str]) -> dict[str, object]:
    per_post = [sentences_of(post) for post in posts]
    sentences = [s for group in per_post for s in group]
    lengths = [len(s) for s in sentences] or [0]
    paragraphs = [p for post in posts for p in re.split(r"\n\s*\n", post) if p.strip()]
    lines = [line.strip() for post in posts for line in post.split("\n") if line.strip()]
    joined = "\n".join(posts)
    count = max(len(posts), 1)
    endings = Counter(ending(s) for s in sentences)
    total = max(len(sentences), 1)
    mean = statistics.mean(lengths)
    return {
        "글 수": len(posts),
        "편당 글자(평균)": round(len(joined) / count),
        "문장 평균 길이": round(mean, 1),
        "문장 중앙 길이": statistics.median(lengths),
        "문장 길이 들쭉날쭉함(변동계수)": round(statistics.pstdev(lengths) / mean, 2) if mean else 0.0,
        "20자 이하 문장 비율(%)": _pct(sum(x <= 20 for x in lengths), len(lengths)),
        "60자 이상 문장 비율(%)": _pct(sum(x >= 60 for x in lengths), len(lengths)),
        "문단당 문장 수": round(len(sentences) / max(len(paragraphs), 1), 1),
        "줄당 글자(평균)": round(statistics.mean(len(line) for line in lines), 1) if lines else 0.0,
        "한 줄에 한 문장 비율(%)": _pct(sum(len(sentences_of(line)) == 1 for line in lines), len(lines)),
        "말투(문장 끝) 비율(%)": {key: _pct(value, total) for key, value in endings.most_common()},
        "질문 문장 비율(%)": _pct(endings.get("질문", 0), total),
        "느낌표 편당": round(joined.count("!") / count, 2),
        "이모지 편당": round(len(_EMOJI.findall(joined)) / count, 2),
        "ㅋㅋ·ㅎㅎ 편당": round(len(re.findall(r"[ㅋㅎ]{2,}", joined)) / count, 2),
        "연결어 편당 빈도": {word: round(joined.count(word) / count, 2) for word in CONNECTIVES if joined.count(word)},
        "정형 틀 편당 빈도": {name: round(len(re.findall(p, joined)) / count, 2) for name, p in PATTERNS.items() if re.search(p, joined)},
        "첫 문장 유형(%)": {k: _pct(v, count) for k, v in Counter(opening_type(g[0]) for g in per_post if g).most_common()},
        "마지막 문장 유형(%)": {k: _pct(v, count) for k, v in Counter(opening_type(g[-1], closing=True) for g in per_post if g).most_common()},
    }


def _squash(text: str) -> tuple[str, list[int]]:
    """공백을 뺀 문자열과, 각 글자가 원문 어디에 있었는지."""
    chars, where = [], []
    for index, char in enumerate(text):
        if not char.isspace():
            chars.append(char)
            where.append(index)
    return "".join(chars), where


def copied_spans(reference: str, draft: str, min_chars: int = DEFAULT_COPY_CHARS) -> list[str]:
    """초안에서 참고 글과 공백 무시 min_chars자 이상 똑같이 겹치는 구간(초안 쪽 원문)."""
    ref, _ = _squash(reference)
    dra, where = _squash(draft)
    grams = {ref[i:i + min_chars] for i in range(len(ref) - min_chars + 1)}
    spans: list[str] = []
    i = 0
    while i <= len(dra) - min_chars:
        if dra[i:i + min_chars] in grams:
            end = i + min_chars
            while end < len(dra) and dra[i:end + 1] in ref:
                end += 1
            spans.append(draft[where[i]:where[end - 1] + 1])
            i = end
        else:
            i += 1
    return spans


HINTS = {
    "문장 평균 길이": ("문장이 참고 글보다 깁니다. 절 단위에서 끊어 보세요.", "문장이 참고 글보다 짧습니다. 짧은 문장 몇 개를 이어 보세요."),
    "20자 이하 문장 비율(%)": ("짧은 문장이 참고 글보다 많습니다.", "짧게 끊는 문장이 참고 글보다 적습니다. 강조할 곳을 한 줄로 떼어 보세요."),
    "한 줄에 한 문장 비율(%)": ("줄바꿈이 참고 글보다 잦습니다.", "참고 글은 문장마다 줄을 내리는 편입니다."),
    "질문 문장 비율(%)": ("질문이 참고 글보다 많습니다.", "참고 글보다 질문이 적습니다."),
    "느낌표 편당": ("느낌표가 참고 글보다 많습니다.", "참고 글보다 느낌표가 적습니다."),
}
TOLERANCE = {"문장 평균 길이": 0.2, "20자 이하 문장 비율(%)": 0.3, "한 줄에 한 문장 비율(%)": 0.25, "질문 문장 비율(%)": 0.5, "느낌표 편당": 0.5}


def compare(ref: dict[str, object], draft: dict[str, object]) -> list[str]:
    notes: list[str] = []
    for key, tolerance in TOLERANCE.items():
        a, b = float(ref[key]), float(draft[key])  # type: ignore[arg-type]
        base = max(abs(a), 1.0)
        if abs(b - a) / base > tolerance:
            step = round(b + (a - b) / 2, 1)
            notes.append(f"- {key}: 참고 {a} / 초안 {b} → {HINTS[key][0] if b > a else HINTS[key][1]} 이번에는 {step} 정도까지만 옮겨 보세요.")
    ref_end = ref["말투(문장 끝) 비율(%)"]
    dra_end = draft["말투(문장 끝) 비율(%)"]
    if isinstance(ref_end, dict) and isinstance(dra_end, dict) and ref_end and dra_end:
        top_ref, top_dra = next(iter(ref_end)), next(iter(dra_end))
        if top_ref != top_dra:
            notes.append(f"- 말투: 참고 글은 주로 '{top_ref}', 초안은 주로 '{top_dra}' → 문장 끝을 '{top_ref}'로 맞춰 보세요.")
    if notes:
        notes.append("- 한 번에 다 맞추지 말고 차이의 절반만 고친 뒤 다시 비교하세요. 문체를 고친 뒤에는 새로 생긴 사실이 없는지도 확인하세요.")
    return notes or ["- 주요 지표가 참고 글과 비슷한 범위입니다."]


def _print_profile(title: str, result: dict[str, object]) -> None:
    print(f"== {title} ==")
    for key, value in result.items():
        print(f"{key}: {value}")


def _read(paths: list[Path]) -> list[str]:
    posts: list[str] = []
    for path in paths:
        posts += split_posts(path.read_text(encoding="utf-8-sig"))
    return posts


def main(argv: list[str] | None = None) -> int:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="참고 글쓴이 문체 관찰과 초안 비교")
    parser.add_argument("files", nargs="+", type=Path, help="참고 글 파일")
    parser.add_argument("--compare", type=Path, help="비교할 내 초안 파일")
    parser.add_argument("--copy-chars", type=int, default=DEFAULT_COPY_CHARS, help="베낀 구간으로 볼 최소 글자 수(공백 제외)")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        reference = _read(args.files)
        draft = _read([args.compare]) if args.compare else []
    except (OSError, UnicodeError) as error:
        print(f"파일을 읽을 수 없습니다: {error}", file=sys.stderr)
        return 2
    if not reference or (args.compare and not draft):
        print("분석할 글이 없습니다.", file=sys.stderr)
        return 2
    ref_profile = profile(reference)
    if not args.compare:
        if args.json:
            print(json.dumps(ref_profile, ensure_ascii=False, indent=1))
        else:
            _print_profile("참고 글 문체", ref_profile)
            print("\n※ 관찰값입니다. 참고 글의 문장과 그 사람의 경험은 옮기지 마세요.")
        return 0
    draft_profile = profile(draft)
    notes = compare(ref_profile, draft_profile)
    copies = copied_spans("\n".join(reference), "\n".join(draft), args.copy_chars)
    if args.json:
        print(json.dumps({"참고": ref_profile, "초안": draft_profile, "조정 제안": notes, "겹치는 구간": copies}, ensure_ascii=False, indent=1))
    else:
        _print_profile("참고 글 문체", ref_profile)
        print()
        _print_profile("내 초안", draft_profile)
        print("\n== 조정 제안 ==")
        print("\n".join(notes))
        print(f"\n== 베낀 구간 검사 (공백 빼고 {args.copy_chars}자 이상 똑같은 부분) ==")
        print("\n".join(f"- {span}" for span in copies) if copies else "- 없음")
    return 1 if copies else 0


if __name__ == "__main__":
    raise SystemExit(main())
