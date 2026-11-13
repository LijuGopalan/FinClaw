"""The pre-market brief must not invent an earnings day."""

from datetime import date

from skills.financial_skills import coerce_earnings_dates
from skills.llm import apply_earnings_guard, build_market_context, classify_earnings


AS_OF = date(2026, 11, 12)
# What Yahoo returned for this session: both names report next year, not today.
CALENDAR = {
    "earnings": [
        {"ticker": "MSFT", "earnings_date": "2027-01-27", "earnings_dates": ["2027-01-27"]},
        {"ticker": "AAPL", "earnings_date": "2027-01-28", "earnings_dates": ["2027-01-28"]},
    ],
    "source": "yfinance (unofficial estimate)",
}


def test_yahoo_list_and_string_dates_stay_intact():
    assert coerce_earnings_dates([date(2027, 1, 27)]) == ["2027-01-27"]
    assert coerce_earnings_dates("2027-01-27") == ["2027-01-27"]
    assert coerce_earnings_dates([date(2027, 1, 27), date(2027, 2, 2)]) == [
        "2027-01-27",
        "2027-02-02",
    ]
    # Indexing a date string with [0] used to yield "2".
    assert coerce_earnings_dates("2027-01-27") != ["2"]


def test_msft_and_aapl_are_not_reporting_on_nov_12_2026():
    classified = classify_earnings(CALENDAR["earnings"], AS_OF)
    assert classified["reporting_today"] == []
    assert ("MSFT" in [ticker for _, ticker, _ in classified["upcoming"]])
    context = build_market_context({"earnings": CALENDAR, "as_of": "2026-11-12"})
    assert "REPORTING TODAY: none" in context
    assert "MSFT 2027-01-27" in context
    assert "AAPL 2027-01-28" in context


def test_estimate_window_is_not_a_confirmed_report_today():
    rows = [{"ticker": "NVDA", "earnings_dates": ["2026-11-12", "2026-11-13"]}]
    classified = classify_earnings(rows, AS_OF)
    assert classified["reporting_today"] == []
    assert classified["unconfirmed"]


def test_single_date_today_is_confirmed():
    rows = [{"ticker": "NVDA", "earnings_date": "2026-11-12"}]
    assert classify_earnings(rows, AS_OF)["reporting_today"] == ["NVDA"]


def test_blunder_sentence_is_removed_when_nobody_reports():
    brief = (
        "### Key Risks for Today\n"
        "1. **Earnings Season**: Several tech giants are scheduled to report earnings today, "
        "including Apple (AAPL) and Microsoft (MSFT). "
        "Earnings surprises can significantly impact stock prices.\n"
        "2. **Sector Rotation**: The tech-heavy SPY and QQQ indices are showing signs of weakness.\n"
    )
    cleaned = apply_earnings_guard(brief, {"earnings": CALENDAR, "as_of": "2026-11-12"})
    assert "scheduled to report earnings today" not in cleaned
    assert "Microsoft (MSFT)" not in cleaned
    assert "Sector Rotation" in cleaned
    assert "Earnings check: no covered company reports today." in cleaned
    assert "MSFT 2027-01-27" in cleaned


def test_negated_earnings_sentence_is_kept():
    text = "No covered companies report earnings today. SPY was flat."
    cleaned = apply_earnings_guard(text, {"earnings": CALENDAR, "as_of": "2026-11-12"})
    assert cleaned.startswith("No covered companies report earnings today.")


def test_confirmed_reporter_is_kept():
    text = "NVDA reports earnings today after the close. MSFT does not."
    payload = {
        "earnings": {"earnings": [{"ticker": "NVDA", "earnings_date": "2026-11-12"}]},
        "as_of": "2026-11-12",
    }
    cleaned = apply_earnings_guard(text, payload)
    assert "NVDA reports earnings today after the close." in cleaned


def test_missing_calendar_still_blocks_invented_reports():
    text = "Microsoft (MSFT) is scheduled to report earnings today."
    cleaned = apply_earnings_guard(text, {"as_of": "2026-11-12"})
    assert "scheduled to report" not in cleaned
    assert "Earnings check: no covered company reports today." in cleaned
    context = build_market_context({"as_of": "2026-11-12"})
    assert "EARNINGS CALENDAR: unavailable" in context
    assert "REPORTING TODAY: none" in context
