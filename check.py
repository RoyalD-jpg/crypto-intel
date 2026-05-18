"""
check.py — score any coin on demand from PowerShell.

Usage:
    python check.py bitcoin
    python check.py pepe
    python check.py 0x6982508145454ce325ddbe47a25d4ec3d2311933   (contract address)
    python check.py So11111111111111111111111111111111111111112  (Solana mint)

The script tries CoinGecko first (best for established coins), then falls back
to DexScreener (best for new/memecoins) if CoinGecko doesn't recognize the
input. DexScreener also gives us real liquidity numbers, which CoinGecko free
tier doesn't.

Both APIs are free. No keys required.
"""

import sys
import os
import requests
from datetime import datetime, timezone

# Add the project's modules to the path
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'src'))
sys.path.insert(0, os.path.join(HERE, 'prompts'))

from scoring import CoinData, full_analysis


CG = "https://api.coingecko.com/api/v3"
DS = "https://api.dexscreener.com/latest/dex"


# ---------------------------------------------------------------------------
# Source 1: CoinGecko (good for established coins)
# ---------------------------------------------------------------------------

def fetch_from_coingecko(coin_id: str):
    r = requests.get(
        f"{CG}/coins/{coin_id}",
        params={"localization": "false", "tickers": "false",
                "community_data": "true", "developer_data": "false"},
        timeout=15,
    )
    if r.status_code == 404:
        return None
    r.raise_for_status()
    d = r.json()

    m = d.get("market_data", {})
    price = (m.get("current_price") or {}).get("usd") or 0
    if price == 0:
        return None

    genesis = d.get("genesis_date")
    if genesis:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(genesis).replace(tzinfo=timezone.utc)).days
    else:
        age = 365

    comm = d.get("community_data", {})
    tw = comm.get("twitter_followers") or 0
    rd = comm.get("reddit_subscribers") or 0

    volume = (m.get("total_volume") or {}).get("usd") or 0

    return CoinData(
        symbol=(d.get("symbol") or "").upper(),
        name=d.get("name", ""),
        contract_address=d.get("contract_address") or "n/a",
        chain=d.get("asset_platform_id") or "native",
        price_usd=price,
        market_cap_usd=(m.get("market_cap") or {}).get("usd") or 0,
        price_change_1h_pct=(m.get("price_change_percentage_1h_in_currency") or {}).get("usd") or 0,
        price_change_24h_pct=m.get("price_change_percentage_24h") or 0,
        price_change_7d_pct=m.get("price_change_percentage_7d") or 0,
        volume_24h_usd=volume,
        avg_volume_7d_usd=volume * 0.7 if volume else 1,
        liquidity_usd=volume * 0.3 if volume else 0,
        liquidity_change_24h_pct=0,
        holder_count=10_000,
        new_holders_24h=0,
        top_10_holder_pct=20.0,
        top_wallet_pct=5.0,
        token_age_days=age,
        contract_verified=True,
        mentions_24h=max(tw // 100, rd // 100, 1),
        mentions_prev_24h=max(tw // 100, rd // 100, 1),
        sentiment_score=0.0,
        has_twitter=tw > 0,
        has_telegram=comm.get("telegram_channel_user_count") is not None,
        bot_mention_ratio=0.1,
        liquidity_locked=True,
        anonymous_team=False,
    )


# ---------------------------------------------------------------------------
# Source 2: DexScreener (good for new coins and memecoins; gives real liquidity)
# ---------------------------------------------------------------------------

def fetch_from_dexscreener(query: str):
    # DexScreener accepts contract addresses or symbol/name searches
    if query.startswith("0x") or len(query) > 30:
        r = requests.get(f"{DS}/tokens/{query}", timeout=15)
    else:
        r = requests.get(f"{DS}/search", params={"q": query}, timeout=15)

    if r.status_code != 200:
        return None

    data = r.json()
    pairs = data.get("pairs") or []
    if not pairs:
        return None

    # Pick the pair with the highest liquidity
    pairs.sort(key=lambda p: (p.get("liquidity") or {}).get("usd") or 0, reverse=True)
    p = pairs[0]

    base = p.get("baseToken", {})
    price = float(p.get("priceUsd") or 0)
    if price == 0:
        return None

    liq = (p.get("liquidity") or {}).get("usd") or 0
    vol_24h = (p.get("volume") or {}).get("h24") or 0
    pc = p.get("priceChange") or {}

    # DexScreener gives us pair creation time — best proxy for token age
    created_ms = p.get("pairCreatedAt")
    if created_ms:
        age = (datetime.now(timezone.utc).timestamp() - created_ms / 1000) / 86400
    else:
        age = 30  # unknown — assume moderate

    # Transaction counts let us estimate holder activity
    txns_24h = (p.get("txns") or {}).get("h24") or {}
    buys = txns_24h.get("buys") or 0
    sells = txns_24h.get("sells") or 0

    return CoinData(
        symbol=(base.get("symbol") or "").upper(),
        name=base.get("name") or "",
        contract_address=base.get("address") or "",
        chain=p.get("chainId") or "unknown",
        price_usd=price,
        market_cap_usd=p.get("fdv") or p.get("marketCap") or 0,
        price_change_1h_pct=pc.get("h1") or 0,
        price_change_24h_pct=pc.get("h24") or 0,
        price_change_7d_pct=0,  # DexScreener doesn't expose 7d
        volume_24h_usd=vol_24h,
        avg_volume_7d_usd=vol_24h * 0.7 if vol_24h else 1,
        liquidity_usd=liq,
        liquidity_change_24h_pct=0,
        holder_count=max(buys + sells, 100),  # rough — real holder count needs an on-chain call
        new_holders_24h=buys,
        top_10_holder_pct=20.0,  # placeholder — needs on-chain
        top_wallet_pct=5.0,      # placeholder — needs on-chain
        token_age_days=age,
        contract_verified=True,
        mentions_24h=max(buys, 1),
        mentions_prev_24h=max(buys // 2, 1),
        sentiment_score=0.0,
        has_twitter=bool(p.get("info", {}).get("socials")),
        has_telegram=False,
        bot_mention_ratio=0.1,
        liquidity_locked=True,  # placeholder — DexScreener doesn't expose lock status
        anonymous_team=True,
        single_lp_only=len(pairs) == 1,
    )


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def print_report(coin: CoinData, source: str):
    a = full_analysis(coin)
    mom = a["momentum"]
    risk = a["scam_risk"]
    opp = a["opportunity"]

    print()
    print("=" * 68)
    print(f"  {coin.symbol} — {coin.name}   ({coin.chain})")
    print("=" * 68)
    print(f"  Source:      {source}")
    print(f"  Price:       ${coin.price_usd:,.8f}".rstrip('0').rstrip('.'))
    print(f"  Market cap:  ${coin.market_cap_usd:,.0f}")
    print(f"  Liquidity:   ${coin.liquidity_usd:,.0f}")
    print(f"  Volume 24h:  ${coin.volume_24h_usd:,.0f}")
    print(f"  Age:         {coin.token_age_days:.1f} days")
    print(f"  Price 24h:   {coin.price_change_24h_pct:+.2f}%")

    print()
    print(f"  MOMENTUM:    {mom['total']}/100")
    print(f"     price {mom['price']}  vol {mom['volume']}  "
          f"social {mom['social']}  liq {mom['liquidity']}")
    print(f"  SCAM RISK:   {risk['score']}/100   {risk['label']}")
    if opp["score"] is not None:
        print(f"  OPPORTUNITY: {opp['score']}/100   {opp['tier'][0]}")
    else:
        print(f"  OPPORTUNITY: hidden (risk too high)")

    if risk["flags"]:
        print("\n  Risk flags:")
        for label, sev in risk["flags"]:
            tag = {"critical": "!!!", "major": " !!", "minor": "  ."}[sev]
            print(f"   {tag} [{sev:8}] {label}")

    print()
    print("  Notes:")
    print("  - Holder concentration and on-chain authority flags are not yet")
    print("    connected. The scam-risk score is conservative — it may MISS")
    print("    serious problems. Treat results as a starting point for research.")
    print()


def main():
    if len(sys.argv) < 2:
        print()
        print("Usage:  python check.py <coin>")
        print()
        print("Examples:")
        print("  python check.py bitcoin")
        print("  python check.py pepe")
        print("  python check.py dogwifcoin")
        print("  python check.py 0x6982508145454ce325ddbe47a25d4ec3d2311933")
        print()
        sys.exit(1)

    query = sys.argv[1].lower()
    print(f"\nLooking up '{query}'...")

    # Try CoinGecko first for known coins (better data for established tokens)
    try:
        coin = fetch_from_coingecko(query)
        if coin and coin.price_usd > 0:
            print_report(coin, "CoinGecko")
            return
    except Exception as e:
        print(f"  (CoinGecko: {e})")

    # Fall back to DexScreener (better for memecoins and contract addresses)
    print("  Not found on CoinGecko — trying DexScreener...")
    try:
        coin = fetch_from_dexscreener(query)
        if coin and coin.price_usd > 0:
            print_report(coin, "DexScreener")
            return
    except Exception as e:
        print(f"  (DexScreener: {e})")

    print()
    print(f"  Could not find '{query}' on either source.")
    print("  Try the CoinGecko ID (e.g. 'bitcoin' not 'BTC') or the contract address.")
    print()


if __name__ == "__main__":
    main()
