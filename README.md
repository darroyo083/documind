# DocuMind

DocuMind is a private AI-powered knowledge platform based on Retrieval-Augmented Generation (RAG).

Upload documents into isolated knowledge spaces, ask questions about their content, and receive grounded answers with verifiable citations.

## Quick Start

```bash
# Copy the environment configuration
cp .env.example .env

# Start all services
docker compose up --build
```

- **Frontend**: http://localhost:5173
- **Backend API**: http://localhost:8000
- **API docs**: http://localhost:8000/docs
- **Health check**: http://localhost:8000/health

## Project Structure

```
documind/
├── backend/               # Python FastAPI application
│   ├── app/               # Application code
│   │   ├── api/           # REST routes and DTOs
│   │   ├── domain/        # Domain contracts and entities
│   │   └── infrastructure/# External adapters (DB, AI providers, storage)
│   ├── alembic/           # Database migrations
│   ├── tests/             # Test suite
│   └── pyproject.toml     # Python dependencies and tooling
├── frontend/              # React + TypeScript + Tailwind CSS
│   ├── src/               # Application code
│   └── package.json       # Node dependencies
├── docker-compose.yml     # Service orchestration
└── docs/                  # Architecture and design documentation
```

## Development Commands

### Backend

```bash
cd backend

# Install with dev dependencies
pip install -e ".[dev]"

# Run tests (requires PostgreSQL and creates a disposable test database)
pytest --cov -v

# Format code
ruff format .

# Lint
ruff check .

# Type check
mypy .

# Run migrations
alembic upgrade head

# Create a migration
alembic revision --autogenerate -m "description"
```

The canonical Docker Compose workflow runs Alembic from the backend container:

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend python scripts/verify_migrations.py
```

See [`docs/migrations.md`](docs/migrations.md) for revision inspection, downgrade, lifecycle verification, and safe local reset commands.

### Frontend

```bash
cd frontend

# Install dependencies
npm install

# Start dev server
npm run dev

# Type check
npx tsc --noEmit

# Lint
npm run lint

# Build
npm run build
```

## Configuration

Key environment variables (see `.env.example`):

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection string (async) | `postgresql+asyncpg://...` |
| `SECRET_KEY` | JWT signing secret | `change-me-in-production` |
| `GENERATION_PROVIDER` | Generation provider (`deepseek`, `mock`) | `mock` |
| `DEEPSEEK_API_KEY` | DeepSeek API key; required when generation uses DeepSeek | empty |
| `DEEPSEEK_MODEL` | DeepSeek chat model | `deepseek-chat` |
| `EMBEDDING_PROVIDER` | Embedding provider (`local`, `mock`) | `local` |
| `EMBEDDING_MODEL` | Local embedding model | `BAAI/bge-small-en-v1.5` |
| `EMBEDDING_DIMENSION` | Local embedding vector dimension | `384` |
| `CHUNK_SIZE` | Target chunk size in characters | `800` |
| `CHUNK_OVERLAP` | Chunk overlap in characters | `120` |
| `MAX_UPLOAD_SIZE_MB` | Maximum file upload size | `10` |
| `UPLOAD_DIR` | Private local PDF storage directory | `uploads` |
| `DEFAULT_TOP_K` | Default number of retrieved chunks | `5` |
| `RETRIEVAL_MAX_TOP_K` | Maximum allowed `top_k` | `10` |
| `DEFAULT_SIMILARITY_THRESHOLD` | Minimum cosine similarity for retrieved chunks | `0.2` |
| `ANALYSIS_PROVIDER` | Structured analysis provider (`deepseek`, `mock`) | `mock` |
| `ANALYSIS_MODEL` | DeepSeek model used for structured analysis | `deepseek-chat` |
| `ANALYSIS_MAX_CONTEXT_CHARS` | Max document characters sent to analysis | `120000` |
| `ANALYSIS_MAX_IMPORTANT_DATES` | Max important dates per analysis | `10` |
| `ANALYSIS_MAX_KEY_FACTS` | Max key facts per analysis | `20` |

## Structured Document Intelligence (PoC 2.1)

Beyond question answering, DocuMind can answer *"what kind of document is this, what
are its most important facts and dates, and where did each fact come from?"*.

For a ready, text-based PDF, call:

```text
POST /knowledge-spaces/{space_id}/documents/{document_id}/analysis
GET  /knowledge-spaces/{space_id}/documents/{document_id}/analysis
```

The result is persisted per document and contains:

