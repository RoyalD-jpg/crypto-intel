"""
dashboard.py — local web dashboard. Opens in your browser.

Run with:
    streamlit run dashboard.py

A browser tab opens at http://localhost:8501 showing a live dashboard.
You add coin IDs in the sidebar, hit Refresh, and it scores them all.

This runs only while the `streamlit run` command is active. Close PowerShell
and the dashboard stops. Step 3 (hosted version) covers always-on.
"""

import sys
import os
import streamlit as st
import requests
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'src'))
sys.path.insert(0, os.path.join(HERE, 'prompts'))

from scoring import CoinData, full_analysis

# Import the fetchers from check.py
sys.path.insert(0, HERE)
from check import fetch_from_coingecko, fetch_from_dexscreener


# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Crypto Intelligence",
    page_icon="📊",
    layout="wide",
)

# Dark-mode-friendly CSS tweaks
st.markdown("""
<style>
    .stMetric { background: rgba(255,255,255,0.03); padding: 12px; border-radius: 8px; }
    .risk-high { color: #ff6b6b; font-weight: 500; }
    .risk-low  { color: #51cf66; font-weight: 500; }
    .risk-mid  { color: #ffd43b; font-weight: 500; }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Cached fetcher (avoid hammering APIs)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=120)  # cache for 2 minutes
def fetch_coin(query: str):
    """Try CoinGecko, fall back to DexScreener."""
    try:
        coin = fetch_from_coingecko(query.lower())
        if coin and coin.price_usd > 0:
            return coin, "CoinGecko"
    except Exception:
        pass
    try:
        coin = fetch_from_dexscreener(query.lower())
        if coin and coin.price_usd > 0:
            return coin, "DexScreener"
    except Exception:
        pass
    return None, None


# ---------------------------------------------------------------------------
# Sidebar: watchlist management
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("Watchlist")

    if "watchlist" not in st.session_state:
        # Reasonable starter list
        st.session_state.watchlist = ["bitcoin", "ethereum", "solana", "pepe", "dogwifcoin"]

    new_coin = st.text_input("Add coin (CoinGecko ID or contract)", "")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Add", use_container_width=True) and new_coin.strip():
            cn = new_coin.strip().lower()
            if cn not in st.session_state.watchlist:
                st.session_state.watchlist.append(cn)
                st.rerun()
    with col2:
        if st.button("Refresh all", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    st.markdown("---")
    st.markdown("**Currently tracking:**")
    for coin_id in list(st.session_state.watchlist):
        cols = st.columns([4, 1])
        cols[0].text(coin_id)
        if cols[1].button("✕", key=f"rm_{coin_id}"):
            st.session_state.watchlist.remove(coin_id)
            st.rerun()

    st.markdown("---")
    st.caption("Data: CoinGecko + DexScreener (free tiers). "
               "Holder & on-chain data not yet connected.")


# ---------------------------------------------------------------------------
# Main: header + summary
# ---------------------------------------------------------------------------

st.title("Crypto Intelligence")
st.caption(f"Updated {datetime.now().strftime('%H:%M:%S')} · cache refreshes every 2 minutes")

# Fetch everything
results = []
with st.spinner(f"Scoring {len(st.session_state.watchlist)} coins..."):
    for q in st.session_state.watchlist:
        coin, source = fetch_coin(q)
        if coin:
            results.append((coin, full_analysis(coin), source))

if not results:
    st.warning("No coins loaded. Add some in the sidebar.")
    st.stop()

# Summary metrics
total = len(results)
high_signal = sum(1 for _, a, _ in results
                  if a["opportunity"]["score"] and a["opportunity"]["score"] >= 60)
flagged = sum(1 for _, a, _ in results if a["scam_risk"]["score"] >= 60)
avg_mom = sum(a["momentum"]["total"] for _, a, _ in results) / total

c1, c2, c3, c4 = st.columns(4)
c1.metric("Tracked", total)
c2.metric("High signal", high_signal)
c3.metric("Flagged", flagged)
c4.metric("Avg momentum", f"{avg_mom:.0f}")

st.markdown("---")


# ---------------------------------------------------------------------------
# Sort: opportunity score descending, hidden coins at bottom
# ---------------------------------------------------------------------------

def sort_key(item):
    _, a, _ = item
    opp = a["opportunity"]["score"]
    return (opp if opp is not None else -1)

results.sort(key=sort_key, reverse=True)


# ---------------------------------------------------------------------------
# Coin cards
# ---------------------------------------------------------------------------

for coin, analysis, source in results:
    mom = analysis["momentum"]
    risk = analysis["scam_risk"]
    opp = analysis["opportunity"]

    # Risk color
    if risk["score"] <= 20:
        risk_class, risk_emoji = "risk-low", "✅"
    elif risk["score"] <= 50:
        risk_class, risk_emoji = "risk-mid", "⚠️"
    else:
        risk_class, risk_emoji = "risk-high", "🚩"

    with st.container():
        header_cols = st.columns([3, 1, 1, 1])

        with header_cols[0]:
            st.subheader(f"{coin.symbol} — {coin.name}")
            st.caption(f"{coin.chain} · ${coin.price_usd:,.8f} · "
                      f"24h {coin.price_change_24h_pct:+.1f}% · source: {source}")

        with header_cols[1]:
            st.metric("Momentum", f"{mom['total']:.0f}")

        with header_cols[2]:
            st.markdown(f"**Risk** <span class='{risk_class}'>{risk_emoji} {risk['score']}</span>",
                       unsafe_allow_html=True)
            st.caption(risk["label"])

        with header_cols[3]:
            if opp["score"] is not None:
                st.metric("Opportunity", f"{opp['score']:.0f}")
            else:
                st.markdown("**Hidden**")
                st.caption("Risk too high")

        # Expandable details
        with st.expander("Details"):
            d1, d2 = st.columns(2)

            with d1:
                st.markdown("**Market**")
                st.text(f"Market cap:  ${coin.market_cap_usd:,.0f}")
                st.text(f"Liquidity:   ${coin.liquidity_usd:,.0f}")
                st.text(f"Volume 24h:  ${coin.volume_24h_usd:,.0f}")
                st.text(f"Age:         {coin.token_age_days:.0f} days")
                st.text(f"1h: {coin.price_change_1h_pct:+.2f}%   "
                       f"7d: {coin.price_change_7d_pct:+.2f}%")

            with d2:
                st.markdown("**Momentum breakdown**")
                st.text(f"Price:      {mom['price']:5.1f}")
                st.text(f"Volume:     {mom['volume']:5.1f}")
                st.text(f"Social:     {mom['social']:5.1f}")
                st.text(f"Holders:    {mom['holders']:5.1f}")
                st.text(f"Liquidity:  {mom['liquidity']:5.1f}")
                st.text(f"Listing:    {mom['listing']:5.1f}")

            if risk["flags"]:
                st.markdown("**Risk flags**")
                for label, sev in risk["flags"]:
                    st.text(f"  [{sev}] {label}")

        st.markdown("---")


# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

st.caption(
    "ℹ️ Not financial advice. Scores are heuristic, based on currently "
    "observable data, and frequently wrong. Holder concentration and on-chain "
    "authority flags are not yet connected — scam risk is conservative and "
    "may miss serious problems. Crypto is high-risk; only deploy capital you "
    "can afford to lose entirely."
)
