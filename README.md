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
| `ACTION_PROVIDER` | Action extraction provider (`deepseek`, `mock`) | `mock` |
| `ACTION_MODEL` | DeepSeek model used for action extraction | `deepseek-chat` |
| `ACTION_MAX_CONTEXT_CHARS` | Max document characters sent to action extraction | `120000` |
| `ACTION_MAX_ITEMS` | Max actions per document | `20` |

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

### Structured analysis UI (PoC 2.2)

The frontend now exposes structured analysis inside each knowledge space.
Selecting a document shows an **Overview** section (structured summary,
important dates, key facts, and expandable source evidence with page numbers
and excerpts) alongside the existing **Ask** flow.

- Analysis must be explicitly triggered with the "Analyze document" action; it
  is only available for ready documents.
- The mock analysis provider is the default in development; a subtle
  "Development analysis" label is shown when the result comes from the mock so
  it is not mistaken for production AI extraction.
- In development the mock provider is deterministic pattern extraction, not
  real AI classification.
- No OCR; text-based PDFs only. Analysis runs synchronously; there is no
  stale-processing recovery, so a document stuck in `processing` requires the
  row to be cleared manually.
- Structured analysis validates source references and server-derived citation
  metadata; it is not a semantic proof that every extracted statement is
  logically entailed by the cited excerpt.

### Grounded Actions & Checklists (PoC 3A)

Each knowledge-space document now has an **Actions** tab between Overview and
Ask. It extracts document-grounded action items you can mark as completed.

- Action types: `required_action` (explicit obligation), `deadline` (explicit
  due date), `reminder` (important date/event without an obligation), and
  `recommended_action` (only when the document explicitly recommends it).
- Action extraction is triggered explicitly with "Extract actions" and is only
  available for ready documents. Generated actions are grounded in the
  document's own chunks with server-validated evidence (page numbers and
  excerpts are derived server-side; the provider never controls trusted
  metadata). Source IDs are validated only against chunks of the analyzed
  document: references to another document's or another user's chunks are
  rejected.
- Checklist completion state is user-controlled (`pending`/`completed`) and
  persists server-side. The provider can never change completion status.
- Dates are normalized only when the document gives an exact calendar date.
  Partial dates, relative deadlines, and ambiguous numeric dates are preserved
  as text without invented precision; no relative-date arithmetic is performed.
- The mock action provider is the default in development (shown as
  "Development extraction"). DeepSeek is optional via `ACTION_PROVIDER=deepseek`
  and `DEEPSEEK_API_KEY`.
- DocuMind does NOT execute actions: it never sends emails, cancels contracts,
  submits forms, creates calendar events, or makes payments. It is not an
  autonomous agent.
- No notifications, calendar or email integration, recurring tasks, or action
  history. Generation is synchronous; there is no stale-processing recovery.
- This is source-validated extraction, not legal, tax, or financial advice, and
  not a semantic proof that every generated statement is entailed by the cited
  excerpt. The server validates source identity and citation metadata; it does
  not independently prove that the assigned action type is semantically
  correct, for example that an item labeled `required_action` is truly an
  obligation rather than a recommendation.

### Shared Reference Knowledge (PoC 3D)

DocuMind separates two knowledge layers for grounded Q&A:

- **Private knowledge**: the user's uploaded documents inside their owned
  knowledge spaces, scoped to the requested space and the authenticated user.
  Never shared with other users through reference mode.
- **Shared reference knowledge**: application-managed reference documents,
  available read-only to every authenticated user. They are imported
  locally/admin-side (`python scripts/import_reference_document.py --file ... 
  --title ...`); ordinary users cannot create, modify, or delete them through
  HTTP APIs.

Query scopes on the Ask endpoint (`knowledge_scope`, defaults to `private` for
backward compatibility):

- `private` — only the current user's documents in the requested space.
- `reference` — only the system-managed reference corpus.
- `combined` — the requested user's private space **plus** the reference
  corpus; it never includes another user's documents.

Citations distinguish provenance with a `source_kind` (`private` /
`reference`); document names, page numbers, excerpts, and source kind are
server-derived and cannot be spoofed by the model. One query embedding is used
per question; `top_k` is applied globally after merging private and reference
candidates; the same embedding model/dimension backs both stores.

- No web search, no automatic external synchronization, no user-to-user
  sharing, no organizations or roles, no OCR, and no semantic-entailment
  verification.
- A reference library may legitimately be empty; the UI degrades gracefully.

