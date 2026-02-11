# Truth Detector Ingestion Pipeline

This project implements the ingestion pipeline for the Truth Detector hackathon:

- fetches curated news RSS feeds
- extracts article text
- cleans and normalizes text
- deduplicates content
- chunks text for retrieval
- generates embeddings
- indexes chunks into Chroma
- stores metadata/state in SQLite for resumable ingestion

## 1) Prerequisites

- macOS/Linux shell
- Python 3.10+
- internet access (for RSS/article fetch)
- OpenAI API key for embedding generation

## 2) Project structure

```text
truth-detector/
  app/
    cli.py
    config/
      sources.yaml
      loader.py
    common/
      http.py
      hashing.py
      logging.py
      time.py
    ingest/
      fetch_rss.py
      extract_article.py
      clean.py
      dedupe.py
      chunk.py
      embed.py
      index.py
    store/
      sqlite.py
      chroma.py
  data/
    news.db
    chroma/
```

## 3) Setup and install

From project root:

```bash
cd /Users/aayushkumar/AI-FC/truth-detector
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install . -i https://pypi.org/simple
```

Note:
- use `pip install .` (not editable mode) for this repo setup
- if your environment has private index overrides, use `-i https://pypi.org/simple`

## 3.1) OpenAI token setup (required)

Embedding stage uses OpenAI API, so token setup is mandatory.

```bash
cd /Users/aayushkumar/AI-FC/truth-detector
source .venv/bin/activate
export OPENAI_API_KEY="sk-..."
```

Quick verification:

```bash
python - <<'PY'
import os
print("OPENAI_API_KEY set:", bool(os.getenv("OPENAI_API_KEY")))
PY
```

Alternative (without env var), pass key in command:

```bash
news ingest --since-minutes 60 --openai-api-key "sk-..."
```

If token is missing, embedding stage will fail fast with:
- `OPENAI_API_KEY is required to generate OpenAI embeddings.`

## 4) Source configuration

Sources are configured in:

- `/Users/aayushkumar/AI-FC/truth-detector/app/config/sources.yaml`

Each source entry includes:

- `id`
- `name`
- `country`
- `category`
- `rss_urls`
- `enabled`
- `fetch_interval_minutes`
- `trust_rank`

To add a source: add a new YAML entry.  
To disable a source temporarily: set `enabled: false`.

## 5) How ingestion works (stage-by-stage)

For each run:

1. **Fetch RSS**  
   Pulls RSS feeds and upserts items into `rss_items` as `queued`.

2. **Extract articles**  
   Fetches each queued URL and extracts main text into `articles`.

3. **Clean + normalize**  
   Normalizes quotes/dashes/whitespace deterministically.

4. **Dedupe**  
   Uses SHA256 `text_hash`; duplicates are linked via `duplicate_of_url`.

5. **Chunk**  
   Token-based chunking (default target 420, overlap 60), stored in `chunks`.

6. **Embed**  
   Calls OpenAI Embeddings API (default model: `text-embedding-3-small`) and stores vectors + model metadata.

7. **Index**  
   Upserts chunks into Chroma collection (default: `news_v1`).

## 6) CLI commands

Primary CLI command:
- `news`

Activate env first:

```bash
cd /Users/aayushkumar/AI-FC/truth-detector
source .venv/bin/activate
export OPENAI_API_KEY="sk-..."
```

### Ingest recent items

```bash
news ingest --since-minutes 60
```

Useful options:

```bash
news ingest --since-minutes 30 --limit-queued 50
news ingest --since-minutes 60 --skip-index
news ingest --since-minutes 60 --embedding-model text-embedding-3-large
news ingest --since-minutes 60 --embedding-model text-embedding-3-small --embedding-dimensions 1024
news ingest --since-minutes 60 --collection-name news_v2
```

### Backfill older items

```bash
news backfill --days 7
```

With OpenAI-compatible base URL (optional):

```bash
news ingest --since-minutes 60 --openai-base-url https://api.openai.com/v1
```

### Health check

```bash
news health
```

Shows, per source:
- total items
- queued/extracted/failed counts
- last success and last error

### Reset commands

```bash
news reset --full --yes
news reset --chunks-only --yes
```

Use `--yes` to confirm destructive action.

## 7) Data locations

- SQLite DB: `/Users/aayushkumar/AI-FC/truth-detector/data/news.db`
- Chroma persistence: `/Users/aayushkumar/AI-FC/truth-detector/data/chroma`

## 7.1) What is stored where

### SQLite (`data/news.db`) stores pipeline state + metadata

Tables:

