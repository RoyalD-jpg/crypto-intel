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
        pc = pair.get("priceChange") or {}

        # Multi-window volume (DexScreener provides h1, h6, h24)
        vol = pair.get("volume") or {}
        vol_24h = vol.get("h24") or 0
        vol_6h = vol.get("h6") or 0
        vol_1h = vol.get("h1") or 0

        # Build a real volume baseline. If the last hour annualized to 24h is
        # much higher than the actual 24h, volume is accelerating right now.
        # Use the 6h window scaled to 24h as a "recent normal" baseline —
        # far better than the old volume * 0.7 guess.
        if vol_6h > 0:
            baseline_24h = vol_6h * 4  # 6h * 4 = 24h-equivalent recent pace
        else:
            baseline_24h = max(vol_24h, 1)

        created_ms = pair.get("pairCreatedAt")
        if created_ms:
            age_days = (datetime.now(timezone.utc).timestamp() - created_ms / 1000) / 86400
        else:
            age_days = 30

        # Multi-window transactions for real buy/sell pressure
        txns = pair.get("txns") or {}
        txns_24h = txns.get("h24") or {}
        txns_1h = txns.get("h1") or {}
        buys_24h = txns_24h.get("buys") or 0
        sells_24h = txns_24h.get("sells") or 0
        buys_1h = txns_1h.get("buys") or 0
        sells_1h = txns_1h.get("sells") or 0

        # Buy pressure ratio (0-1): fraction of recent txns that are buys
        total_1h = buys_1h + sells_1h
        if total_1h > 0:
            buy_pressure_1h = buys_1h / total_1h
        else:
            total_24h = buys_24h + sells_24h
            buy_pressure_1h = (buys_24h / total_24h) if total_24h > 0 else 0.5

        chain = (pair.get("chainId") or "").lower()

        info = pair.get("info") or {}
        socials = info.get("socials") or []
        websites = info.get("websites") or []
        has_twitter = any("twitter" in str(s).lower() or "x.com" in str(s).lower()
                          for s in socials)
        has_telegram = any("telegram" in str(s).lower() or "t.me" in str(s).lower()
                           for s in socials)

        # Use buy-pressure as a sentiment proxy (-1 to +1): more buys = positive
        sentiment = (buy_pressure_1h - 0.5) * 2

        cd = CoinData(
            symbol=(base.get("symbol") or "?").upper(),
            name=base.get("name") or base.get("symbol") or "Unknown",
            contract_address=base.get("address") or "",
            chain=chain,
            price_usd=price,
            market_cap_usd=pair.get("marketCap") or pair.get("fdv") or 0,
            price_change_1h_pct=pc.get("h1") or 0,
            price_change_24h_pct=pc.get("h24") or 0,
            price_change_7d_pct=0,
            volume_24h_usd=vol_24h,
            avg_volume_7d_usd=baseline_24h,  # real recent-pace baseline now
            liquidity_usd=liq,
            liquidity_change_24h_pct=0,
            holder_count=max(buys_24h + sells_24h, 50),
            new_holders_24h=buys_24h,
            top_10_holder_pct=20.0,   # placeholder until on-chain (Helius) fills it
            top_wallet_pct=5.0,        # placeholder until on-chain (Helius) fills it
            token_age_days=age_days,
            contract_verified=True,
            mentions_24h=max(buys_24h, 1),
            mentions_prev_24h=max(buys_24h // 2, 1),
            sentiment_score=sentiment,
            has_twitter=has_twitter or bool(websites),
            has_telegram=has_telegram,
            bot_mention_ratio=0.1,
            liquidity_locked=True,     # placeholder until lock-check wired
            anonymous_team=True,
            single_lp_only=False,
        )

        # Attach extra DexScreener fields as attributes for the UI to display.
        # (Not part of the scoring contract, just richer display data.)
        cd.vol_1h = vol_1h
        cd.vol_6h = vol_6h
        cd.buys_24h = buys_24h
        cd.sells_24h = sells_24h
        cd.buys_1h = buys_1h
        cd.sells_1h = sells_1h
        cd.buy_pressure_1h = buy_pressure_1h
        cd.price_change_6h_pct = pc.get("h6") or 0
        cd.dex_url = pair.get("url") or ""
        return cd
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
    """Single coin lookup — returns the best match.

    For broad compatibility we keep this returning one coin. Use search_many()
    when you want to disambiguate between coins sharing a symbol.
    """
    results = search_many(query, limit=1)
    return results[0] if results else None


def search_many(query: str, limit: int = 8) -> list[CoinData]:
    """Return up to `limit` candidates matching the query.

    Strategy:
      1. If it looks like a contract address, fetch all its pairs (could be
         multi-chain or multi-pool — return distinct ones).
      2. Otherwise search by symbol/name and return the top matches.
      3. Enrich Solana results with Helius.

    Newly-launched coins (1 minute old) appear here because DexScreener
    indexes new pairs within seconds. The user just needs to either know
    the contract address, or accept that "PEPE" will return the most-liquid
    PEPE first (which is what they almost always want).
    """
    query = query.strip()
    if not query:
        return []

    coins: list[CoinData] = []
    seen_addrs: set[str] = set()

    def add(coin: CoinData | None):
        if not coin:
            return
        addr = coin.contract_address
        if not addr or addr in seen_addrs:
            return
        seen_addrs.add(addr)
        coins.append(coin)

    # Step 1: Contract address path
    is_addr = query.startswith("0x") or (len(query) >= 32 and " " not in query)
    if is_addr:
        try:
            r = requests.get(f"{DS_LATEST}/tokens/{query}", timeout=TIMEOUT)
            if r.status_code == 200:
                pairs = r.json().get("pairs") or []
                # Highest-liquidity pair per chain
                pairs.sort(key=lambda p: (p.get("liquidity") or {}).get("usd") or 0,
                          reverse=True)
                for p in pairs[:limit]:
                    add(pair_to_coindata(p))
        except Exception:
            pass

    # Step 2: Symbol/name search
    if len(coins) < limit:
        try:
            r = requests.get(f"{DS_LATEST}/search", params={"q": query}, timeout=TIMEOUT)
            if r.status_code == 200:
                pairs = r.json().get("pairs") or []

                # Group by token address, keep best (most liquid) pair per token
                by_addr: dict[str, dict] = {}
                for p in pairs:
                    addr = (p.get("baseToken") or {}).get("address")
                    if not addr:
                        continue
                    cur = by_addr.get(addr)
                    cur_liq = (cur.get("liquidity") or {}).get("usd") or 0 if cur else -1
                    new_liq = (p.get("liquidity") or {}).get("usd") or 0
                    if new_liq > cur_liq:
                        by_addr[addr] = p

                # Rank: exact symbol match first, then by liquidity
                qu = query.upper()
                def rank(p):
                    sym = (p.get("baseToken") or {}).get("symbol", "").upper()
                    name = (p.get("baseToken") or {}).get("name", "").upper()
                    liq = (p.get("liquidity") or {}).get("usd") or 0
                    exact_sym = (sym == qu)
                    starts = sym.startswith(qu) or name.startswith(qu)
                    # negative for descending sort
                    return (-int(exact_sym), -int(starts), -liq)

                candidates = sorted(by_addr.values(), key=rank)
                for p in candidates:
                    if len(coins) >= limit:
                        break
                    add(pair_to_coindata(p))
        except Exception:
            pass

    # Step 3: Enrich with Helius
    try:
        from helius import enrich_solana_coin, is_configured
        if is_configured():
            with ThreadPoolExecutor(max_workers=min(8, max(1, len(coins)))) as ex:
                list(ex.map(enrich_solana_coin, coins))
    except Exception:
        pass

    return coins
