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
- Docker Compose development environment
- CI with linting, type checking, and tests

## License

Private project — all rights reserved.
