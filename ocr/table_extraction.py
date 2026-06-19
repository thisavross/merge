from __future__ import annotations

from collections import Counter
import html
import re
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from bs4 import BeautifulSoup
from rapidocr import RapidOCR
from table_cls import TableCls
import re as regex
from lineless_table_rec.main import LinelessTableInput, LinelessTableRecognition
from wired_table_rec.main import WiredTableInput, WiredTableRecognition


IMG_PATH = Path(r"dataset\images\5.png")
OUT_HTML = Path("output/output_2.html")
OUT_TXT = Path("output/table_chunks_2.txt")
OUT_MD = Path("output/output_2.md")

# OCR words with lower confidence than this are ignored.
MIN_OCR_SCORE = 0.35

# If TSR loses too many OCR words, the script falls back to OCR-layout extraction.
MIN_TSR_WORD_COVERAGE = 0.72


@dataclass
class Word:
    text: str
    x1: float
    y1: float
    x2: float
    y2: float
    score: float

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2

    @property
    def cy(self) -> float:
        return (self.y1 + self.y2) / 2

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1


@dataclass
class Segment:
    words: list[Word]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in sorted(self.words, key=lambda w: w.x1)).strip()

    @property
    def x1(self) -> float:
        return min(w.x1 for w in self.words)

    @property
    def y1(self) -> float:
        return min(w.y1 for w in self.words)

    @property
    def x2(self) -> float:
        return max(w.x2 for w in self.words)

    @property
    def y2(self) -> float:
        return max(w.y2 for w in self.words)

    @property
    def cx(self) -> float:
        return (self.x1 + self.x2) / 2


def box_to_xyxy(box) -> tuple[float, float, float, float]:
    xs = box[:, 0]
    ys = box[:, 1]
    return float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())


def normalize_spaces(text: str) -> str:
    return " ".join(str(text).split())


def is_numeric_like(text: str) -> bool:
    text = normalize_spaces(text)
    return bool(re.fullmatch(r"[()+\-]?\d[\d,.)/%]*", text))


def split_glued_numeric_text(
    text: str, x1: float, y1: float, x2: float, y2: float, score: float
) -> list[Word]:
    match = re.match(r"^([(+\-]?\d[\d,.)]*%?)([A-Za-z].*)$", text)

    if not match:
        return [Word(text=text, x1=x1, y1=y1, x2=x2, y2=y2, score=score)]

    value, rest = match.groups()
    total_len = max(len(value) + len(rest), 1)
    split_x = x1 + (x2 - x1) * (len(value) / total_len)

    return [
        Word(text=value, x1=x1, y1=y1, x2=split_x, y2=y2, score=score),
        Word(text=rest, x1=split_x, y1=y1, x2=x2, y2=y2, score=score),
    ]


def split_spaced_text_box(
    text: str, x1: float, y1: float, x2: float, y2: float, score: float
) -> list[Word]:
    parts = text.split()

    if len(parts) <= 1:
        return split_glued_numeric_text(text, x1, y1, x2, y2, score)

    total_units = sum(len(part) for part in parts) + (len(parts) - 1)
    cursor = x1
    words = []

    for idx, part in enumerate(parts):
        part_width = (x2 - x1) * (len(part) / max(total_units, 1))
        next_x = cursor + part_width
        words.extend(split_glued_numeric_text(part, cursor, y1, next_x, y2, score))
        cursor = next_x

        if idx < len(parts) - 1:
            cursor += (x2 - x1) * (1 / max(total_units, 1))

    return words


def median(values: Iterable[float], default: float) -> float:
    values = list(values)
    return statistics.median(values) if values else default


def overlap_ratio(word: Word, cell: tuple[float, float, float, float]) -> float:
    x1, y1, x2, y2 = cell
    ix1 = max(word.x1, x1)
    iy1 = max(word.y1, y1)
    ix2 = min(word.x2, x2)
    iy2 = min(word.y2, y2)

    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0

    intersection = (ix2 - ix1) * (iy2 - iy1)
    word_area = max(word.width * word.height, 1.0)
    return intersection / word_area