- `sources`  
  Per-source configuration snapshot and health state:
  - `source_id`, `name`, `enabled`, `fetch_interval_minutes`
  - `last_success_at`, `last_error_at`, `last_error`

- `rss_items`  
  Feed-level ingestion queue/state:
  - `source_id`, `guid`, `url`, `title`, `published_at`, `fetched_at`
  - `status` (`queued` / `extracted` / `failed`)
  - `error`

- `articles`  
  Extracted article text and dedupe metadata:
  - `url`, `final_url`, `title`, `published_at`, `author`
  - `text`, `extracted_at`, `text_hash`
  - `duplicate_of_url`

- `chunks`  
  Chunked text + embedding payload/metadata:
  - `chunk_id`, `url`, `source_id`, `title`, `published_at`, `chunk_index`
  - `text`, `chunk_hash`, `token_count`, `created_at`
  - `embedding` (JSON vector), `embedding_model`, `embedding_dim`, `embedding_created_at`
  - `indexed_at`

- `indexed_chunks`  
  Index bookkeeping:
  - `chunk_id`, `collection_name`, `indexed_at`

Why SQLite:
- system of record for ingestion
- resumability/idempotency
- debugging and auditability

### Chroma (`data/chroma`) stores vector index for retrieval

Collection (default): `news_v1`

Per vector record:
- `id`: `chunk_id`
- `document`: chunk text
- `embedding`: OpenAI embedding vector
- `metadata`: `url`, `source_id`, `published_at`, `title`, `chunk_index`, `embedding_model`

Why Chroma:
- fast similarity search over embeddings during retrieval/verification
- retrieval-optimized storage separate from ingestion state

## 8) Inspect ingested data

### SQLite quick checks

```bash
sqlite3 /Users/aayushkumar/AI-FC/truth-detector/data/news.db "SELECT COUNT(*) FROM rss_items;"
sqlite3 /Users/aayushkumar/AI-FC/truth-detector/data/news.db "SELECT COUNT(*) FROM articles;"
sqlite3 /Users/aayushkumar/AI-FC/truth-detector/data/news.db "SELECT COUNT(*) FROM chunks;"
sqlite3 /Users/aayushkumar/AI-FC/truth-detector/data/news.db "SELECT COUNT(*) FROM indexed_chunks;"
```

### Open SQLite shell

```bash
sqlite3 /Users/aayushkumar/AI-FC/truth-detector/data/news.db
```

Inside shell:

```sql
.tables
SELECT source_id, COUNT(*) AS c FROM rss_items GROUP BY source_id ORDER BY c DESC;
SELECT url, title, substr(text, 1, 300) FROM articles LIMIT 5;
SELECT chunk_id, url, chunk_index, token_count FROM chunks ORDER BY chunk_id DESC LIMIT 20;
```

### Chroma count check

```bash
cd /Users/aayushkumar/AI-FC/truth-detector
source .venv/bin/activate
python - <<'PY'
import chromadb
client = chromadb.PersistentClient(path="data/chroma")
col = client.get_collection("news_v1")
print("news_v1 count:", col.count())
PY
```

### No items ingested

Check:
- source URLs are valid and enabled
- `--since-minutes` window is not too small
- internet connectivity / firewall
- `OPENAI_API_KEY` is set for embedding stage
- `news health` for per-source error messages

### OpenAI key/config issues

If embedding fails:

- verify `OPENAI_API_KEY` is set in the same shell session
- verify model name is valid (default: `text-embedding-3-small`)
- if using a proxy/provider, set `--openai-base-url`

### Existing data and reruns

- SQLite + unique constraints prevent duplicate ingestion work
- rerunning `news ingest` is expected and safe

## 10) Typical daily workflow

```bash
cd /Users/aayushkumar/AI-FC/truth-detector
source .venv/bin/activate
news ingest --since-minutes 30
news health
```

For demo prep:

```bash
news backfill --days 7
news health
```

## 11) Reset data (clear SQLite/Chroma)

Warning: these operations permanently delete ingested data.

Activate env:

```bash
cd /Users/aayushkumar/AI-FC/truth-detector
source .venv/bin/activate
```

### Option A: Full reset (start from zero)

Deletes entire SQLite DB and Chroma index.

```bash
news reset --full --yes
news health
```

After this, run ingestion again:

```bash
news ingest --since-minutes 60
```

### Option B: Reset only chunks + vectors (keep fetched RSS/articles)

Keeps `sources`, `rss_items`, and `articles`, but clears chunking/embedding/indexing outputs.

```bash
news reset --chunks-only --yes
```

Then rerun from chunk/embed/index path via normal ingest:

```bash
news ingest --since-minutes 60
```
