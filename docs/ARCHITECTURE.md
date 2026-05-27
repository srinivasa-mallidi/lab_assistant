# LabAssist AI — Complete Architecture & Implementation Guide

## Executive Summary

LabAssist AI is a **modular monolithic** Django application that provides an AI-powered chatbot for SampleManager LIMS environments. It combines **Retrieval-Augmented Generation (RAG)** for document knowledge with **Natural Language to SQL** for live LIMS data queries, all powered by local Ollama models.

---

## 1. Project Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     LabAssist AI (Django)                        │
│                                                                  │
│  ┌──────────┐   ┌──────────────┐   ┌────────────────────────┐  │
│  │ Frontend │   │ REST API     │   │ WebSocket (Channels)   │  │
│  │ HTML/CSS │◄──│ DRF Views    │◄──│ AsyncWebsocketConsumer │  │
│  │ Vanilla  │   │ JWT Auth     │   │ Streaming responses    │  │
│  └──────────┘   └──────┬───────┘   └────────────┬───────────┘  │
│                         │                         │              │
│  ┌─────────────────────▼─────────────────────────▼───────────┐ │
│  │                  Orchestrator Agent                         │ │
│  │   1. Security Check  2. Intent Classification  3. Route    │ │
│  └──────────┬───────────────┬───────────────────┬────────────┘ │
│             │               │                   │              │
│  ┌──────────▼──┐   ┌────────▼────────┐  ┌──────▼──────────┐  │
│  │  Document   │   │  Database       │  │  Security       │  │
│  │  Agent      │   │  Agent          │  │  Agent          │  │
│  │  RAG/Search │   │  NL→SQL→Execute │  │  Injection Det. │  │
│  └──────┬──────┘   └────────┬────────┘  └─────────────────┘  │
│         │                   │                                  │
│  ┌──────▼──────┐   ┌────────▼────────┐                        │
│  │ ChromaDB /  │   │ SampleManager   │                        │
│  │ FAISS       │   │ LIMS (RO)       │                        │
│  │ Vector Store│   │ SQL Server/ORA  │                        │
│  └─────────────┘   └─────────────────┘                        │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              Ollama (Local LLM)                           │  │
│  │   llama3 · mistral · qwen · deepseek (your choice)       │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Folder Structure

```
lab_assistant/
├── config/                     # Django project configuration
│   ├── settings.py             # All settings with env variable support
│   ├── urls.py                 # Root URL routing
│   ├── asgi.py                 # ASGI (WebSocket + HTTP)
│   └── wsgi.py                 # WSGI (traditional HTTP)
│
├── apps/
│   ├── chat/                   # Chat sessions & messages
│   │   ├── models.py           # ChatSession, Message, Feedback, Memory
│   │   ├── consumers.py        # WebSocket async consumer
│   │   ├── routing.py          # WebSocket URL patterns
│   │   ├── urls.py             # HTTP URL patterns
│   │   └── frontend_views.py   # Login/index views
│   │
│   ├── agents/                 # AI Agent implementations
│   │   ├── orchestrator.py     # Central routing + synthesis
│   │   ├── document_agent.py   # RAG retrieval
│   │   ├── database_agent.py   # NL→SQL + LIMS execution
│   │   └── security_agent.py   # Injection detection + RBAC
│   │
│   ├── documents/              # Document management
│   │   ├── models.py           # Document tracking model
│   │   └── management/
│   │       └── commands/
│   │           └── ingest_documents.py  # Batch ingestion CLI
│   │
│   ├── security/               # Security middleware
│   │   └── middleware.py       # AuditLog + PromptInjection
│   │
│   └── api/                    # REST API layer
│       ├── views.py            # All API endpoints
│       └── urls.py             # API URL routing
│
├── frontend/
│   ├── templates/
│   │   ├── index.html          # ChatGPT-style SPA
│   │   └── login.html          # Login page
│   └── static/
│       ├── css/
│       ├── js/
│       └── fonts/
│
├── data/
│   ├── uploads/                # Uploaded documents
│   ├── chroma_db/              # ChromaDB vector store
│   └── faiss_index/            # FAISS index (alternative)
│
├── logs/
│   ├── app.log                 # Application logs
│   ├── audit.log               # Compliance audit trail
│   └── security.log            # Security events
│
├── tests/
│   ├── unit/                   # Unit tests
│   └── integration/            # Integration tests
│
├── scripts/
│   └── setup.py                # Initial setup script
│
├── db/
│   └── lab_assistant.sqlite3   # SQLite (dev) / migrate to PG (prod)
│
├── requirements.txt
├── manage.py
└── .env                        # Environment configuration
```