def html_to_tokens_span_aware(html_text: str) -> list[dict]:

    soup = BeautifulSoup(html_text, "html.parser")
    tokens = []
    occupied = set()

    for row_idx, row in enumerate(soup.find_all("tr")):
        logical_col = 0

        for cell in row.find_all(["td", "th"]):
            while (row_idx, logical_col) in occupied:
                logical_col += 1

            rowspan = int(cell.get("rowspan", 1))
            colspan = int(cell.get("colspan", 1))
            text = cell.get_text(separator=" ", strip=True)

            if text:
                tokens.append(
                    {
                        "row": row_idx,
                        "col": logical_col,
                        "rowspan": rowspan,
                        "colspan": colspan,
                        "text": text,
                    }
                )

            for rr in range(row_idx, row_idx + rowspan):
                for cc in range(logical_col, logical_col + colspan):
                    occupied.add((rr, cc))

            logical_col += colspan

    return tokens


def read_ocr_words(img) -> tuple[list[Word], list[tuple]]:
    ocr_engine = RapidOCR()
    result = ocr_engine(img, return_word_box=True)

    if result is None or result.boxes is None:
        return [], []

    words = []
    raw_ocr_result = []

    for box, text, score in zip(result.boxes, result.txts, result.scores):
        text = normalize_spaces(text)

        if not text or float(score) < MIN_OCR_SCORE:
            continue

        x1, y1, x2, y2 = box_to_xyxy(box)
        words.extend(split_spaced_text_box(text, x1, y1, x2, y2, float(score)))
        raw_ocr_result.append((box, text, score))
    return words, raw_ocr_result


def words_to_text(words):

    if not words:
        return ""

    words = sorted(
        words,
        key=lambda w: (
            w.cy,
            w.x1,
        ),
    )

    rows = []

    for w in words:
        placed = False

        for row in rows:
            y = sum(x.cy for x in row) / len(row)

            if abs(y - w.cy) < 8:
                row.append(w)

                placed = True
                break

        if not placed:
            rows.append([w])

    output = []

    for row in rows:
        row = sorted(row, key=lambda x: x.x1)

        output.append(" ".join(x.text for x in row))

    return "\n".join(output)


def is_interval_only(text: str) -> bool:
    text = normalize_spaces(text)
    return bool(re.fullmatch(r"\([^)]+\)", text)) and bool(re.search(r"\d", text))


def has_confidence_interval(text: str) -> bool:

    text = normalize_spaces(text)

    return bool(
        re.search(
            r"\(\s*\d+(?:\.\d+)?\s*[-–]\s*\d+(?:\.\d+)?\s*\)",
            text,
        )
    )


def is_stat_continuation(text: str) -> bool:
    text = normalize_spaces(text)
    if not text:
        return False

    if is_interval_only(text):
        return True

    return bool(
        re.fullmatch(
            r"[+\-]?\d+(?:[.,]\d+)?(?:\s*\([+\-]?\d+(?:[.,]\d+)?[-\u2013][+\-]?\d+(?:[.,]\d+)?\))?",
            text,
        )
    )


def cell_center(cell: dict) -> float:
    bbox = cell.get("bbox")

    if bbox:
        return (bbox[0] + bbox[2]) / 2

    return float(cell.get("col", 0))


def closest_visual_col(cell: dict, target_row: dict[int, dict]) -> int | None:

    if not target_row:
        return None

    sx1, _, sx2, _ = cell["bbox"]
    source_center = (sx1 + sx2) / 2

    best_col = None
    best_distance = float("inf")

    for col_idx, target in target_row.items():
        tx1, _, tx2, _ = target["bbox"]
        target_center = (tx1 + tx2) / 2

        distance = abs(source_center - target_center)

        if distance < best_distance:
            best_distance = distance
            best_col = col_idx

    return best_col


def append_cell_text(target: dict, value: str) -> None:
    value = normalize_spaces(value)
    current = normalize_spaces(target.get("text", ""))

    if not value:
        return

    if value in current:
        return

    target["text"] = f"{current} {value}".strip() if current else value


def vertical_continuation(cell, prev_row):

    if not prev_row:
        return False

    y1 = cell["bbox"][1]

    prev_bottom = max(c["bbox"][3] for c in prev_row.values())

    distance = y1 - prev_bottom

    return distance < 25


