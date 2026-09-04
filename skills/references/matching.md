# Matching

How `search_and_match` decides a scraped Google Maps place is "the same business" as one of your own records, and how to use the scoring functions directly if you're matching against a candidate list you already have (e.g. from your own `search_places_adaptive` results) instead of letting `search_and_match` search for you.

## The Two Identity Types

* `BusinessIdentity(name, website=None)` — the business as your system knows it (a company/provider record). One `BusinessIdentity` typically covers many outlets.
* `OutletIdentity(name, phone=None, address=None)` — the specific location being matched. `name` here is usually the outlet/branch name, not the parent business name — pass the parent name too (as `BusinessIdentity.name`) since Google Business Profile listings are sometimes titled with the outlet name and sometimes the parent brand.

Both are plain dataclasses — construct them fresh per match attempt, don't share instances.

## Confidence Tiers

`match_place(place, outlet, business)` checks, in order of strength:

1. `phone_and_domain_match` — normalized phone AND normalized domain both match.
2. `phone_match` — phone matches, domain doesn't (or business has no website on record).
3. `domain_match` — domain matches, phone doesn't.
4. `exact_name_match` — no phone/domain signal, but the normalized place name exactly equals the normalized outlet or business name.

If none of the four fire, `match_place` returns `None` — there is no "weak match" tier below `exact_name_match`. A fuzzy/partial name match is not enough on its own; that's deliberate, since a partial-name-only match rate is where false positives across chains and franchises come from.

`is_definitive_match(place)` is `True` for any of the four reasons — used internally by `search_and_match` to stop scraping further candidates as soon as it finds one, rather than checking every result on the page.

## Gate Before You Scrape

`has_match_key(outlet, business)` tells you up front whether there's *any* chance of a match — phone, website, or a name to compare. If it's `False`, don't bother searching/scraping candidates at all; there's nothing to match against and you'll only burn browser time for a guaranteed `None`. `search_and_match` does not call this gate itself (it assumes you've already decided the record is worth attempting), so callers doing bulk enrichment should check it themselves before queuing a browser task:

```python
from gmbscraper import BusinessIdentity, OutletIdentity, has_match_key

if not has_match_key(outlet, business):
    continue  # nothing to match on — skip without touching the browser
```

## Scoring Your Own Candidate List

If you already have a list of scraped `PlaceProfile` candidates (e.g. you called `scrape_place` yourself in a loop) and just need to pick the best one, skip `search_and_match` and use the scoring functions directly:

```python
from gmbscraper import match_place, pick_best_match

scored = [
    matched for place in candidates if (matched := match_place(place, outlet, business)) is not None
]
best = pick_best_match(scored)  # None if scored is empty
```

`pick_best_match` sorts by confidence tier first, then by `PlaceProfile.rank` (position in your candidate list) as a tiebreaker — pass the `rank` you scraped each candidate at (`scrape_place(url, rank=i)`) so ties resolve toward earlier/more relevant search results.

## Normalization Gotchas

* `normalize_phone` assumes AU-style numbers: it strips a `+61`/`0011 61` prefix down to a local `0`-leading number, then compares the last 9 digits. Phone matching against non-AU/NZ numbers may under-match.
* `normalize_domain` unwraps Google's `google.com/url?q=...` redirect links before comparing, and treats a fixed list of AU/NZ multi-part suffixes (`com.au`, `co.nz`, `org.au`, ...) as part of the registrable domain rather than stripping them like an ordinary two-part TLD.
* `normalize_name` strips legal suffixes (`pty`, `ltd`, `inc`, ...) and a fixed stop-word list (`the`, `group`, `services`, `co`, ...) before comparing — two differently-branded businesses that both reduce to the same stripped name (e.g. two outlets both named "The Community Group") would collide on `exact_name_match`. Combine name matching with phone/domain whenever you have them; don't rely on name alone for anything you can't afford to get wrong.
