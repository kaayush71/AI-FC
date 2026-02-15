# AI-FC: Truth Detector

An intelligent fact-checking system that uses Agentic RAG (Retrieval-Augmented Generation) to verify claims against a curated database of news articles and external sources.

## Overview

Truth Detector is a two-pipeline system designed for automated claim verification:

1. **Data Ingestion Pipeline**: Continuously fetches, processes, and indexes news articles from trusted sources into a vector database
2. **Agentic RAG Verification Pipeline**: Uses AI agents to intelligently verify user claims through multi-stage reasoning and evidence retrieval

## Key Features

### 🤖 Agentic Intelligence
- **Query Enhancement Agent**: Automatically detects ambiguous claims and prompts for clarification
- **Smart External Search**: LLM-driven decision-making for when to search external sources
- **Multi-Query Retrieval**: Generates and searches multiple query variations for comprehensive evidence gathering
- **Two-Pass Verification**: First checks internal database, then conditionally searches external sources

### 📰 Comprehensive News Coverage
- Multi-source ingestion from trusted news outlets (BBC, Guardian, Al Jazeera, Indian Express, etc.)
- Automated RSS feed fetching and article extraction
- Deduplication and metadata enrichment
- Vector-based semantic search using ChromaDB

### 🎯 Flexible Verification
- Command-line interface for quick claim verification
- Batch processing support for multiple claims
- Configurable verification parameters (models, thresholds, external search)
- Detailed output with evidence, confidence scores, and source citations

## Quick Start

### Prerequisites

- macOS/Linux
- Python 3.10+
- OpenAI API key (for embeddings and verification)
- Tavily API key (optional, for external search)

### Installation

```bash
cd truth-detector
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install .
```

### Setup API Keys

```bash
export OPENAI_API_KEY="sk-..."
export TAVILY_API_KEY="tvly-..."  # Optional for external search
```

### Ingest News Data

```bash
# Fetch recent articles (last 60 minutes)
truth-news ingest --since-minutes 60

# Backfill older articles (last 7 days)
truth-news backfill --days 7

# Check ingestion health
truth-news health
```

### Verify Claims

```bash
# Simple verification
truth-news verify "Elon Musk announced Tesla's new factory in India"

# Verify without external search
truth-news verify --no-external "Tesla stock dropped 10% yesterday"

# Verify with raw claim (skip enhancement)
truth-news verify --no-enhance "Biden announced new AI regulations"

# Batch verify from file
truth-news verify --file claims.txt

# Compact output (single line per claim)
truth-news verify --compact "Some claim to verify"
```

## Architecture

### Data Flow

```
News Sources → Fetch → Clean → Chunk → Embed → ChromaDB
                                                    ↓
User Claim → Query Enhancement → Multi-Query Retrieval
                                        ↓
                              First-Pass Verification
                                        ↓
                    ┌──────────────────┴──────────────────┐
                    ↓                                     ↓
            needs_external: false               needs_external: true
                    ↓                                     ↓
              Final Result ←───── Tavily Search + Re-verify
```

### Key Components

**Ingestion Pipeline** (`app/ingest/`)
- `fetch_rss.py`: RSS feed fetching
- `extract_article.py`: Article text extraction (Trafilatura)
- `clean.py`: Text normalization
- `dedupe.py`: Content deduplication via SHA256
- `chunk.py`: Token-based chunking (300-500 tokens)
- `embed.py`: OpenAI embedding generation
- `index.py`: ChromaDB vector indexing

**Verification Pipeline** (`app/verify/`)
- `enhance.py`: Query Enhancement Agent (ambiguity detection, multi-query generation)
- `retrieve.py`: Multi-query evidence retrieval from ChromaDB
- `analyze.py`: Verification Agent with agentic external search decision
- `search.py`: Tavily external search and result caching
- `output.py`: Result formatting with colored CLI output

**Storage** (`app/store/`)
- `sqlite.py`: SQLite for ingestion state and metadata
- `chroma.py`: ChromaDB vector database for semantic search

## Project Structure

```
AI-FC/
├── truth-detector/
│   ├── app/
│   │   ├── cli.py              # Main CLI entry point
│   │   ├── config/
│   │   │   ├── sources.yaml    # RSS source configuration
│   │   │   └── loader.py       # Config loader
│   │   ├── common/             # Shared utilities
│   │   ├── ingest/             # Data ingestion pipeline
│   │   ├── verify/             # Claim verification pipeline
│   │   └── store/              # Database interfaces
│   ├── data/
│   │   ├── news.db             # SQLite database
│   │   └── chroma/             # ChromaDB vector store
│   ├── pyproject.toml
│   └── README.md
└── README.md                   # This file
```

## CLI Commands Reference

### Ingestion

