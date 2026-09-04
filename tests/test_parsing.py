from __future__ import annotations

from decimal import Decimal

from gmbscraper.parsing import (
    extract_lat_lng,
    extract_place_id,
    extract_place_name_from_url,
    is_generic_search_heading,
    normalize_domain,
    normalize_name,
    normalize_phone,
    normalize_text,
    parse_decimal,
    parse_int,
    parse_relative_date,
    parse_review_count_label,
    read_review_count_from_page_source,
)


def test_normalize_text_collapses_whitespace() -> None:
    assert normalize_text("  Acme   Plumbing \n Pty Ltd  ") == "Acme Plumbing Pty Ltd"
    assert normalize_text(None) == ""


def test_parse_decimal() -> None:
    assert parse_decimal("4.5 stars") == Decimal("4.5")
    assert parse_decimal("4,5") == Decimal("4.5")
    assert parse_decimal("no rating") is None


def test_parse_int() -> None:
    assert parse_int("1,234 reviews") == 1234
    assert parse_int("") is None


def test_parse_review_count_label() -> None:
    assert parse_review_count_label("1,234 reviews") == 1234
    assert parse_review_count_label("4.5 (87)") == 87
    assert parse_review_count_label("no reviews yet") is None


def test_parse_relative_date_units() -> None:
    from datetime import date

    ref = date(2026, 1, 10)
    assert parse_relative_date("just now", reference=ref) == "2026-01-10"
    assert parse_relative_date("2 days ago", reference=ref) == "2026-01-08"
    assert parse_relative_date("a week ago", reference=ref) == "2026-01-03"
    assert parse_relative_date("garbage") == ""


def test_extract_place_id_prefers_cid() -> None:
    assert extract_place_id("https://maps.google.com/?cid=12345") == "12345"
    assert extract_place_id("https://maps.google.com/maps/place/x/@0,0/data=!0x1:0x2") == "0x1:0x2"
    assert extract_place_id("https://maps.google.com/") == ""


def test_extract_lat_lng() -> None:
    lat, lng = extract_lat_lng("https://www.google.com/maps/place/x/@-33.87,151.21,15z")
    assert lat == Decimal("-33.87")
    assert lng == Decimal("151.21")
    assert extract_lat_lng("no coords here") == (None, None)


def test_extract_place_name_from_url() -> None:
    assert (
        extract_place_name_from_url("https://www.google.com/maps/place/Acme+Plumbing/@0,0")
        == "Acme Plumbing"
    )
    assert extract_place_name_from_url("https://www.google.com/maps/search/x") == ""


def test_normalize_phone_au_variants_converge() -> None:
    local = normalize_phone("0400 123 456")
    international = normalize_phone("+61 400 123 456")
    zero_zero_prefixed = normalize_phone("0011 61 400 123 456")
    assert local == international == zero_zero_prefixed


def test_normalize_domain_strips_www_and_unwraps_google_redirect() -> None:
    assert normalize_domain("https://www.acme.com.au/contact") == "acme.com.au"
    assert normalize_domain("acme.co.nz") == "acme.co.nz"
    assert normalize_domain("sub.acme.com") == "acme.com"
    assert (
        normalize_domain("https://www.google.com/url?q=https://acme.com.au&sa=D") == "acme.com.au"
    )


def test_normalize_name_strips_legal_and_stop_words() -> None:
    assert normalize_name("Acme Plumbing & Gas Pty Ltd") == "acme plumbing gas"
    assert normalize_name("The Acme Group") == "acme"


def test_is_generic_search_heading() -> None:
    assert is_generic_search_heading("Results")
    assert not is_generic_search_heading("Acme Plumbing")


def test_read_review_count_from_page_source() -> None:
    html = "window.APP_INITIALIZATION_STATE=[[null,[null,42,null,null,1]]]"
    assert read_review_count_from_page_source(html) == 42
    assert read_review_count_from_page_source("<html></html>") is None
