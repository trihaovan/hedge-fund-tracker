-- Hedge Fund Tracker Schema
-- Optimized for: ticker → funds AND fund → holdings queries

-- =============================================================================
-- CORE TABLES
-- =============================================================================

-- Hedge funds we track
CREATE TABLE IF NOT EXISTS hedge_funds (
    id SERIAL PRIMARY KEY,
    cik VARCHAR(20) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Securities (stocks, ETFs, etc.)
CREATE TABLE IF NOT EXISTS securities (
    id SERIAL PRIMARY KEY,
    cusip VARCHAR(9) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    ticker VARCHAR(10),  
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 13F filing metadata
CREATE TABLE IF NOT EXISTS filings (
    id SERIAL PRIMARY KEY,
    hedge_fund_id INTEGER REFERENCES hedge_funds(id),
    filing_date DATE NOT NULL,
    quarter VARCHAR(7) NOT NULL,  -- e.g., "2025_Q3"
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(hedge_fund_id, quarter)
);

-- Holdings (the core data)
CREATE TABLE IF NOT EXISTS holdings (
    id SERIAL PRIMARY KEY,
    filing_id INTEGER REFERENCES filings(id) ON DELETE CASCADE,
    security_id INTEGER REFERENCES securities(id),
    shares BIGINT NOT NULL,
    value BIGINT NOT NULL,  -- in dollars
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- =============================================================================
-- INDEXES FOR FAST QUERIES
-- =============================================================================

-- For "which funds own this stock?" queries
CREATE INDEX idx_holdings_security ON holdings(security_id);
CREATE INDEX idx_securities_cusip ON securities(cusip);
CREATE INDEX idx_securities_ticker ON securities(ticker);

-- For "what does this fund hold?" queries
CREATE INDEX idx_holdings_filing ON holdings(filing_id);
CREATE INDEX idx_filings_fund ON filings(hedge_fund_id);
CREATE INDEX idx_filings_quarter ON filings(quarter);

-- For fund lookups
CREATE INDEX idx_hedge_funds_cik ON hedge_funds(cik);

-- =============================================================================
-- USEFUL VIEWS
-- =============================================================================

-- Denormalized view for easy querying
CREATE OR REPLACE VIEW holdings_detail AS
SELECT 
    h.id as holding_id,
    hf.cik,
    hf.name as fund_name,
    s.cusip,
    s.ticker,
    s.name as security_name,
    h.shares,
    h.value,
    f.quarter,
    f.filing_date
FROM holdings h
JOIN filings f ON h.filing_id = f.id
JOIN hedge_funds hf ON f.hedge_fund_id = hf.id
JOIN securities s ON h.security_id = s.id;

-- Which funds own a stock (aggregated by quarter)
CREATE OR REPLACE VIEW stock_ownership AS
SELECT 
    s.cusip,
    s.ticker,
    s.name as security_name,
    f.quarter,
    COUNT(DISTINCT hf.id) as fund_count,
    SUM(h.shares) as total_shares,
    SUM(h.value) as total_value,
    ARRAY_AGG(DISTINCT hf.name) as fund_names
FROM holdings h
JOIN filings f ON h.filing_id = f.id
JOIN hedge_funds hf ON f.hedge_fund_id = hf.id
JOIN securities s ON h.security_id = s.id
GROUP BY s.cusip, s.ticker, s.name, f.quarter;

-- Fund portfolio summary
CREATE OR REPLACE VIEW fund_portfolio AS
SELECT 
    hf.cik,
    hf.name as fund_name,
    f.quarter,
    COUNT(h.id) as position_count,
    SUM(h.value) as total_value,
    f.filing_date
FROM holdings h
JOIN filings f ON h.filing_id = f.id
JOIN hedge_funds hf ON f.hedge_fund_id = hf.id
GROUP BY hf.cik, hf.name, f.quarter, f.filing_date;