def assign_words_to_cells(
    words,
    cell_bboxes,
    min_overlap=0.15,
):

    parsed = [tuple(map(float, b)) for b in cell_bboxes]

    assignments = {}
    matched = set()

    cell_centers = [(x1 + x2) / 2 for x1, y1, x2, y2 in parsed]

    cell_widths = [
        max(
            x2 - x1,
            1,
        )
        for x1, y1, x2, y2 in parsed
    ]

    for wid, word in enumerate(words):
        candidates = []

        for cid, (
            x1,
            y1,
            x2,
            y2,
        ) in enumerate(parsed):
            ov = overlap_ratio(
                word,
                (
                    x1,
                    y1,
                    x2,
                    y2,
                ),
            )

            if ov <= 0:
                continue

            # penalti jika center jauh dari center cell
            dx = abs(word.cx - cell_centers[cid])

            penalty = dx / cell_widths[cid]

            score = ov * (1 - 0.35 * penalty)

            candidates.append(
                (
                    score,
                    cid,
                )
            )

        if not candidates:
            continue

        candidates.sort(reverse=True)

        score, cid = candidates[0]

        if score < min_overlap:
            continue

        assignments.setdefault(
            cid,
            [],
        ).append(word)

        matched.add(wid)

    return (
        assignments,
        matched,
    )


def extract_with_tsr(
    img_path,
    words,
    raw_ocr_result,
):

    import html

    table_type, _ = TableCls()(str(img_path))

    if table_type == "wired":
        engine = WiredTableRecognition(WiredTableInput())
    else:
        engine = LinelessTableRecognition(LinelessTableInput())

    result = engine(
        str(img_path),
        ocr_result=raw_ocr_result,
        need_ocr=False,
    )

    logic = result.logic_points
    boxes = result.cell_bboxes

    if logic is None or boxes is None:
        return "", 0.0

    assignments, matched = assign_words_to_cells(
        words,
        boxes,
    )

    grid = {}

    # ====================
    # BUILD GRID
    # ====================

    for idx in range(
        min(
            len(logic),
            len(boxes),
        )
    ):
        rs, re, cs, ce = map(
            int,
            logic[idx],
        )

        bbox = tuple(
            map(
                float,
                boxes[idx],
            )
        )

        text = normalize_spaces(
            words_to_text(
                assignments.get(
                    idx,
                    [],
                )
            )
        )

        grid[
            (
                rs,
                cs,
            )
        ] = {
            "text": text,
            "bbox": bbox,
            "rowspan": re - rs + 1,
            "colspan": ce - cs + 1,
        }

    max_row = max(v[1] for v in logic)
    max_col = max(v[3] for v in logic)

    # ====================
    # RENDER HTML
    # ====================

    occupied = set()

    parts = ["<table border='1'>"]

    for r in range(max_row + 1):
        parts.append("<tr>")

        for c in range(max_col + 1):
            if (
                r,
                c,
            ) in occupied:
                continue

            cell = grid.get(
                (
                    r,
                    c,
                )
            )

            if not cell:
                continue

            text = html.escape(cell["text"])

            attrs = []

            if cell["rowspan"] > 1:
                attrs.append(f"rowspan='{cell['rowspan']}'")

            if cell["colspan"] > 1:
                attrs.append(f"colspan='{cell['colspan']}'")

            attr_text = " " + " ".join(attrs) if attrs else ""
            parts.append(f"<td{attr_text}>{text}</td>")

            for rr in range(
                r,
                r + cell["rowspan"],
            ):
                for cc in range(
                    c,
                    c + cell["colspan"],
                ):
                    occupied.add(
                        (
                            rr,
                            cc,
                        )
                    )

        parts.append("</tr>")

    parts.append("</table>")

    coverage = len(matched) / max(
        len(words),
        1,
    )

    return (
        "\n".join(parts),
        coverage,
    )


def group_words_into_rows(words: list[Word]) -> list[list[Word]]:
    row_tol = max(median((w.height for w in words), 10.0) * 0.65, 5.0)
    rows: list[list[Word]] = []

    for word in sorted(words, key=lambda w: (w.cy, w.x1)):
        for row in rows:
            row_y = sum(w.cy for w in row) / len(row)

            if abs(word.cy - row_y) <= row_tol:
                row.append(word)
                break
        else:
            rows.append([word])

    for row in rows:
        row.sort(key=lambda w: w.x1)

    rows.sort(key=lambda row: sum(w.cy for w in row) / len(row))
    return rows