```bash
# Ingest recent articles
truth-news ingest --since-minutes <MINUTES>

# Options:
#   --limit-queued <N>           Limit articles to process
#   --skip-index                 Skip ChromaDB indexing
#   --embedding-model <MODEL>    Embedding model (default: text-embedding-3-small)
#   --embedding-dimensions <N>   Vector dimensions
#   --collection-name <NAME>     ChromaDB collection name

# Backfill older articles
truth-news backfill --days <N>

# Check source health
truth-news health

# Reset data
truth-news reset --full --yes           # Full reset (SQLite + ChromaDB)
truth-news reset --chunks-only --yes    # Reset chunks only (keep articles)
```

### Verification

```bash
# Verify a single claim
truth-news verify "CLAIM TEXT"
truth-news verify --file claims.txt     # Batch verify

# Options:
#   --no-enhance                 Skip query enhancement
#   --no-external                Disable external search
#   --top-k <N>                  Number of evidence chunks (default: 10)
#   --embedding-model <MODEL>    Embedding model
#   --verification-model <MODEL> LLM for verification (default: gpt-4o)
#   --compact                    Compact single-line output
#   --no-color                   Disable colored output
```

## Configuration

### News Sources

Edit `truth-detector/app/config/sources.yaml` to add or configure news sources:

```yaml
sources:
  - id: source_identifier
    name: Source Display Name
    country: US
    category: news
    rss_urls:
      - https://example.com/rss
    enabled: true
    fetch_interval_minutes: 30
    trust_rank: 1  # 1-10, higher is more trusted
```

### Environment Variables

- `OPENAI_API_KEY`: Required for embeddings and verification
- `OPENAI_BASE_URL`: Optional OpenAI-compatible API endpoint
- `TAVILY_API_KEY`: Required for external search (optional feature)

## Data Storage

### SQLite (`data/news.db`)
- **sources**: Source configurations and health status
- **rss_items**: Feed-level ingestion queue
- **articles**: Extracted article text and metadata
- **chunks**: Text chunks with embeddings
- **indexed_chunks**: Index tracking

### ChromaDB (`data/chroma`)
- Collection: `news_openai_v1` (default)
- Stores: chunk text, embeddings, metadata (URL, source, date, etc.)
- Used for: semantic similarity search during verification

## Examples

### Basic Claim Verification

```bash
$ truth-news verify "Tesla announced a new Gigafactory in India"

Query enhanced: "Tesla Gigafactory India announcement"

Verdict: TRUE (85% confidence)

Reasoning:
Multiple credible sources confirm Tesla's announcement of a new Gigafactory 
in India scheduled for 2026, with an investment of $3 billion.

Supporting Evidence:
  [1] The Indian Express (2026-02-15): "Tesla CEO Elon Musk announced..."
      https://indianexpress.com/article/...
  
  [2] BBC World (2026-02-14): "Electric car maker Tesla confirms..."
      https://bbc.co.uk/news/...

Contradicting Evidence: None
```

### Ambiguous Claim with Clarification

```bash
$ truth-news verify "The president announced new tariffs"

Query Enhancement Agent detected ambiguity:
  Original: "The president announced new tariffs"
  Issue: Which country's president?

Please select the intended context:
  [1] US President (Joe Biden)
  [2] Chinese President (Xi Jinping)
  [3] French President (Emmanuel Macron)
  [4] Keep original (search as-is)
  [5] Custom: Enter your own clarification

Your choice [1-5]: 1

Query enhanced: "US President Joe Biden tariffs announcement"
...
```

## Development

### Adding New News Sources

1. Edit `app/config/sources.yaml`
2. Add source configuration with RSS URLs
3. Run ingestion: `truth-news ingest --since-minutes 60`

### Customizing Verification Logic

- **Query Enhancement**: Edit `app/verify/enhance.py` → `ENHANCEMENT_SYSTEM_PROMPT`
- **Verification Prompts**: Edit `app/verify/analyze.py` → system prompts
- **Search Integration**: Edit `app/verify/search.py`

### Debugging

```bash
# Check ingestion status
truth-news health

# Inspect database
sqlite3 data/news.db "SELECT COUNT(*) FROM articles;"
sqlite3 data/news.db "SELECT * FROM chunks LIMIT 5;"

# Check ChromaDB
python -c "import chromadb; print(chromadb.PersistentClient('data/chroma').get_collection('news_openai_v1').count())"
```

## Documentation

- [Full README](truth-detector/README.md) - Detailed ingestion pipeline documentation
- [Design Document](DESIGN.md) - Architecture and system design
- [Design Diagrams](truth-detector/design-diagram.md) - Mermaid diagrams of data flow

## Tech Stack

- **Language**: Python 3.10+
- **Vector Database**: ChromaDB
- **Metadata Store**: SQLite
- **LLM Provider**: OpenAI (GPT-4o, text-embedding-3-small)
- **External Search**: Tavily API
- **Article Extraction**: Trafilatura, BeautifulSoup
- **RSS Parsing**: feedparser

## License

MIT License - See LICENSE file for details

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## Support

For issues, questions, or contributions, please open an issue on the GitHub repository.