"""
Demo: Run the scoring engine on three realistic coin scenarios.

Run with:  python demo/run_demo.py

This shows you the engine working end-to-end without needing any API keys
or live data. The three scenarios are designed to stress-test the scoring:

  1. LEGIT_MOMENTUM — a real, organically growing token
  2. CLASSIC_RUG    — obvious red flags everywhere
  3. AMBIGUOUS      — moving fast but with concerning signals

Compare the scores to your gut read. If they don't agree, either the scoring
needs calibration or your gut needs more data. Both happen.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'prompts'))

from scoring import CoinData, full_analysis
from llm_prompts import build_thesis_prompt, build_scam_analysis_prompt


# ---------------------------------------------------------------------------
# Scenario 1: Legit momentum
# ---------------------------------------------------------------------------
# A token in the AI-agent narrative space, three months old, organic growth.
# Verified contract, locked liquidity, distributed holders. Listed on a mid-tier
# CEX a week ago. Mention growth is real but not insane.

LEGIT_MOMENTUM = CoinData(
    symbol="NEXUS",
    name="Nexus Protocol",
    contract_address="0x7a3...",
    chain="base",
    price_usd=0.0847,
    market_cap_usd=12_400_000,
    price_change_1h_pct=2.1,
    price_change_24h_pct=18.4,
    price_change_7d_pct=64.0,
    volume_24h_usd=2_800_000,
    avg_volume_7d_usd=900_000,
    liquidity_usd=580_000,
    liquidity_change_24h_pct=12.0,
    holder_count=8_400,
    new_holders_24h=620,
    top_10_holder_pct=24.0,
    top_wallet_pct=4.8,
    token_age_days=92,
    contract_verified=True,
    mentions_24h=1_840,
    mentions_prev_24h=780,
    sentiment_score=0.42,
    has_twitter=True,
    has_telegram=True,
    bot_mention_ratio=0.18,
    new_cex_listing_7d=True,
    mint_authority_active=False,
    freeze_authority_active=False,
    owner_can_modify=False,
    honeypot_detected=False,
    liquidity_locked=True,
    buy_tax_pct=0.0,
    sell_tax_pct=0.0,
    anonymous_team=False,
)


# ---------------------------------------------------------------------------
# Scenario 2: Classic rug-in-waiting
# ---------------------------------------------------------------------------
# Brand new Solana token. Mint authority still live. Top wallet holds majority.
# Massive 24h pump on heavy bot mentions. Tiny liquidity. No socials.

CLASSIC_RUG = CoinData(
    symbol="MOONPEPE",
    name="MoonPepe Inu",
    contract_address="Hf3...",
    chain="solana",
    price_usd=0.0000042,
    market_cap_usd=420_000,
    price_change_1h_pct=89.0,
    price_change_24h_pct=1240.0,
    price_change_7d_pct=1240.0,
    volume_24h_usd=380_000,
    avg_volume_7d_usd=15_000,
    liquidity_usd=8_400,
    liquidity_change_24h_pct=-5.0,
    holder_count=340,
    new_holders_24h=290,
    top_10_holder_pct=78.0,
    top_wallet_pct=64.0,
    token_age_days=0.6,
    contract_verified=False,
    mentions_24h=4_200,
    mentions_prev_24h=12,
    sentiment_score=0.78,
    has_twitter=False,
    has_telegram=False,
    bot_mention_ratio=0.72,
    mint_authority_active=True,
    freeze_authority_active=True,
    owner_can_modify=False,
    honeypot_detected=False,
    liquidity_locked=False,
    classic_pump_pattern=True,
    single_lp_only=True,
)


# ---------------------------------------------------------------------------
# Scenario 3: Ambiguous — real movement, concerning concentration
# ---------------------------------------------------------------------------
# Two-week-old Ethereum token. Real momentum, real holder growth, but the top
# 10 wallets hold a worrying amount. Contract is verified, liquidity locked.
# Could be early-stage legitimate; could be slow rug. Genuinely uncertain.

AMBIGUOUS = CoinData(
    symbol="GLITCH",
    name="Glitch.AI",
    contract_address="0x4f2...",
    chain="ethereum",
    price_usd=0.024,
    market_cap_usd=2_400_000,
    price_change_1h_pct=4.2,
    price_change_24h_pct=42.0,
    price_change_7d_pct=180.0,
    volume_24h_usd=420_000,
    avg_volume_7d_usd=90_000,
    liquidity_usd=145_000,
    liquidity_change_24h_pct=22.0,
    holder_count=1_240,
    new_holders_24h=380,
    top_10_holder_pct=44.0,
    top_wallet_pct=11.0,
    token_age_days=14.0,
    contract_verified=True,
    mentions_24h=520,
    mentions_prev_24h=180,
    sentiment_score=0.31,
    has_twitter=True,
    has_telegram=True,
    bot_mention_ratio=0.28,
    mint_authority_active=False,
    freeze_authority_active=False,
    owner_can_modify=False,
    honeypot_detected=False,
    liquidity_locked=True,
    anonymous_team=True,
)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def print_analysis(coin: CoinData):
    analysis = full_analysis(coin)
    print(f"\n{'='*72}")
    print(f"  {coin.symbol} — {coin.name} ({coin.chain})")
    print(f"{'='*72}")

    mom = analysis["momentum"]
    print(f"\n  MOMENTUM: {mom['total']}/100")
    print(f"    price: {mom['price']:>5}  volume: {mom['volume']:>5}  "
          f"social: {mom['social']:>5}")
    print(f"    holders: {mom['holders']:>5}  liquidity: {mom['liquidity']:>5}  "
          f"listing: {mom['listing']:>5}")

    risk = analysis["scam_risk"]
    print(f"\n  SCAM RISK: {risk['score']}/100  {risk['label']}")
    if risk["flags"]:
        for label, sev in risk["flags"]:
            marker = {"critical": "❌", "major": "⚠️ ", "minor": "·"}[sev]
            print(f"    {marker} [{sev}] {label}")
    else:
        print("    (no flags)")

    opp = analysis["opportunity"]
    if opp["score"] is None:
        print(f"\n  OPPORTUNITY: hidden (scam risk too high)")
    else:
        tier_label, tier_color = opp["tier"]
        print(f"\n  OPPORTUNITY: {opp['score']}/100  {tier_label}")

    print(f"\n  --- THESIS PROMPT (what gets sent to the LLM) ---")
    prompt = build_thesis_prompt(coin, analysis)
    # Print just first 600 chars so output stays readable
    print(prompt[:600] + "..." if len(prompt) > 600 else prompt)


def main():
    print("\n" + "█" * 72)
    print("  CRYPTO INTELLIGENCE — SCORING ENGINE DEMO")
    print("█" * 72)

    for coin in [LEGIT_MOMENTUM, CLASSIC_RUG, AMBIGUOUS]:
        print_analysis(coin)

    print("\n" + "█" * 72)
    print("  Demo complete. Compare these scores to your own read of the data.")
    print("█" * 72 + "\n")


if __name__ == "__main__":
    main()