---

## 3. Database Schema Design

### Application Database (SQLite → PostgreSQL in prod)

```sql
-- Chat Sessions
CREATE TABLE chat_chatsession (
    id          UUID PRIMARY KEY,
    user_id     INT REFERENCES auth_user(id),
    title       VARCHAR(255),
    status      VARCHAR(20),    -- active | archived | deleted
    model_used  VARCHAR(50),
    created_at  TIMESTAMP,
    updated_at  TIMESTAMP,
    metadata    JSONB
);

-- Messages
CREATE TABLE chat_message (
    id              UUID PRIMARY KEY,
    session_id      UUID REFERENCES chat_chatsession(id),
    role            VARCHAR(20),   -- user | assistant | system
    content         TEXT,
    intent_type     VARCHAR(20),   -- knowledge | database | hybrid | general
    sources         JSONB,         -- RAG source citations
    sql_query       TEXT,          -- Generated SQL (audit)
    tokens_used     INT,
    response_time_ms INT,
    created_at      TIMESTAMP,
    metadata        JSONB
);

-- Documents
CREATE TABLE documents_document (
    id            UUID PRIMARY KEY,
    title         VARCHAR(255),
    file_name     VARCHAR(255),
    file_path     VARCHAR(1000),
    document_type VARCHAR(30),
    version       VARCHAR(50),
    status        VARCHAR(20),
    chunks_count  INT,
    file_size     BIGINT,
    uploaded_by   INT REFERENCES auth_user(id),
    created_at    TIMESTAMP
);
```

### SampleManager LIMS (Read-Only Access)

```
SAMPLES → TEST_RESULTS → APPROVALS
                         ANALYSTS
                         AUDIT_TRAIL
```
*(See apps/agents/database_agent.py for full schema context)*

---

## 4. RAG Pipeline Design

```
Document Upload
      │
      ▼
File Validation (type, size, content)
      │
      ▼
Document Loader
  ├── PDF    → PyPDFLoader / PyMuPDF
  ├── DOCX   → Docx2txtLoader
  ├── PPTX   → UnstructuredPowerPointLoader
  └── TXT/MD → TextFileLoader
      │
      ▼
Text Splitter (RecursiveCharacterTextSplitter)
  chunk_size=1000, overlap=200
      │
      ▼
Metadata Enrichment
  { source_file, title, document_type, page, doc_id }
      │
      ▼
Embedding Generation (sentence-transformers/all-MiniLM-L6-v2)
  768-dimensional vectors, normalized
      │
      ▼
Vector Store (ChromaDB or FAISS)
  ├── ChromaDB: persistent SQLite backend, collection="lab_documents"
  └── FAISS: flat index, saved to disk
      │
      ▼
─────────────────────────────────────────
           QUERY TIME
─────────────────────────────────────────
User Query → Embedding → Similarity Search
    │
    ├── top_k=5 results
    ├── similarity_threshold=0.3 filter
    └── Deduplicated sources
          │
          ▼
    Formatted context + citations
          │
          ▼
    LLM Synthesis (Ollama)
```

---

## 5. AI Agent Workflow

