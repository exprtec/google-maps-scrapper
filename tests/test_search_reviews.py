from __future__ import annotations

from gmbscraper._search_reviews import place_feature_id


def test_place_feature_id_reads_maps_place_urls() -> None:
    url = (
        "https://www.google.com/maps/place/Best+Builders/@31.44,73.17,17z/data=!3m1!4b1!4m6!3m5"
        "!1s0x3922691029581c13:0x1B3FF9D4247B4509!8m2"
    )
    assert place_feature_id(url) == "0x3922691029581c13:0x1b3ff9d4247b4509"


def test_place_feature_id_reads_search_review_fragments() -> None:
    url = "https://www.google.com/search?q=x#lrd=0x3922691029581c13:0x1b3ff9d4247b4509,1,,,,"
    assert place_feature_id(url) == "0x3922691029581c13:0x1b3ff9d4247b4509"


def test_place_feature_id_is_empty_without_one() -> None:
    assert place_feature_id("https://maps.google.com/?cid=1963562652097266953") == ""
    assert place_feature_id("") == ""
