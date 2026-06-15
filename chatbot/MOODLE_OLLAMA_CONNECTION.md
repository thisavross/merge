# Koneksi Moodle → Ollama (local_chatbot)

Moodle **tidak** memanggil Ollama langsung. Ada 2 lompatan:

```
Browser (popup.js)
    → Moodle PHP (externallib.php + fastapi_client.php)
    → FastAPI RAG (main.py)
    → Ollama (ollama_http.py)
```

---

## Cara connect FastAPI ke PHP (Moodle) — step by step

PHP dan FastAPI **tidak di-link lewat library**. Koneksinya = **HTTP REST**: PHP kirim JSON, FastAPI balas JSON.

### Langkah 1 — Jalankan FastAPI

```bash
cd local/chatbot/rag_service
source .venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8787
```

Pastikan bisa diakses: `curl http://127.0.0.1:8787/health`

Endpoint yang dipakai Moodle:

| Method | URL | Dipanggil dari |
|--------|-----|----------------|
| POST | `/chat` | `fastapi_client.php` |
| POST | `/quiz/pdf` | `quiz_pdf.php` |

Definisi endpoint FastAPI: `rag_service/main.py` → `@app.post("/chat")`

### Langkah 2 — Set URL di Moodle (admin)

File: `local/chatbot/settings.php`

Di Moodle UI: **Site administration → Plugins → Local plugins → Moodle AI chatbot**

| Field admin | Disimpan sebagai | Nilai contoh |
|-------------|------------------|--------------|
| FastAPI base URL | `local_chatbot/fastapiurl` | `http://127.0.0.1:8787` |
| Shared secret | `local_chatbot/fastapisecret` | kosong atau sama dengan `.env` |

PHP baca URL di sini (`fastapi_client.php` baris 56–66):

```php
$base = trim((string)get_config('local_chatbot', 'fastapiurl'));
$url = rtrim($base, '/') . '/chat';   // → http://127.0.0.1:8787/chat
```

### Langkah 3 — (Opsional) Secret harus sama

**Moodle** kirim header:

```php
$curl->setHeader('X-Chatbot-Secret: ' . $secret);
```

**FastAPI** cek di `main.py`:

```python
if settings.chatbot_secret and (x_chatbot_secret or "") != settings.chatbot_secret:
    raise HTTPException(status_code=401, ...)
```

Set di:

- Moodle admin → Shared secret
- `rag_service/.env` → `CHATBOT_SECRET=nilai_sama`

Kalau kosong di kedua sisi → tidak perlu header.

### Langkah 4 — Alur PHP memanggil FastAPI

```
popup.js
  Ajax.call({ methodname: 'local_chatbot_send_message', args: {...} })
       ↓
db/services.php          (daftar webservice)
       ↓
externallib.php        send_message()
       ↓
fastapi_client.php     send_chat()  ← SATU-SATUNYA file HTTP ke FastAPI
       ↓
POST http://127.0.0.1:8787/chat
       ↓
main.py                chat()
```

**File PHP yang connect ke FastAPI:**

| # | File | Peran |
|---|------|--------|
| 1 | `db/services.php` | Register webservice `local_chatbot_send_message` |
| 2 | `externallib.php` | `send_message()` — siapkan `course_id`, `user_id`, lalu panggil client |
| 3 | **`classes/fastapi_client.php`** | **`curl->post($url, $json)`** — koneksi HTTP |

Cuplikan pemanggilan (`externallib.php`):

```php
$result = \local_chatbot\fastapi_client::send_chat(
    $message,
    $ragcourseid,
    (int) $USER->id,
    $attachments,
    self::page_course_context($courseid),
    $CFG->wwwroot,
    $pending_quiz_json,
    $quiz_mode,
    $roomid,
    current_language() === 'en' ? 'en' : 'id'
);
```

### Langkah 5 — JSON request (PHP → FastAPI)

PHP kirim (`fastapi_client.php`):

```json
{
  "question": "summarize this course",
  "course_id": 4,
  "page_course_id": 0,
  "user_id": 123,
  "room_id": 1,
  "language": "id",
  "moodle_wwwroot": "http://localhost/moodle500",
  "attachments": [],
  "pending_quiz_json": "",
  "force_quiz": false
}
```

FastAPI terima lewat model `ChatRequest` di `main.py` — field harus sama nama/key-nya.

### Langkah 6 — JSON response (FastAPI → PHP)

FastAPI balas (`main.py` → `ChatResponse`):

```json
{
  "reply": "teks jawaban bot",
  "error": null,
  "quiz_json": "",
  "quiz_ready_for_pdf": false
}
```

PHP parse (`fastapi_client.php`):

```php
$data = json_decode($response, true);
$reply = (string)($data['reply'] ?? '');
```

Lalu `externallib.php` return ke `popup.js` → `data.reply` ditampilkan di chat.

### Langkah 7 — Test tanpa Moodle UI

Sama seperti yang PHP kirim:

```bash
curl -X POST http://127.0.0.1:8787/chat \
  -H "Content-Type: application/json" \
  -H "X-Chatbot-Secret: rahasia_kamu" \
  -d '{"question":"halo","course_id":4,"user_id":1,"language":"id"}'
```

Kalau curl OK tapi Moodle error → masalah di URL admin, firewall, atau timeout PHP (sudah 300s di `fastapi_client.php`).

### Troubleshooting PHP ↔ FastAPI

| Gejala | Cek |
|--------|-----|
| "FastAPI URL is not configured" | Isi `fastapiurl` di admin Moodle |
| "Could not reach the FastAPI service" | `uvicorn` jalan? URL benar? `127.0.0.1` vs `localhost` |
| HTTP 401 | `fastapisecret` Moodle ≠ `CHATBOT_SECRET` `.env` |
| Invalid response | FastAPI crash? Lihat log terminal uvicorn |

