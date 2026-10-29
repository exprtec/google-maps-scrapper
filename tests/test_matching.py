from __future__ import annotations

from gmbscraper._matching import has_match_key, is_definitive_match, match_place, pick_best_match
from gmbscraper.models import BusinessIdentity, OutletIdentity, PlaceProfile


def test_has_match_key_requires_some_signal() -> None:
    assert not has_match_key(OutletIdentity(name=""), BusinessIdentity(name=""))
    assert has_match_key(OutletIdentity(name="", phone="0400123456"), BusinessIdentity(name=""))
    assert has_match_key(OutletIdentity(name=""), BusinessIdentity(name="Acme"))


def test_match_place_phone_and_domain_outranks_name() -> None:
    outlet = OutletIdentity(name="Acme Plumbing", phone="0400 123 456", address="1 Main St")
    business = BusinessIdentity(name="Acme Plumbing Pty Ltd", website="https://acme.com.au")
    place = PlaceProfile(
        name="Acme Plumbing", phone="0400123456", website="https://www.acme.com.au/"
    )
    matched = match_place(place, outlet, business)
    assert matched is not None
    assert matched.match_reason == "phone_and_domain_match"
    assert is_definitive_match(matched)


def test_match_place_falls_back_to_exact_name() -> None:
    outlet = OutletIdentity(name="Acme Plumbing")
    business = BusinessIdentity(name="Acme Plumbing")
    place = PlaceProfile(name="Acme Plumbing", phone="", website="", address="1 Main St")
    matched = match_place(place, outlet, business)
    assert matched is not None
    assert matched.match_reason == "exact_name_match"


def test_match_place_name_match_needs_no_conflicting_website() -> None:
    outlet = OutletIdentity(name="Connect Care Australia Pty Ltd", phone="0406 941 117")
    business = BusinessIdentity(name="Connect Care Australia Pty Ltd", website="connectcare.com.au")
    place = PlaceProfile(
        name="Care Connect",
        phone="1800 692 464",
        website="https://careconnect.org.au/",
        address="14 Lexington Dr, Bella Vista NSW 2153",
    )
    assert match_place(place, outlet, business) is None

    place.website = "https://connectcare.net.au/"
    assert match_place(place, outlet, business) is not None

    place.website = ""
    matched = match_place(place, outlet, business)
    assert matched is not None
    assert matched.match_reason == "exact_name_match"


def test_match_place_name_match_skips_suburbs() -> None:
    outlet = OutletIdentity(name="Rosebery Clinic", address="Rosebery, NSW, 2018")
    business = BusinessIdentity(name="Lifehackers Institute")
    assert match_place(PlaceProfile(name="Rosebery"), outlet, business) is None

    place = PlaceProfile(name="Rosebery", phone="0400 000 000", address="Rosebery NSW 2018")
    assert match_place(place, outlet, business) is None


def test_match_place_returns_none_without_any_signal() -> None:
    outlet = OutletIdentity(name="Acme Plumbing", phone="0400 123 456")
    business = BusinessIdentity(name="Acme Plumbing")
    place = PlaceProfile(name="Totally Different Co", phone="0499999999", website="other.com")
    assert match_place(place, outlet, business) is None


def test_pick_best_match_prefers_stronger_reason_then_earlier_rank() -> None:
    weak = PlaceProfile(rank=1, match_reason="exact_name_match")
    strong = PlaceProfile(rank=3, match_reason="phone_match")
    assert pick_best_match([weak, strong]) is strong

    tied_a = PlaceProfile(rank=2, match_reason="domain_match")
    tied_b = PlaceProfile(rank=1, match_reason="domain_match")
    assert pick_best_match([tied_a, tied_b]) is tied_b

    assert pick_best_match([]) is None
