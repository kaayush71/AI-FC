# Truth Detector - Agentic RAG Architecture

## System Overview

The Truth Detector consists of two main pipelines:
1. **Data Ingestion Pipeline** - Fetches, processes, and indexes news articles
2. **Agentic RAG Pipeline** - Verifies claims using intelligent retrieval and reasoning

---

## 1. Data Ingestion Pipeline

```mermaid
graph TB
    subgraph DataInputs["DATA INPUTS"]
        RSS["RSS Feeds / News APIs"]
        FACT["Verified Fact-Check Sites"]
        URL["Optional: On-demand URL"]
    end

    subgraph IngestionLogic["INGESTION LOGIC"]
        FETCH["1. Fetcher & Cleaner<br/>Trafilatura/RSS"]
        CHUNK["2. Transformation<br/>Chunking (300-500 tokens)"]
        META["3. Metadata Enrichment<br/>Source + Timestamp"]
        EMBED["4. Embedding<br/>Vector Generation"]
    end

    subgraph FinalStores["FINAL STORES"]
        VECTOR[("Vector DB: ChromaDB")]
        RAW[("Raw Store: SQLite<br/>Metadata + Text")]
    end

    subgraph Models["MODEL SERVICES"]
        EM["text-embedding-3-small"]
    end

    %% Data Flow
    RSS --> FETCH
    FACT --> FETCH
    URL --> FETCH
    
    FETCH --> CHUNK
    CHUNK --> META
    META --> EMBED
    
    EMBED --> EM
    EM --> VECTOR
    
    META -.-> RAW
    CHUNK -.-> RAW

    %% Styling
    style DataInputs fill:#e3f2fd,stroke:#1976d2
    style IngestionLogic fill:#fff9c4,stroke:#fbc02d
    style FinalStores fill:#e8f5e9,stroke:#388e3c
    style Models fill:#fff3e0
```

### Ingestion Pipeline Stages

| Stage | Description | Output |
|-------|-------------|--------|
| **1. Fetch & Clean** | Pull RSS feeds, extract article text using Trafilatura | Clean article text |
| **2. Chunking** | Split articles into 300-500 token chunks with overlap | Text chunks |
| **3. Metadata** | Attach source, URL, publish date, trust rank | Enriched chunks |
| **4. Embedding** | Generate vectors using OpenAI embeddings | 1536-dim vectors |

### CLI Commands

```bash
# Ingest recent articles (last 60 minutes)
truth-news ingest --since-minutes 60

# Backfill older articles
truth-news backfill --days 7

# Check ingestion health
truth-news health

# Reset data
truth-news reset --full --yes
```

---

## 2. Agentic RAG Verification Pipeline

```mermaid
graph TB
    subgraph Clients["CLIENTS"]
        CLI["CLI (truth-news verify)"]
    end

    subgraph Backend["AGENTIC RAG PIPELINE"]
        
        subgraph Enhancement["Step 0: Query Enhancement Agent"]
            QA["Query Analyzer"]
            AMB{{"Ambiguous?"}}
            CLARIFY["User Clarification Prompt"]
            ENHANCE["Generate Enhanced Queries"]
        end
        
        subgraph Retrieval["Step 1: Evidence Retrieval"]
            MULTI["Multi-Query Search"]
            DEDUP["Deduplicate Evidence"]
        end
        
        subgraph FirstPass["Step 2: First-Pass Verification"]
            VERIFY1["LLM Verification Agent"]
            DECISION{{"Agent Decision: Need External?"}}
        end
        
        subgraph SecondPass["Step 3: External Search (Conditional)"]
            TAVILY["Tavily Web Search"]
            CACHE["Cache to ChromaDB"]
            VERIFY2["Second-Pass Verification"]
        end
        
        subgraph Output["Step 4: Output"]
            FORMAT["Result Formatter"]
        end
    end

    subgraph DataStores["INTERNAL DATA"]
        CHROMA[("ChromaDB: News Vectors")]
        SQLITE[("SQLite: Ingestion State")]
    end

    subgraph External["EXTERNAL SOURCES"]
        SEARCH["Tavily API: Live Web Search"]
    end

    subgraph Models["MODEL SERVICES"]
        LLM["GPT-4o: Reasoning & Decisions"]
        EM["text-embedding-3-small"]
    end

    %% Query Enhancement Flow
    CLI --> QA
    QA --> AMB
    AMB -- "Yes" --> CLARIFY
    CLARIFY --> ENHANCE
    AMB -- "No" --> ENHANCE
    
    %% Retrieval Flow
    ENHANCE --> MULTI
    MULTI -- "Query Embedding" --> EM
    EM --> CHROMA
    CHROMA --> DEDUP
    
    %% First Pass Verification
    DEDUP --> VERIFY1
    VERIFY1 --> LLM
    LLM --> DECISION
    
    %% Agentic Decision Branch
    DECISION -- "needs_external_search: true" --> TAVILY
    DECISION -- "needs_external_search: false" --> FORMAT
    
    %% External Search & Second Pass
    TAVILY --> SEARCH
    SEARCH --> CACHE
    CACHE --> CHROMA
    CACHE --> VERIFY2
    VERIFY2 --> LLM
    VERIFY2 --> FORMAT
    
    %% Output
    FORMAT --> CLI

    %% Styling
    style Enhancement fill:#e3f2fd,stroke:#1976d2
    style Retrieval fill:#f3e5f5,stroke:#7b1fa2
    style FirstPass fill:#fff9c4,stroke:#fbc02d
    style SecondPass fill:#fce4ec,stroke:#c2185b
    style Output fill:#e8f5e9,stroke:#388e3c
    style DataStores fill:#e8f5e9
    style External fill:#fce4ec
    style Models fill:#fff3e0
```

