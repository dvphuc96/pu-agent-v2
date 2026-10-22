"""Pricing — what a call cost, in dollars a human can feel.

The loop writes a permanent ledger (`.pu/usage.jsonl`): one line per API call
with provider, model, and token counts. It deliberately does NOT store a price.
Prices change; tokens don't. So cost is derived HERE, at read time, from the
current tables — which means fixing a wrong rate silently corrects every past
race and every historical spend chart.

Three tables, checked in this order by `price_for()`:

  _price_cache    exact per-model rates learned from a live catalog fetch
                  (OpenRouter reports them) — see catalog.list_models()
  MODEL_PRICING   hand-maintained rates for endpoints with no listable catalog
  PRICING         a provider-level fallback, deliberately rough, labelled "est"

`MODEL_CUTOFF` is the same idea for knowledge cutoffs: evaluation/reporting can disclose when
each model's world knowledge ends, so a 2025 model denying that 2026 models
exist reads as stale data, not stupidity.

Imported by the dashboard and evaluation/reporting surfaces.
"""

from __future__ import annotations

import json

# Rough $/million tokens (in, out) for a dollar ESTIMATE — the number humans
# actually feel. Keyed by provider; deliberately approximate and labelled "est".
PRICING = {
    "anthropic": (3.0, 15.0),
    "openai": (2.5, 15.0),
    # Compatibility providers are rough fallbacks only. Live catalogs, when
    # they publish per-model prices (notably OpenRouter), override these.
    "openrouter": (3.0, 15.0),
    "deepseek": (0.5, 2.0),
    "glm": (1.0, 3.0),
    "gemini": (0.75, 3.75),
}


# model id -> exact ($/M in, $/M out), filled from the live catalog fetch in
# list_models() when an endpoint reports pricing metadata.
_price_cache: dict[str, tuple[float, float]] = {}


