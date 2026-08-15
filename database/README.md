# Turgot Database

This directory contains the database processing and vector store management for Turgot. It handles the ingestion, processing, and storage of French public administration data from Service-Public.fr into a ChromaDB vector database for efficient semantic search and RAG operations.

## Overview

The database module provides:

- **Data Acquisition**: Automated download of Service-Public.fr XML dumps
- **XML Processing**: Parsing and structuring of government administration data
- **Vector Database**: ChromaDB management with persistent storage
- **Embedding Generation**: Mistral AI-powered text embeddings for semantic search
- **Data Pipeline**: Complete ETL pipeline from raw XML to searchable vectors
- **Incremental Processing**: Smart change detection to process only modified files
- **Testing Framework**: Comprehensive testing utilities for vector operations

## Technical Stack

- **Vector Database**: ChromaDB with persistent file storage
- **AI/ML**:
  - LangChain for document processing and embeddings
  - Mistral AI for text embeddings
  - ChromaDB for vector similarity search
- **Data Processing**:
  - Python XML parsing with ElementTree
  - TQDM for progress tracking and monitoring
  - Loguru for structured logging
  - SQLite for change tracking
- **Python Version**: 3.13+
- **Package Management**: UV for dependency management

## Project Structure

```
database/
├── chroma_db/                    # ChromaDB persistent storage
│   ├── chroma.sqlite3           # SQLite database (546MB)
│   └── collections/             # Vector collections storage
├── data/                        # Raw and processed data
│   ├── xml_dumps/              # Downloaded XML files
│   └── processed/              # Cleaned and structured data
├── parse_xml_dump.py           # Main XML processing pipeline
├── incremental_parser.py       # Incremental processing with change detection
├── manage_incremental.py       # Management utilities for incremental processing
├── parse_xml_dump_debug.py     # Debug version with detailed logging
├── download.py                 # Data download automation
├── test_vector_db.py           # Vector database testing
├── test_turgot_vector.py      # Turgot-specific vector tests
├── test_parse_xml.ipynb        # Interactive XML parsing notebook
├── pyproject.toml              # Dependencies and project config
└── uv.lock                     # Locked dependency versions
```

## Data Sources

The system processes official French government data from:

### Service-Public.fr

- **XML Dumps**: Complete database exports from data.gouv.fr
- **Vosdroits Dataset**: Comprehensive rights and procedures information
- **Schema Definitions**: XML schema for proper data parsing
- **Update Frequency**: Regular updates to maintain data freshness

### BOFiP (tax doctrine)

- **API source**: [BOFiP publications en vigueur](https://data.economie.gouv.fr/explore/dataset/bofip-vigueur/) (~9k in-force documents)
- **Format**: JSON per record (`contenu`, `identifiant_juridique`, `permalien`, `serie`)
- **Chroma collection**: `bofip` (separate from `service_public`)
- **Update frequency**: Weekly (re-download + content-hash delta)

#### BOFiP pipeline

```bash
cd database

# 1. Download (~9k records from data.economie.gouv.fr API)
uv run python -m sources.bofip.download

# 2. Validate relevance without embeddings
uv run python -m sources.bofip.probe

# 3. Estimate embedding cost (~$1.9 for full corpus at mistral-embed rates)
uv run python -m sources.bofip.ingest --estimate-only

# 4. Pilot embed (first 100 docs) or full ingest
uv run python -m sources.bofip.ingest --max-documents 100
uv run python -m sources.bofip.ingest

# Or combined:
uv run python -m sources.bofip.run_update --skip-embed   # download only
uv run python -m sources.bofip.run_update --max-documents 200 --max-cost-usd 0.50

# Long-running full embed in tmux (resumable):
./scripts/run_bofip_ingest_tmux.sh
# Attach: tmux attach -t turgot-bofip
# Log:    tail -f /tmp/bofip_ingest.log
```

### Data Structure

The processed data includes:

- Administrative procedures and requirements
- Citizen rights and obligations
- Official forms and documents
- Contact information for government services
- Legal references and regulatory information

## Setup

### Prerequisites

- Python 3.13+
- Internet connection for data downloads
- Sufficient disk space (2GB+ for full database)
- Mistral AI API access for embeddings

### Installation

1. **Create and activate virtual environment**:

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

2. **Install dependencies** (using UV):

```bash
# Install UV if not available
pip install uv

# Install project dependencies
uv pip install -e .
```

3. **Set up environment variables**:

```bash
cp .env.example .env
```

Edit `.env` with your configuration:

```bash
# Required
MISTRAL_API_KEY=your_mistral_api_key_here

# Optional
LOG_LEVEL=INFO
CHROMA_DB_PATH=chroma_db/
BATCH_SIZE=100
MAX_WORKERS=4
```

## Usage

### Data Pipeline

#### 1. Download Data

Download the latest Service-Public.fr XML dumps:

```bash
python download.py
```

This will:

- Fetch the latest XML dumps from data.gouv.fr
- Extract compressed files to `data/xml_dumps/`
- Validate file integrity
- Clean up temporary files

#### 2. Process and Index Data

**Option A: Full Processing (Legacy)**
Process all XML files and create vector embeddings:

```bash
python parse_xml_dump.py
```

**Option B: Incremental Processing (Recommended)**
Process only changed files for efficiency:

```bash
python incremental_parser.py
```

The incremental processor will:

- Check file modification times and content hashes
- Process only files that have changed since last run
- Track processed files in a SQLite database
- Skip unchanged files to save time and API costs
- Handle new, modified, and deleted files automatically

#### 3. Debug Processing (Optional)

For detailed debugging and monitoring:

```bash
python parse_xml_dump_debug.py
```

Features:

- Detailed logging of each processing step
- Error handling and recovery
- Performance monitoring
- Memory usage tracking

### Incremental Processing Management

The incremental processing system includes powerful management tools:

#### Check Processing Status

```bash
# View overall statistics
python manage_incremental.py status

# List all tracked files
python manage_incremental.py list

# List files by data source
python manage_incremental.py list --source vosdroits
python manage_incremental.py list --source entreprendre
```

#### File Management

```bash
# Check status of specific file
python manage_incremental.py check --file "data/service-public/vosdroits-latest/some-file.xml"

# Remove tracking for specific file (will be reprocessed)
python manage_incremental.py remove --file "data/service-public/vosdroits-latest/some-file.xml"

# Clean up tracking for deleted files
python manage_incremental.py cleanup
```

#### Force Full Reprocessing

```bash
# Clear all tracking data (forces full reprocessing)
python manage_incremental.py clear
```

**⚠️ Warning**: This will cause all files to be reprocessed on the next run, which can be expensive in terms of time and API costs.

### Incremental Processing Benefits

- **Cost Efficiency**: Only process changed files, reducing API calls by 80-95%
- **Time Savings**: Skip unchanged files, processing time reduced by 70-90%
- **Smart Change Detection**: Uses both modification time and content hash for reliability
- **Automatic Cleanup**: Handles deleted files and orphaned tracking data
- **Flexible Management**: Easy to force reprocessing when needed

### When to Use Each Processing Method

**Use Incremental Processing (`incremental_parser.py`)**:
- Regular updates and maintenance
- After downloading new data
- When you want to minimize costs and time
- For production environments

**Use Full Processing (`parse_xml_dump.py`)**:
- Initial setup and first-time processing
- When you suspect tracking data is corrupted
- For testing and development
- When you want to ensure complete reprocessing

### Testing and Validation

#### Vector Database Tests

```