def split_row_into_segments(row: list[Word], gap_threshold: float) -> list[Segment]:
    if not row:
        return []

    segments = [[row[0]]]

    for prev, word in zip(row, row[1:]):
        gap = word.x1 - prev.x2

        if gap > gap_threshold:
            segments.append([word])
        else:
            segments[-1].append(word)

    return [Segment(words=segment) for segment in segments]


def cluster_positions(values: list[float], tolerance: float) -> list[tuple[float, int]]:
    if not values:
        return []

    clusters: list[list[float]] = []

    for value in sorted(values):
        if clusters and abs(value - statistics.mean(clusters[-1])) <= tolerance:
            clusters[-1].append(value)
        else:
            clusters.append([value])

    return [(statistics.mean(cluster), len(cluster)) for cluster in clusters]


def infer_column_separators(rows: list[list[Word]]) -> list[float]:
    """
    Infer column boundaries from repeated vertical whitespace gutters.

    This stays content-agnostic: no fixed column count, no language-specific
    labels, and no numeric-column assumptions. A gap only becomes a separator
    when roughly the same x-position appears across several rows.
    """
    all_words = [w for row in rows for w in row]

    if not all_words:
        return []

    word_height = median((w.height for w in all_words), 10.0)
    min_gap = max(6.0, word_height * 0.55)
    cluster_tol = max(5.0, word_height * 0.55)
    min_support = max(2, min(6, int(len(rows) * 0.12)))

    separator_candidates = []

    for row in rows:
        row = sorted(row, key=lambda w: w.x1)

        for left, right in zip(row, row[1:]):
            gap = right.x1 - left.x2

            if gap >= min_gap:
                separator_candidates.append((left.x2 + right.x1) / 2)

    clusters = cluster_positions(separator_candidates, tolerance=cluster_tol)
    supported = [center for center, count in clusters if count >= min_support]

    min_x = int(min(w.x1 for w in all_words))
    max_x = int(max(w.x2 for w in all_words))
    width = max(max_x - min_x + 1, 1)
    occupancy = [0] * width

    for row in rows:
        row_mask = [0] * width

        for word in row:
            start = max(0, int(word.x1) - min_x)
            end = min(width - 1, int(word.x2) - min_x)

            for idx in range(start, end + 1):
                row_mask[idx] = 1

        for idx, value in enumerate(row_mask):
            occupancy[idx] += value

    low_coverage = max(1, int(len(rows) * 0.06))
    idx = 0

    while idx < width:
        if occupancy[idx] > low_coverage:
            idx += 1
            continue

        start = idx

        while idx < width and occupancy[idx] <= low_coverage:
            idx += 1

        end = idx - 1
        gap_width = end - start + 1

        if gap_width < min_gap:
            continue

        sep = min_x + (start + end) / 2
        support = 0

        for row in rows:
            has_left = any(word.x2 < sep for word in row)
            has_right = any(word.x1 > sep for word in row)

            if has_left and has_right:
                support += 1

        if support >= min_support:
            supported.append(sep)

    if not supported:
        return []

    min_sep_distance = max(10.0, word_height * 0.9)
    separators: list[float] = []

    for sep in supported:
        if not separators or sep - separators[-1] >= min_sep_distance:
            separators.append(sep)
        else:
            separators[-1] = (separators[-1] + sep) / 2

    return separators


def word_to_col(word: Word, separators: list[float]) -> int:
    col = 0

    for sep in separators:
        if word.cx > sep:
            col += 1
        else:
            break

    return col


def row_to_cells(row: list[Word], separators: list[float]) -> list[str]:
    col_count = max(len(separators) + 1, 1)
    buckets: list[list[Word]] = [[] for _ in range(col_count)]

    for word in sorted(row, key=lambda w: w.x1):
        buckets[word_to_col(word, separators)].append(word)

    return [words_to_text(bucket) if bucket else "" for bucket in buckets]