### Retrieval Evaluation (PoC 3C)

DocuMind ships a reproducible retrieval benchmark that measures the current
retrieval system **directly** (which chunks are retrieved) rather than judging
answer generation.

- Evaluation dataset: `backend/app/evaluation/datasets/retrieval_v1.json`
  (version 1) — a synthetic corpus (2 users, 4 spaces, 8 private documents,
  3 reference documents, 21 chunks) with explicit chunk/document ground truth,
  hard negatives, cross-user and cross-space decoys, and 43 queries across
  private/reference/combined scopes (34 answerable, 9 unanswerable). Semantic
  page identifiers used for ground truth live outside the embedded text, so the
  exact corpus text that FastEmbed embeds contains no benchmark markers.
- Metrics: Chunk Hit@K, macro Recall@K, MRR, Document Hit@K, unanswerable
  rejection rate, cross-user leakage, cross-space leakage, and combined source
  coverage.
- The evaluator exercises the production retrieval service; it does **not**
  require an answer provider or any LLM. Deterministic evaluator unit tests use
  mock embeddings and are not headline quality numbers.
- Generated raw reports go to `backend/evaluation/results/` (gitignored); the
  dataset is committed.

Run the real local FastEmbed baseline:

```bash
cd backend
docker compose up -d db
docker compose run --rm backend python scripts/evaluate_retrieval.py
```

The default embedding provider is the local FastEmbed model
`BAAI/bge-small-en-v1.5` (downloaded to the FastEmbed cache on first run). No
paid LLM API is called. Results depend on the dataset version, embedding
model, threshold, and top_k; they are a synthetic benchmark baseline, not a
claim of production or general RAG quality.

Synthetic baseline (dataset v1, BAAI/bge-small-en-v1.5, 384 dimensions,
top_k=5, threshold 0.5):

| Metric | Result |
|---|---|
| Chunk Hit@1 | 0.882 |
| Chunk Hit@3 | 0.971 |
| Chunk Hit@5 | 1.000 |
| Recall@1 | 0.809 |
| Recall@3 | 0.971 |
| Recall@5 | 1.000 |
| MRR | 0.929 |
| Document Hit@5 | 1.000 |
| Unanswerable rejection | 0 / 9 (0.000) |
| Cross-user leakage | 0 / 13 |
| Cross-space leakage | 0 / 6 |
| Combined source coverage | 1.000 |

Observed findings (measured, not tuned — production defaults unchanged):

- The benchmark similarity threshold (0.5; see the threshold terminology note
  below) is permissive for unanswerable queries: all 9 returned candidates. The
  threshold sweep shows rejection only improves to 2/9 (22.2%) at 0.6 and 5/9
  (55.6%) at 0.7, where answerable Hit@5 collapses from 1.000 to 0.706.
  Unanswerable top scores (0.54–0.79) overlap heavily with relevant scores
  (0.52–0.88), so **no threshold in the swept range provides a good
  recall/rejection tradeoff** on this corpus. This supersedes any earlier
  suggestion that ~0.55–0.65 might be worth exploring.
- Weakest categories at Hit@1: combined private-winner (0.333), cross-space
  decoy and semantic decoy (0.500) — embedding/proximity limitations, not
  retrieval bugs. All 34 answerable queries retrieved their relevant chunk
  within top 5.
- Chunking limitation: the v1 corpus largely uses one synthetic chunk per page
  (21 chunks / 21 pages), so it does not stress long-page splitting, overlap
  boundaries, or facts spanning a chunk boundary. It is not a comprehensive
  chunking-strategy benchmark.

### Evidence Sufficiency / Unsupported-Question Detection (PoC 3E)

