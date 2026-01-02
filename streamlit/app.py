import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://admin:admin@localhost:5432/hedge_fund_tracker"
)


@st.cache_resource
def get_engine():
    return create_engine(DATABASE_URL, pool_pre_ping=True)


@st.cache_data(ttl=300)
def get_securities_with_tickers():
    engine = get_engine()
    query = """
        SELECT MIN(s.id) as id, s.ticker, MIN(s.name) as name
        FROM securities s
        JOIN holdings h ON h.security_id = s.id
        WHERE s.ticker IS NOT NULL
        GROUP BY s.ticker
        ORDER BY s.ticker
    """
    with engine.connect() as conn:
        return pd.read_sql(text(query), conn)


@st.cache_data(ttl=300)
def get_top_holders(ticker: str, limit: int = 10):
    engine = get_engine()
    query = """
        SELECT 
            hf.name as fund_name,
            SUM(h.value) as total_value,
            SUM(h.shares) as total_shares
        FROM holdings h
        JOIN filings f ON f.id = h.filing_id
        JOIN hedge_funds hf ON hf.id = f.hedge_fund_id
        JOIN securities s ON s.id = h.security_id
        WHERE s.ticker = :ticker
        GROUP BY hf.id, hf.name
        ORDER BY total_value DESC
        LIMIT :limit
    """
    with engine.connect() as conn:
        return pd.read_sql(text(query), conn, params={"ticker": ticker, "limit": limit})


@st.cache_data(ttl=300)
def get_related_holdings(ticker: str, limit: int = 10):
    engine = get_engine()
    query = """
        WITH funds_holding_security AS (
            SELECT DISTINCT f.hedge_fund_id
            FROM holdings h
            JOIN filings f ON f.id = h.filing_id
            JOIN securities s ON s.id = h.security_id
            WHERE s.ticker = :ticker
        )
        SELECT 
            COALESCE(s.ticker, s.name) as security_name,
            s.ticker,
            SUM(h.value) as total_value,
            COUNT(DISTINCT f.hedge_fund_id) as fund_count
        FROM holdings h
        JOIN filings f ON f.id = h.filing_id
        JOIN securities s ON s.id = h.security_id
        WHERE f.hedge_fund_id IN (SELECT hedge_fund_id FROM funds_holding_security)
          AND (s.ticker IS NULL OR s.ticker != :ticker)
        GROUP BY s.ticker, s.name
        ORDER BY total_value DESC
        LIMIT :limit
    """
    with engine.connect() as conn:
        return pd.read_sql(text(query), conn, params={"ticker": ticker, "limit": limit})


@st.cache_data(ttl=300)
def get_fund_coverage(ticker: str):
    engine = get_engine()

    with engine.connect() as conn:
        total_query = "SELECT COUNT(DISTINCT hedge_fund_id) as total FROM filings"
        total_df = pd.read_sql(text(total_query), conn)
        total_funds = total_df["total"].iloc[0]

        holding_query = """
            SELECT COUNT(DISTINCT f.hedge_fund_id) as holding
            FROM holdings h
            JOIN filings f ON f.id = h.filing_id
            JOIN securities s ON s.id = h.security_id
            WHERE s.ticker = :ticker
        """
        holding_df = pd.read_sql(text(holding_query), conn, params={"ticker": ticker})
        holding_funds = holding_df["holding"].iloc[0]

    return holding_funds, total_funds


@st.cache_data(ttl=300)
def get_all_holders(ticker: str):
    engine = get_engine()
    query = """
        SELECT 
            hf.name as "Fund Name",
            SUM(h.value) as "Value ($)"
        FROM holdings h
        JOIN filings f ON f.id = h.filing_id
        JOIN hedge_funds hf ON hf.id = f.hedge_fund_id
        JOIN securities s ON s.id = h.security_id
        WHERE s.ticker = :ticker
        GROUP BY hf.id, hf.name
        ORDER BY "Value ($)" DESC
    """
    with engine.connect() as conn:
        return pd.read_sql(text(query), conn, params={"ticker": ticker})


# Page config
st.set_page_config(page_title="Hedge Fund Tracker", page_icon="📊", layout="wide")

st.title("📊 Hedge Fund Tracker")
st.markdown("Explore which hedge funds hold which securities")

