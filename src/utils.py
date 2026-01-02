from datetime import datetime, timedelta


def get_latest_quarter() -> tuple[int, int]:
    """
    Get the latest SEC quarter with available 13F filings.

    Returns (year, quarter) tuple.

    13F filings are due 45 days after quarter end. We add 50 days buffer
    to ensure filings are available.
    """
    today = datetime.now()
    year = today.year

    quarters = [
        (1, 3, 31),  # Q1
        (2, 6, 30),  # Q2
        (3, 9, 30),  # Q3
        (4, 12, 31),  # Q4
    ]

    for q, month, day in reversed(quarters):
        deadline = datetime(year, month, day) + timedelta(days=50)
        if today > deadline:
            return year, q

    # If no quarter is ready this year, use Q4 of last year
    return year - 1, 4