**Tidak ada file PHP lain yang wajib diubah** untuk connect dasar — cukup `settings.php` (admin) + `fastapi_client.php` (sudah ada) + FastAPI `main.py` jalan.

---

## 1. Moodle → FastAPI

| File | Path | Fungsi |
|------|------|--------|
| UI chat | `amd/src/popup.js` | Kirim pesan via Ajax `local_chatbot_send_message` |
| Webservice | `externallib.php` | `send_message()` → panggil FastAPI, simpan reply ke DB |
| **HTTP client** | **`classes/fastapi_client.php`** | **POST `{fastapiurl}/chat`** — file koneksi utama Moodle ke backend |
| Admin URL | `settings.php` | Set `fastapiurl` (default `http://127.0.0.1:8787`) |
| PDF quiz | `quiz_pdf.php` | POST `{fastapiurl}/quiz/pdf` |

**Config Moodle:** Site administration → Plugins → Local plugins → Moodle AI chatbot

- **FastAPI base URL** → `get_config('local_chatbot', 'fastapiurl')`
- **Shared secret** (opsional) → header `X-Chatbot-Secret`

Payload yang dikirim Moodle (`fastapi_client.php`):

```json
{
  "question": "...",
  "course_id": 4,
  "user_id": 123,
  "room_id": 1,
  "language": "id",
  "force_quiz": false,
  "attachments": []
}
```

---

## 2. FastAPI → Ollama

| File | Path | Fungsi |
|------|------|--------|
| API entry | `rag_service/main.py` | `POST /chat` → routing chat / quiz / summarize |
| Config | `rag_service/config.py` | Baca env Ollama, MySQL, Chroma |
| Env | **`rag_service/.env`** | **`OLLAMA_BASE_URL`**, **`OLLAMA_CHAT_MODEL`**, dll. |
| **Ollama client** | **`rag_service/ollama_http.py`** | **Satu-satunya file yang HTTP ke Ollama** |
| RAG chat | `rag_service/rag_engine.py` | Embed + Chroma + `chat_completion()` |
| Summarize | `rag_service/course_summarize.py` | Ringkasan kursus |
| Quiz | `rag_service/quiz_engine.py` | Generate kuis |
| Course DB | `rag_service/moodle_course.py` | Baca materi dari MySQL Moodle |

**Endpoint Ollama yang dipanggil** (`ollama_http.py`):

- `POST {OLLAMA_BASE_URL}/api/chat` — jawaban LLM
- `POST {OLLAMA_BASE_URL}/api/embed` — embedding (Chroma / semantic cache)

---

## 3. Service yang harus jalan

```bash
# Terminal 1 — Ollama
ollama serve
# → http://127.0.0.1:11434

# Terminal 2 — RAG / FastAPI
cd local/chatbot/rag_service
source .venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8787
# → http://127.0.0.1:8787

# Terminal 3 — Moodle (MAMP)
# → http://localhost/moodle500 (atau wwwroot kamu)
```

---

## 4. Setting yang harus cocok

### Moodle (`settings.php` / admin UI)

| Setting | Contoh |
|---------|--------|
| FastAPI URL | `http://127.0.0.1:8787` |
| Shared secret | Sama dengan `CHATBOT_SECRET` di `.env` (kalau dipakai) |

### RAG (`rag_service/.env`)

```env
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_CHAT_MODEL=qwen3_q4km:latest
OLLAMA_EMBED_MODEL=bge-m3
OLLAMA_CHAT_NUM_CTX=16384

MYSQL_DATABASE=moodle500
MYSQL_PREFIX=mdl_
MOODLE_DATAROOT=/Applications/MAMP/data/moodle500

CHATBOT_SECRET=          # opsional, sama Moodle
```

---

## 5. Cek koneksi

```bash
# Ollama
curl http://127.0.0.1:11434/api/tags

# FastAPI
curl http://127.0.0.1:8787/health

# Full chain (tanpa Moodle UI)
curl -X POST http://127.0.0.1:8787/chat \
  -H "Content-Type: application/json" \
  -d '{"question":"halo","course_id":4,"user_id":1,"language":"id"}'
```

---

## 6. Urutan eksekusi (1 pesan chat)

1. `popup.js` → `local_chatbot_send_message`
2. `externallib.php::send_message()` → `fastapi_client::send_chat()`
3. `fastapi_client.php` → HTTP POST `http://127.0.0.1:8787/chat`
4. `main.py::chat()` → `answer_question()` / quiz / summarize
5. `rag_engine.py` (atau modul lain) → `ollama_http.chat_completion()` / `get_embedding()`
6. `ollama_http.py` → `http://127.0.0.1:11434/api/chat`
7. Response balik ke Moodle → `data.reply` di UI

---

## File inti (copy-paste path)

```
local/chatbot/
├── amd/src/popup.js              # UI → webservice
├── externallib.php               # webservice → fastapi_client
├── classes/fastapi_client.php    # ★ Moodle → FastAPI
├── settings.php                  # URL FastAPI di admin
└── rag_service/
    ├── .env                      # ★ URL/model Ollama + MySQL
    ├── main.py                   # FastAPI router
    ├── ollama_http.py            # ★ FastAPI → Ollama
    ├── config.py                 # load .env
    ├── rag_engine.py             # chat RAG
    ├── course_summarize.py       # summarize
    └── quiz_engine.py            # quiz
```

**★ = titik koneksi utama ke layer berikutnya**
