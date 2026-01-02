from bs4 import BeautifulSoup
from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from rapidfuzz import fuzz, process
from typing import List, Optional

import asyncio
import httpx
import os

load_dotenv()


OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

USER_AGENT = f"{os.environ.get("APP_NAME")} {os.environ.get("EMAIL")}"


def get_wiki_hedge_fund_names() -> list[str]:
    """
    Extract all hedge fund names from the Wikipedia 'List of hedge funds' HTML.

    Args:
        html_content: The raw HTML content of the Wikipedia page

    Returns:
        A list of hedge fund names extracted from the page
    """

    response = httpx.get(
        "https://en.wikipedia.org/wiki/List_of_hedge_funds",
        headers={"User-Agent": USER_AGENT},
        timeout=30,
    )
    response.raise_for_status()

    html_content = response.text
    soup = BeautifulSoup(html_content, "html.parser")

    hedge_funds = set()

    # Extract from the "Largest hedge fund firms" table
    tables = soup.find_all("table", class_="wikitable")
    for table in tables:
        rows = table.find_all("tr")
        for row in rows[1:]:  # Skip header row
            cells = row.find_all("td")
            if len(cells) >= 2:
                # The fund name is typically in the second cell
                fund_cell = cells[1]
                link = fund_cell.find("a")
                if link:
                    fund_name = link.get_text(strip=True)
                    if fund_name:
                        hedge_funds.add(fund_name)

    # Extract from the "Notable hedge fund firms" lists (Americas, Asia-Pacific, EMEA)
    div_cols = soup.find_all("div", class_="div-col")
    for div_col in div_cols:
        list_items = div_col.find_all("li")
        for item in list_items:
            link = item.find("a")
            if link:
                fund_name = link.get_text(strip=True)
                if fund_name:
                    hedge_funds.add(fund_name)

    # Sort and return as a list
    return sorted(hedge_funds)


openai_client = AsyncOpenAI()


class HedgeFundNames(BaseModel):
    name: str = Field(description="The original hedge fund name provided as input.")
    name_variations: list[str] = Field(
        default_factory=list,
        description="10 known or possible name variations for the hedge fund to be used in SEC searches for CIK.",
        min_length=10,
        max_length=10,
    )


class HedgeFund(BaseModel):
    name: str
    cik: int
    matched_name: str
    score: float


def match_hedge_funds_to_filings(
    funds: List[HedgeFundNames], company_to_cik: dict[str, int], threshold: int = 95
) -> List[HedgeFund]:
    matched_funds: List[HedgeFund] = []
    matched_ciks: set[int] = set()
    company_names = list(company_to_cik.keys())
    company_names_upper = [c.upper() for c in company_names]

    for fund in funds:
        names_to_try = [fund.name] + fund.name_variations

        best_match: Optional[tuple[str, float]] = None

        for name in names_to_try:
            result = process.extractOne(
                name.upper(),
                company_names_upper,
                scorer=fuzz.WRatio,
                score_cutoff=threshold,
            )

            if result:
                _, score, idx = result
                if best_match is None or score > best_match[1]:
                    best_match = (company_names[idx], score)

        if best_match:
            matched_company, score = best_match
            cik = company_to_cik[matched_company]
            if cik not in matched_ciks:
                matched_ciks.add(cik)
                matched_funds.append(
                    HedgeFund(
                        name=matched_company,
                        cik=cik,
                        matched_name=fund.name,
                        score=score,
                    )
                )

    return matched_funds


async def get_name_variations(fund_name: str) -> HedgeFundNames | None:
    sys_prompt = """You are a hedge fund expert with an in depth knowledge of all hedge funds
    You will be provided with the name of a hedge fund. You must come up with 10 name variations
    which will be used to search the SEC EDGAR database for their CIKs. if you happen to know the 
    exact name which is present in the EDGAR db, include that as the first entry in your output. 
    Case is unimportant as text will be normalised before searching"""

    response = await openai_client.beta.chat.completions.parse(
        model="gpt-5-mini",
        messages=[
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": fund_name},
        ],
        response_format=HedgeFundNames,
    )

    hedge_fund = response.choices[0].message.parsed
    if hedge_fund is None:
        return None
    hedge_fund.name = fund_name  # Ensure original name is preserved

    return hedge_fund


async def get_hedge_fund_names_with_variations() -> List[HedgeFundNames]:
    hedge_fund_names = get_wiki_hedge_fund_names()

    tasks = [get_name_variations(fund_name) for fund_name in hedge_fund_names]
    results = await asyncio.gather(*tasks)

    return [r for r in results if r is not None]
