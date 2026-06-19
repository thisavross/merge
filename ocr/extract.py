import os
import cv2
import fitz
import pandas as pd
import traceback
from docling.document_converter import DocumentConverter
import re
import json
import uuid
import tempfile

import fitz
import pandas as pd
import wordninja
from collections import defaultdict
from docling.document_converter import DocumentConverter

from transformers import AutoTokenizer

from table_extraction import (
    read_ocr_words,
    extract_with_tsr,
    extract_with_ocr_layout,
    html_to_tokens_span_aware,
    MIN_TSR_WORD_COVERAGE,
)
from ultralytics import YOLO

table_detector = YOLO("model/table_det.pt")

tokenizer = AutoTokenizer.from_pretrained("BAAI/bge-small-en-v1.5")

converter = DocumentConverter()


def token_count(text: str) -> int:
    return len(tokenizer.encode(text, add_special_tokens=False))


MAX_TOKENS = 450
TABLE_ROWS_PER_CHUNK = 8


def render_page_to_image(pdf_path, page_no):
    doc = fitz.open(pdf_path)

    try:
        page = doc[page_no - 1]
        pix = page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp_path = tmp.name
        tmp.close()
        pix.save(tmp_path)

        return tmp_path

    finally:
        doc.close()


def clean_text(text):
    if text is None:
        return ""
    text = str(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fix_broken_spacing(text):
    text = clean_text(text)
    if not text:
        return ""

    words = text.split()
    if len(words) >= 3 or text.isupper():
        return text

    return " ".join(wordninja.split(text)).strip()


def detect_tables(page_img):
    results = table_detector.predict(page_img, conf=0.85, verbose=False, device="cpu")
    boxes = []
    for r in results:
        for box in r.boxes.xyxy.cpu().numpy():
            x1, y1, x2, y2 = map(int, box)
            boxes.append((x1, y1, x2, y2))

    return boxes


def crop_table(img_path, bbox, pad=5):

    img = cv2.imread(img_path)

    h, w = img.shape[:2]

    x1, y1, x2, y2 = bbox

    x1 = max(0, x1 - pad)
    y1 = max(0, y1 - pad)
    x2 = min(w, x2 + pad)
    y2 = min(h, y2 + pad)

    crop = img[y1:y2, x1:x2]

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)

    tmp_path = tmp.name
    tmp.close()

    cv2.imwrite(tmp_path, crop)

    return tmp_path


def tsr_html_to_chunk_text(html_text):

    tokens = html_to_tokens_span_aware(html_text)

    rows = defaultdict(list)

    for token in tokens:
        rows[token["row"]].append(token)

    output = []

    for row_id in sorted(rows.keys()):
        row_tokens = sorted(rows[row_id], key=lambda x: x["col"])

        row_text = " | ".join(clean_text(x["text"]) for x in row_tokens if x["text"])

        if row_text:
            output.append(row_text)

    return "\n".join(output), tokens


# TOKEN CHUNKER
def chunk_by_tokens(text_list, max_tokens=350, overlap=50):
    full_text = " ".join(clean_text(t) for t in text_list if clean_text(t))

    if not full_text:
        return []

    token_ids = tokenizer.encode(full_text, add_special_tokens=False)

    chunks = []

    start = 0

    while start < len(token_ids):
        end = min(start + max_tokens, len(token_ids))

        chunk_ids = token_ids[start:end]

        chunk_text = tokenizer.decode(chunk_ids, skip_special_tokens=True)

        chunks.append(chunk_text)

        if end == len(token_ids):
            break

        start += max_tokens - overlap

    return chunks


def chunk_table_text(table_text, max_tokens=350):
    lines = table_text.splitlines()
    chunks = []
    current = []
    for line in lines:
        test = "\n".join(current + [line])
        if token_count(test) > max_tokens:
            if current:
                chunks.append("\n".join(current))
            current = [line]

        else:
            current.append(line)

    if current:
        chunks.append("\n".join(current))

    return chunks


def is_toc(df):
    if df.shape[1] <= 2:
        return True

    col0 = df.iloc[:, 0].astype(str)
    ratio = col0.str.match(r"^\d+$").mean()
    return ratio > 0.6


def is_heading_item(item):
    item_type = type(item).__name__

    return item_type in {"TitleItem", "SectionHeaderItem", "HeadingItem"}


def split_pdf_batches(pdf_path, batch_size=3):
    doc = fitz.open(pdf_path)
    temp_files = []

    for start in range(0, len(doc), batch_size):
        end = min(start + batch_size, len(doc))
        temp_doc = fitz.open()
        temp_doc.insert_pdf(doc, from_page=start, to_page=end - 1)
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        tmp_path = tmp.name
        tmp.close()
        temp_doc.save(tmp_path)
        temp_doc.close()

        temp_files.append(tmp_path)

    doc.close()

    return temp_files