- `document_type` — one of `contract`, `invoice`, `insurance_policy`,
  `bank_statement`, `tax_document`, `employment_document`, `housing_document`,
  `pension_document`, `official_letter`, `receipt`, `report`, `other`, `unknown`.
- `normalized_title` — the title as written in the document.
- `summary` — one concise sentence grounded in the document.
- `important_dates` — labeled dates with a `normalized_date` (`YYYY-MM-DD`) only
  when the document expresses an exact, unambiguous date. Partial dates
  (e.g. "January 2027") or relative dates (e.g. "within 30 days") stay `null`.
- `key_facts` — labeled, short facts.
- `sources` on every date and fact — server-constructed citation metadata
  (`chunk_id`, `page_number`, `excerpt`) resolved from the document's stored
  chunks. The model can never supply page numbers or chunk metadata; every
  `chunk:<id>` reference is validated against the authenticated user's own
  document chunks, and any unknown or cross-document reference fails the
  analysis instead of being trusted. This is source-validated structured
  extraction: validation proves the cited references exist in the analyzed
  document and that page numbers and excerpts are server-derived; it does NOT
  independently prove semantic entailment between an extracted value and its
  cited excerpt.

### Provider behavior

- Default `ANALYSIS_PROVIDER=mock` is for local development and tests only. It is a
  deterministic keyword/pattern extractor: it is NOT real AI extraction and its
  output must not be mistaken for intelligent classification.
- Set `ANALYSIS_PROVIDER=deepseek` together with `DEEPSEEK_API_KEY` to use the
  DeepSeek structured-analysis adapter. It reuses `DEEPSEEK_API_KEY`,
  `DEEPSEEK_BASE_URL` and the provider timeout; no additional API key is needed.
- Analysis runs synchronously in the request. A document has at most one current
  analysis: an existing ready analysis is returned idempotently, an in-progress
  analysis returns `409`, and a failed analysis can be retried. There is no
  re-analysis or version history in this PoC.
- Analysis is limited to the document's persisted text chunks; documents whose
  full content exceeds `ANALYSIS_MAX_CONTEXT_CHARS` are rejected with a clear
  error rather than silently truncated.

### Limitations (PoC 2.1)

- Text-based PDFs only; OCR is not implemented.
- No frontend for structured analysis yet (PoC 2.2).
- Date normalization never invents missing day/month/year components.
- Structured results are grounded in stored chunks, not external knowledge.
- If the backend process terminates after an analysis is marked `processing`
  but before it becomes `ready`/`failed`, the analysis row can remain
  `processing` indefinitely; later POSTs return `409` until the row is cleared.
  PoC 2.1 has no recovery, workers, leases, or timeouts for this case.

## Development defaults and mock behavior

The default `GENERATION_PROVIDER=mock` is for local development only. It does **not** call an
AI model: the deterministic mock echoes the top retrieved chunk verbatim as the answer and
cites that single chunk. This makes the retrieval, grounding, and citation pipeline testable
without an API key, but the text shown is raw document content, not a generated answer.
Set `GENERATION_PROVIDER=deepseek` and `DEEPSEEK_API_KEY` to enable real grounded answers.
The embedding pipeline defaults to the real local model (`EMBEDDING_PROVIDER=local`), which is
downloaded to the FastEmbed cache on first use.

## Known limitations (v0.1)

- Text-based PDFs only. OCR is not implemented; scanned or image-only PDFs are rejected as failed.
- Ingestion is synchronous: uploads block until extraction, chunking, and embedding complete.
- Background workers, chat history, and evaluation tooling are not implemented.
- The local embedding model `BAAI/bge-small-en-v1.5` is optimized for English text. Quality on
  other languages is not guaranteed; a multilingual model comparison is a later milestone.
- Local disk storage is for development. Object storage and lifecycle policies are out of scope
  for v0.1.

## v0.1 Scope

- User authentication and resource-level authorization
- Isolated knowledge spaces
- Text-based PDF upload and processing
- Text extraction and fixed-size chunking
- Local embeddings and pgvector storage
- Semantic retrieval with configurable top-k and similarity threshold
- DeepSeek generation (or mock provider for testing)
- RAG pipeline with page-level citations and insufficient-context detection
- Structured Document Intelligence: document type, title, summary, important
  dates, key facts, and server-validated citations (mock or DeepSeek provider)
- Docker Compose development environment
- CI with linting, type checking, and tests

## License

Private project — all rights reserved.
