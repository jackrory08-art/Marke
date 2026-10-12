"""Deterministic offline provider for tests, the simulation demo and screenshots.

Enabled only with ``ai.provider: mock`` and labelled MOCK in the UI. It applies
simple text heuristics to the prompt, so it is *not* a real verifier.
"""

import json
import re
from typing import Optional

from core.ai.provider import LLMProvider, ProviderBadOutput, StructuredResult, T, Usage

_WORD = re.compile(r"[a-z0-9]+")
_NUM = re.compile(r"\d[\d,]*\.?\d*\s*[km]?", re.I)
_NOISE = {"will", "the", "a", "an", "be", "to", "in", "on", "by", "at", "of", "or",
          "and", "is", "are", "for", "before", "after", "this", "that", "yes", "no"}


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _NOISE}


def _numbers(text: str) -> set[str]:
    return {n.strip().lower().replace(",", "") for n in _NUM.findall(text)}


def _extract(prompt: str, tag: str) -> dict:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", prompt, re.S)
    if not m:
        raise ProviderBadOutput(f"mock: no <{tag}> in prompt")
    return json.loads(m.group(1))


class MockProvider(LLMProvider):
    name = "mock"
    model = "mock-1"

    async def generate_structured(
        self, *, system: str, prompt: str, schema: type[T], max_output_tokens: int = 1024,
    ) -> StructuredResult[T]:
        usage = Usage(input_tokens=max(1, len(prompt) // 4), output_tokens=60)
        if schema.__name__ == "MatchVerdict":
            return StructuredResult(schema.model_validate(self._verdict(prompt)), usage)
        if schema.__name__ == "OpportunityAnalysis":
            from core.ai.mock_analysis import analysis_for
            return StructuredResult(schema.model_validate(analysis_for(prompt)), usage)
        raise ProviderBadOutput(f"mock: unsupported schema {schema.__name__}")

    @staticmethod
    def _verdict(prompt: str) -> dict:
        a, b = _extract(prompt, "market_a"), _extract(prompt, "market_b")
        ta, tb = _tokens(a["title"]), _tokens(b["title"])
        jaccard = len(ta & tb) / len(ta | tb) if (ta | tb) else 0.0
        diffs: list[dict] = []

        na, nb = _numbers(a["title"]), _numbers(b["title"])
        if na and nb and na != nb:
            return {"verdict": "different", "confidence": 0.93, "short_reason":
                    "The titles use different numeric thresholds.",
                    "differences": [{"kind": "threshold",
                                     "detail": f"{sorted(na)} vs {sorted(nb)}"}]}

        neg_a = bool(re.search(r"\b(not|fail|fails|no longer)\b", a["title"].lower()))
        neg_b = bool(re.search(r"\b(not|fail|fails|no longer)\b", b["title"].lower()))
        if neg_a != neg_b and jaccard >= 0.4:
            return {"verdict": "equivalent_with_caveats", "confidence": 0.95,
                    "short_reason": "Same event, but one market's YES is the other's NO.",
                    "differences": [{"kind": "inverse_polarity",
                                     "detail": "YES on one side corresponds to NO on the other."}]}

        if jaccard < 0.5:
            return {"verdict": "different", "confidence": 0.9,
                    "short_reason": "The titles describe different events.", "differences": []}

        dates_differ = bool(a["end_date"] and b["end_date"]
                            and a["end_date"][:10] != b["end_date"][:10])
        if dates_differ:
            diffs.append({"kind": "date", "detail":
                          f"End dates differ: {a['end_date'][:10]} vs {b['end_date'][:10]}."})
        if not a["rules_available"] or not b["rules_available"]:
            diffs.append({"kind": "missing_rules",
                          "detail": "Resolution rules are not available for one market."})
        if jaccard < 0.85:
            diffs.append({"kind": "wording", "detail": "Titles are worded differently."})

        if not diffs:
            return {"verdict": "identical", "confidence": 0.95,
                    "short_reason": "Same event, same terms and end date.", "differences": []}
        return {"verdict": "equivalent_with_caveats", "confidence": 0.92,
                "short_reason": "Same underlying event; minor differences noted.",
                "differences": diffs}