## Agentic Features

### 1. Query Enhancement Agent (Pre-Retrieval)
- **Purpose**: Optimize user claims for better retrieval
- **Capabilities**:
  - Entity extraction (people, orgs, dates, locations)
  - Ambiguity detection (e.g., "the president" without country context)
  - Interactive user clarification when ambiguous
  - Multi-query generation for broader evidence coverage
- **CLI Flag**: `--no-enhance` to disable

### 2. Agentic External Search Decision (Post-First-Pass)
- **Purpose**: LLM decides if external search is needed (replaces hardcoded threshold)
- **Decision Factors**:
  - Evidence quality and recency
  - Confidence level from first-pass verification
  - Whether internal evidence is sufficient
- **Output Fields**:
  - `needs_external_search`: boolean decision
  - `search_rationale`: reasoning for the decision
  - `suggested_search_query`: optimized query for external search
- **CLI Flag**: `--no-external` to disable external search entirely

## Data Flow Summary

```
User Claim
    │
    ▼
┌─────────────────────────────────────┐
│  Query Enhancement Agent            │
│  - Analyze claim                    │
│  - Detect ambiguity                 │
│  - Prompt user if needed            │
│  - Generate enhanced queries        │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│  Multi-Query Retrieval              │
│  - Search ChromaDB with 1-3 queries │
│  - Deduplicate evidence chunks      │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│  First-Pass Verification            │
│  - Analyze evidence                 │
│  - Generate verdict + confidence    │
│  - Decide: need external search?    │
└─────────────────────────────────────┘
    │
    ├── needs_external_search: false ──► Output Result
    │
    ▼ needs_external_search: true
┌─────────────────────────────────────┐
│  External Search (Tavily)           │
│  - Use suggested_search_query       │
│  - Cache results to ChromaDB        │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│  Second-Pass Verification           │
│  - Combined internal + external     │
│  - Final verdict + confidence       │
└─────────────────────────────────────┘
    │
    ▼
Output Result with:
- Query enhancement info (original vs enhanced)
- Verdict, confidence, reasoning
- Supporting/contradicting evidence with URLs
- Source breakdown (internal vs external)
```

## Files Structure

```
app/verify/
├── enhance.py      # Query Enhancement Agent
├── retrieve.py     # ChromaDB evidence retrieval
├── analyze.py      # Verification engine + agentic decision
├── search.py       # Tavily external search + caching
├── output.py       # Result formatting
└── parse.py        # Claim parsing utilities
```

## CLI Usage

```bash
# Standard verification (with all agentic features)
truth-news verify "The president announced new AI regulations"

# Skip query enhancement
truth-news verify --no-enhance "Biden announced new AI regulations"

# Skip external search
truth-news verify --no-external "Tesla stock dropped 10%"

# Both disabled (raw claim, internal only)
truth-news verify --no-enhance --no-external "Some claim"
```

---

## 3. Combined System Architecture

