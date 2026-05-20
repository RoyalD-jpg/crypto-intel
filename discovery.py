"""
discovery.py — pulls trending coins from multiple free sources.

Sources (all free, no API keys required):
  - DexScreener: /token-boosts/latest (active paid promotions = real money behind it)
  - DexScreener: /token-boosts/top (top boosted of all time)
  - DexScreener: /search?q=... (top-volume by chain)
  - CoinGecko: /search/trending (mainstream attention)

Returns a deduplicated list of CoinData objects ready for scoring.
"""

import sys
import os
import requests
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'src'))
from scoring import CoinData


DS = "https://api.dexscreener.com"
DS_LATEST = "https://api.dexscreener.com/latest/dex"
CG = "https://api.coingecko.com/api/v3"

# Chains we'll surface. Solana-only for now — that's where most of the
# action lives and where Helius gives us real on-chain risk data.
SUPPORTED_CHAINS = {"solana"}

# Request timeout per call (seconds)
TIMEOUT = 10


# ---------------------------------------------------------------------------
# Pair -> CoinData conversion
# ---------------------------------------------------------------------------

def pair_to_coindata(pair: dict) -> CoinData | None:
    """Convert a DexScreener pair to our CoinData shape."""
    try:
        base = pair.get("baseToken") or {}
        price = float(pair.get("priceUsd") or 0)
        if price <= 0:
            return None

        liq = (pair.get("liquidity") or {}).get("usd") or 0
        vol_24h = (pair.get("volume") or {}).get("h24") or 0
        pc = pair.get("priceChange") or {}

        created_ms = pair.get("pairCreatedAt")
        if created_ms:
            age_days = (datetime.now(timezone.utc).timestamp() - created_ms / 1000) / 86400
        else:
            age_days = 30

        txns_24h = (pair.get("txns") or {}).get("h24") or {}
        buys = txns_24h.get("buys") or 0
        sells = txns_24h.get("sells") or 0

        chain = (pair.get("chainId") or "").lower()

        info = pair.get("info") or {}
        socials = info.get("socials") or []
        websites = info.get("websites") or []
        has_twitter = any("twitter" in str(s).lower() or "x.com" in str(s).lower()
                          for s in socials)
        has_telegram = any("telegram" in str(s).lower() or "t.me" in str(s).lower()
                           for s in socials)

        return CoinData(
            symbol=(base.get("symbol") or "?").upper(),
            name=base.get("name") or base.get("symbol") or "Unknown",
            contract_address=base.get("address") or "",
            chain=chain,
            price_usd=price,
            market_cap_usd=pair.get("fdv") or pair.get("marketCap") or 0,
            price_change_1h_pct=pc.get("h1") or 0,
            price_change_24h_pct=pc.get("h24") or 0,
            price_change_7d_pct=0,
            volume_24h_usd=vol_24h,
            avg_volume_7d_usd=max(vol_24h * 0.7, 1),
            liquidity_usd=liq,
            liquidity_change_24h_pct=0,
            holder_count=max(buys + sells, 50),
            new_holders_24h=buys,
            top_10_holder_pct=20.0,   # placeholder until on-chain wired
            top_wallet_pct=5.0,        # placeholder until on-chain wired
            token_age_days=age_days,
            contract_verified=True,
            mentions_24h=max(buys, 1),
            mentions_prev_24h=max(buys // 2, 1),
            sentiment_score=0.0,
            has_twitter=has_twitter or bool(websites),
            has_telegram=has_telegram,
            bot_mention_ratio=0.1,
            liquidity_locked=True,     # placeholder
            anonymous_team=True,
            single_lp_only=False,
        )
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Source 1: DexScreener boosted tokens (real money behind these)
# ---------------------------------------------------------------------------

def fetch_boosted_tokens(endpoint: str = "latest") -> list:
    """Boosted tokens are ones paying for DexScreener promotion — usually
    means an active community putting money behind visibility."""
    try:
        url = f"{DS}/token-boosts/{endpoint}/v1"
        r = requests.get(url, timeout=TIMEOUT)
        if r.status_code != 200:
            return []
        data = r.json()
        if not isinstance(data, list):
            return []
        return data
    except Exception:
        return []


def fetch_pair_for_token(chain: str, address: str) -> dict | None:
    """Get full pair data for a token address."""
    try:
        url = f"{DS_LATEST}/tokens/{address}"
        r = requests.get(url, timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        data = r.json()
        pairs = data.get("pairs") or []
        if not pairs:
            return None
        # Best pair = highest liquidity
        pairs.sort(key=lambda p: (p.get("liquidity") or {}).get("usd") or 0, reverse=True)
        return pairs[0]
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Source 2: DexScreener search by chain (gets top-volume coins)
# ---------------------------------------------------------------------------

def fetch_top_pairs_for_chain(chain: str, limit: int = 30) -> list[dict]:
    """Use the search endpoint with a chain filter to surface top-volume pairs."""
    try:
        # Search by common quote tokens to find active pairs
        results = []
        seen_addrs = set()
        queries = {
            "solana": ["SOL", "USDC"],
            "ethereum": ["WETH", "USDC", "USDT"],
            "base": ["WETH", "USDC"],
            "bsc": ["WBNB", "BUSD"],
        }.get(chain, ["USDC"])

        for q in queries:
            try:
                r = requests.get(f"{DS_LATEST}/search", params={"q": q}, timeout=TIMEOUT)
                if r.status_code != 200:
                    continue
                pairs = r.json().get("pairs") or []
                for p in pairs:
                    if (p.get("chainId") or "").lower() != chain:
                        continue
                    addr = (p.get("baseToken") or {}).get("address")
                    if not addr or addr in seen_addrs:
                        continue
                    # Filter: at least $10k liquidity, not the quote token itself
                    liq = (p.get("liquidity") or {}).get("usd") or 0
                    if liq < 10_000:
                        continue
                    seen_addrs.add(addr)
                    results.append(p)
                    if len(results) >= limit:
                        break
                if len(results) >= limit:
                    break
            except Exception:
                continue
        return results[:limit]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Source 3: CoinGecko trending
# ---------------------------------------------------------------------------

def fetch_coingecko_trending() -> list[str]:
    """Returns contract addresses or coin IDs of trending coins on CG."""
    try:
        r = requests.get(f"{CG}/search/trending", timeout=TIMEOUT)
        if r.status_code != 200:
            return []
        data = r.json()
        coins = data.get("coins") or []
        # Return coin ids — we'll look these up
        return [c.get("item", {}).get("id") for c in coins if c.get("item")]
    except Exception:
        return []


def fetch_coingecko_coin_as_pair(coin_id: str) -> dict | None:
    """Fetch a CG coin and try to find it on DexScreener for full pair data."""
    try:
        r = requests.get(f"{CG}/coins/{coin_id}",
                        params={"localization": "false", "tickers": "false",
                                "community_data": "false", "developer_data": "false"},
                        timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        d = r.json()
        # Try to get contract address for DexScreener lookup
        platforms = d.get("platforms") or {}
        for chain_id, addr in platforms.items():
            if not addr:
                continue
            # Map CG chain names to DexScreener
            chain_map = {
                "ethereum": "ethereum",
                "solana": "solana",
                "base": "base",
                "binance-smart-chain": "bsc",
            }
            ds_chain = chain_map.get(chain_id)
            if not ds_chain:
                continue
            pair = fetch_pair_for_token(ds_chain, addr)
            if pair:
                return pair
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Main discovery function
# ---------------------------------------------------------------------------

def discover_trending(max_per_chain: int = 25) -> list[CoinData]:
    """Pull trending coins from all sources, normalize, deduplicate.

    Returns up to ~100 coins total across all supported chains.
    """
    all_pairs: list[dict] = []
    seen_addrs: set[str] = set()

    def add_pair(p: dict):
        if not p:
            return
        chain = (p.get("chainId") or "").lower()
        if chain not in SUPPORTED_CHAINS:
            return
        addr = (p.get("baseToken") or {}).get("address")
        if not addr or addr in seen_addrs:
            return
        seen_addrs.add(addr)
        all_pairs.append(p)

    # --- Source A: Top pairs per chain (the meat of the discovery) ---
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(fetch_top_pairs_for_chain, ch, max_per_chain): ch
                  for ch in SUPPORTED_CHAINS}
        for f in as_completed(futures):
            try:
                for p in f.result():
                    add_pair(p)
            except Exception:
                continue

    # --- Source B: DexScreener boosted tokens (have active promotion) ---
    boosted_lists = []
    try:
        boosted_lists.append(fetch_boosted_tokens("latest"))
        boosted_lists.append(fetch_boosted_tokens("top"))
    except Exception:
        pass

    boosted_addrs = []
    for lst in boosted_lists:
        for item in lst:
            chain = (item.get("chainId") or "").lower()
            addr = item.get("tokenAddress")
            if chain in SUPPORTED_CHAINS and addr and addr not in seen_addrs:
                boosted_addrs.append((chain, addr))

    # Fetch pair data for boosted tokens in parallel
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = [ex.submit(fetch_pair_for_token, ch, a)
                  for ch, a in boosted_addrs[:40]]  # cap to keep latency reasonable
        for f in as_completed(futures):
            try:
                add_pair(f.result())
            except Exception:
                continue

    # --- Source C: CoinGecko trending ---
    try:
        trending_ids = fetch_coingecko_trending()[:10]
        with ThreadPoolExecutor(max_workers=4) as ex:
            futures = [ex.submit(fetch_coingecko_coin_as_pair, cid) for cid in trending_ids]
            for f in as_completed(futures):
                try:
                    add_pair(f.result())
                except Exception:
                    continue
    except Exception:
        pass

    # Convert to CoinData
    coins = []
    for p in all_pairs:
        cd = pair_to_coindata(p)
        if cd:
            coins.append(cd)

    # Enrich with on-chain data from Helius (in parallel, best-effort)
    try:
        from helius import enrich_solana_coin, is_configured
        if is_configured():
            with ThreadPoolExecutor(max_workers=10) as ex:
                list(ex.map(enrich_solana_coin, coins))
    except Exception:
        pass  # if Helius is unavailable, scoring still works with defaults

    return coins


# ---------------------------------------------------------------------------
# Single-coin lookup (for the search box)
# ---------------------------------------------------------------------------

def lookup_one(query: str) -> CoinData | None:
    """Find a single coin by name, symbol, or contract address."""
    query = query.strip()
    if not query:
        return None

    coin = None

    # Contract address (long hex string or Solana base58)
    if query.startswith("0x") or len(query) > 30:
        try:
            r = requests.get(f"{DS_LATEST}/tokens/{query}", timeout=TIMEOUT)
            if r.status_code == 200:
                pairs = r.json().get("pairs") or []
                if pairs:
                    pairs.sort(key=lambda p: (p.get("liquidity") or {}).get("usd") or 0,
                              reverse=True)
                    coin = pair_to_coindata(pairs[0])
        except Exception:
            pass

    # Search by name/symbol on DexScreener
    if not coin:
        try:
            r = requests.get(f"{DS_LATEST}/search", params={"q": query}, timeout=TIMEOUT)
            if r.status_code == 200:
                pairs = r.json().get("pairs") or []
                exact = [p for p in pairs
                        if (p.get("baseToken") or {}).get("symbol", "").upper() == query.upper()]
                candidates = exact or pairs
                candidates.sort(key=lambda p: (p.get("liquidity") or {}).get("usd") or 0,
                               reverse=True)
                if candidates:
                    coin = pair_to_coindata(candidates[0])
        except Exception:
            pass

    # Enrich with Helius if available
    if coin:
        try:
            from helius import enrich_solana_coin
            enrich_solana_coin(coin)
        except Exception:
            pass

    return coin