def compact_sparse_columns(table: list[list[str]]) -> list[list[str]]:
    if not table:
        return table

    col_count = max(len(row) for row in table)
    keep = []

    for col_idx in range(col_count):
        filled = sum(1 for row in table if col_idx < len(row) and row[col_idx])

        if filled > 0:
            keep.append(col_idx)

    return [[row[idx] if idx < len(row) else "" for idx in keep] for row in table]


def repair_header_offset(table: list[list[str]]) -> list[list[str]]:
    if len(table) < 2 or not table[0]:
        return table

    first_row_values = [value for value in table[0] if value]

    if not first_row_values:
        return table

    first_row_is_numeric_header = all(
        is_numeric_like(value) for value in first_row_values
    )
    body_has_left_text_and_numeric_value = any(
        len(row) > 1
        and row[0]
        and not is_numeric_like(row[0])
        and row[1]
        and is_numeric_like(row[1])
        for row in table[1:]
    )

    if not first_row_is_numeric_header or not body_has_left_text_and_numeric_value:
        return table

    width = max(len(row) for row in table)
    repaired = [row + [""] * (width - len(row)) for row in table]
    repaired[0] = [""] + repaired[0][:-1]
    return repaired


def pop_leading_value(text: str) -> tuple[str | None, str]:
    text = text.strip()
    match = re.match(r"^([(+\-]?\d[\d,.)]*%?)(.*)$", text)

    if not match:
        return None, text

    value = match.group(1).strip()
    rest = match.group(2).strip()
    return value, rest


def repair_leading_values(table: list[list[str]]) -> list[list[str]]:
    repaired = [row[:] for row in table]

    for row in repaired:
        for col_idx in range(1, len(row)):
            if not row[col_idx]:
                continue

            empty_left = []
            scan_idx = col_idx - 1

            while scan_idx >= 0 and not row[scan_idx]:
                empty_left.append(scan_idx)
                scan_idx -= 1

            if not empty_left:
                continue

            text = row[col_idx]
            values = []

            while True:
                value, rest = pop_leading_value(text)

                if value is None:
                    break

                values.append(value)
                text = rest

                if not text:
                    break

            if not values:
                continue

            targets = list(reversed(empty_left))[: len(values)]

            for target, value in zip(targets, values[-len(targets) :]):
                row[target] = value

            row[col_idx] = text

    return repaired


def split_row_into_cell_segments(row: list[Word]) -> list[Segment]:
    if not row:
        return []

    row = sorted(row, key=lambda w: w.x1)
    word_height = median((w.height for w in row), 10.0)
    gap_threshold = max(4.0, word_height * 0.55)
    segments: list[list[Word]] = [[row[0]]]

    for prev, word in zip(row, row[1:]):
        gap = word.x1 - prev.x2
        numeric_to_text = is_numeric_like(prev.text) and not is_numeric_like(word.text)

        if gap > gap_threshold or numeric_to_text:
            segments.append([word])
        else:
            segments[-1].append(word)

    return [Segment(words=segment) for segment in segments]


def segment_anchor(segment: Segment) -> tuple[float, str]:
    text = segment.text

    if is_numeric_like(text):
        return segment.x2, "numeric"

    return segment.x1, "text"


def infer_column_anchors(
    segments_by_row: list[list[Segment]],
) -> list[tuple[float, str]]:
    text_positions = []
    numeric_positions = []

    for segments in segments_by_row:
        for segment in segments:
            position, kind = segment_anchor(segment)

            if kind == "numeric":
                numeric_positions.append(position)
            else:
                text_positions.append(position)

    text_clusters = cluster_positions(text_positions, tolerance=14.0)
    numeric_clusters = cluster_positions(numeric_positions, tolerance=18.0)
    anchors = [(pos, "text") for pos, _ in text_clusters]
    anchors.extend((pos, "numeric") for pos, _ in numeric_clusters)
    anchors.sort(key=lambda item: item[0])

    deduped: list[tuple[float, str]] = []

    for position, kind in anchors:
        if deduped and kind == deduped[-1][1] and abs(position - deduped[-1][0]) < 4:
            prev_position, prev_kind = deduped[-1]
            deduped[-1] = ((prev_position + position) / 2, prev_kind)
        else:
            deduped.append((position, kind))

    return deduped


