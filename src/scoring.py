"""
Crypto Intelligence Scoring Engine
===================================

Pure-Python scoring functions. No external dependencies — these can be unit
tested in isolation from any API. Feed them dicts of normalized data and
they return scores.

The CoinData dataclass defines the contract: whatever you pull from
CoinGecko/DexScreener/on-chain has to be reshaped into this before scoring.
That gives you a clean seam — if a data source dies you swap it out without
touching the scoring code.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import math


# ---------------------------------------------------------------------------
# Data contract
# ---------------------------------------------------------------------------

@dataclass
class CoinData:
    """Normalized coin data. Populate this from your data sources."""

    # Identity
    symbol: str
    name: str
    contract_address: str
    chain: str  # "solana", "ethereum", "base", "bsc", etc.

    # Price & market
    price_usd: float
    market_cap_usd: float
    price_change_1h_pct: float       # e.g. 5.2 means +5.2%
    price_change_24h_pct: float
    price_change_7d_pct: float

    # Volume & liquidity
    volume_24h_usd: float
    avg_volume_7d_usd: float
    liquidity_usd: float
    liquidity_change_24h_pct: float

    # Holders
    holder_count: int
    new_holders_24h: int
    top_10_holder_pct: float          # 0-100, % of supply held by top 10
    top_wallet_pct: float             # 0-100, % held by single largest wallet

    # Token metadata
    token_age_days: float
    contract_verified: bool

    # Social signals
    mentions_24h: int
    mentions_prev_24h: int
    sentiment_score: float            # -1 to +1 (negative to positive)
    has_twitter: bool
    has_telegram: bool
    bot_mention_ratio: float          # 0-1, fraction of mentions that look bot-like

    # Exchange activity
    new_cex_listing_24h: bool = False
    new_cex_listing_7d: bool = False
    announced_listing_pending: bool = False

    # Security flags (chain-specific, populated by on-chain checks)
    mint_authority_active: bool = False       # Solana
    freeze_authority_active: bool = False     # Solana
    owner_can_modify: bool = False            # EVM proxy / owner functions
    honeypot_detected: bool = False
    liquidity_locked: bool = True
    buy_tax_pct: float = 0.0
    sell_tax_pct: float = 0.0
    dev_wallet_has_rugged_before: bool = False
    single_lp_only: bool = False
    anonymous_team: bool = True               # assume true unless verified
    classic_pump_pattern: bool = False        # chart shape heuristic


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _safe_log2_ratio(numerator: float, denominator: float) -> float:
    """log2(n/d) with safe handling of zero/negative."""
    if denominator <= 0 or numerator <= 0:
        return 0.0
    return math.log2(numerator / denominator)


# ---------------------------------------------------------------------------
# Momentum (0-100)
# ---------------------------------------------------------------------------

def momentum_components(c: CoinData) -> dict:
    """Returns each component score plus the weighted total. Useful for debugging
    and for showing the user *why* a momentum score is what it is."""

    # 1. Price momentum — reward sustained moves, penalize flash spikes
    price = 50 + _clamp(c.price_change_1h_pct * 2, -25, 25) \
               + _clamp(c.price_change_24h_pct, -25, 25)
    price = _clamp(price, 0, 100)

    # 2. Volume momentum — ratio against 7d baseline
    vol_log_ratio = _safe_log2_ratio(c.volume_24h_usd, c.avg_volume_7d_usd)
    volume = _clamp(vol_log_ratio * 20 + 50, 0, 100)

    # 3. Social momentum — growth in mentions
    if c.mentions_prev_24h > 0:
        mention_growth = (c.mentions_24h / c.mentions_prev_24h) - 1
    else:
        mention_growth = 1.0 if c.mentions_24h > 0 else 0.0
    social = _clamp(mention_growth * 50 + 50, 0, 100)

    # Penalize bot-heavy mention spikes
    social *= (1 - c.bot_mention_ratio * 0.5)

    # 4. Holder growth — new holders as fraction of total
    if c.holder_count > 0:
        new_holder_pct = c.new_holders_24h / c.holder_count
    else:
        new_holder_pct = 0.0
    holders = _clamp(new_holder_pct * 500, 0, 100)

    # 5. Liquidity change
    liquidity = _clamp(c.liquidity_change_24h_pct * 2 + 50, 0, 100)

    # 6. Exchange listing signal
    listing = 0
    if c.new_cex_listing_24h:
        listing += 60
    elif c.new_cex_listing_7d:
        listing += 40
    if c.announced_listing_pending:
        listing += 30
    listing = _clamp(listing, 0, 100)

    total = (
        0.25 * price +
        0.20 * volume +
        0.15 * social +
        0.15 * holders +
        0.15 * liquidity +
        0.10 * listing
    )

    return {
        "price": round(price, 1),
        "volume": round(volume, 1),
        "social": round(social, 1),
        "holders": round(holders, 1),
        "liquidity": round(liquidity, 1),
        "listing": round(listing, 1),
        "total": round(total, 1),
    }


def momentum_score(c: CoinData) -> float:
    return momentum_components(c)["total"]


# ---------------------------------------------------------------------------
# Scam risk (0-100)
# ---------------------------------------------------------------------------

# Each flag: (label, severity) — severity is "critical" / "major" / "minor"
def scam_risk_analysis(c: CoinData) -> dict:
    """Returns {score, flags: [(label, severity), ...]}.

    Critical flag → 100 immediately.
    Otherwise: 25 per major + 10 per minor, capped at 99.
    """
    flags: list[tuple[str, str]] = []

    # ---- CRITICAL flags ----
    if c.chain == "solana" and c.mint_authority_active:
        flags.append(("Mint authority not renounced — dev can print tokens", "critical"))
    if c.chain == "solana" and c.freeze_authority_active:
        flags.append(("Freeze authority active — dev can freeze wallets", "critical"))
    if c.owner_can_modify:
        flags.append(("Contract owner has modification powers", "critical"))
    if c.honeypot_detected:
        flags.append(("Honeypot — sells revert in simulation", "critical"))
    if c.top_wallet_pct > 50:
        flags.append((f"Top wallet holds {c.top_wallet_pct:.1f}% of supply", "critical"))
    if not c.liquidity_locked and c.token_age_days < 30:
        flags.append(("Liquidity not locked on a <30d old token", "critical"))

    # ---- MAJOR flags ----
    if c.top_10_holder_pct > 40 and c.top_wallet_pct <= 50:  # avoid double-counting
        flags.append((f"Top 10 wallets hold {c.top_10_holder_pct:.1f}%", "major"))
    if c.liquidity_usd < 20_000:
        flags.append((f"Liquidity only ${c.liquidity_usd:,.0f} — exit difficulty", "major"))
    if c.token_age_days < 1:
        flags.append(("Contract less than 24 hours old", "major"))
    if c.dev_wallet_has_rugged_before:
        flags.append(("Dev wallet linked to prior rug pull", "major"))
    if not c.has_twitter and not c.has_telegram:
        flags.append(("No social presence — likely abandoned", "major"))
    if not c.contract_verified:
        flags.append(("Contract not verified on block explorer", "major"))
    if c.sell_tax_pct > 10 or abs(c.sell_tax_pct - c.buy_tax_pct) > 5:
        flags.append((f"Tax asymmetry — buy {c.buy_tax_pct}%, sell {c.sell_tax_pct}%", "major"))

    # ---- MINOR flags ----
    if c.single_lp_only:
        flags.append(("Single liquidity pool — concentration risk", "minor"))
    if c.anonymous_team:
        flags.append(("Anonymous team (common but worth noting)", "minor"))
    if c.bot_mention_ratio > 0.4:
        flags.append((f"{c.bot_mention_ratio:.0%} of mentions look bot-driven", "minor"))
    if c.classic_pump_pattern:
        flags.append(("Chart shows classic pump-and-dump shape", "minor"))

    # ---- Score calculation ----
    if any(severity == "critical" for _, severity in flags):
        score = 100
    else:
        majors = sum(1 for _, s in flags if s == "major")
        minors = sum(1 for _, s in flags if s == "minor")
        score = min(99, 25 * majors + 10 * minors)

    return {"score": score, "flags": flags}


def scam_risk_score(c: CoinData) -> int:
    return scam_risk_analysis(c)["score"]


# ---------------------------------------------------------------------------
# Opportunity (composite, only if not obvious scam)
# ---------------------------------------------------------------------------

def opportunity_score(c: CoinData) -> Optional[float]:
    """Returns None if scam risk too high — surface the risk instead."""
    risk = scam_risk_score(c)
    if risk >= 60:
        return None
    momentum = momentum_score(c)
    risk_penalty = risk / 100.0
    return round(momentum * (1 - risk_penalty * 0.7), 1)


# ---------------------------------------------------------------------------
# Convenience: score everything at once
# ---------------------------------------------------------------------------

def full_analysis(c: CoinData) -> dict:
    """One-shot analysis. This is what your API endpoint returns."""
    mom = momentum_components(c)
    risk = scam_risk_analysis(c)
    opp = opportunity_score(c)

    # Tier label for the dashboard
    if opp is None:
        tier = None
    elif opp >= 80:
        tier = ("🔥 High signal", "green")
    elif opp >= 60:
        tier = ("⚡ Notable", "yellow")
    elif opp >= 40:
        tier = ("👀 Watch", "blue")
    else:
        tier = ("—", "gray")

    if risk["score"] <= 20:
        risk_label = "✅ Low risk"
    elif risk["score"] <= 50:
        risk_label = "⚠️ Moderate — DYOR"
    elif risk["score"] <= 80:
        risk_label = "🚩 High risk"
    else:
        risk_label = "☠️ Avoid"

    return {
        "symbol": c.symbol,
        "name": c.name,
        "chain": c.chain,
        "momentum": mom,
        "scam_risk": {
            "score": risk["score"],
            "label": risk_label,
            "flags": risk["flags"],
        },
        "opportunity": {
            "score": opp,
            "tier": tier,
        },
    }
