"""Portable, read-only repetition review signals for a draft.

The inspector uses exact surface forms rather than morphology. In particular,
Korean particle variants are not conflated: ``메뉴는`` and ``메뉴가`` remain
different words. Phrase analysis is bounded to local 2-8 word draft phrases
and 4-12 word history overlaps so runtime grows linearly with ordinary input
size and nested fragments do not flood the report.

Findings are review signals, not semantic, authorship, AI, or plagiarism
verdicts. This module never rewrites the input and has no project imports.
Inputs exceeding 50,000 tokens per document fail explicitly rather than
silently skipping phrase analysis. Unpunctuated blocks use line-level units,
not a claim of full Korean sentence or morphology parsing.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Final, TypedDict

_WORD: Final = re.compile(r"[^\W_]+(?:[-'][^\W_]+)*", re.UNICODE)
_TERMINALS: Final = frozenset(".!?。？！")
_MAX_DRAFT_PHRASE: Final = 8
_MIN_HISTORY_PHRASE: Final = 4
_MAX_HISTORY_PHRASE: Final = 12
_PHRASE_TOKEN_BUDGET: Final = 50_000
_WORD_REPEAT_MIN: Final = 4
_PHRASE_REPEAT_MIN: Final = 3
_STOPWORDS: Final = frozenset(
    {
        "대한",
        "위한",
        "있는",
        "없는",
        "합니다",
        "했습니다",
        "입니다",
        "있습니다",
        "것은",
        "것을",
        "수가",
        "에서",
        "으로",
        "에게",
        "까지",
        "부터",
    }
)


@dataclass(frozen=True, slots=True)
class RepetitionFinding:
    """One immutable repetition review signal."""

    code: str
    text: str
    count: int
    lines: tuple[int, ...]
    source: str | None = None


class RepetitionInputError(ValueError):
    """An input cannot be fully analyzed under the documented limits."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class _FindingPayload(TypedDict):
    code: str
    text: str
    count: int
    lines: list[int]
    source: str | None


class _HistoryPayload(TypedDict):
    status: str
    files: int


class _ReportPayload(TypedDict, total=False):
    error: str
    history: _HistoryPayload
    findings: list[_FindingPayload]
    manual_review_required: bool


@dataclass(frozen=True, slots=True)
class _Sentence:
    text: str
    normalized: str
    line: int
    token_lines: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class _Token:
    text: str
    normalized: str
    line: int
    sentence: int
    position: int


