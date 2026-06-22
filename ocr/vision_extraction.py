# import subprocess
# import sys
# import time
# import requests
# from ollama import Client
# import os

# OLLAMA_HOST = "http://127.0.0.1:11434"
# QWEN_MODEL = "qwen25vl-ai2d-vision"


# def ensure_ollama_running() -> bool:
#     """Ensures Ollama server is running. Returns True if ready."""
#     try:
#         requests.get(OLLAMA_HOST, timeout=2)
#         return True
#     except Exception:
#         print("Starting Ollama...")
#         try:
#             if sys.platform == "win32":
#                 subprocess.Popen(
#                     ["ollama", "serve"],
#                     stdout=subprocess.DEVNULL,
#                     stderr=subprocess.DEVNULL,
#                     creationflags=subprocess.CREATE_NO_WINDOW,
#                 )
#             else:
#                 subprocess.Popen(
#                     ["ollama", "serve"],
#                     stdout=subprocess.DEVNULL,
#                     stderr=subprocess.DEVNULL,
#                     start_new_session=True,
#                 )

#             for i in range(30):
#                 time.sleep(1)
#                 try:
#                     requests.get(OLLAMA_HOST, timeout=2)
#                     print("Ollama started successfully")
#                     return True
#                 except Exception:
#                     if i % 5 == 0:
#                         print(f"Waiting for Ollama... ({i + 1}s)")

#             print("Failed to start Ollama within 30s")
#             return False

#         except Exception as e:
#             print(f"Error starting Ollama: {e}")
#             return False


# def get_client() -> Client:
#     """Returns a cached Ollama client, starting the server if needed."""
#     global _ollama_client
#     if _ollama_client is None:
#         if not ensure_ollama_running():
#             raise RuntimeError("Ollama server is not available")
#         _ollama_client = Client(host=OLLAMA_HOST)
#     return _ollama_client


# _TABLE_PROMPT = """You are a Table Structure Recognition model.

# Extract the table from the image.

# Return ONLY a markdown table, nothing else — no explanation, no preamble, no code block fences.

# Rules:
# - Preserve original row and column structure exactly
# - Preserve headers exactly as shown
# - Merge cell content with a space if cells are visually merged (rowspan/colspan)
# - Preserve all numbers exactly as shown
# - Every row must have the same number of columns as the header"""


# def extract_with_qwenvl(crop_path: str) -> str | None:
#     """
#     Send a cropped table image to QwenVL and return a markdown table string.
#     Returns None if extraction fails or the response is empty.
#     """
#     if not os.path.exists(crop_path):
#         print(f"[QwenVL] Image not found: {crop_path}")
#         return None

#     try:
#         client = get_client()
#         response = client.chat(
#             model=QWEN_MODEL,
#             messages=[
#                 {
#                     "role": "user",
#                     "content": _TABLE_PROMPT,
#                     "images": [crop_path],
#                 }
#             ],
#             options={"temperature": 0},
#         )
#         markdown = response["message"]["content"].strip()

#         # Strip accidental code fences the model sometimes adds
#         if markdown.startswith("```"):
#             lines = markdown.splitlines()
#             # Drop first and last fence lines
#             lines = [l for l in lines if not l.strip().startswith("```")]
#             markdown = "\n".join(lines).strip()

#         if not markdown or "|" not in markdown:
#             print(f"[QwenVL] Empty or non-table response for {crop_path}")
#             return None

#         return markdown

#     except Exception as e:
#         print(f"[QwenVL] Error processing {crop_path}: {e}")
#         return None


# def markdown_table_to_text(markdown: str) -> str:
#     """
#     Convert a markdown table into pipe-delimited plain text rows
#     (one row per line, separator rows stripped).

#     Example:
#         | A | B |        ->  A | B
#         |---|---|            foo | bar
#         | foo | bar |
#     """
#     lines = []
#     for line in markdown.splitlines():
#         stripped = line.strip()
#         if not stripped:
#             continue
#         # Skip separator rows like |---|:---|---:|
#         if all(c in "-|: " for c in stripped):
#             continue
#         # Strip leading/trailing pipes and extra whitespace per cell
#         cells = [c.strip() for c in stripped.strip("|").split("|")]
#         row_text = " | ".join(c for c in cells if c)
#         if row_text:
#             lines.append(row_text)
#     return "\n".join(lines)

import os
import subprocess
import sys
import time
from urllib.parse import urlparse

import requests
from ollama import Client


def _ollama_base_url() -> str:
    return (
        os.getenv("OLLAMA_BASE_URL")
        or os.getenv("OLLAMA_HOST")
        or "http://127.0.0.1:11434"
    ).rstrip("/")