Semantic retrieval relevance does not equal answer sufficiency. Retrieval asks
"which chunks are most similar?"; sufficiency asks "do these chunks contain the
evidence the question asks for?". A document can be topically relevant while the
requested fact is absent (e.g. a cancellation-notice clause versus "what is the
cancellation fee?").

PoC 3C showed that a single similarity threshold cannot separate these cases:
unanswerable top scores (0.54–0.79) overlap heavily with relevant scores
(0.52–0.88), and raising the threshold destroys answerable retrieval. PoC 3E
therefore evaluates an explicit evidence-sufficiency decision layer rather than
tuning production retrieval.

- Experimental evaluator: `scripts/evaluate_sufficiency.py` reuses the committed
  PoC 3C corpus and queries (43 queries, 34 answerable / 9 unanswerable) and
  the real local FastEmbed model. No paid LLM API is called; DeepSeek is never
  contacted during the comparison. The benchmark runs at similarity threshold
  `0.5` / `top_k=5` to match the committed PoC 3C baseline (see note on
  thresholds below).
- Dataset split: each query carries a deterministic `evaluation_split`
  (`dev` 30 / `holdout` 13; dev 24 answerable + 6 unanswerable, holdout 10
  answerable + 3 unanswerable) validated in `app/evaluation/dataset.py`.
  Methodology: candidate configurations are evaluated on **DEV only**;
  the frozen selected strategy is then evaluated once on **HOLDOUT** as an
  overfitting guard. The generated report contains no holdout metrics for
  unselected candidates.
- Candidate strategies: max-score threshold (baseline), score margin,
  score concentration, lexical query-token coverage (top1 and topK union), and
  a combined score+coverage rule — all deterministic and cheap.
- Metrics: Answerable Retention, Unsupported Detection, Supported/Unsupported
  Precision, False Support Rate, False Rejection Rate, Balanced Accuracy.
- Measured result (dataset v1, BAAI/bge-small-en-v1.5, top_k=5, threshold 0.5):

| Metric | Baseline (threshold 0.5) | DEV-best strategy | HOLDOUT (selected) | Overall (selected) |
|---|---|---|---|---|
| Answerable Retention | 34/34 (1.000) | 23/24 (0.958) | 9/10 (0.900) | 32/34 (0.941) |
| Unsupported Detection | 0/9 (0.000) | 4/6 (0.667) | 0/3 (0.000) | 4/9 (0.444) |
| Balanced Accuracy | 0.500 | 0.813 | 0.450 | ≈0.693 |

  The DEV-selected strategy (`lexical_topk(min_coverage=0.1)`) collapses on
  holdout: all three holdout unanswerable queries are semantic near-misses with
  high top scores (0.72–0.79), which deterministic score/lexical signals cannot
  separate. The frozen selected strategy fails holdout.
- Outcome: per the milestone policy, no heuristic was forced into production.
  No retrieval setting was changed during PoC 3E. This experimentally rules out
  cheap deterministic abstention on the current corpus and motivates a
  dedicated evidence-verification model as a future milestone. The sufficiency
  layer would only ever operate over the already-authorized retrieval
  candidates, so source privacy/isolation is unaffected by design.
- `evaluate_sufficiency.py` emits `sufficiency_report.json` / `.md` into the
  gitignored `backend/evaluation/results/` directory. The retrieval benchmark
  (`scripts/evaluate_retrieval.py`) is unchanged and remains the canonical
  retrieval measurement.

### Holdout methodology disclosure

The 13-query `holdout` split was exposed to the candidate grid during the
initial PoC 3E development run (an earlier evaluator reported holdout metrics
for every candidate configuration). Although strategy selection itself remained
DEV-only and the corrected implementation reproduces the same Outcome B, this
split is **no longer considered a pristine untouched holdout**. It should be
retained as a **regression set**. A future evidence-verification milestone must
create a **fresh v2 holdout**.

### PoC 3E limitations

- The current corpus is synthetic, with only **9 unanswerable queries**.
- Lexical coverage experiments are English-oriented; no multilingual claim.
- The corpus largely has one chunk per page, so chunking behavior is not
  stressed.
- Results do not establish universal abstention quality; no
  hallucination-elimination claim is made.
- A dedicated evidence-verification model is a **future experiment**, not
  implemented.

### Retrieval threshold terminology

There are two distinct values for the retrieval similarity threshold:

- **Code / committed default**: `config.py` sets `default_similarity_threshold
  = 0.2`, and the committed `.env.example` documents `DEFAULT_SIMILARITY_THRESHOLD=0.2`.
- **Local runtime / benchmark value**: the untracked local `.env` sets
  `DEFAULT_SIMILARITY_THRESHOLD=0.5`. `docker-compose.yml` loads that `.env`,
  so the committed PoC 3C baseline and the PoC 3E experiment ran at threshold
  `0.5` with `top_k=5`.

The phrase "production default threshold 0.5" is therefore not accurate: the
committed code/example default is `0.2`; `0.5` is a local-environment value.
Neither value was changed by PoC 3E. Tests pin `DEFAULT_SIMILARITY_THRESHOLD=0.2`
in `tests/conftest.py`, so the test suite exercises the code default.
`top_k=5` is the same in the code default, `.env.example`, local `.env`, and
the benchmark.

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
