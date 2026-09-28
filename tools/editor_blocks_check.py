"""Read-only check that a blog draft contains the editor blocks a store requires.

Draft markers (one per line):

    <!-- slogan --> ... <!-- /slogan -->   slogan quote block
    <!-- toc --> 목차 / 1) ... <!-- /toc -->  table of contents box
    ## subheading                          left-bar subheading
    <!-- info --> ... <!-- /info -->       centered store info block

Rules come from WRITING_POLICY.json -> channels.blog.editor_blocks:

    {"required": ["slogan", "toc", "heading", "info"], "min_headings": 3,
     "slogans": ["approved slogan"], "info_facts": ["store name", "address", "phone"]}

The tool only reports; it never rewrites the draft. Exit codes: 0 = no BLOCK,
1 = BLOCK found, 2 = input or policy error. Python 3.10+, no extra packages.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Final

_NAMES: Final = ("slogan", "toc", "heading", "info")
_MARKER: Final = re.compile(r"^<!--\s*(/?)(slogan|toc|info)\s*-->$")
_HEADING: Final = re.compile(r"^#{2,3}[ \t]+\S")
_TOC_ITEM: Final = re.compile(r"^(\d+)\)\s*\S")
_LABELS: Final = {"slogan": "슬로건 인용구", "toc": "목차 박스", "info": "매장 안내 블록"}


class PolicyError(ValueError):
    pass


def _compact(value: str) -> str:
    return re.sub(r"[\s\"'“”‘’]+", "", value)


def load_rules(policy_path: Path) -> dict[str, object]:
    data = json.loads(policy_path.read_text(encoding="utf-8-sig"))
    rules = data.get("channels", {}).get("blog", {}).get("editor_blocks")
    if not isinstance(rules, dict):
        raise PolicyError("channels.blog.editor_blocks가 정책에 없습니다.")
    required = rules.get("required")
    if not isinstance(required, list) or any(item not in _NAMES for item in required):
        raise PolicyError(f"required는 {', '.join(_NAMES)} 중에서 고릅니다.")
    if not isinstance(rules.get("min_headings"), int) or rules["min_headings"] < 0:
        raise PolicyError("min_headings는 0 이상의 정수입니다.")
    for key in ("slogans", "info_facts"):
        value = rules.get(key)
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise PolicyError(f"{key}는 문자열 목록입니다.")
    return rules


def inspect(text: str, rules: dict[str, object]) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []

    def block(code: str, message: str, **evidence: object) -> None:
        findings.append({"level": "BLOCK", "code": code, "message": message, "evidence": evidence})

    blocks: dict[str, list[tuple[int, list[str]]]] = {}
    headings = 0
    current: tuple[str, int, list[str]] | None = None
    lines = text.removeprefix("\ufeff").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        marker = _MARKER.fullmatch(stripped)
        if marker is not None:
            closing, name = marker.group(1) == "/", marker.group(2)
            if not closing and current is None:
                current = (name, number, [])
            elif closing and current is not None and current[0] == name:
                blocks.setdefault(name, []).append((current[1], current[2]))
                current = None
            else:
                block("editor-block-marker", "편집 블록 표시가 짝이 맞지 않습니다.", line=number, marker=stripped)
            continue
        if current is not None:
            if stripped:
                current[2].append(stripped)
        elif _HEADING.match(stripped):
            headings += 1
    if current is not None:
        block("editor-block-marker", "닫히지 않은 편집 블록이 있습니다.", line=current[1], block=current[0])

    for name in rules["required"]:  # type: ignore[union-attr]
        if name == "heading":
            if headings < int(rules["min_headings"]):  # type: ignore[arg-type]
                block("editor-heading-missing", "세로선 소제목(## 소제목)이 부족합니다.",
                      count=headings, min=rules["min_headings"])
        elif name not in blocks:
            block("editor-block-missing", f"{_LABELS[name]}가 없습니다.", block=name)

    slogans = {_compact(item) for item in rules["slogans"]}  # type: ignore[union-attr]
    for number, rows in blocks.get("slogan", []):
        if slogans and _compact("".join(rows)) not in slogans:
            block("editor-slogan-unapproved", "승인된 슬로건이 아닙니다.", line=number, text=" ".join(rows))

    for number, rows in blocks.get("toc", []):
        items = [row for row in rows if row != "목차"]
        numbers = []
        for row in items:
            item = _TOC_ITEM.match(row)
            if item is None:
                block("editor-toc-format", "목차 항목은 1) 형식으로 씁니다.", line=number, text=row)
            else:
                numbers.append(int(item.group(1)))
        if numbers != list(range(1, len(numbers) + 1)):
            block("editor-toc-format", "목차 번호가 1부터 이어지지 않습니다.", line=number, numbers=numbers)
        if len(items) != headings:
            block("editor-toc-mismatch", "목차 항목 수와 소제목 수가 다릅니다.",
                  line=number, toc=len(items), headings=headings)

    for number, rows in blocks.get("info", []):
        body = _compact("".join(rows))
        missing = [fact for fact in rules["info_facts"] if _compact(fact) not in body]  # type: ignore[union-attr]
        if missing:
            block("editor-info-fact", "매장 안내 블록에 필수 정보가 빠졌습니다.", line=number, missing=missing)

    findings.append({
        "level": "INFO", "code": "manual-review",
        "message": "편집기 서식(인용 부호·접힌 모서리·세로선·모서리 장식)은 PC·모바일 공개 화면에서 확인하세요.",
        "evidence": {},
    })
    return findings


def main(argv: list[str] | None = None) -> int:
    configure = getattr(sys.stdout, "reconfigure", None)
    if callable(configure):
        configure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="블로그 편집 블록 필수 요소 검사(읽기 전용)")
    parser.add_argument("draft")
    parser.add_argument("--policy", required=True, type=Path, help="WRITING_POLICY.json 경로")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        rules = load_rules(args.policy)
        findings = inspect(Path(args.draft).read_text(encoding="utf-8-sig"), rules)
    except (OSError, ValueError, UnicodeError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False) if args.json else f"입력 오류: {error}")
        return 2
    code = int(any(item["level"] == "BLOCK" for item in findings))
    if args.json:
        print(json.dumps({"exit_code": code, "findings": findings}, ensure_ascii=False))
    else:
        for item in findings:
            print(f"[{item['level']}] {item['code']}: {item['message']} {item['evidence'] or ''}".rstrip())
        print(f"종료 코드: {code}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