```
User Message
     │
     ▼
┌─────────────────────────────────────────────────────┐
│ SecurityAgent.check()                               │
│  ✓ Length check (≤2000 chars)                      │
│  ✓ Prompt injection patterns (15 regex)            │
│  ✓ Data exfiltration patterns                      │
│  ✓ RBAC check (role permissions)                   │
└──────────────────┬──────────────────────────────────┘
                   │ SAFE
                   ▼
┌─────────────────────────────────────────────────────┐
│ OrchestratorAgent.classify_intent()                 │
│  LLM call → JSON response                          │
│  → knowledge | database | hybrid | general         │
└──────────┬──────────────┬────────────────────────────┘
           │              │
    knowledge/hybrid  database/hybrid
           │              │
           ▼              ▼
  DocumentAgent     DatabaseAgent
  .retrieve()       .query()
  - Embed query     - NL→SQL (LLM)
  - ChromaDB/FAISS  - SQLSafetyValidator
  - Top-5 chunks    - Execute (RO)
  - Source refs     - Summarize results
           │              │
           └──────┬───────┘
                  │
                  ▼
     OrchestratorAgent (Synthesis)
     SYNTHESIS_PROMPT:
     - RAG context
     - DB results  
     - Chat history (last 6)
     - User role
                  │
                  ▼
           Final Response
           + sources + intent
```

---

## 6. API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/chat/` | Send message, get AI response |
| GET | `/api/v1/sessions/` | List user chat sessions |
| POST | `/api/v1/sessions/` | Create new session |
| GET | `/api/v1/history/{session_id}/` | Get chat history |
| POST | `/api/v1/documents/upload/` | Upload & ingest document |
| GET | `/api/v1/documents/` | List knowledge base docs |
| GET | `/api/v1/sources/` | Vector store statistics |
| POST | `/api/v1/feedback/` | Rate a response (👍/👎) |
| GET | `/api/v1/health/` | System health check |
| WS | `ws://host/ws/chat/` | WebSocket streaming |

---

## 7. Security Architecture

### Layers

1. **Django Authentication** — Session + JWT tokens
2. **Role-Based Access** — LAB_ANALYST, LAB_SUPERVISOR, LIMS_ADMIN, READ_ONLY
3. **PromptInjectionMiddleware** — 15 regex patterns, logs to security.log
4. **SecurityAgent** — Deep semantic check before every agent call
5. **SQLSafetyValidator** — Blocks all non-SELECT SQL (12 forbidden patterns)
6. **AuditLogMiddleware** — Logs every API call to audit.log
7. **Read-Only LIMS** — Database connection configured with readonly=True

### RBAC Matrix

| Permission | READ_ONLY | LAB_ANALYST | LAB_SUPERVISOR | LIMS_ADMIN |
|------------|-----------|-------------|----------------|------------|
| Chat (knowledge) | ✓ | ✓ | ✓ | ✓ |
| Chat (database) | ✗ | ✓ | ✓ | ✓ |
| Upload documents | ✗ | ✗ | ✓ | ✓ |
| Admin panel | ✗ | ✗ | ✗ | ✓ |

---

## 8. Step-by-Step Implementation Plan

### Phase 1: Foundation (Week 1–2)
```
1. Install dependencies: pip install -r requirements.txt
2. Configure .env (LIMS DB credentials, Ollama URL)
3. Run: python scripts/setup.py
4. Pull Ollama model: ollama pull llama3
5. Start server: daphne -p 8000 config.asgi:application
6. Verify health: GET /api/v1/health/
```

### Phase 2: Knowledge Base (Week 2–3)
```
7. Upload SOPs/manuals via UI or:
   python manage.py ingest_documents --dir ./sop_docs --type sop
8. Test RAG queries via chat UI
9. Tune chunk_size/overlap in settings.py
10. Evaluate citation accuracy
```

### Phase 3: LIMS Integration (Week 3–4)
```
11. Configure LIMS_DATABASE in .env
12. Grant read-only DB access to service account
13. Test NL→SQL generation with sample questions
14. Review generated SQL in audit.log
15. Tune SAMPLEMANAGER_SCHEMA in database_agent.py
```

