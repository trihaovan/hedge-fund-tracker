"""
Initialize Database with 13F Holdings Data
===========================================

Fetches 13F filings from SEC and populates the Postgres database.

Usage:
    python initialize_db.py                    # Fetch from SEC
    python initialize_db.py --use-preloaded    # Load from CSV files    python initialize_db.py --refresh          # Clear DB and refetch
Prerequisites:
    1. Start Postgres: docker-compose up -d
"""

import argparse
import asyncio
import edgar
import os
import pandas as pd
from dotenv import load_dotenv
from pydantic import BaseModel
from psycopg2.extras import execute_values
import psycopg2
from typing import Optional

from .utils import get_latest_quarter
from .get_hedge_funds import (
    get_hedge_fund_names_with_variations,
    match_hedge_funds_to_filings,
)

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://admin:admin@localhost:5432/hedge_fund_tracker"
)

APP_NAME = os.getenv("APP_NAME")
EMAIL = os.getenv("EMAIL")

edgar.set_identity(f"{APP_NAME} {EMAIL}")

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")


class Holding(BaseModel):
    cusip: Optional[str] = None
    name: Optional[str] = None
    ticker: Optional[str] = None
    class_title: Optional[str] = None
    shares: int = 0
    value: int = 0
    cik: Optional[int] = None
    filing_date: Optional[str] = None


def get_db_connection():
    """Get a database connection."""
    return psycopg2.connect(DATABASE_URL)


def clear_database(conn):
    """Clear all data from the database tables."""
    with conn.cursor() as cur:
        # Delete in order respecting foreign keys
        cur.execute(
            "TRUNCATE TABLE holdings, filings, securities, hedge_funds RESTART IDENTITY CASCADE"
        )
    conn.commit()
    print("  Database cleared!")


def insert_hedge_funds(conn, hedge_funds) -> dict[int, int]:
    """Insert hedge funds and return CIK -> DB ID mapping."""
    cik_to_id = {}
    rows = [(str(hf.cik), hf.name) for hf in hedge_funds]

    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO hedge_funds (cik, name) VALUES %s
            ON CONFLICT (cik) DO UPDATE SET name = EXCLUDED.name
        """,
            rows,
        )

        # Fetch all IDs
        cur.execute(
            "SELECT cik, id FROM hedge_funds WHERE cik = ANY(%s)",
            ([str(hf.cik) for hf in hedge_funds],),
        )
        for cik, id in cur.fetchall():
            cik_to_id[int(cik)] = id

    conn.commit()
    return cik_to_id


def insert_securities(conn, holdings_data: list[Holding]) -> dict[str, int]:
    cusip_to_id = {}
    securities = {}
    for h in holdings_data:
        if h.cusip and h.cusip not in securities:
            securities[h.cusip] = {"name": h.name or "Unknown", "ticker": h.ticker}

    rows = [(cusip, info["name"], info["ticker"]) for cusip, info in securities.items()]

    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO securities (cusip, name, ticker) VALUES %s
            ON CONFLICT (cusip) DO UPDATE SET 
                name = EXCLUDED.name,
                ticker = COALESCE(EXCLUDED.ticker, securities.ticker)
        """,
            rows,
        )

        # Fetch all IDs
        cur.execute(
            "SELECT cusip, id FROM securities WHERE cusip = ANY(%s)",
            (list(securities.keys()),),
        )
        for cusip, id in cur.fetchall():
            cusip_to_id[cusip] = id

    conn.commit()
    return cusip_to_id


