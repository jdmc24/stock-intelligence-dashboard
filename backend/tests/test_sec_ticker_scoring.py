"""Unit tests for SEC ticker matching heuristics (no network)."""

from __future__ import annotations

from app.services.sec_ticker_registry import SecCompanyEntry, _score_match, significant_query_tokens


PNC = SecCompanyEntry(ticker="PNC", title="PNC FINANCIAL SERVICES GROUP, INC")
HBAN = SecCompanyEntry(ticker="HBAN", title="HUNTINGTON BANCSHARES INC /MD/")


def test_significant_tokens_drop_generic_bank():
    assert significant_query_tokens("pnc bank") == ["pnc"]


def test_pnc_bank_scores_against_pnc():
    assert _score_match("pnc bank", PNC) >= 195.0


def test_lowercase_pnc_scores():
    assert _score_match("pnc", PNC) >= 195.0


def test_huntington_bancshares_scores():
    assert _score_match("huntington bancshares", HBAN) >= 80.0


def test_generic_bank_alone_scores_zero():
    assert _score_match("bank", PNC) == 0.0


def test_substring_words_do_not_false_match():
    assert _score_match("were", PNC) == 0.0
    assert _score_match("earning", PNC) == 0.0
