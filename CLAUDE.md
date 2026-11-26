# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

RAG Quiz: a web app that turns lecture slides (PPTX/PDF) into a bank of Vietnamese 4-option MCQs. Each question has per-option explanations and a citation of its source slide. On top of the bank: quiz creation (no LLM calls), taking and reviewing quizzes, a cited chatbot, misconception profiles and an admin view. Code comments, prompts, docs and UI text are in Vietnamese. Keep new comments and user-facing strings in Vietnamese.

Stack: FastAPI (Python 3.11) + PostgreSQL 16/pgvector + React/TS (Vite, Tailwind, TanStack Query) served by nginx, all through Docker Compose. LLM calls go through LiteLLM. `bge-m3` embeddings, ViT5, NLI and the reranker run locally.

## Commands

The whole system runs in Docker. The developer works on Windows and drives it through the `.bat` files in `scripts/`.

```
docker compose up -d --build        # after changing code in app/ or web/
docker compose restart api          # after changing config.yaml only (mounted read-only)
```
- UI: http://localhost:8080 (nginx serves `/` as the SPA and proxies `/api` to FastAPI with the prefix stripped)
- API docs: http://localhost:8000/docs (bound to 127.0.0.1)

**Backend tests** run inside the `api` container against the real DB. `scripts\0_kiem_thu_tu_dong.bat` rebuilds, backs up the DB, applies migrations 004–006 and runs everything. To run tests by hand:
```
docker compose cp tests api:/app/tests
docker compose exec api sh -c "pip install -q pytest httpx scikit-learn scipy openpyxl"
docker compose exec api sh -c "cd /app && TEST_DATABASE_URL=\$DATABASE_URL python -m pytest -q tests/test_auth.py"
docker compose exec api sh -c "cd /app && TEST_DATABASE_URL=\$DATABASE_URL python -m pytest -q tests/test_v2_pipeline.py::test_name"
```
- `tests/` is not mounted into the container, so copy it in again after every edit.
- `tests/conftest.py` forces `AUTH_REQUIRED=false`. Tests that need auth turn it on in their own fixtures.
- DB-backed tests skip when `TEST_DATABASE_URL` is unset. They create rows prefixed `__test_` and delete them afterwards.
- No backend test calls an LLM API, so they cost nothing.

**UI e2e tests** (Playwright in Docker; needs the stack running): `scripts\10_kiem_thu_giao_dien.bat`, which runs `docker compose --profile e2e run --rm e2e`. The tests create `__e2e@ictu.edu.vn` users and sessions directly in the DB.

**Frontend** (`web/`): `npm run dev` serves port 8080 and proxies `/api` to `localhost:8000`. Also `npm run typecheck` and `npm run build`.

**ViT5 training tests:** `pip install -r requirements/train.txt && python -m pytest -q training/tests`.

**Evaluation:** `scripts\1_…` through `scripts\9_…` run in numeric order (see `scripts/DOC_TRUOC.txt`, `docs/huong-dan-test.md`). These scripts call paid or quota-limited APIs (OpenAI, Gemini), so don't run them without asking. Scripts in `scripts\_da_chay\` were one-offs. Re-running 2b regenerates the NLP question set and invalidates the existing human grading sheets.

## Architecture

**Config split.** `app/config.py` reads secrets and infrastructure from `.env` (pydantic-settings) and algorithm parameters plus model names from `config.yaml`. Models are named per *role* (`vlm`, `mcq_generator`, `chat_answer`, `judge`, …) in LiteLLM format. `app/llm_client.py` is the only LLM call layer, so switching models means editing `config.yaml`, not code.

**Ingestion** (`app/ingestion/pipeline.py`) runs as a FastAPI `BackgroundTask`. It parses slides (PyMuPDF/python-pptx; LibreOffice converts PPTX), removes repeated headers and logos, captions image-heavy slides with the VLM, chunks per slide (short slides get merged into a neighbour), embeds dense+sparse with bge-m3, and then builds the question bank automatically. Document status moves `uploaded → parsing → embedding → generating → ready/failed`. On startup, `app/main.py` marks any in-progress document `failed`, because a restart loses background jobs.

**Question generation.** `app/generation/bank_builder.py` picks seed chunks, loads context and dispatches on `bank.pipeline`:
- `v1`: one LLM call per question.
- `v2` (`pipeline_v2.py`, current): (1) LLM picks key point + answer + verbatim evidence (2) LLM writes the stem (3) candidates from ViT5 (`local_models`) + LLM "misconception" candidates (`candidates.py`) (4) rule filters (5) NLI filter (`filters.py`) (6) pick the 3-distractor set by max entropy with constraints (δ margin, length balance, misconception-type diversity, key-length rank) in `selector.py` (7) LLM writes explanations (8) v1 post-checks, dedup, save with all candidates.

A failed step raises `StepFailed`. The question is then regenerated with the failure reason fed back into the prompt (`bank.max_retries`). Without a ViT5 checkpoint in `checkpoints/dg-vit5-stage1/best`, the ViT5 source is skipped silently. Design rationale: `docs/ke-hoach-v2.md` and `docs/ke-hoach-v3*.md`.

**Prompts** live in `app/prompts/*.txt` and are filled by `render()`, which does plain `{name}` substitution, not `str.format`, because the prompts contain JSON examples. `misconception_types.json` is the single source for misconception labels used by the generation prompt, the tagging prompt and learner diagnosis.

**Local models** load lazily through `app/singleton.thread_safe_cache`. Use it, not `lru_cache`, for any model loader: concurrent loads under transformers 5.x corrupt tied weights.

**Quiz and learner.** `quiz_sampler.py` builds quizzes from the bank without an LLM: scope, Bloom mix, difficulty, and weakness-priority sampling from the misconception profile in `app/learner/`.

**Auth and access control.** Google OIDC + PKCE is handled in the backend (`app/auth/`), restricted to `@ictu.edu.vn`, with server-side sessions in Postgres and CSRF protection. Admins come from `ADMIN_EMAILS`. Every read of document content (lists, slide images, chunks, search, quiz creation, chatbot retrieval) must go through `app/auth/access.py` (`visible_clause` etc.), so one student's private slides never leak to another. `user=None` (auth disabled) means unrestricted. `Scope(document_ids=[])` means "no filter", so use `[NO_DOC]` to mean "nothing".

**Schema.** The SQL files in `migrations/` are the source of truth, and `app/models.py` mirrors them. Migrations run automatically only when the `pgdata` volume is empty. On an existing DB, apply new ones by hand with `docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -f /docker-entrypoint-initdb.d/00X_….sql'`, and back up to `backups/` first.

## Directories to leave alone

- `legacy/v1/` is a frozen copy of v1 (git tag `v1.0`).
- `ui/` is the old Streamlit UI. It no longer runs and is kept for reference.
- `_luu_tru/` holds old files that can be deleted.
- `eval/eval_retrieval.py` and `eval/eval_ragas.py` are stubs.
