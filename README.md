
# Hedge Fund Tracker

A tool to explore institutional 13F holdings data from the SEC. Select a ticker to see which hedge funds hold that security, discover related holdings, and analyse fund coverage across your tracked universe.

## Features

- **Ticker Search**: Select any security and instantly see which hedge funds hold it
- **Top Holders Chart**: Visualise the top 10 institutional holders by value
- **Related Holdings**: Discover what else the funds holding your selected security own
- **Fund Coverage**: See what proportion of tracked funds hold each security
- **All Holders Table**: Browse the complete list of institutional holders

## How It Works

1. **Data Source**: Holdings data is fetched from SEC EDGAR 13F filings using the [edgartools](https://github.com/dgunning/edgartools) library
2. **Fund Matching**: Wikipedia's list of hedge funds is matched to SEC filers using fuzzy matching and OpenAI-generated name variations
3. **Data Filtering**: Only share-based holdings are included (options and principal amounts are excluded)
4. **Storage**: Data is stored in PostgreSQL for fast querying
5. **Dashboard**: Streamlit provides an interactive web interface

## Requirements

- **Python 3.12+**
- **Docker** (for PostgreSQL database)
- **uv** (Python package manager) - [Install uv](https://docs.astral.sh/uv/getting-started/installation/)
- **OpenAI API Key** (optional - only needed for fetching fresh data)

## Quick Start

### 1. Clone and Setup

```bash
git clone <repository-url>
cd hedge-fund-tracker
```

### 2. Configure Environment

Copy the example environment file and update with your details:

```bash
cp .env.example .env
```

Edit `.env` with your configuration:

```dotenv
DATABASE_URL=postgresql://admin:admin@localhost:5432/hedge_fund_tracker
EMAIL="your-email@example.com"  # Required for SEC API
OPENAI_API_KEY="sk-..."         # Optional - for fresh data fetching
```

> **Note**: The `EMAIL` is required by the SEC for API access. If you don't have an OpenAI API key, the app will use preloaded data.

### 3. Run Everything

```bash
make
```

This single command will:
- Start the PostgreSQL database
- Load holdings data (uses preloaded data if no OpenAI key is configured)
- Launch the Streamlit dashboard

The app will be available at **http://localhost:8501**

## Make Commands

| Command | Description |
|---------|-------------|
| `make` | Start everything (database + data + Streamlit) |
| `make db` | Start the PostgreSQL database only |
| `make data` | Load data (auto-detects OpenAI key, falls back to preloaded) |
| `make data-fresh` | Force fresh data fetch from SEC (clears existing data) |
| `make streamlit` | Start the Streamlit app |
| `make stop` | Stop all services |
| `make clean` | Stop services and remove database volumes |
| `make help` | Show available commands |

## Manual Setup

If you prefer not to use Make:

### Start the Database

```bash
docker compose up -d
```

### Install Dependencies

```bash
uv sync
```

### Load Data

With preloaded data (no API key required):

```bash
uv run python -m src.initialize_db --use-preloaded
```

Or fetch fresh data from SEC (requires OpenAI API key):

```bash
uv run python -m src.initialize_db
```

To clear existing data and refetch:

```bash
uv run python -m src.initialize_db --refresh
```

### Start the Dashboard

```bash
uv run streamlit run streamlit/app.py
```

## Project Structure

```
hedge-fund-tracker/
├── Makefile                 # Build automation
├── docker-compose.yml       # PostgreSQL container config
├── pyproject.toml           # Python dependencies
├── sandbox.ipynb            # Jupyter notebook for data exploration
├── src/                     # Source code
│   ├── __init__.py
│   ├── initialize_db.py     # Data fetching and loading script
│   ├── get_hedge_funds.py   # Wikipedia scraping and fund matching
│   └── utils.py             # Shared utilities
├── streamlit/
│   └── app.py               # Dashboard application
├── data/                    # Preloaded CSV data
│   ├── hedge_funds_*.csv    # Matched hedge fund names
│   └── holdings_*.csv       # Holdings data
├── outputs/                 # Generated outputs (NVDA holders and presentation slides)
│   └── *.csv, *.pdf, etc.   # Exported data and presentations
└── postgres/
    └── schema.sql           # Database schema
```

## Data Pipeline

1. **Scrape Wikipedia** for list of major hedge funds
2. **Generate Name Variations** using OpenAI (handles "LLC" vs "L.L.C.", abbreviations, etc.)
3. **Match to SEC Filers** using fuzzy string matching (rapidfuzz)
4. **Fetch 13F Filings** from SEC EDGAR for matched funds
5. **Extract Holdings** and store in PostgreSQL
6. **Export to CSV** for future preloading

## Database Schema

- **hedge_funds**: CIK, name, matched Wikipedia name
- **securities**: CUSIP, ticker, security name
- **filings**: Filing metadata per fund per quarter
- **holdings**: Individual positions (security, shares, value)

## Troubleshooting

### Database Connection Issues

Ensure Docker is running and the database container is healthy:

```bash
docker compose ps
```

### Missing Data

If the dashboard shows no data, try reloading:

```bash
make data
```

### SEC Rate Limiting

The SEC EDGAR API has rate limits. If you encounter errors during fresh data fetches, wait a few minutes and try again.

## Technology Stack

- **Python 3.12** - Core language
- **edgartools** - SEC EDGAR API wrapper
- **PostgreSQL 17** - Data storage
- **Streamlit** - Dashboard framework
- **Plotly** - Interactive charts
- **rapidfuzz** - Fuzzy string matching
- **OpenAI** - Name variation generation
- **Docker** - Database containerisation
- **uv** - Fast Python package management
