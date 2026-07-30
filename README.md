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
| `EMBEDDING_PROVIDER` | Embedding provider (`local`, `mock`) | `mock` |
| `MAX_UPLOAD_SIZE_MB` | Maximum file upload size | `10` |

## v0.1 Scope

- User authentication and resource-level authorization
- Isolated knowledge spaces
- PDF, Markdown, and TXT upload and processing
- Text extraction and fixed-size chunking
- Local embeddings and pgvector storage
- Semantic retrieval with configurable top-k and similarity threshold
- DeepSeek generation (or mock provider for testing)
- RAG pipeline with citations and insufficient-context detection
- Conversation history
- Docker Compose development environment
- CI with linting, type checking, and tests

## License

Private project — all rights reserved.