### Phase 4: Security Hardening (Week 4–5)
```
16. Review security.log for false positives
17. Tune injection patterns if needed
18. Enable HTTPS (nginx reverse proxy)
19. Set DEBUG=False, update ALLOWED_HOSTS
20. Change SECRET_KEY to cryptographic random value
```

### Phase 5: Production (Week 5–6)
```
21. Switch to PostgreSQL (update DATABASES in settings.py)
22. Add Redis for channel layer (update CHANNEL_LAYERS)
23. Configure nginx + daphne as Windows service
24. Set up log rotation
25. Configure backup for ChromaDB/FAISS
```

---

## 9. Installation Quick Start (Windows)

```powershell
# Prerequisites
# - Python 3.11+: https://python.org
# - Ollama: https://ollama.ai
# - Git

# 1. Create virtual environment
python -m venv venv
venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Pull LLM model
ollama pull llama3

# 4. Run setup wizard
python scripts/setup.py

# 5. Start server
daphne -b 0.0.0.0 -p 8000 config.asgi:application

# Open browser: http://localhost:8000
```

---

## 10. Configuration Reference

```env
# .env file
DJANGO_SECRET_KEY=<random-64-char-string>
DEBUG=False                          # True for development only
ALLOWED_HOSTS=localhost,192.168.1.x

OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3                  # llama3 | mistral | qwen | deepseek

VECTOR_STORE_TYPE=chroma             # chroma | faiss
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2

LIMS_DB_ENGINE=mssql                 # mssql | oracle | postgresql
LIMS_DB_HOST=your-lims-server
LIMS_DB_PORT=1433
LIMS_DB_NAME=SAMPLEMANAGER
LIMS_DB_USER=lims_readonly
LIMS_DB_PASSWORD=your-password
```

---

## 11. LLM Model Selection Guide

| Model | Best For | RAM Required |
|-------|----------|-------------|
| llama3:8b | General Q&A + SQL | 8 GB |
| mistral:7b | Fast responses | 6 GB |
| qwen2:7b | Multilingual labs | 8 GB |
| deepseek-r1:8b | Complex reasoning, validation docs | 10 GB |

**Recommended for production:** `qwen2:7b` (fast) or `deepseek-r1:8b` (accurate)

---

## 12. Extending the System

### Add a New Agent
```python
# apps/agents/my_agent.py
class MyAgent:
    async def process(self, context: AgentContext) -> MyResult:
        ...

# Register in orchestrator.py
@property
def my_agent(self):
    if "my" not in self._agents:
        self._agents["my"] = MyAgent()
    return self._agents["my"]
```

### Add a New Document Type
```python
# In DocumentAgent._load_document():
elif suffix == ".xlsx":
    loader = UnstructuredExcelLoader(file_path)
```

### Add a New Database
```python
# In LIMSConnection._create_connection():
elif engine == "mysql":
    import mysql.connector
    return mysql.connector.connect(host=host, ...)
```

---

## 13. Monitoring & Maintenance

### Key Log Files
- `logs/app.log` — Application events, errors
- `logs/audit.log` — Every API call (GDPR/GxP compliance)
- `logs/security.log` — Injection attempts, RBAC violations

### Health Check Response (GET /api/v1/health/)
```json
{
  "status": "ok",
  "components": {
    "ollama": {"status": "ok", "models": ["llama3:8b"]},
    "database": {"status": "ok"},
    "vector_store": {"status": "ok", "document_chunks": 1247}
  }
}
```

### Vector Store Maintenance
```bash
# View stats
python manage.py shell -c "
from apps.agents.document_agent import DocumentAgent
print(DocumentAgent().get_collection_stats())
"

# Re-ingest a document
python manage.py ingest_documents --file updated-sop.pdf --type sop
```
