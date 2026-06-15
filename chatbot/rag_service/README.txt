Moodle Chatbot — FastAPI RAG service
====================================

Flow: Moodle plugin POSTs JSON { question, course_id, user_id? } to /chat
      → load course text from the same MySQL DB as Moodle (phpMyAdmin)
      → chunk → Ollama embeddings → FAISS (IndexFlatIP, cosine via normalized vectors)
      → build prompt with top-k chunks → Ollama chat → JSON { reply } or { error }

Setup
-----
1. Create a Python 3.11+ venv in this folder and install:
   pip install -r requirements.txt

2. Copy .env.example to .env and set MYSQL_* to match your MAMP Moodle database
   (same credentials you use in Moodle config.php).

3. Pull Ollama models (examples):
   ollama pull nomic-embed-text
   ollama pull llama3.2

4. Start the API:
   uvicorn main:app --host 0.0.0.0 --port 8787

5. In Moodle: Site administration → Plugins → Local plugins → Course AI chatbot
   Set FastAPI base URL to http://127.0.0.1:8787 (or your host)
   Optionally set the shared secret to match CHATBOT_SECRET in .env.

Security
--------
- Use CHATBOT_SECRET in .env and the same value in Moodle (X-Chatbot-Secret).
- Do not expose the FastAPI port to the public internet without a reverse proxy and TLS.
