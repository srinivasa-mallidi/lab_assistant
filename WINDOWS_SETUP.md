# LabAssist AI — Windows Installation Guide

## Prerequisites Checklist

| Tool | Version | Download |
|------|---------|----------|
| Python | 3.10 or 3.11 | https://python.org/downloads |
| Ollama | Latest | https://ollama.com/download/OllamaSetup.exe |
| Git | Latest | https://git-scm.com (optional) |

> ⚠️ **Python 3.10 detected** — all packages are compatible. Python 3.12+ may have issues with some packages.

---

## Step 1 — Fix: Install Dependencies

The `requirements.txt` has been updated to fix the `langchain-core` version conflict.
The issue was: `langchain-community==0.3.7` needs `langchain-core>=0.3.17`, but the original file pinned `==0.3.15`.

**Run this in your activated virtual environment:**

```powershell
# Make sure you're in the lab_assistant folder with venv activated
# (srienv) S:\WorkSpace\claude\lab_assistant_v1\lab_assistant>

# Upgrade pip first (recommended)
python.exe -m pip install --upgrade pip

# Install with the FIXED requirements.txt
pip install -r requirements.txt
```

If torch download is slow (it's 200MB), you can install it separately first:
```powershell
# Optional: Install torch first from PyTorch CDN (faster)
pip install torch==2.4.1 --index-url https://download.pytorch.org/whl/cpu

# Then install the rest
pip install -r requirements.txt
```

---

## Step 2 — Install Ollama

Ollama is a separate application, **not** a pip package. Install it like a normal Windows program:

### Option A: Download Installer (Recommended)
1. Go to **https://ollama.com/download**
2. Click **"Download for Windows"** → runs as `OllamaSetup.exe`
3. Install it (it runs as a background Windows service automatically)
4. Open a **new** PowerShell/CMD window after install

### Option B: Via winget (Windows 11)
```powershell
winget install Ollama.Ollama
```

### Verify Ollama is running:
```powershell
# In a NEW terminal after installing:
ollama --version

# You should see something like: ollama version 0.5.x
```

### Pull the LLM model:
```powershell
# Pull Llama3 (4.7 GB download - recommended)
ollama pull llama3

# OR smaller/faster alternatives:
ollama pull mistral          # 4.1 GB
ollama pull qwen2:7b         # 4.4 GB
ollama pull deepseek-r1:8b   # 4.9 GB

# Verify model is available:
ollama list
```

> 💡 **While the model downloads**, continue with Steps 3-4 — they don't need Ollama yet.

---

## Step 3 — Create Required Directories

```powershell
# From inside lab_assistant\ folder:
mkdir db
mkdir data\uploads\documents
mkdir data\chroma_db
mkdir data\faiss_index
mkdir logs
mkdir staticfiles
```

---

## Step 4 — Create .env Configuration

Create a file named `.env` in the `lab_assistant\` folder:

```powershell
# Create .env file
notepad .env
```

Paste this content (edit as needed):

```env
DJANGO_SECRET_KEY=change-this-to-a-long-random-string-at-least-50-chars
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1

# Ollama settings
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3

# Vector store (chroma = default, no extra setup needed)
VECTOR_STORE_TYPE=chroma
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2

# SampleManager LIMS database (fill in your details)
LIMS_DB_ENGINE=mssql
LIMS_DB_HOST=YOUR_LIMS_SERVER
LIMS_DB_PORT=1433
LIMS_DB_NAME=SAMPLEMANAGER
LIMS_DB_USER=lims_readonly
LIMS_DB_PASSWORD=YOUR_PASSWORD
```

---

## Step 5 — Initialize Database & Create Admin User

```powershell
# Run Django migrations (creates SQLite database)
python manage.py makemigrations
python manage.py migrate

# Create admin user
python manage.py createsuperuser
# Enter: username, email, password when prompted

# Collect static files
python manage.py collectstatic --noinput
```

---

## Step 6 — Start the Server

```powershell
# Option A: Standard Django server (HTTP only, no WebSocket)
python manage.py runserver

# Option B: Daphne ASGI server (HTTP + WebSocket streaming - RECOMMENDED)
daphne -b 127.0.0.1 -p 8000 config.asgi:application
```

Open your browser: **http://localhost:8000**

---

## Step 7 — Upload Your First Document

1. Log in at http://localhost:8000/login/
2. Click the 📖 **Knowledge Base** icon (top right)
3. Select document type (SOP, Training Manual, etc.)
4. Drag & drop or click to upload a PDF/DOCX

---

## Troubleshooting

### "ollama is not recognized"
- Ollama is not installed, or the terminal was opened before Ollama was installed
- Fix: Install from https://ollama.com/download, then **open a NEW terminal**

### "langchain-core conflict"
- Use the updated `requirements.txt` (already fixed above)
- Run: `pip install -r requirements.txt --upgrade`

### "No module named 'apps.chat'"
- You're running `python manage.py` from the wrong folder
- Fix: Make sure you're in `lab_assistant\` (the folder containing `manage.py`)

### Torch download is too slow
```powershell
pip install torch==2.4.1 --index-url https://download.pytorch.org/whl/cpu
```

### ChromaDB SQLite error on Windows
```powershell
pip install pysqlite3-binary
```
Then add to top of `config/settings.py`:
```python
__import__('pysqlite3')
import sys
sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')
```

### ODBC Driver not found (SQL Server)
Download: https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server
Install "ODBC Driver 17 for SQL Server" or 18

---

## Folder Structure After Setup

```
lab_assistant\
├── .env                  ← Your configuration
├── manage.py
├── db\
│   └── lab_assistant.sqlite3   ← Created after migrate
├── data\
│   ├── uploads\          ← Uploaded documents stored here
│   └── chroma_db\        ← Vector store (auto-created)
├── logs\
│   ├── app.log
│   ├── audit.log
│   └── security.log
└── ...
```

---

## Quick Reference Commands

```powershell
# Activate venv (run from lab_assistant_v1 folder)
.\srienv\Scripts\activate

# Start server
cd lab_assistant
daphne -b 127.0.0.1 -p 8000 config.asgi:application

# Check Ollama models
ollama list

# Ingest documents via CLI
python manage.py ingest_documents --dir C:\path\to\sop_docs --type sop

# Run tests
pytest tests/unit/ -v

# View logs
type logs\app.log
type logs\security.log
```