```mermaid
graph TB
    subgraph DataSources["DATA SOURCES"]
        RSS["RSS Feeds"]
        FACT["Fact-Check Sites"]
        TAVILY_EXT["Tavily Web Search"]
    end

    subgraph IngestionPipeline["INGESTION PIPELINE (Offline)"]
        direction TB
        FETCH["Fetch & Clean"]
        CHUNK["Chunk Text"]
        ENRICH["Enrich Metadata"]
        EMBED_ING["Generate Embeddings"]
    end

    subgraph Storage["SHARED STORAGE"]
        CHROMA[("ChromaDB<br/>Vector Index")]
        SQLITE[("SQLite<br/>State & Metadata")]
    end

    subgraph VerificationPipeline["AGENTIC RAG PIPELINE (Online)"]
        direction TB
        
        subgraph AgentLayer["AGENT LAYER"]
            ENHANCE_AG["Query Enhancement<br/>Agent"]
            VERIFY_AG["Verification<br/>Agent"]
            DECISION_AG["External Search<br/>Decision Agent"]
        end
        
        RETRIEVE["Multi-Query<br/>Retrieval"]
        EXTERNAL["External Search<br/>+ Cache"]
        FORMAT_OUT["Format Output"]
    end

    subgraph Clients["CLIENTS"]
        CLI["CLI: truth-news"]
    end

    subgraph Models["MODEL SERVICES"]
        LLM["GPT-4o"]
        EMBED_MOD["Embeddings API"]
    end

    %% Ingestion Flow
    RSS --> FETCH
    FACT --> FETCH
    FETCH --> CHUNK
    CHUNK --> ENRICH
    ENRICH --> EMBED_ING
    EMBED_ING --> EMBED_MOD
    EMBED_MOD --> CHROMA
    ENRICH --> SQLITE

    %% Verification Flow
    CLI --> ENHANCE_AG
    ENHANCE_AG --> LLM
    ENHANCE_AG --> RETRIEVE
    RETRIEVE --> EMBED_MOD
    EMBED_MOD --> CHROMA
    CHROMA --> VERIFY_AG
    VERIFY_AG --> LLM
    VERIFY_AG --> DECISION_AG
    
    %% External Search Branch
    DECISION_AG -- "needs_external: true" --> EXTERNAL
    EXTERNAL --> TAVILY_EXT
    TAVILY_EXT --> EXTERNAL
    EXTERNAL --> CHROMA
    EXTERNAL --> VERIFY_AG
    
    %% Output
    DECISION_AG -- "needs_external: false" --> FORMAT_OUT
    VERIFY_AG --> FORMAT_OUT
    FORMAT_OUT --> CLI

    %% Styling
    style DataSources fill:#e3f2fd,stroke:#1976d2
    style IngestionPipeline fill:#fff9c4,stroke:#fbc02d
    style Storage fill:#e8f5e9,stroke:#388e3c
    style VerificationPipeline fill:#f3e5f5,stroke:#7b1fa2
    style AgentLayer fill:#fce4ec,stroke:#c2185b
    style Clients fill:#e1f5fe,stroke:#0288d1
    style Models fill:#fff3e0,stroke:#f57c00
```

### System Integration Points

| Component | Ingestion Pipeline | Verification Pipeline |
|-----------|-------------------|----------------------|
| **ChromaDB** | Writes indexed chunks | Reads for retrieval, writes external cache |
| **SQLite** | Tracks ingestion state | Not used directly |
| **Embedding Model** | Generates chunk vectors | Generates query vectors |
| **LLM (GPT-4o)** | Not used | Query enhancement, verification, decisions |
| **Tavily** | Not used | On-demand external search |

### Data Lifecycle

```
┌─────────────────────────────────────────────────────────────────┐
│                     OFFLINE (Batch)                              │
│  RSS/News ──► Fetch ──► Chunk ──► Embed ──► ChromaDB            │
│                                              ▲                   │
└──────────────────────────────────────────────│───────────────────┘
                                               │
                                               │ cached external
                                               │ results
┌──────────────────────────────────────────────│───────────────────┐
│                     ONLINE (Real-time)       │                   │
│  User Claim ──► Enhance ──► Retrieve ────────┴──► Verify         │
│                    │                                  │          │
│                    │         ┌────────────────────────┤          │
│                    │         │ needs_external: true   │          │
│                    │         ▼                        ▼          │
│                    │      Tavily ──► Cache      Output Result    │
│                    │         │                                   │
│                    │         └──► Re-verify ──► Output Result    │
└─────────────────────────────────────────────────────────────────┘
```

---

## Complete Files Structure

```
truth-detector/
├── app/
│   ├── cli.py                 # Main CLI entry point
│   ├── config/
│   │   ├── sources.yaml       # RSS source configuration
│   │   └── loader.py          # Config loader
│   ├── common/
│   │   ├── http.py            # HTTP utilities
│   │   ├── hashing.py         # Hash functions
│   │   ├── logging.py         # Logging setup
│   │   └── time.py            # Time utilities
│   ├── ingest/                # INGESTION PIPELINE
│   │   ├── fetch_rss.py       # RSS fetching
│   │   ├── extract_article.py # Article extraction
│   │   ├── clean.py           # Text cleaning
│   │   ├── dedupe.py          # Deduplication
│   │   ├── chunk.py           # Text chunking
│   │   ├── embed.py           # Embedding generation
│   │   └── index.py           # ChromaDB indexing
│   ├── verify/                # VERIFICATION PIPELINE
│   │   ├── enhance.py         # Query Enhancement Agent
│   │   ├── retrieve.py        # Evidence retrieval
│   │   ├── analyze.py         # Verification + agentic decision
│   │   ├── search.py          # External search + caching
│   │   ├── output.py          # Result formatting
│   │   └── parse.py           # Claim parsing
│   └── store/
│       ├── sqlite.py          # SQLite operations
│       └── chroma.py          # ChromaDB operations
├── data/
│   ├── news.db                # SQLite database
│   └── chroma/                # ChromaDB persistence
└── pyproject.toml             # Dependencies
```