def _clean_surface(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _normalize_text(text: str) -> str:
    if _WORD.search(text) is None:
        return ""
    return re.sub(r"[\s\u200b\ufeff]+", "", text).casefold().strip(".!?。？！\"'“”‘’")


def _row_stream(rows: list[tuple[int, str]]) -> tuple[str, list[int]]:
    parts: list[str] = []
    line_map: list[int] = []
    for index, (line_number, text) in enumerate(rows):
        if index:
            parts.append("\n")
            line_map.append(line_number)
        parts.append(text)
        line_map.extend([line_number] * len(text))
    return "".join(parts), line_map


def _sentence_from_span(text: str, line_map: list[int], start: int, end: int) -> _Sentence | None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    if start >= end:
        return None
    surface = _clean_surface(text[start:end])
    normalized = _normalize_text(surface)
    if not normalized:
        return None
    token_lines = tuple(
        line_map[start + match.start()] for match in _WORD.finditer(text[start:end])
    )
    return _Sentence(surface, normalized, token_lines[0], token_lines)


def _paragraph_sentences(rows: list[tuple[int, str]]) -> list[_Sentence]:
    text, line_map = _row_stream(rows)
    if not text:
        return []
    result: list[_Sentence] = []
    start = 0
    saw_terminal = False
    for index, character in enumerate(text):
        if character not in _TERMINALS:
            continue
        if character == "." and index > 0 and index + 1 < len(text):
            if text[index - 1].isdigit() and text[index + 1].isdigit():
                continue
        sentence = _sentence_from_span(text, line_map, start, index + 1)
        if sentence is not None:
            result.append(sentence)
        start = index + 1
        saw_terminal = True
    trailing = _sentence_from_span(text, line_map, start, len(text))
    if trailing is not None:
        if saw_terminal or "\n" not in text[start:]:
            result.append(trailing)
        else:
            for line_number, row in rows:
                surface = _clean_surface(row)
                normalized = _normalize_text(surface)
                if normalized:
                    token_lines = tuple(line_number for _ in _WORD.finditer(surface))
                    result.append(_Sentence(surface, normalized, line_number, token_lines))
    return result


def _sentences(
    rows: list[tuple[int, str]], allowed: tuple[tuple[str, ...], ...]
) -> list[_Sentence]:
    """Join wrapped prose only inside one paragraph, not across labels or gaps."""
    result: list[_Sentence] = []
    paragraph: list[tuple[int, str]] = []
    previous_line: int | None = None
    for line_number, row in rows:
        words = tuple(match.group(0).casefold() for match in _WORD.finditer(row))
        allowed_label = _entirely_allowed(words, allowed)
        blank = not row.strip()
        gap = previous_line is not None and line_number > previous_line + 1
        if paragraph and (gap or blank or allowed_label):
            result.extend(_paragraph_sentences(paragraph))
            paragraph = []
        if allowed_label:
            result.extend(_paragraph_sentences([(line_number, row)]))
        elif not blank:
            paragraph.append((line_number, row))
        previous_line = line_number
    result.extend(_paragraph_sentences(paragraph))
    return result


def _tokens(sentences: list[_Sentence]) -> list[_Token]:
    result: list[_Token] = []
    position = 0
    for sentence_index, sentence in enumerate(sentences):
        for token_index, match in enumerate(_WORD.finditer(sentence.text)):
            surface = match.group(0)
            result.append(
                _Token(surface, surface.casefold(), sentence.token_lines[token_index], sentence_index, position)
            )
            position += 1
    return result


def _allowed_sequences(allowed_terms: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    unique: set[tuple[str, ...]] = set()
    for term in allowed_terms:
        sequence = tuple(match.group(0).casefold() for match in _WORD.finditer(term))
        if sequence:
            unique.add(sequence)
    return tuple(sorted(unique, key=lambda item: (-len(item), item)))


def _entirely_allowed(normalized_words: tuple[str, ...], allowed: tuple[tuple[str, ...], ...]) -> bool:
    if not normalized_words or not allowed:
        return False
    remaining = [True] * len(normalized_words)
    index = 0
    while index < len(normalized_words):
        matched = False
        for sequence in allowed:
            end = index + len(sequence)
            if normalized_words[index:end] == sequence:
                for offset in range(index, end):
                    remaining[offset] = False
                index = end
                matched = True
                break
        if not matched:
            index += 1
    return not any(remaining)


def _sentence_findings(
    sentences: list[_Sentence], allowed: tuple[tuple[str, ...], ...]
) -> tuple[list[RepetitionFinding], set[str]]:
    occurrences: dict[str, list[_Sentence]] = defaultdict(list)
    for sentence in sentences:
        words = tuple(match.group(0).casefold() for match in _WORD.finditer(sentence.text))
        if len(sentence.normalized) >= 6 and not _entirely_allowed(words, allowed):
            occurrences[sentence.normalized].append(sentence)
    findings: list[RepetitionFinding] = []
    repeated: set[str] = set()
    for normalized, matches in occurrences.items():
        if len(matches) < 2:
            continue
        repeated.add(normalized)
        findings.append(
            RepetitionFinding(
                "internal-sentence-repeat",
                matches[0].text,
                len(matches),
                tuple(item.line for item in matches),
            )
        )
    return findings, repeated


def _meaningful_word(word: str) -> bool:
    if word in _STOPWORDS or word.isdecimal():
        return False
    if len(word) >= 2 and not word.isascii():
        return True
    return len(word) >= 3


def _word_findings(tokens: list[_Token], allowed: tuple[tuple[str, ...], ...]) -> list[RepetitionFinding]:
    allowed_positions: set[int] = set()
    for group in _sentence_token_groups(tokens):
        words = tuple(token.normalized for token in group)
        for sequence in allowed:
            for start in range(len(words) - len(sequence) + 1):
                end = start + len(sequence)
                if words[start:end] == sequence:
                    allowed_positions.update(token.position for token in group[start:end])
    occurrences: dict[str, list[_Token]] = defaultdict(list)
    for token in tokens:
        if token.position not in allowed_positions and _meaningful_word(token.normalized):
            occurrences[token.normalized].append(token)
    findings: list[RepetitionFinding] = []
    for matches in occurrences.values():
        if len(matches) >= _WORD_REPEAT_MIN:
            findings.append(
                RepetitionFinding(
                    "internal-word-repeat",
                    matches[0].text,
                    len(matches),
                    tuple(item.line for item in matches),
                )
            )
    return findings


def _sentence_token_groups(tokens: list[_Token]) -> list[list[_Token]]:
    groups: list[list[_Token]] = []
    for token in tokens:
        while len(groups) <= token.sentence:
            groups.append([])
        groups[token.sentence].append(token)
    return groups


def _draft_phrase_findings(
    tokens: list[_Token],
    sentences: list[_Sentence],
    repeated_sentences: set[str],
    allowed: tuple[tuple[str, ...], ...],
) -> list[RepetitionFinding]:
    occurrences: dict[tuple[str, ...], list[tuple[int, int, int, int]]] = defaultdict(list)
    groups = _sentence_token_groups(tokens)
    budget = _PHRASE_TOKEN_BUDGET
    for sentence_index, group in enumerate(groups):
        if budget <= 0:
            break
        usable = group[:budget]
        budget -= len(usable)
        for size in range(2, min(_MAX_DRAFT_PHRASE, len(usable)) + 1):
            for start in range(len(usable) - size + 1):
                window = usable[start : start + size]
                key = tuple(token.normalized for token in window)
                if sum(len(word) for word in key) < 6 or _entirely_allowed(key, allowed):
                    continue
                occurrences[key].append((window[0].position, window[-1].position + 1, window[0].line, sentence_index))

    candidates = [
        (key, matches)
        for key, matches in occurrences.items()
        if len(matches) >= _PHRASE_REPEAT_MIN
        and not all(sentences[item[3]].normalized in repeated_sentences for item in matches)
    ]
    candidates.sort(key=lambda item: (-len(item[0]), -len(item[1]), item[1][0][0], item[0]))
    covered_positions: set[int] = set()
    findings: list[RepetitionFinding] = []
    for key, matches in candidates:
        if all(
            all(position in covered_positions for position in range(start, end))
            for start, end, _, _ in matches
        ):
            continue
        for start, end, _, _ in matches:
            covered_positions.update(range(start, end))
        first_start, first_end, _, _ = matches[0]
        surface = " ".join(token.text for token in tokens[first_start:first_end])
        findings.append(
            RepetitionFinding(
                "internal-phrase-repeat",
                surface,
                len(matches),
                tuple(line for _, _, line, _ in matches),
            )
        )
    return findings


def _history_sentence_findings(
    draft_sentences: list[_Sentence],
    history_sentences: list[_Sentence],
    source: str,
    allowed: tuple[tuple[str, ...], ...],
) -> tuple[list[RepetitionFinding], set[str]]:
    historical = {sentence.normalized for sentence in history_sentences}
    matched_normalized: set[str] = set()
    grouped: dict[str, list[_Sentence]] = defaultdict(list)
    for sentence in draft_sentences:
        words = tuple(match.group(0).casefold() for match in _WORD.finditer(sentence.text))
        if sentence.normalized in historical and len(sentence.normalized) >= 6 and not _entirely_allowed(words, allowed):
            grouped[sentence.normalized].append(sentence)
            matched_normalized.add(sentence.normalized)
    findings = [
        RepetitionFinding(
            "history-sentence-repeat",
            matches[0].text,
            len(matches),
            tuple(item.line for item in matches),
            source,
        )
        for matches in grouped.values()
    ]
    return findings, matched_normalized


def _ngram_sets(groups: list[list[_Token]]) -> dict[int, set[tuple[str, ...]]]:
    result: dict[int, set[tuple[str, ...]]] = {}
    for size in range(_MIN_HISTORY_PHRASE, _MAX_HISTORY_PHRASE + 1):
        values: set[tuple[str, ...]] = set()
        budget = _PHRASE_TOKEN_BUDGET
        for group in groups:
            if budget <= 0:
                break
            usable = group[:budget]
            budget -= len(usable)
            values.update(
                tuple(token.normalized for token in usable[start : start + size])
                for start in range(len(usable) - size + 1)
            )
        result[size] = values
    return result


def _history_phrase_findings(
    draft_tokens: list[_Token],
    draft_sentences: list[_Sentence],
    history_tokens: list[_Token],
    exact_sentence_normalized: set[str],
    source: str,
    allowed: tuple[tuple[str, ...], ...],
) -> list[RepetitionFinding]:
    draft_groups = _sentence_token_groups(draft_tokens)
    historical = _ngram_sets(_sentence_token_groups(history_tokens))
    grouped: dict[tuple[str, ...], list[tuple[str, int]]] = defaultdict(list)
    budget = _PHRASE_TOKEN_BUDGET
    for sentence_index, group in enumerate(draft_groups):
        if budget <= 0:
            continue
        sentence_normalized = draft_sentences[sentence_index].normalized
        if sentence_normalized in exact_sentence_normalized:
            continue
        usable = group[:budget]
        budget -= len(usable)
        covered = [False] * len(usable)
        for size in range(min(_MAX_HISTORY_PHRASE, len(usable)), _MIN_HISTORY_PHRASE - 1, -1):
            for start in range(len(usable) - size + 1):
                if any(covered[start : start + size]):
                    continue
                window = usable[start : start + size]
                key = tuple(token.normalized for token in window)
                if key not in historical[size] or sum(len(word) for word in key) < 12 or _entirely_allowed(key, allowed):
                    continue
                for offset in range(start, start + size):
                    covered[offset] = True
                grouped[key].append((" ".join(token.text for token in window), window[0].line))
    return [
        RepetitionFinding(
            "history-phrase-repeat",
            matches[0][0],
            len(matches),
            tuple(line for _, line in matches),
            source,
        )
        for matches in grouped.values()
    ]


def inspect_repetition(
    rows: list[tuple[int, str]],
    *,
    allowed_terms: tuple[str, ...] = (),
    history: tuple[tuple[str, str], ...] = (),
) -> list[RepetitionFinding]:
    """Inspect already-selected body rows without changing or re-filtering them."""
    allowed = _allowed_sequences(allowed_terms)
    sentences = _sentences(rows, allowed)
    tokens = _tokens(sentences)
    if len(tokens) > _PHRASE_TOKEN_BUDGET:
        raise RepetitionInputError(f"draft exceeds {_PHRASE_TOKEN_BUDGET} tokens; split the input")
    sentence_findings, repeated_sentences = _sentence_findings(sentences, allowed)
    findings = [
        *sentence_findings,
        *_draft_phrase_findings(tokens, sentences, repeated_sentences, allowed),
        *_word_findings(tokens, allowed),
    ]
    for source, text in history:
        history_rows = [(number, line) for number, line in enumerate(text.splitlines(), start=1)]
        history_sentences = _sentences(history_rows, allowed)
        history_tokens = _tokens(history_sentences)
        if len(history_tokens) > _PHRASE_TOKEN_BUDGET:
            raise RepetitionInputError(
                f"history {source} exceeds {_PHRASE_TOKEN_BUDGET} tokens; split the input"
            )
        history_sentence_findings, exact_normalized = _history_sentence_findings(
            sentences, history_sentences, source, allowed
        )
        findings.extend(history_sentence_findings)
        findings.extend(
            _history_phrase_findings(tokens, sentences, history_tokens, exact_normalized, source, allowed)
        )
    code_order = {
        "internal-sentence-repeat": 0,
        "internal-phrase-repeat": 1,
        "internal-word-repeat": 2,
        "history-sentence-repeat": 3,
        "history-phrase-repeat": 4,
    }
    findings.sort(
        key=lambda item: (
            code_order[item.code],
            item.source or "",
            item.lines[0] if item.lines else 0,
            item.text.casefold(),
        )
    )
    return findings


def _finding_dict(finding: RepetitionFinding) -> _FindingPayload:
    return {
        "code": finding.code,
        "text": finding.text,
        "count": finding.count,
        "lines": list(finding.lines),
        "source": finding.source,
    }


def _configure_stdout() -> None:
    configure = getattr(sys.stdout, "reconfigure", None)
    if callable(configure):
        configure(encoding="utf-8", errors="replace", line_buffering=True)


def _history_files(directory: Path, target: Path) -> list[Path]:
    if not directory.is_dir():
        raise OSError(f"history directory does not exist: {directory}")
    own = target.resolve()
    candidates = [*directory.glob("*.md"), *directory.glob("*.txt")]
    return sorted(
        (path for path in candidates if path.resolve() != own),
        key=lambda path: (path.name.casefold(), path.name),
    )


def main(argv: list[str] | None = None) -> int:
    """Run the standalone inspector; review findings intentionally exit zero."""
    _configure_stdout()
    parser = argparse.ArgumentParser(description="Read-only repetition review signals")
    parser.add_argument("draft", type=Path)
    parser.add_argument("--allow-term", action="append", default=[])
    parser.add_argument("--history-dir", type=Path)
    parser.add_argument("--json", action="store_true")
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        match error.code:
            case int() as code:
                return code
            case _:
                return 2

    history_status = "absent"
    history_count = 0
    try:
        draft_text = args.draft.read_text(encoding="utf-8-sig")
        if not draft_text.strip():
            raise RepetitionInputError("draft has no body text")
        history: list[tuple[str, str]] = []
        if args.history_dir is not None:
            files = _history_files(args.history_dir, args.draft)
            history_count = len(files)
            history_status = "checked" if files else "empty"
            for path in files:
                history.append((path.name, path.read_text(encoding="utf-8-sig")))
        rows = [(number, line) for number, line in enumerate(draft_text.splitlines(), start=1)]
        findings = inspect_repetition(
            rows,
            allowed_terms=tuple(args.allow_term),
            history=tuple(history),
        )
    except (OSError, UnicodeError, RepetitionInputError) as error:
        payload: _ReportPayload = {
            "error": str(error),
            "history": {"status": "error" if args.history_dir is not None else history_status, "files": history_count},
            "manual_review_required": True,
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        else:
            print(f"[INPUT ERROR] {error}", file=sys.stderr)
        return 2

    payload = {
        "history": {"status": history_status, "files": history_count},
        "findings": [_finding_dict(finding) for finding in findings],
        "manual_review_required": True,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    else:
        print(f"history: {history_status} ({history_count} files)")
        for finding in findings:
            source = f" source={finding.source}" if finding.source is not None else ""
            print(
                f"[REVIEW] {finding.code}: {finding.text} "
                f"count={finding.count} lines={','.join(map(str, finding.lines))}{source}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
