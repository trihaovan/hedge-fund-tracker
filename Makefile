.PHONY: all db data data-fresh streamlit stop clean help

# Default target
all: db data streamlit

# Start the database
db:
	@echo "Starting database..."
	@docker compose up -d
	@echo "Waiting for database to be ready..."
	@sleep 3

# Load data - uses preloaded if no OpenAI API key
data: db
	@if [ -z "$$OPENAI_API_KEY" ] && ! grep -q "^OPENAI_API_KEY=" .env 2>/dev/null; then \
		echo "No OpenAI API key found, using preloaded data..."; \
		uv run python -m src.initialize_db --use-preloaded; \
	elif grep -q "^OPENAI_API_KEY=.*XXXX" .env 2>/dev/null; then \
		echo "OpenAI API key not configured, using preloaded data..."; \
		uv run python -m src.initialize_db --use-preloaded; \
	else \
		echo "OpenAI API key found, fetching fresh data from SEC..."; \
		uv run python -m src.initialize_db; \
	fi

# Force fresh data fetch (requires OpenAI API key)
data-fresh: db
	@echo "Fetching fresh data from SEC (requires OpenAI API key)..."
	uv run python -m src.initialize_db --refresh

# Start the Streamlit app
streamlit:
	@echo "Starting Streamlit app..."
	uv run streamlit run streamlit/app.py

# Stop all services
stop:
	@echo "Stopping services..."
	@docker compose down

# Clean up database and stop services
clean: stop
	@echo "Cleaning up..."
	@docker compose down -v

# Show help
help:
	@echo "Hedge Fund Tracker - Available commands:"
	@echo ""
	@echo "  make          - Start everything (db + data + streamlit)"
	@echo "  make db       - Start the database only"
	@echo "  make data     - Load data (auto-detects OpenAI key, falls back to preloaded)"
	@echo "  make data-fresh - Force fresh data fetch from SEC (clears existing data)"
	@echo "  make streamlit - Start the Streamlit app"
	@echo "  make stop     - Stop all services"
	@echo "  make clean    - Stop services and remove database volumes"
	@echo "  make help     - Show this help message"
