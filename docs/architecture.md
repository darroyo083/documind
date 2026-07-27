# DocuMind Architecture

## Overview

DocuMind is a modular monolith with three services orchestrated through Docker Compose:

- **postgres**: PostgreSQL 16 with pgvector for relational data and vector storage.
- **backend**: FastAPI application containing API layer, application use cases, domain contracts, and infrastructure adapters.
- **frontend**: React application with TypeScript and Tailwind CSS.

## Textual Architecture

```text
Browser
└── React + TypeScript + Tailwind
    └── REST/JSON
        └── FastAPI Modular Monolith
            ├── API layer (routes, DTOs, validation)
            ├── Application layer (use cases, orchestration)
            ├── Domain layer (interfaces, contracts)
            └── Infrastructure layer
                ├── SQLAlchemy repositories
                ├── AI provider adapters
                ├── Document extractors
                ├── Storage adapters
                └── Authentication

External
├── PostgreSQL + pgvector
├── Local filesystem (uploads)
├── Local embedding model
└── DeepSeek API (generation)
```

## Module Dependency Direction

```
API → Application/Use Cases → Domain ← Infrastructure
                                    ↕
                            External systems
                              (PostgreSQL, DeepSeek, etc.)
```

Domain contracts (GenerationProvider, EmbeddingProvider, repositories) are defined at the domain level and implemented in infrastructure adapters.

## v0.1 Stack

| Component | Technology |
|-----------|-----------|
| Backend | Python 3.12, FastAPI, Pydantic v2 |
| Database | PostgreSQL 16, pgvector |
| ORM | SQLAlchemy 2.0 (async) |
| Migrations | Alembic |
| Generation | DeepSeek API / Mock |
| Embeddings | Local model / Mock |
| Testing | Pytest, httpx AsyncClient |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS 3 |
| Infrastructure | Docker Compose |
| CI | GitHub Actions |

## Key Design Decisions

- **Modular monolith over microservices**: Avoid distributed complexity until a demonstrated need exists.
- **PostgreSQL + pgvector over a separate vector database**: One less infrastructure dependency; sufficient for the data volumes this project handles.
- **Async SQLAlchemy**: Matches FastAPI's async nature without blocking the event loop.
- **Provider interfaces**: Generation and embedding are separate, pluggable capabilities with explicit contracts.
- **No LangChain in v0.1**: The RAG pipeline must be readable and debuggable end-to-end.
- **Configuration-driven provider selection**: Providers are selected through environment variables, not code changes.
