"""The optimised matcher must give exactly the same results as the original logic."""

import random
import time
from difflib import SequenceMatcher

from core.cross_platform_arb import MarketMatcher
from core.market_ref import ComparableMarket

TITLES = [
    "Will Trump win the 2028 presidential election?",
    "Trump wins 2028 election",
    "Will Biden approve the new bill?",
    "Will the Chiefs beat the Bills on Sep 8?",
    "Kansas City Chiefs vs Buffalo Bills, Sep 8",
    "Will the Lakers beat the Celtics on Dec 25?",
    "Boston Celtics at Los Angeles Lakers Dec 26",
    "Will Bitcoin be above $100,000 on December 31?",
    "Bitcoin price above 100k by year end",
    "Will Ethereum trade above $5,000 in June?",
    "Will BTC hit 150000 before 2027?",
    "Will the Fed cut rates at the March 2027 meeting?",
    "Fed cuts rates in March",
    "Will US unemployment be above 4.5% in January 2027?",
    "Unemployment rate above 4.5%",
    "Will CPI exceed 3.1% in May?",
    "Will Powell resign as Fed chair?",
    "Will OpenAI release GPT-6 before July?",
    "Will Elon Musk tweet about Dogecoin this week?",
    "Best Picture winner at the Oscars: The Brutalist",
    "Will the NBA finals go to 7 games?",
    "NFL: Packers vs Bears 12/8/24",
    "Will Harris win the popular vote?",
    "Which party will win the House in 2026?",
    "Will Republicans control the Senate after 2026?",
    "Will Solana flip Ethereum by market cap?",
    "Will Tesla deliver over 2 million cars in 2026?",
    "",
    "?",
]


def reference_similarity(m: MarketMatcher, a: str, b: str) -> float:
    """The original calculate_similarity, built from the unchanged helper methods."""
    is_sports, sports_score = m.is_sports_match(a, b)
    if is_sports and sports_score > 0.7:
        return sports_score
    is_person, person_score = m.is_same_person_event(a, b)
    if is_person and person_score > 0.7:
        return person_score
    na, nb = m.normalize_text(a), m.normalize_text(b)
    text_sim = SequenceMatcher(None, na, nb).ratio()
    ea, eb = m.extract_key_entities(a), m.extract_key_entities(b)
    if ea and eb:
        combined = 0.5 * text_sim + 0.5 * len(ea & eb) / max(len(ea), len(eb))
    else:
        combined = text_sim
    sports = ["nfl", "nba", "mlb", "nhl", "football", "basketball", "baseball", "hockey"]
    if {s for s in sports if s in a.lower()} & {s for s in sports if s in b.lower()}:
        combined = min(1.0, combined + 0.15)
    crypto = ["bitcoin", "btc", "ethereum", "eth", "solana", "sol"]
    if {c for c in crypto if c in a.lower()} & {c for c in crypto if c in b.lower()}:
        combined = min(1.0, combined + 0.2)
    return combined


def test_scores_are_identical_to_the_original_logic():
    m = MarketMatcher()
    for a in TITLES:
        for b in TITLES:
            assert abs(m.calculate_similarity(a, b) - reference_similarity(m, a, b)) < 1e-12, (a, b)


def test_floor_only_ever_skips_scores_below_the_floor():
    m = MarketMatcher()
    for floor in (0.3, 0.6, 0.9):
        for a in TITLES:
            for b in TITLES:
                exact = reference_similarity(m, a, b)
                fast = m.calculate_similarity(a, b, floor=floor)
                if exact >= floor:
                    assert abs(fast - exact) < 1e-12, (floor, a, b)
                else:
                    assert fast < floor, (floor, a, b)


async def test_bulk_matching_finds_the_same_pairs_as_before():
    rng = random.Random(3)
    a_refs = [ComparableMarket("polymarket", f"p{i}", t) for i, t in enumerate(TITLES) if t]
    b_refs = [ComparableMarket("kalshi", f"k{i}", t) for i, t in enumerate(rng.sample(TITLES, len(TITLES))) if t]
    m = MarketMatcher(min_similarity=0.5)
    pairs = await m.match_refs(a_refs, b_refs)

    expected = {}
    for ra in a_refs:
        cat = m._categorize_market(ra.title)
        if cat == "other":
            continue
        best, best_score = None, 0.0
        for rb in b_refs:
            if m._categorize_market(rb.title) != cat:
                continue
            score = reference_similarity(m, ra.title, rb.title)
            if score > best_score:
                best, best_score = rb, score
        if best and best_score >= 0.5:
            expected[(ra.market_id, best.market_id)] = best_score
    got = {(p.market_a_id, p.market_b_id): p.similarity_score for p in pairs}
    assert got.keys() == expected.keys()
    for k, v in expected.items():
        assert abs(got[k] - v) < 1e-12


def test_bulk_matching_is_much_faster():
    rng = random.Random(1)
    vocab = [w for t in TITLES for w in t.split()]
    texts_a = [" ".join(rng.choices(vocab, k=9)) + "?" for _ in range(150)]
    texts_b = [" ".join(rng.choices(vocab, k=9)) + "?" for _ in range(150)]
    m = MarketMatcher(min_similarity=0.6)

    start = time.perf_counter()
    for a in texts_a:
        for b in texts_b:
            reference_similarity(m, a, b)
    slow = time.perf_counter() - start

    start = time.perf_counter()
    for a in texts_a:
        best = 0.0
        for b in texts_b:
            s = m.calculate_similarity(a, b, floor=max(best, 0.6))
            best = max(best, s)
    fast = time.perf_counter() - start
    assert fast < slow / 2, f"expected at least 2x faster, got {slow / fast:.1f}x"
