"""Parakeet 영어 자막 포매터 (segment-merge 안정형)

전략:
- Parakeet의 segment를 기본 단위로 사용
- segment overlap으로 생기는 중복 word/text를 최대한 정리
- 짧고 어색한 segment는 앞/뒤와 merge
- 너무 긴 segment만 보수적으로 split
- spaCy 없이 영어 전용 기본 규칙만 사용
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .config import Config
from .transcriber import SegmentStamp, WordStamp


@dataclass
class SubtitleBlock:
    index: int
    start: float
    end: float
    text: str


@dataclass
class _Fmt:
    max_chars_per_line: int
    max_lines_per_sub: int
    max_chars_per_sub: int
    min_gap_sec: float
    min_sub_duration_sec: float
    max_sub_duration_sec: float
    pause_split_sec: float
    strong_pause_split_sec: float
    target_cps: float
    hard_cps: float


_NO_SPACE_BEFORE = {".", ",", "!", "?", ";", ":", "%", ")", "]", "}", "”", '"'}
_NO_SPACE_PREFIXES = ("'s", "'re", "'ve", "'ll", "'m", "'d", "n't")

# 이런 단어에서 끝나면 웬만하면 거기서 끊지 않음
_INCOMPLETE_END_WORDS = {
    "a", "an", "the",
    "to", "of", "in", "on", "at", "for", "with", "by", "from",
    "about", "into", "over", "under", "through", "across", "between", "within",
    "and", "or", "but", "so", "yet", "nor",
    "that", "which", "who", "whom", "whose", "what",
    "is", "are", "was", "were", "be", "been", "being",
    "do", "does", "did", "have", "has", "had",
    "can", "could", "will", "would", "shall", "should", "may", "might", "must",
    "this", "these", "those", "my", "your", "his", "her", "its", "our", "their",
    "most", "more", "less",
}

# 이런 단어로 다음 자막이 시작하면 앞 자막과 붙을 가능성이 큼
_CONTINUATION_START_WORDS = {
    "a", "an", "the",
    "to", "of", "in", "on", "at", "for", "with", "by", "from",
    "about", "into", "over", "under", "through", "across", "between", "within",
    "and", "or", "but", "so", "because", "if", "when", "while",
    "although", "though", "however", "therefore", "then",
    "that", "which", "who", "whom", "whose", "what",
    "is", "are", "was", "were", "be", "been", "being",
    "most", "more", "less",
}

_MARKER_WORDS = {
    "okay", "ok", "right", "exactly", "well", "now", "yeah", "yes",
    "uh", "um", "actually", "basically", "honestly"
}


def format_segments_to_blocks(
    segments: list[SegmentStamp],
    cfg: Config,
) -> list[SubtitleBlock]:
    fmt = _get_fmt(cfg)
    if not segments:
        return []

    cleaned = _clean_segments(segments)

    # 1) 먼저 너무 잘게 잘린 segment를 합친다
    merged = _merge_segments(cleaned, fmt)
    merged = _merge_segments(merged, fmt)

    # 2) 그래도 너무 긴 segment만 split
    split_done: list[SegmentStamp] = []
    for seg in merged:
        split_done.extend(_split_segment_if_needed(seg, fmt))

    # 3) split 후 생긴 어색한 조각 정리
    final_segments = _merge_segments(split_done, fmt)
    final_segments = _merge_marker_only_segments(final_segments, fmt)

    blocks: list[SubtitleBlock] = []
    for idx, seg in enumerate(final_segments, 1):
        text = _normalize_space(seg.text)
        if not text:
            continue

        wrapped = _wrap_text(
            text,
            fmt.max_chars_per_line,
            fmt.max_lines_per_sub,
        )
        blocks.append(
            SubtitleBlock(
                index=idx,
                start=seg.start,
                end=max(seg.end, seg.start + 0.35),
                text=wrapped,
            )
        )

    _stabilize_block_timings(blocks, fmt)
    for i, block in enumerate(blocks, 1):
        block.index = i
    return blocks


def _get_fmt(cfg: Config) -> _Fmt:
    max_chars_per_line = int(getattr(cfg, "max_chars_per_line", 42))
    max_lines_per_sub = int(getattr(cfg, "max_lines_per_sub", 2))
    return _Fmt(
        max_chars_per_line=max_chars_per_line,
        max_lines_per_sub=max_lines_per_sub,
        max_chars_per_sub=max_chars_per_line * max_lines_per_sub,
        min_gap_sec=float(getattr(cfg, "min_gap_ms", 100)) / 1000.0,
        min_sub_duration_sec=float(getattr(cfg, "min_sub_duration_sec", 1.2)),
        max_sub_duration_sec=float(getattr(cfg, "max_sub_duration_sec", 6.2)),
        pause_split_sec=float(getattr(cfg, "pause_split_sec", 0.65)),
        strong_pause_split_sec=float(getattr(cfg, "strong_pause_split_sec", 1.00)),
        target_cps=float(getattr(cfg, "target_cps", 15.5)),
        hard_cps=float(getattr(cfg, "hard_cps", 18.5)),
    )


# ──────────────────────────────────────────────
# segment 정리
# ──────────────────────────────────────────────
def _clean_segments(segments: list[SegmentStamp]) -> list[SegmentStamp]:
    cleaned: list[SegmentStamp] = []
    last_word_end = -1.0

    for seg in sorted(segments, key=lambda s: (s.start, s.end)):
        seg_words = sorted(seg.words or [], key=lambda w: (w.start, w.end))
        kept_words: list[WordStamp] = []

        # overlapping segment prefix 제거
        for w in seg_words:
            token = _normalize_space(w.word)
            if not token:
                continue

            start = float(w.start)
            end = float(w.end)
            if end <= start:
                end = start + 0.01

            if end <= last_word_end + 0.03:
                continue

            kept_words.append(WordStamp(word=token, start=start, end=end))

        if kept_words:
            text = _words_to_text(kept_words)
            if not text:
                continue
            new_seg = SegmentStamp(
                text=text,
                start=kept_words[0].start,
                end=kept_words[-1].end,
                words=kept_words,
            )
            cleaned.append(new_seg)
            last_word_end = kept_words[-1].end
            continue

        # word가 없으면 text fallback
        text = _normalize_space(seg.text)
        if not text:
            continue

        if cleaned:
            text = _trim_textual_overlap(cleaned[-1].text, text)
            text = _normalize_space(text)

        if not text:
            continue

        start = float(seg.start)
        end = float(seg.end)
        if end <= start:
            end = start + 0.35

        cleaned.append(
            SegmentStamp(
                text=text,
                start=start,
                end=end,
                words=[],
            )
        )
        last_word_end = max(last_word_end, end)

    return cleaned


def _trim_textual_overlap(prev_text: str, cur_text: str) -> str:
    prev_words = [_word_core(w) for w in prev_text.split()]
    cur_words = [_word_core(w) for w in cur_text.split()]
    raw_cur_words = cur_text.split()

    prev_words = [w for w in prev_words if w]
    cur_words = [w for w in cur_words if w]

    if not prev_words or not cur_words:
        return cur_text

    max_k = min(8, len(prev_words), len(cur_words))
    for k in range(max_k, 1, -1):
        if prev_words[-k:] == cur_words[:k]:
            return " ".join(raw_cur_words[k:]).strip()

    return cur_text


# ──────────────────────────────────────────────
# merge-first
# ──────────────────────────────────────────────
def _merge_segments(segments: list[SegmentStamp], fmt: _Fmt) -> list[SegmentStamp]:
    if len(segments) <= 1:
        return segments

    result: list[SegmentStamp] = []
    i = 0

    while i < len(segments):
        cur = segments[i]

        if i + 1 < len(segments):
            nxt = segments[i + 1]
            if _should_merge(cur, nxt, fmt):
                result.append(_combine_segments(cur, nxt))
                i += 2
                continue

        result.append(cur)
        i += 1

    return result


def _should_merge(a: SegmentStamp, b: SegmentStamp, fmt: _Fmt) -> bool:
    a_text = _normalize_space(a.text)
    b_text = _normalize_space(b.text)
    if not a_text or not b_text:
        return False

    gap = max(0.0, b.start - a.end)
    combined = _normalize_space(f"{a_text} {b_text}")
    combined_duration = max(0.01, b.end - a.start)
    combined_cps = len(combined) / combined_duration

    if gap > max(fmt.pause_split_sec + 0.15, 0.55):
        return False
    if combined_duration > fmt.max_sub_duration_sec + 1.0:
        return False
    if combined_cps > fmt.hard_cps:
        return False
    if len(combined) > fmt.max_chars_per_sub + 18:
        return False

    a_dur = a.end - a.start
    b_dur = b.end - b.start

    a_short = a_dur < 1.6 or len(a_text) < 30
    b_short = b_dur < 1.4 or len(b_text) < 22

    a_incomplete = _ends_incomplete_phrase(a_text)
    b_cont = _starts_continuation_phrase(b_text)

    a_marker = _is_marker_like(a_text)
    b_marker = _is_marker_like(b_text)

    # 핵심 merge 조건
    if a_marker or b_marker:
        return True
    if a_incomplete:
        return True
    if b_cont:
        return True
    if a_short and not _ends_with_strong_punct(a_text):
        return True
    if a_short and b_short:
        return True

    # 약한 pause + 앞이 짧으면 합침
    if gap <= 0.25 and (a_short or b_short):
        return True

    return False


def _merge_marker_only_segments(segments: list[SegmentStamp], fmt: _Fmt) -> list[SegmentStamp]:
    if len(segments) <= 1:
        return segments

    result: list[SegmentStamp] = []
    for seg in segments:
        text = _normalize_space(seg.text)

        if result and _is_marker_like(text):
            prev = result[-1]
            merged = _combine_segments(prev, seg)
            merged_text = _normalize_space(merged.text)
            merged_duration = max(0.01, merged.end - merged.start)

            if (
                len(merged_text) <= fmt.max_chars_per_sub + 10
                and merged_duration <= fmt.max_sub_duration_sec + 0.8
            ):
                result[-1] = merged
                continue

        result.append(seg)

    return result


def _combine_segments(a: SegmentStamp, b: SegmentStamp) -> SegmentStamp:
    if a.words and b.words:
        words = a.words + b.words
        text = _words_to_text(words)
    else:
        words = a.words + b.words
        text = _normalize_space(f"{a.text} {b.text}")

    return SegmentStamp(
        text=text,
        start=min(a.start, b.start),
        end=max(a.end, b.end),
        words=words,
    )


# ──────────────────────────────────────────────
# split-last
# ──────────────────────────────────────────────
def _split_segment_if_needed(seg: SegmentStamp, fmt: _Fmt) -> list[SegmentStamp]:
    text = _normalize_space(seg.text)
    duration = max(0.01, seg.end - seg.start)

    needs_split = (
        len(text) > fmt.max_chars_per_sub
        or duration > fmt.max_sub_duration_sec
    )
    if not needs_split:
        return [seg]

    # word timestamp 있으면 그걸 우선 사용
    if seg.words and len(seg.words) >= 6:
        return _split_word_segment_recursively(seg, fmt)

    # 없으면 text 기준 fallback
    return _split_text_segment_fallback(seg, fmt)


def _split_word_segment_recursively(seg: SegmentStamp, fmt: _Fmt) -> list[SegmentStamp]:
    if not seg.words or len(seg.words) < 6:
        return [seg]

    text = _normalize_space(seg.text)
    duration = max(0.01, seg.end - seg.start)
    if len(text) <= fmt.max_chars_per_sub and duration <= fmt.max_sub_duration_sec:
        return [seg]

    split_idx = _choose_split_index(seg.words, fmt)
    if split_idx is None or split_idx <= 1 or split_idx >= len(seg.words) - 1:
        return [seg]

    left_words = seg.words[:split_idx]
    right_words = seg.words[split_idx:]

    left = SegmentStamp(
        text=_words_to_text(left_words),
        start=left_words[0].start,
        end=left_words[-1].end,
        words=left_words,
    )
    right = SegmentStamp(
        text=_words_to_text(right_words),
        start=right_words[0].start,
        end=right_words[-1].end,
        words=right_words,
    )

    out: list[SegmentStamp] = []
    for part in (left, right):
        if (
            len(_normalize_space(part.text)) > fmt.max_chars_per_sub
            or (part.end - part.start) > fmt.max_sub_duration_sec
        ):
            out.extend(_split_word_segment_recursively(part, fmt))
        else:
            out.append(part)
    return out


def _choose_split_index(words: list[WordStamp], fmt: _Fmt) -> int | None:
    if len(words) < 6:
        return None

    best_idx: int | None = None
    best_score = float("inf")
    target_fill = fmt.max_chars_per_sub * 0.82

    for i in range(3, len(words) - 2):
        left = words[:i]
        right = words[i:]

        left_text = _words_to_text(left)
        right_text = _words_to_text(right)

        left_len = len(left_text)
        right_len = len(right_text)
        left_dur = max(0.01, left[-1].end - left[0].start)
        right_dur = max(0.01, right[-1].end - right[0].start)

        if left_len < 18 or right_len < 14:
            continue
        if left_dur < 0.9 or right_dur < 0.8:
            continue

        # 왼쪽이 화면 하나 채울 정도로 차는 걸 선호
        score = abs(left_len - target_fill) * 0.08
        score += abs(left_dur - 3.3) * 0.35

        last_word = left[-1].word
        next_word = right[0].word
        gap = max(0.0, right[0].start - left[-1].end)

        if _ends_with_strong_punct(last_word):
            score -= 4.5
        elif _ends_with_soft_punct(last_word):
            score -= 2.0

        if gap >= fmt.strong_pause_split_sec:
            score -= 4.0
        elif gap >= fmt.pause_split_sec:
            score -= 2.0

        if _word_core(last_word) in _INCOMPLETE_END_WORDS:
            score += 5.0
        if _word_core(next_word) in _CONTINUATION_START_WORDS:
            score += 4.0

        # 왼쪽도 오른쪽도 너무 크면 안 좋음
        if left_len > fmt.max_chars_per_sub + 10:
            score += 10.0
        if right_len > fmt.max_chars_per_sub + 18:
            score += 6.0

        if score < best_score:
            best_score = score
            best_idx = i

    return best_idx


def _split_text_segment_fallback(seg: SegmentStamp, fmt: _Fmt) -> list[SegmentStamp]:
    text = _normalize_space(seg.text)
    words = text.split()
    if len(words) < 8:
        return [seg]

    max_chars = fmt.max_chars_per_sub
    split_idx = None
    best_score = float("inf")

    for i in range(3, len(words) - 2):
        left = " ".join(words[:i]).strip()
        right = " ".join(words[i:]).strip()

        if len(left) < 18 or len(right) < 14:
            continue

        score = abs(len(left) - max_chars * 0.82) * 0.08

        if _ends_with_strong_punct(left):
            score -= 4.0
        elif _ends_with_soft_punct(left):
            score -= 1.5

        if _word_core(words[i - 1]) in _INCOMPLETE_END_WORDS:
            score += 5.0
        if _word_core(words[i]) in _CONTINUATION_START_WORDS:
            score += 4.0

        if score < best_score:
            best_score = score
            split_idx = i

    if split_idx is None:
        return [seg]

    left_text = " ".join(words[:split_idx]).strip()
    right_text = " ".join(words[split_idx:]).strip()

    total = max(1, len(words))
    ratio = split_idx / total
    mid = seg.start + (seg.end - seg.start) * ratio

    left = SegmentStamp(
        text=left_text,
        start=seg.start,
        end=max(mid, seg.start + 0.6),
        words=[],
    )
    right = SegmentStamp(
        text=right_text,
        start=min(mid, seg.end - 0.6),
        end=seg.end,
        words=[],
    )

    return [left, right]


# ──────────────────────────────────────────────
# timing / wrap
# ──────────────────────────────────────────────
def _stabilize_block_timings(blocks: list[SubtitleBlock], fmt: _Fmt) -> None:
    if not blocks:
        return

    for block in blocks:
        if block.end <= block.start:
            block.end = block.start + 0.35

    for i in range(len(blocks) - 1):
        cur = blocks[i]
        nxt = blocks[i + 1]

        desired_end = nxt.start - fmt.min_gap_sec
        if cur.end > desired_end:
            cur.end = max(cur.start + 0.35, desired_end)

        if cur.end > nxt.start - fmt.min_gap_sec:
            nxt.start = cur.end + fmt.min_gap_sec
            if nxt.end <= nxt.start:
                nxt.end = nxt.start + 0.35

    for block in blocks:
        if block.end <= block.start:
            block.end = block.start + 0.35


def _wrap_text(text: str, max_chars: int, max_lines: int) -> str:
    text = _normalize_space(text)
    if not text:
        return ""

    if max_lines <= 1 or len(text) <= max_chars:
        return text

    if max_lines == 2:
        balanced = _balanced_two_line_wrap(text, max_chars)
        if balanced is not None:
            return balanced

    lines = _greedy_wrap(text, max_chars)
    if len(lines) <= max_lines:
        return "\n".join(lines)

    kept = lines[: max_lines - 1]
    tail = " ".join(lines[max_lines - 1 :]).strip()
    kept.append(tail)
    return "\n".join(kept)


def _balanced_two_line_wrap(text: str, max_chars: int) -> str | None:
    words = text.split()
    if len(words) < 2:
        return None

    best: str | None = None
    best_score = float("inf")

    for i in range(1, len(words)):
        left = " ".join(words[:i]).strip()
        right = " ".join(words[i:]).strip()

        if not left or not right:
            continue
        if len(left) > max_chars or len(right) > max_chars:
            continue

        score = abs(len(left) - len(right))

        left_last = _word_core(words[i - 1])
        right_first = _word_core(words[i])

        if left_last in _INCOMPLETE_END_WORDS:
            score += 10.0
        if right_first in _CONTINUATION_START_WORDS:
            score += 5.0
        if re.search(r"[,:;.!?]$", left):
            score -= 1.5

        if score < best_score:
            best_score = score
            best = f"{left}\n{right}"

    return best


def _greedy_wrap(text: str, max_chars: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current: list[str] = []

    for word in words:
        test = " ".join(current + [word]).strip()
        if current and len(test) > max_chars:
            lines.append(" ".join(current).strip())
            current = [word]
        else:
            current.append(word)

    if current:
        lines.append(" ".join(current).strip())

    return lines


# ──────────────────────────────────────────────
# text helpers
# ──────────────────────────────────────────────
def _words_to_text(words: list[WordStamp]) -> str:
    out = ""
    for w in words:
        token = _normalize_space(w.word)
        if not token:
            continue

        if not out:
            out = token
            continue

        if token in _NO_SPACE_BEFORE:
            out += token
        elif token.startswith(_NO_SPACE_PREFIXES):
            out += token
        elif token.startswith("'"):
            out += token
        else:
            out += " " + token

    return _normalize_space(out)


def _ends_with_strong_punct(text: str) -> bool:
    return bool(re.search(r'[.!?]["”\')\]]*$', text.strip()))


def _ends_with_soft_punct(text: str) -> bool:
    return bool(re.search(r'[,:;]["”\')\]]*$', text.strip()))


def _ends_incomplete_phrase(text: str) -> bool:
    words = text.replace("\n", " ").split()
    if not words:
        return False
    last = _word_core(words[-1])
    if last in _INCOMPLETE_END_WORDS:
        return True

    # punctuation 없이 짧게 끝나면 약간 더 보수적으로 incomplete 취급
    if len(text) < 32 and not _ends_with_strong_punct(text) and not _ends_with_soft_punct(text):
        return True

    return False


def _starts_continuation_phrase(text: str) -> bool:
    words = text.replace("\n", " ").split()
    if not words:
        return False
    first = _word_core(words[0])
    return first in _CONTINUATION_START_WORDS


def _is_marker_like(text: str) -> bool:
    words = [_word_core(w) for w in text.split()]
    words = [w for w in words if w]
    if not words or len(words) > 3:
        return False
    return all(w in _MARKER_WORDS for w in words)


def _word_core(word: str) -> str:
    return re.sub(r"^[^\w$£€#]+|[^\w%]+$", "", word.lower()).strip()


def _normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()