# Known per-model prices ($/M in, out) for endpoints with no listable catalog
# (the anthropic wire has no /models), checked before the provider-level
# fallback. Within a provider, model prices can diverge substantially, so
# pricing per *model* is the only honest basis for cost reporting. Rates are
# standard short-context list prices (cache/batch discounts not modelled),
# fact-checked Jul 2026 against each vendor's pricing page. See docs/benchmarks.md.
MODEL_PRICING = {
    "claude-opus-4-8": (5.0, 25.0),
    "claude-fable-5": (10.0, 50.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "gpt-5.6-sol": (5.0, 30.0),
    "gpt-5.5": (2.5, 15.0),
    "gpt-4.1-mini": (0.4, 1.6),
}



# Knowledge cutoff (YYYY-MM) per model — the UI may disclose when a model's
# world knowledge ends so stale knowledge is not misread as an application
# failure. Values are each vendor's published knowledge
# cutoff (for Anthropic, the "reliable knowledge cutoff"; training data runs
# later). None = the vendor hasn't published one. Fact-checked Jul 2026 against
# vendor model cards/docs. Every MODEL_PRICING id must have an entry here —
# enforced by evals/deterministic/test_providers.py.
MODEL_CUTOFF = {
    "claude-opus-4-8": "2026-01",
    "claude-fable-5": "2026-01",
    "claude-sonnet-5": "2026-01",
    "claude-haiku-4-5-20251001": "2025-02",
    "gpt-5.6-sol": "2026-02",
    "gpt-5.5": None,
    "gpt-4.1-mini": "2024-06",
}



def remember_price(model: str, price_in: float, price_out: float) -> None:
    """Record an EXACT per-model rate learned from a live catalog fetch, so
    `price_for` stops guessing for this model. Called by catalog.list_models()
    when an endpoint reports pricing metadata. Process-lifetime only —
    the ledger stores tokens, so a restart just falls back to the tables above."""
    _price_cache[model] = (price_in, price_out)


def cutoff_for(model: str) -> str | None:
    """Knowledge-cutoff date ('YYYY-MM') for a model id, or None when the
    vendor hasn't published one (the UI shows a dash rather than a guess)."""
    return MODEL_CUTOFF.get(model)


def price_for(provider: str, model: str) -> tuple[float, float]:
    """$/M tokens (in, out) for one call: the catalog's per-model price when
    known, $0 for ":free" ids, a known MODEL_PRICING id, else the provider-level
    PRICING estimate."""
    if model in _price_cache:
        return _price_cache[model]
    if model.endswith(":free"):
        return (0.0, 0.0)
    if model in MODEL_PRICING:
        return MODEL_PRICING[model]
    return PRICING.get(provider, (3.0, 15.0))


def _usage_records(paths) -> list[dict]:
    recs = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                recs.append(record)
    return recs


def _ledger_label(value: object) -> str:
    """Provider and model ids only. Sentences, mail, and secrets are dropped."""
    from pu.harness.audit import redact_text

    text = str(value or "")
    if not text or len(text) > 120 or any(char in text for char in " \n\t@"):
        return ""
    redacted = redact_text(text)
    if redacted != text:
        return ""
    return text


def _numeric_usage(record: dict) -> dict:
    """Drop free text. Provider and model stay because cost is keyed by them."""
    stamp = str(record.get("ts") or "")
    if len(stamp) < 10 or stamp[4] != "-" or stamp[7] != "-":
        stamp = ""
    return {
        "ts": stamp[:32],
        "provider": _ledger_label(record.get("provider")),
        "model": _ledger_label(record.get("model")),
        "in": record.get("in", 0) if isinstance(record.get("in", 0), (int, float)) and not isinstance(record.get("in", 0), bool) else 0,
        "out": record.get("out", 0) if isinstance(record.get("out", 0), (int, float)) and not isinstance(record.get("out", 0), bool) else 0,
    }


def usage_summary(home) -> dict:
    """Read the permanent spend ledger → tokens and dollar cost.

    A user sees only their own ledger. A platform admin sees numeric totals
    across ledgers and none of the prompt, mail, or report text. Cost is
    derived from tokens with PRICING (approximate, labelled 'est').
    """
    from pathlib import Path

    from pu.ops.telemetry import all_usage_files, telemetry_scope, usage_read_paths

    home = Path(home)
    scope = telemetry_scope(home)
    if scope.denied:
        recs = []
    elif scope.admin:
        recs = [_numeric_usage(record) for record in _usage_records(all_usage_files(home))]
    else:
        recs = []
        for record in _usage_records(usage_read_paths(home)):
            stamped = str(record.get("owner_user_id") or "")
            if stamped and scope.owner_user_id and stamped != scope.owner_user_id:
                continue
            recs.append(_numeric_usage(record))

    def cost(r) -> float:
        # the ledger stores tokens + provider/model, so old rows reprice too
        pin, pout = price_for(r.get("provider", ""), r.get("model", ""))
        return r.get("in", 0) / 1e6 * pin + r.get("out", 0) / 1e6 * pout

    def add(bucket, key, extra):
        b = bucket.setdefault(key, {**extra, "calls": 0, "in": 0, "out": 0, "cost": 0.0})
        b["calls"] += 1
        b["in"] += r.get("in", 0)
        b["out"] += r.get("out", 0)
        b["cost"] += cost(r)

    by_day, by_provider = {}, {}
    for r in recs:
        day = (r.get("ts") or "")[:10]
        add(by_day, day, {"date": day})
        add(by_provider, r.get("provider", "?"), {"provider": r.get("provider", "?")})

    return {
        "calls": len(recs),
        "total_in": sum(r.get("in", 0) for r in recs),
        "total_out": sum(r.get("out", 0) for r in recs),
        "total_cost": round(sum(cost(r) for r in recs), 4),
        "by_day": sorted(by_day.values(), key=lambda x: x["date"], reverse=True)[:30],
        "by_provider": sorted(by_provider.values(), key=lambda x: -x["cost"]),
    }