# Get securities
securities_df = get_securities_with_tickers()

if securities_df.empty:
    st.error("No securities found. Run `make data` to load holdings data.")
    st.stop()

# Dropdown to select ticker
ticker_options: list[str] = securities_df["ticker"].tolist()
selected_ticker: str = st.selectbox(
    "Select a security",
    options=ticker_options,
    format_func=lambda x: f"{x} - {securities_df[securities_df['ticker'] == x]['name'].iloc[0][:50]}",  # type: ignore[union-attr]
)  # type: ignore[assignment]

# Get security name for display
security_row = securities_df[securities_df["ticker"] == selected_ticker].iloc[0]
security_name: str = security_row["name"]  # type: ignore[assignment]

st.markdown(f"### {selected_ticker} - {security_name}")

# Layout: 3 columns
col1, col2, col3 = st.columns([2, 2, 1.5])

# Column 1: Top holders bar chart
with col1:
    st.subheader("Top 10 Holders")

    holders_df = get_top_holders(selected_ticker)

    if not holders_df.empty:
        # Shorten fund names for display
        holders_df["short_name"] = holders_df["fund_name"].str[:25]

        fig = px.bar(
            holders_df,
            x="total_value",
            y="short_name",
            orientation="h",
            labels={"total_value": "Value ($)", "short_name": ""},
            color="total_value",
            color_continuous_scale="Blues",
        )
        fig.update_layout(
            showlegend=False,
            coloraxis_showscale=False,
            yaxis={"categoryorder": "total ascending"},
            height=400,
            margin=dict(l=0, r=0, t=10, b=0),
        )
        fig.update_traces(
            hovertemplate="<b>%{y}</b><br>Value: %{x:$,.0f}<extra></extra>"
        )
        st.plotly_chart(fig)
    else:
        st.info("No holders found for this security")

# Column 2: Related holdings bar chart
with col2:
    st.subheader("Top Holdings by These Funds")

    related_df = get_related_holdings(selected_ticker)

    if not related_df.empty:
        fig = px.bar(
            related_df,
            x="total_value",
            y="security_name",
            orientation="h",
            labels={"total_value": "Value ($)", "security_name": ""},
            color="total_value",
            color_continuous_scale="Greens",
        )
        fig.update_layout(
            showlegend=False,
            coloraxis_showscale=False,
            yaxis={"categoryorder": "total ascending"},
            height=400,
            margin=dict(l=0, r=0, t=10, b=0),
        )
        fig.update_traces(
            hovertemplate="<b>%{y}</b><br>Value: %{x:$,.0f}<extra></extra>"
        )
        st.plotly_chart(fig)
    else:
        st.info("No related holdings found")

# Column 3: Pie chart
with col3:
    st.subheader("Fund Coverage")

    holding_funds, total_funds = get_fund_coverage(selected_ticker)
    not_holding = total_funds - holding_funds

    fig = go.Figure(
        data=[
            go.Pie(
                labels=["Holding", "Not Holding"],
                values=[holding_funds, not_holding],
                hole=0.4,
                marker_colors=["#2E86AB", "#E8E8E8"],
                textinfo="value",
                hovertemplate="<b>%{label}</b><br>%{value} funds<br>%{percent}<extra></extra>",
            )
        ]
    )
    fig.update_layout(
        height=300,
        margin=dict(l=0, r=0, t=10, b=0),
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5),
    )
    st.plotly_chart(fig)

    st.metric(label="Funds Holding", value=f"{holding_funds} / {total_funds}")
    st.caption(f"{holding_funds/total_funds*100:.1f}% of tracked funds")

# All Holders table
st.divider()
st.subheader("All Holders")

all_holders_df = get_all_holders(selected_ticker)

if not all_holders_df.empty:
    # Format for display
    display_df = all_holders_df.copy()
    display_df["Value ($)"] = display_df["Value ($)"].apply(
        lambda x: f"${x:,.0f}" if pd.notna(x) else "N/A"
    )

    st.dataframe(display_df, width="stretch", hide_index=True)

    # Summary stats
    total_value = all_holders_df["Value ($)"].sum()
    st.caption(f"**Total:** {len(all_holders_df)} holders | ${total_value:,.0f}")
else:
    st.info("No holders found for this security")