def _vision_model_name() -> str:
    return (
        os.getenv("OLLAMA_EXTRACT_VISION_MODEL")
        or os.getenv("OLLAMA_VISION_MODEL")
        or "qwen25vl-ai2d-vision"
    )


def _is_local_ollama_host(base_url: str) -> bool:
    hostname = (urlparse(base_url).hostname or "").lower()
    return hostname in {"127.0.0.1", "localhost", "::1"}


_ollama_client: Client | None = None
_ollama_client_host: str | None = None


# ============================================================
# Ollama management
# ============================================================


def ensure_ollama_running() -> bool:
    base_url = _ollama_base_url()

    try:
        requests.get(base_url, timeout=2)
        return True
    except Exception:
        if not _is_local_ollama_host(base_url):
            print(f"[Vision] Remote Ollama not reachable at {base_url}")
            return False

        print("Starting Ollama...")

        try:
            if sys.platform == "win32":
                subprocess.Popen(
                    ["ollama", "serve"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )

            else:
                subprocess.Popen(
                    ["ollama", "serve"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )

            for i in range(30):
                time.sleep(1)

                try:
                    requests.get(base_url, timeout=2)

                    print("Ollama started")

                    return True

                except Exception:
                    if i % 5 == 0:
                        print(f"Waiting Ollama {i + 1}s")

            return False

        except Exception as e:
            print(f"Ollama error: {e}")

            return False


def get_client() -> Client:
    global _ollama_client, _ollama_client_host

    base_url = _ollama_base_url()
    if _ollama_client is None or _ollama_client_host != base_url:
        if not ensure_ollama_running():
            raise RuntimeError("Ollama unavailable")

        _ollama_client = Client(host=base_url)
        _ollama_client_host = base_url

    return _ollama_client


VISION_TABLE_PROMPT = """
You are a Table Structure Recognition model.

Extract the table from the image.

Return ONLY markdown table format.

Rules:
- Preserve original row and column structure
- Preserve headers exactly
- Preserve numbers exactly
- Handle merged cells
- Do not add explanation
- Do not use code fences
"""


VISION_DOCUMENT_PROMPT = """
You are a document understanding model.

Extract information from this image.

Tasks:
- OCR all visible text
- Preserve headings
- Preserve paragraphs
- Preserve lists
- Convert tables into markdown
- Explain diagrams, charts, and figures
- Keep original meaning
- Do not hallucinate missing information

Return only extracted content.
"""


VISION_EXPLAIN_PROMPT = """
Analyze this image.

Describe:
- objects
- text
- charts
- diagrams
- important visual information

Return a detailed explanation.
"""



def extract_with_qwenvl(
    image_path: str, task: str = "table", num_ctx: int = 8192
) -> str | None:
    """
    Unified QwenVL extraction.

    task:
        table
        document
        explain

    num_ctx:
        Context window passed to Ollama. Large rendered images (full pages,
        especially at high render scale) can exceed the model's default
        context window (commonly 4096), causing a 400 "exceed_context_size_error".
        8192 gives headroom; raise further if you still hit that error on
        large/high-DPI pages, or lower the image render scale on the caller side.
    """

    if not os.path.exists(image_path):
        print(f"[Vision] Image not found {image_path}")

        return None

    prompts = {
        "table": VISION_TABLE_PROMPT,
        "document": VISION_DOCUMENT_PROMPT,
        "explain": VISION_EXPLAIN_PROMPT,
    }

    prompt = prompts.get(task, VISION_DOCUMENT_PROMPT)

    try:
        client = get_client()

        response = client.chat(
            model=_vision_model_name(),
            messages=[{"role": "user", "content": prompt, "images": [image_path]}],
            options={"temperature": 0, "num_ctx": num_ctx},
        )

        result = response["message"]["content"].strip()

        if not result:
            return None

        # remove markdown fence
        if result.startswith("```"):
            lines = result.splitlines()

            lines = [x for x in lines if not x.strip().startswith("```")]

            result = "\n".join(lines).strip()

        return result

    except Exception as e:
        print(f"[Vision] error: {e}")

        return None

def markdown_table_to_text(markdown: str) -> str:

    lines = []

    for line in markdown.splitlines():
        line = line.strip()

        if not line:
            continue

        # remove markdown separator
        if all(c in "-|: " for c in line):
            continue

        cells = [c.strip() for c in line.strip("|").split("|")]

        row = " | ".join(c for c in cells if c)

        if row:
            lines.append(row)

    return "\n".join(lines)