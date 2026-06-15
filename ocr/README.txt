local/ocr — Document processing for Moda chatbot
================================================

See FLOW.txt for end-to-end behaviour and integration points.

Quick start (OCR developers):
  - Implement or extend modules in this folder.
  - Keep chatbot imports going through local/chatbot/rag_service/integrations/ocr_client.py.
  - Do not import chatbot/rag_service from ocr (one-way dependency).

Dependencies (install in chatbot venv or a dedicated ocr venv):
  pypdf, pymupdf (fitz), python-docx, python-pptx, openpyxl

Chatbot loads this package via bootstrap.py (adds parent `local/` to sys.path).