def process_pdf(pdf_path, batch_size=3):

    doc_id = str(uuid.uuid4())
    source_pdf = os.path.basename(pdf_path)

    batches = split_pdf_batches(pdf_path, batch_size)

    all_chunks = []
    global_chunk_index = 0

    for batch_idx, batch_file in enumerate(batches):
        batch_start_page = batch_idx * batch_size
        print(f"Batch {batch_idx + 1}/{len(batches)}")

        try:
            result = converter.convert(batch_file)
            doc = result.document

            buffer_text = []
            current_page = 1

            section_stack = []
            current_section = "Document"
            processed_table_pages = set()

            for item, level in doc.iterate_items():
                try:
                    item_type = type(item).__name__
                    try:
                        current_page = item.prov[0].page_no
                    except:
                        pass

                    if current_page not in processed_table_pages:
                        page_img = None
                        try:
                            absolute_page = batch_start_page + current_page

                            page_img = render_page_to_image(pdf_path, absolute_page)

                            table_boxes = detect_tables(page_img)
                            for bbox in table_boxes:
                                crop = crop_table(page_img, bbox)
                                try:
                                    words, raw_ocr = read_ocr_words(crop)
                                    if len(words) < 3:
                                        continue
                                    tsr_html, coverage = extract_with_tsr(
                                        crop, words, raw_ocr
                                    )
                                    if not tsr_html:
                                        print(
                                            f"[TSR FAILED] "
                                            f"page={current_page} "
                                            f"bbox={bbox} "
                                            f"words={len(words)} "
                                            f"coverage={coverage:.2f}"
                                        )
                                        continue

                                finally:
                                    if os.path.exists(crop):
                                        try:
                                            os.remove(crop)
                                        except:
                                            pass
                                if tsr_html and coverage >= MIN_TSR_WORD_COVERAGE:
                                    final_html = tsr_html
                                else:
                                    if len(words) == 0:
                                        continue
                                    final_html, _ = extract_with_ocr_layout(words)

                                table_text, tokens = tsr_html_to_chunk_text(final_html)
                                table_chunks = chunk_table_text(
                                    table_text, max_tokens=350
                                )

                                for chunk in table_chunks:
                                    all_chunks.append(
                                        {
                                            "id": str(uuid.uuid4()),
                                            "doc_id": doc_id,
                                            "source_pdf": source_pdf,
                                            "page": current_page,
                                            "type": "table",
                                            "section": current_section,
                                            "content": chunk,
                                            "metadata": {
                                                "chunk_index": global_chunk_index,
                                                "token_count": token_count(chunk),
                                                "tsr_tokens": tokens,
                                                "bbox": bbox,
                                            },
                                        }
                                    )

                                    global_chunk_index += 1
                        finally:
                            if page_img and os.path.exists(page_img):
                                try:
                                    os.remove(page_img)
                                except PermissionError:
                                    pass
                        processed_table_pages.add(current_page)

                    if is_heading_item(item):
                        heading = clean_text(getattr(item, "text", ""))

                        if heading:
                            if buffer_text:
                                global_chunk_index = flush_text_chunks(
                                    buffer_text,
                                    doc_id,
                                    source_pdf,
                                    current_page,
                                    current_section,
                                    all_chunks,
                                    global_chunk_index,
                                )

                                buffer_text = []

                            while len(section_stack) > level:
                                section_stack.pop()

                            section_stack.append(heading)

                            current_section = " > ".join(section_stack)

                        continue

                    # TEXT
                    if hasattr(item, "text"):
                        text = clean_text(item.text)

                        if text:
                            buffer_text.append(text)

                except Exception:
                    traceback.print_exc()

            if buffer_text:
                global_chunk_index = flush_text_chunks(
                    buffer_text,
                    doc_id,
                    source_pdf,
                    current_page,
                    current_section,
                    all_chunks,
                    global_chunk_index,
                )

        except Exception:
            traceback.print_exc()

        finally:
            if os.path.exists(batch_file):
                os.remove(batch_file)

    print(f"Total chunks: {len(all_chunks)}")

    return {"doc_id": doc_id, "source_pdf": source_pdf, "chunks": all_chunks}


# TEXT FLUSH (TOKEN BASED + ROUTING)
def flush_text_chunks(
    buffer_text,
    doc_id,
    source_pdf,
    page,
    section,
    all_chunks,
    global_index,
):

    if not buffer_text:
        return global_index

    chunks = chunk_by_tokens(buffer_text)

    for local_idx, chunk in enumerate(chunks):
        all_chunks.append(
            {
                "id": str(uuid.uuid4()),
                "doc_id": doc_id,
                "source_pdf": source_pdf,
                "page": page,
                "type": "text",
                "section": section,
                "content": chunk,
                "metadata": {
                    "chunk_index": global_index + local_idx,
                    "local_index": local_idx,
                    "token_count": token_count(chunk),
                },
            }
        )

    return global_index + len(chunks)


def save_jsonl(result, output_path):

    with open(output_path, "w", encoding="utf-8") as f:
        for chunk in result["chunks"]:
            f.write(json.dumps(chunk, ensure_ascii=False) + "\n")

    print(f"Saved: {output_path}")


def preview_chunks(result, n=5):

    print("\n")
    print("=" * 80)
    print("EXTRACTION PREVIEW")
    print("=" * 80)

    for i, chunk in enumerate(result["chunks"][:n]):
        print(f"\nChunk {i + 1}")

        print(f"Page: {chunk['page']}")

        print(f"Type: {chunk['type']}")

        print(f"Tokens: {chunk['metadata']['token_count']}")

        print(chunk["content"][:300])

        print("-" * 80)


# if __name__ == "__main__":
#     PDF_PATH = r"C:\Users\asus\OneDrive\Documents\docs\ocr_sample.pdf"

#     OUTPUT = "ocr_sample.jsonl"

#     result = process_pdf(PDF_PATH, batch_size=2)

#     preview_chunks(result, n=10)

#     save_jsonl(result, OUTPUT)

#     print("\nDONE")
