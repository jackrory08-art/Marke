"""Deterministic analysis text for the mock provider (tests, demo, screenshots)."""

import json
import re

from core.ai.provider import ProviderBadOutput


def analysis_for(prompt: str) -> dict:
    m = re.search(r"<opportunity>(.*?)</opportunity>", prompt, re.S)
    if not m:
        raise ProviderBadOutput("mock: no <opportunity> in prompt")
    snap = json.loads(m.group(1))
    risks: list[dict] = []
    score = 85

    diffs = snap.get("verdict_differences") or []
    if snap.get("verdict") == "equivalent_with_caveats" or diffs:
        kinds = ", ".join(sorted({d.get("kind", "other") for d in diffs})) or "wording"
        risks.append({"kind": "resolution_mismatch", "severity": "medium",
                      "detail": f"The verifier noted differences ({kinds}); read both rules."})
        score -= 15
    depth = snap.get("depth")
    if depth is None:
        risks.append({"kind": "thin_depth", "severity": "medium",
                      "detail": "Order size at the best price is not published for one platform."})
        score -= 10
    elif depth < 25:
        risks.append({"kind": "thin_depth", "severity": "high" if depth < 10 else "medium",
                      "detail": f"Only about {depth:.0f} shares are available at the best prices."})
        score -= 20
    tte = snap.get("time_to_expiry_s")
    if tte is not None and tte > 90 * 86400:
        risks.append({"kind": "time_to_expiry", "severity": "low",
                      "detail": "Capital is tied up for months until the markets resolve."})
        score -= 10
    if snap.get("manual_trade"):
        risks.append({"kind": "manual_execution", "severity": "medium",
                      "detail": "A PredictIt leg cannot be automated and must be placed by hand."})
        score -= 5
    if snap.get("net_edge", 0) < 0.03:
        risks.append({"kind": "fee_slippage_sensitivity", "severity": "medium",
                      "detail": "The net edge is small, so a little slippage could erase it."})
        score -= 15

    summary = (
        f"Buy {snap['token']} on {snap['buy_platform']} and sell it on {snap['sell_platform']}. "
        f"The listed net edge is {snap['net_edge']:.1%} after fees. "
        + ("The main risk is that the two markets resolve on slightly different terms."
           if any(r["kind"] == "resolution_mismatch" for r in risks)
           else "Check depth before sizing.")
    )
    return {"summary": summary, "risks": risks, "quality_score": max(0, min(100, score))}