def segment_to_col(segment: Segment, anchors: list[tuple[float, str]]) -> int:
    if not anchors:
        return 0

    position, kind = segment_anchor(segment)
    same_kind = [
        (idx, anchor) for idx, anchor in enumerate(anchors) if anchor[1] == kind
    ]
    candidates = same_kind if same_kind else list(enumerate(anchors))
    return min(candidates, key=lambda item: abs(position - item[1][0]))[0]


def segments_to_table(
    segments_by_row: list[list[Segment]], anchors: list[tuple[float, str]]
) -> list[list[str]]:
    col_count = max(len(anchors), 1)
    table = []

    for segments in segments_by_row:
        row = [""] * col_count

        for segment in segments:
            col_idx = segment_to_col(segment, anchors)
            value = normalize_spaces(segment.text)

            if row[col_idx]:
                row[col_idx] += " " + value
            else:
                row[col_idx] = value

        table.append(row)

    return table


def table_to_html(table: list[list[str]]) -> str:
    parts = ["<table border='1'>"]

    for row in table:
        parts.append("  <tr>")

        for value in row:
            parts.append(f"    <td>{html.escape(value)}</td>")

        parts.append("  </tr>")

    parts.append("</table>")
    return "\n".join(parts)


def table_to_markdown(table: list[list[str]]) -> str:
    if not table:
        return ""

    width = max(len(row) for row in table)
    normalized = [row + [""] * (width - len(row)) for row in table]

    def esc(value: str) -> str:
        return value.replace("|", "\\|").replace("\n", " ").strip()

    parts = []
    parts.append("| " + " | ".join(esc(value) for value in normalized[0]) + " |")
    parts.append("| " + " | ".join("---" for _ in range(width)) + " |")

    for row in normalized[1:]:
        parts.append("| " + " | ".join(esc(value) for value in row) + " |")

    return "\n".join(parts)


def extract_with_ocr_layout(words: list[Word]) -> tuple[str, str]:
    rows = group_words_into_rows(words)
    segments_by_row = [split_row_into_cell_segments(row) for row in rows]
    anchors = infer_column_anchors(segments_by_row)
    table = segments_to_table(segments_by_row, anchors)
    table = repair_leading_values(table)
    table = compact_sparse_columns(table)
    table = repair_header_offset(table)
    return table_to_html(table), table_to_markdown(table)


def save_tokens(html_text: str, path: Path) -> list[dict]:
    tokens = html_to_tokens_span_aware(html_text)

    print("\n===== TOKENS =====")

    for t in tokens:
        print(t)

    with path.open("w", encoding="utf-8") as f:
        for token in tokens:
            f.write(
                f"row={token['row']} col={token['col']} "
                f"rowspan={token.get('rowspan', 1)} colspan={token.get('colspan', 1)} "
                f"value={token['text']}\n"
            )

    return tokens


def main() -> None:
    if not IMG_PATH.exists():
        raise FileNotFoundError(f"Image not found: {IMG_PATH}")

    words, raw_ocr_result = read_ocr_words(IMG_PATH)
    print(f"OCR words: {len(words)}")

    tsr_html, coverage = extract_with_tsr(IMG_PATH, words, raw_ocr_result)
    print(f"TSR OCR-word coverage: {coverage:.2%}")

    if tsr_html and coverage >= MIN_TSR_WORD_COVERAGE:
        final_html = tsr_html
        final_md = ""
        method = "tsr"
    else:
        final_html, final_md = extract_with_ocr_layout(words)
        method = "ocr-layout-fallback"

    OUT_HTML.write_text(final_html, encoding="utf-8")
    if final_md:
        OUT_MD.write_text(final_md, encoding="utf-8")

    tokens = save_tokens(final_html, OUT_TXT)

    print(f"Extraction method: {method}")
    print("\n===== HTML =====\n")
    print(final_html[:3000])

    print("\n===== TOKENS =====\n")
    for token in tokens[:80]:
        print(token)

    print("\nSaved:")
    print(OUT_HTML)
    print(OUT_TXT)
    if final_md:
        print(OUT_MD)


if __name__ == "__main__":
    main()