def insert_filing(conn, hedge_fund_id: int, filing_date: str, quarter: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO filings (hedge_fund_id, filing_date, quarter) VALUES (%s, %s, %s)
            ON CONFLICT (hedge_fund_id, quarter) DO UPDATE SET filing_date = EXCLUDED.filing_date
            RETURNING id
        """,
            (hedge_fund_id, filing_date, quarter),
        )
        return cur.fetchone()[0]


def insert_all_filings_and_holdings(
    conn, holdings_by_cik: dict, cik_to_id: dict, cusip_to_id: dict, quarter_str: str
):
    # First batch insert all filings
    filing_rows = []
    for cik, data in holdings_by_cik.items():
        hedge_fund_id = cik_to_id.get(cik)
        if hedge_fund_id:
            filing_rows.append((hedge_fund_id, data["filing_date"], quarter_str))

    with conn.cursor() as cur:
        execute_values(
            cur,
            """
            INSERT INTO filings (hedge_fund_id, filing_date, quarter) VALUES %s
            ON CONFLICT (hedge_fund_id, quarter) DO UPDATE SET filing_date = EXCLUDED.filing_date
        """,
            filing_rows,
        )

        # Get filing IDs
        cur.execute(
            """
            SELECT hedge_fund_id, id FROM filings WHERE quarter = %s AND hedge_fund_id = ANY(%s)
        """,
            (
                quarter_str,
                [
                    cik_to_id.get(cik)
                    for cik in holdings_by_cik.keys()
                    if cik_to_id.get(cik)
                ],
            ),
        )
        hf_id_to_filing_id = {row[0]: row[1] for row in cur.fetchall()}

    # Delete existing holdings for these filings
    filing_ids = list(hf_id_to_filing_id.values())
    with conn.cursor() as cur:
        cur.execute("DELETE FROM holdings WHERE filing_id = ANY(%s)", (filing_ids,))

    # Batch insert all holdings
    holding_rows = []
    for cik, data in holdings_by_cik.items():
        hedge_fund_id = cik_to_id.get(cik)
        if not hedge_fund_id:
            continue
        filing_id = hf_id_to_filing_id.get(hedge_fund_id)
        if not filing_id:
            continue
        for h in data["holdings"]:
            security_id = cusip_to_id.get(h.cusip) if h.cusip else None
            if (
                security_id and h.value
            ):  # Only require value, shares can be 0 for some securities
                holding_rows.append((filing_id, security_id, h.shares or 0, h.value))

    if holding_rows:
        with conn.cursor() as cur:
            execute_values(
                cur,
                "INSERT INTO holdings (filing_id, security_id, shares, value) VALUES %s",
                holding_rows,
            )

    conn.commit()
    return len(holding_rows)


def extract_holdings_from_filing(filing) -> list[Holding]:
    holdings = []
    try:
        thirteenf = filing.obj()
        if thirteenf and thirteenf.holdings is not None:
            df = thirteenf.holdings
            for _, row in df.iterrows():
                if row.get("Type") != "Shares":
                    continue
                holdings.append(
                    Holding(
                        cusip=row.get("Cusip"),
                        name=row.get("Issuer"),
                        ticker=row.get("Ticker"),
                        class_title=row.get("Class"),
                        shares=int(row.get("SharesPrnAmount", 0)),
                        value=int(row.get("Value", 0)),
                    )
                )
    except Exception as e:
        print(f"  Error: {e}")
    return holdings


def export_to_csv(hedge_funds, all_holdings: list[Holding], quarter_str):
    """Export data to CSV files for later reloading."""
    os.makedirs(DATA_DIR, exist_ok=True)

    # Export hedge funds
    hf_data = [{"cik": hf.cik, "name": hf.name} for hf in hedge_funds]
    hf_df = pd.DataFrame(hf_data)
    hf_path = os.path.join(DATA_DIR, f"hedge_funds_{quarter_str}.csv")
    hf_df.to_csv(hf_path, index=False)
    print(f"  Exported hedge funds to {hf_path}")

    # Export holdings (includes security info)
    holdings_df = pd.DataFrame([h.model_dump() for h in all_holdings])
    holdings_path = os.path.join(DATA_DIR, f"holdings_{quarter_str}.csv")
    holdings_df.to_csv(holdings_path, index=False)
    print(f"  Exported holdings to {holdings_path}")


def load_from_csv(quarter_str) -> tuple[list, list[Holding]]:
    hf_path = os.path.join(DATA_DIR, f"hedge_funds_{quarter_str}.csv")
    holdings_path = os.path.join(DATA_DIR, f"holdings_{quarter_str}.csv")

    if not os.path.exists(hf_path) or not os.path.exists(holdings_path):
        raise FileNotFoundError(
            f"CSV files not found for {quarter_str}. Run without --use-preloaded first."
        )

    hf_df = pd.read_csv(hf_path)

    class HedgeFundRecord:
        def __init__(self, cik, name):
            self.cik = int(cik)
            self.name = name

    hedge_funds = [
        HedgeFundRecord(row["cik"], row["name"]) for _, row in hf_df.iterrows()
    ]

    holdings_df = pd.read_csv(holdings_path)
    all_holdings = []
    for record in holdings_df.to_dict("records"):
        # Convert NaN to None and ensure cik is int
        cleaned = {}
        for k, v in record.items():
            if pd.isna(v):
                cleaned[k] = None
            elif k == "cik" and v is not None:
                cleaned[k] = int(v)
            else:
                cleaned[k] = v
        all_holdings.append(Holding(**cleaned))

    return hedge_funds, all_holdings


async def main(use_preloaded: bool = False, refresh: bool = False):
    print("=" * 60)
    print("Initialize Database with 13F Holdings")
    print("=" * 60)

    year, quarter = get_latest_quarter()
    quarter_str = f"{year}_Q{quarter}"

    print(f"\nQuarter: {quarter_str}")
    mode = (
        "Refreshing DB"
        if refresh
        else ("Loading from CSV" if use_preloaded else "Fetching from SEC")
    )
    print(f"Mode: {mode}")

    if use_preloaded:
        # Load from CSV files
        print("\nLoading data from CSV files...")
        try:
            hedge_funds, all_holdings = load_from_csv(quarter_str)
            print(f"  Loaded {len(hedge_funds)} hedge funds")
            print(f"  Loaded {len(all_holdings)} holdings")
        except FileNotFoundError as e:
            print(f"Error: {e}")
            return
    else:
        print("\nFetching 13F filings index from SEC...")
        filings = edgar.get_filings(year, quarter, form="13F-HR")
        if filings is None:
            print("No filings returned from SEC.")
            return
        company_to_cik = {f.company: f.cik for f in filings}
        print(f"  Total 13F-HR filings: {len(company_to_cik)}")

        print("\nGetting hedge fund names and variations...")
        hedge_fund_names = await get_hedge_fund_names_with_variations()
        print(f"  Wikipedia hedge funds: {len(hedge_fund_names)}")

        print("\nMatching hedge funds to 13F filers...")
        hedge_funds = match_hedge_funds_to_filings(hedge_fund_names, company_to_cik)
        print(f"  Matched hedge funds: {len(hedge_funds)}")

        if not hedge_funds:
            print("Error: No hedge funds matched. Check matching threshold.")
            return

        hedge_fund_ciks = {hf.cik for hf in hedge_funds}
        hedge_fund_13f = [f for f in filings if f.cik in hedge_fund_ciks]
        print(f"  13F filings to process: {len(hedge_fund_13f)}")

        print("\nProcessing 13F filings...")
        print("-" * 60)

        all_holdings: list[Holding] = []

        for filing in hedge_fund_13f:
            print(f"  Processing: {filing.company}...")

            holdings = extract_holdings_from_filing(filing)
            if holdings:
                for h in holdings:
                    h.cik = filing.cik
                    h.filing_date = str(filing.filing_date)

                all_holdings.extend(holdings)
                print(f"    -> {len(holdings)} holdings")
            else:
                print("    -> No holdings found")

        print("-" * 60)
        print(f"Total holdings extracted: {len(all_holdings)}")

        if not all_holdings:
            print("No holdings to insert.")
            return

        print("\nExporting data to CSV...")
        export_to_csv(hedge_funds, all_holdings, quarter_str)

    print("\nConnecting to database...")
    try:
        conn = get_db_connection()
        print("Connected!")
    except Exception as e:
        print(f"Error connecting to database: {e}")
        print("Make sure Postgres is running: docker-compose up -d")
        return

    try:
        # Clear database if refresh requested
        if refresh:
            print("\nClearing database...")
            clear_database(conn)

        # Insert hedge funds
        print("\nInserting hedge funds...")
        cik_to_id = insert_hedge_funds(conn, hedge_funds)
        print(f"  {len(cik_to_id)} hedge funds in database")

        # Insert securities
        print("\nInserting securities...")
        cusip_to_id = insert_securities(conn, all_holdings)
        print(f"  {len(cusip_to_id)} securities in database")

        # Group holdings by CIK
        print("\nInserting filings and holdings...")
        holdings_by_cik: dict[int, dict] = {}
        for h in all_holdings:
            cik = h.cik
            if cik is None:
                continue
            if cik not in holdings_by_cik:
                holdings_by_cik[cik] = {"filing_date": h.filing_date, "holdings": []}
            holdings_by_cik[cik]["holdings"].append(h)

        # Batch insert filings and holdings
        total_holdings = insert_all_filings_and_holdings(
            conn, holdings_by_cik, cik_to_id, cusip_to_id, quarter_str
        )

        print()
        print("=" * 60)
        print("Done!")
        print(f"  - {len(cik_to_id)} hedge funds")
        print(f"  - {len(cusip_to_id)} securities")
        print(f"  - {len(holdings_by_cik)} filings")
        print(f"  - {total_holdings} holdings")
        print("=" * 60)

    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Initialize hedge fund tracker database"
    )
    parser.add_argument(
        "--use-preloaded",
        action="store_true",
        help="Load from CSV files instead of fetching from SEC",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Clear all database tables before inserting fresh data",
    )
    args = parser.parse_args()

    asyncio.run(main(use_preloaded=args.use_preloaded, refresh=args.refresh))
