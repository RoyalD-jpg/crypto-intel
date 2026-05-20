"""
helius.py — On-chain data from Helius for Solana tokens.

Turns the scam-risk score from decorative into real. Helius gives us:

  - Mint authority (can dev print more tokens?)
  - Freeze authority (can dev freeze wallets?)
  - Top holders (concentration analysis)
  - Total supply

These are the four single most important signals for Solana scam detection.

Free tier: 100 requests/second, 1M requests/month. We cache aggressively
because token authority/holder data doesn't change minute-to-minute.

API key: set HELIUS_API_KEY environment variable. On Streamlit Cloud,
add it via "Manage app" → Secrets.
"""

import os
import requests
from functools import lru_cache

HELIUS_KEY = os.environ.get("HELIUS_API_KEY", "").strip()
HELIUS_RPC = f"https://mainnet.helius-rpc.com/?api-key={HELIUS_KEY}" if HELIUS_KEY else None
HELIUS_API = f"https://api.helius.xyz/v0" if HELIUS_KEY else None

TIMEOUT = 8


# ---------------------------------------------------------------------------
# Public function: enrich a CoinData with on-chain data
# ---------------------------------------------------------------------------

def enrich_solana_coin(coin):
    """Mutates the CoinData in place, filling in real on-chain values.

    Quietly returns if no API key, if it's not a Solana coin, or if the
    Helius calls fail. The scoring engine works fine with the placeholder
    defaults — this just upgrades them when possible.
    """
    if not HELIUS_KEY:
        return
    if coin.chain != "solana":
        return
    if not coin.contract_address or len(coin.contract_address) < 30:
        return

    try:
        on_chain = _fetch_token_onchain(coin.contract_address)
        if not on_chain:
            return

        # Update authority flags
        coin.mint_authority_active = on_chain.get("mint_authority_active", False)
        coin.freeze_authority_active = on_chain.get("freeze_authority_active", False)

        # Update holder concentration if we got it
        top_wallet_pct = on_chain.get("top_wallet_pct")
        top_10_pct = on_chain.get("top_10_holder_pct")
        if top_wallet_pct is not None:
            coin.top_wallet_pct = top_wallet_pct
        if top_10_pct is not None:
            coin.top_10_holder_pct = top_10_pct

        # Real holder count if we have it
        holder_count = on_chain.get("holder_count")
        if holder_count and holder_count > 0:
            coin.holder_count = holder_count

        # Bundle / sniper concentration signal: if a cluster of the top
        # non-pool wallets holds a large share on a young token, that's the
        # classic bundle launch pattern (one entity across many wallets).
        # We approximate "bundle" as top-5 wallets (excluding the largest,
        # which is usually the LP) holding a heavy combined share.
        top5_ex_pool = on_chain.get("top5_excluding_largest_pct")
        if top5_ex_pool is not None:
            coin.bundle_concentration_pct = top5_ex_pool
            # Flag as likely bundle if those 5 wallets hold >25% on a <7d token
            coin.likely_bundle = (top5_ex_pool > 25 and coin.token_age_days < 7)

    except Exception:
        # Helius issues should never break the dashboard — fall back to defaults
        return


# ---------------------------------------------------------------------------
# Internal: do the actual API calls
# ---------------------------------------------------------------------------

@lru_cache(maxsize=512)
def _fetch_token_onchain(mint: str) -> dict:
    """Cached on-chain fetch. Cache scoped to process lifetime; Streamlit
    cache layer adds the time-based eviction on top."""

    result = {}

    # 1. Get mint info (authorities + supply) via standard JSON-RPC
    mint_info = _rpc_get_asset(mint)
    if mint_info:
        # The DAS API returns a flat structure
        token_info = mint_info.get("token_info") or {}
        result["mint_authority_active"] = bool(token_info.get("mint_authority"))
        result["freeze_authority_active"] = bool(token_info.get("freeze_authority"))
        supply = token_info.get("supply")
        decimals = token_info.get("decimals", 0)
        if supply and decimals is not None:
            try:
                result["_total_supply"] = float(supply) / (10 ** decimals)
            except Exception:
                pass

    # 2. Get top holders to compute concentration
    holders = _get_top_holders(mint, limit=20)
    if holders and result.get("_total_supply"):
        total = result["_total_supply"]
        if total > 0:
            top_pct = (holders[0]["amount"] / total) * 100 if holders else 0
            top_10_pct = sum(h["amount"] for h in holders[:10]) / total * 100
            result["top_wallet_pct"] = round(top_pct, 2)
            result["top_10_holder_pct"] = round(top_10_pct, 2)
            # Top 5 EXCLUDING the largest holder (largest is usually the LP
            # pool, which isn't a concentration risk). The next 5 wallets
            # holding a heavy share is the bundle/sniper signature.
            if len(holders) > 1:
                next5 = holders[1:6]
                top5_ex = sum(h["amount"] for h in next5) / total * 100
                result["top5_excluding_largest_pct"] = round(top5_ex, 2)

    return result


def _rpc_get_asset(mint: str) -> dict | None:
    """Helius DAS getAsset — gives us mint/freeze authority in one call."""
    if not HELIUS_RPC:
        return None
    try:
        r = requests.post(
            HELIUS_RPC,
            json={
                "jsonrpc": "2.0",
                "id": "1",
                "method": "getAsset",
                "params": {"id": mint},
            },
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            return None
        return r.json().get("result")
    except Exception:
        return None


def _get_top_holders(mint: str, limit: int = 20) -> list[dict]:
    """Largest token accounts via getTokenLargestAccounts RPC."""
    if not HELIUS_RPC:
        return []
    try:
        r = requests.post(
            HELIUS_RPC,
            json={
                "jsonrpc": "2.0",
                "id": "1",
                "method": "getTokenLargestAccounts",
                "params": [mint, {"commitment": "confirmed"}],
            },
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            return []
        data = r.json().get("result", {}).get("value", []) or []
        holders = []
        for h in data[:limit]:
            try:
                # uiAmount is human-readable, accounts for decimals
                amount = float(h.get("uiAmount") or 0)
                if amount > 0:
                    holders.append({
                        "address": h.get("address"),
                        "amount": amount,
                    })
            except Exception:
                continue
        return holders
    except Exception:
        return []


def is_configured() -> bool:
    """For the dashboard to show 'Helius connected' status."""
    return bool(HELIUS_KEY)
