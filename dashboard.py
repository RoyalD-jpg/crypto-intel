"""
dashboard.py — Crypto Intelligence Platform (v3, Solana-focused)

Changes from v2:
  - Solana-only discovery (where the action is, and where Helius gives us
    real on-chain risk data)
  - Clickable coin cards → expanded detail view
  - Helius integration for mint/freeze authority and holder concentration
  - Richer detail page: full momentum breakdown, risk flags with explanations,
    contract info, external links

Run locally:
    set HELIUS_API_KEY=your_key_here   (Windows PowerShell: $env:HELIUS_API_KEY="your_key")
    streamlit run dashboard.py
"""

import sys
import os
import streamlit as st
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'src'))
sys.path.insert(0, os.path.join(HERE, 'prompts'))
sys.path.insert(0, HERE)

# Surface Streamlit secrets as environment variables BEFORE importing helius
# (helius reads HELIUS_API_KEY at import time)
try:
    if hasattr(st, "secrets") and "HELIUS_API_KEY" in st.secrets:
        os.environ["HELIUS_API_KEY"] = st.secrets["HELIUS_API_KEY"]
except Exception:
    pass

from scoring import full_analysis
from discovery import discover_trending, lookup_one
from helius import is_configured as helius_configured


# ---------------------------------------------------------------------------
# Page config + styling
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Crypto Intelligence",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    .block-container {padding-top: 2rem; padding-bottom: 2rem; max-width: 1400px;}

    /* Coin card */
    .coin-card {
        background: linear-gradient(135deg, rgba(255,255,255,0.04) 0%, rgba(255,255,255,0.01) 100%);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 12px;
        padding: 16px 20px;
        margin-bottom: 12px;
    }
    .coin-card-rank {
        opacity: 0.4;
        font-size: 14px;
        margin-right: 8px;
        font-weight: 500;
    }

    /* Badges */
    .badge {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 999px;
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.3px;
        text-transform: uppercase;
        margin-right: 6px;
    }
    .badge-green {background: rgba(34, 197, 94, 0.15); color: #4ade80;}
    .badge-yellow {background: rgba(234, 179, 8, 0.15); color: #facc15;}
    .badge-blue {background: rgba(59, 130, 246, 0.15); color: #60a5fa;}
    .badge-red {background: rgba(239, 68, 68, 0.15); color: #f87171;}
    .badge-gray {background: rgba(148, 163, 184, 0.15); color: #94a3b8;}

    /* Score displays */
    .score-display {font-size: 32px; font-weight: 700; line-height: 1;}
    .score-display-dim {color: #94a3b8;}
    .score-label {
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        opacity: 0.6;
        margin-bottom: 4px;
    }

    /* Meta */
    .meta-row {
        display: flex;
        gap: 16px;
        font-size: 12px;
        opacity: 0.75;
        margin-top: 6px;
        flex-wrap: wrap;
    }
    .price-up {color: #4ade80;}
    .price-down {color: #f87171;}

    /* Chain pill (kept even though Solana-only — looks clean) */
    .chain-pill {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 10px;
        font-weight: 500;
        text-transform: uppercase;
        background: rgba(153, 69, 255, 0.15);
        color: #c084fc;
        margin-left: 8px;
    }

    /* Connection status indicator */
    .status-dot {
        display: inline-block;
        width: 8px;
        height: 8px;
        border-radius: 50%;
        margin-right: 6px;
        vertical-align: middle;
    }
    .status-on {background: #4ade80; box-shadow: 0 0 8px #4ade80;}
    .status-off {background: #94a3b8;}

    [data-testid="stMetricValue"] {font-size: 22px; font-weight: 600;}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Cached data layer
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def cached_discover():
    coins = discover_trending(max_per_chain=40)
    scored = []
    for c in coins:
        try:
            a = full_analysis(c)
            scored.append((c, a))
        except Exception:
            continue
    return scored


@st.cache_data(ttl=300, show_spinner=False)
def cached_lookup(query: str):
    coin = lookup_one(query)
    if not coin:
        return None
    return coin, full_analysis(coin)


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def fmt_price(p: float) -> str:
    if p >= 1: return f"${p:,.4f}"
    if p >= 0.01: return f"${p:.4f}"
    if p >= 0.0001: return f"${p:.6f}"
    if p > 0:
        s = f"${p:.10f}"
        return s.rstrip('0').rstrip('.') or "$0"
    return "$0"


def fmt_money(m: float) -> str:
    if m is None or m <= 0: return "—"
    if m >= 1_000_000_000: return f"${m/1e9:.2f}B"
    if m >= 1_000_000: return f"${m/1e6:.2f}M"
    if m >= 1_000: return f"${m/1e3:.1f}K"
    return f"${m:,.0f}"


def fmt_pct(p: float) -> str:
    return f"{p:+.2f}%"


def tier_badge(score) -> str:
    if score is None:
        return '<span class="badge badge-red">RISK HIDDEN</span>'
    if score >= 80: return '<span class="badge badge-green">🔥 HIGH SIGNAL</span>'
    if score >= 60: return '<span class="badge badge-yellow">⚡ NOTABLE</span>'
    if score >= 40: return '<span class="badge badge-blue">👀 WATCH</span>'
    return '<span class="badge badge-gray">LOW</span>'


def risk_badge(score: int) -> str:
    if score <= 20: return f'<span class="badge badge-green">✓ RISK {score}</span>'
    if score <= 50: return f'<span class="badge badge-yellow">⚠ RISK {score}</span>'
    if score <= 80: return f'<span class="badge badge-red">🚩 RISK {score}</span>'
    return f'<span class="badge badge-red">☠ RISK {score}</span>'


# ---------------------------------------------------------------------------
# Coin card (clickable via a button below it)
# ---------------------------------------------------------------------------

def render_coin_card(coin, analysis, rank: int | None = None, key_prefix: str = ""):
    mom = analysis["momentum"]
    risk = analysis["scam_risk"]
    opp = analysis["opportunity"]

    pc_24h = coin.price_change_24h_pct
    pc_class = "price-up" if pc_24h >= 0 else "price-down"

    rank_html = f'<span class="coin-card-rank">#{rank}</span>' if rank else ""
    opp_display = f'{opp["score"]:.0f}' if opp["score"] is not None else "—"
    opp_class = "score-display-dim" if opp["score"] is None else ""

    safe_name = (coin.name or "")[:40]

    card_html = f"""
    <div class="coin-card">
      <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:16px;">
        <div style="flex:1; min-width:0;">
          <div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;">
            <span style="font-size:18px; font-weight:600;">{rank_html}{coin.symbol}</span>
            <span style="opacity:0.6; font-size:14px;">{safe_name}</span>
            <span class="chain-pill">{coin.chain}</span>
          </div>
          <div class="meta-row">
            <span><strong>{fmt_price(coin.price_usd)}</strong></span>
            <span class="{pc_class}">{fmt_pct(pc_24h)} 24h</span>
            <span>MC {fmt_money(coin.market_cap_usd)}</span>
            <span>Vol {fmt_money(coin.volume_24h_usd)}</span>
            <span>Liq {fmt_money(coin.liquidity_usd)}</span>
            <span>{coin.token_age_days:.0f}d old</span>
          </div>
          <div style="margin-top:10px;">
            {tier_badge(opp["score"])}
            {risk_badge(risk["score"])}
          </div>
        </div>
        <div style="text-align:right; min-width:90px;">
          <div class="score-label">Momentum</div>
          <div class="score-display">{mom["total"]:.0f}</div>
        </div>
        <div style="text-align:right; min-width:90px;">
          <div class="score-label">Opportunity</div>
          <div class="score-display {opp_class}">{opp_display}</div>
        </div>
      </div>
    </div>
    """
    st.markdown(card_html, unsafe_allow_html=True)

    # Click-through button
    btn_key = f"{key_prefix}detail_{coin.contract_address or coin.symbol}_{rank or 'x'}"
    if st.button(f"View details →", key=btn_key, use_container_width=False):
        st.session_state.detail_address = coin.contract_address
        st.session_state.detail_symbol = coin.symbol
        st.rerun()


# ---------------------------------------------------------------------------
# Flag explanations (for the detail page)
# ---------------------------------------------------------------------------

FLAG_EXPLANATIONS = {
    "Mint authority not renounced": "The developer can create unlimited new tokens at any moment. If they do, the value of every existing token crashes to near zero instantly.",
    "Freeze authority active": "The developer can freeze any user's wallet, preventing them from selling. This is one of the most aggressive scam vectors on Solana.",
    "Contract owner has modification powers": "The deployer retains the ability to change contract behavior. They could enable selling restrictions, add fees, or drain liquidity.",
    "Honeypot": "Buy transactions succeed but sell transactions revert. You can put money in but you can't take it out.",
    "Top wallet holds": "When one wallet controls a majority of supply, that single holder can dump and crash the price whenever they want.",
    "Liquidity not locked": "The dev's liquidity isn't locked in a vault. They can pull it out at any moment, leaving holders unable to sell.",
    "Top 10 wallets hold": "Concentrated holdings mean a handful of wallets can coordinate to crash the price.",
    "Liquidity only": "When liquidity is tiny, even small sells crash the price. You may not be able to exit a meaningful position.",
    "Contract less than 24 hours old": "Brand-new tokens have no track record. The vast majority of <24h tokens are pump-and-dump schemes.",
    "No social presence": "Legitimate projects build communities. Total absence usually means the token has been abandoned or was never serious.",
    "Contract not verified": "Without verified source code, you can't see what the contract actually does. Hidden malicious functions are common.",
    "Tax asymmetry": "When sell tax is much higher than buy tax, the dev is making it expensive to exit. Often paired with rising sell taxes over time.",
    "Single liquidity pool": "All exit liquidity is in one pool. If that pool is drained or compromised, there's nowhere to sell.",
    "Anonymous team": "Common in crypto but worth noting — no accountability if things go wrong.",
    "of mentions look bot-driven": "Coordinated bot activity inflates apparent interest. Real organic demand may be much lower than mention counts suggest.",
    "Chart shows classic pump": "Vertical price spike followed by distribution is the textbook pump-and-dump signature.",
}


def explain_flag(flag_text: str) -> str:
    """Find the explanation matching the flag prefix."""
    for prefix, explanation in FLAG_EXPLANATIONS.items():
        if prefix.lower() in flag_text.lower():
            return explanation
    return "Worth investigating further."


# ---------------------------------------------------------------------------
# Detail page
# ---------------------------------------------------------------------------

def render_coin_detail(coin, analysis):
    mom = analysis["momentum"]
    risk = analysis["scam_risk"]
    opp = analysis["opportunity"]

    # Back button
    if st.button("← Back to dashboard"):
        st.session_state.detail_address = None
        st.session_state.detail_symbol = None
        st.rerun()

    # Header
    pc_class = "price-up" if coin.price_change_24h_pct >= 0 else "price-down"
    st.markdown(f"""
    <div style="margin-bottom: 24px;">
      <div style="display:flex; align-items:baseline; gap:12px; flex-wrap:wrap;">
        <h1 style="margin:0;">{coin.symbol}</h1>
        <span style="opacity:0.6; font-size:18px;">{coin.name}</span>
        <span class="chain-pill">{coin.chain}</span>
      </div>
      <div style="margin-top:8px;">
        <span style="font-size:28px; font-weight:600;">{fmt_price(coin.price_usd)}</span>
        <span class="{pc_class}" style="margin-left:12px; font-size:16px;">{fmt_pct(coin.price_change_24h_pct)} 24h</span>
        <span class="{pc_class}" style="margin-left:8px; font-size:13px; opacity:0.7;">{fmt_pct(coin.price_change_1h_pct)} 1h</span>
      </div>
      <div style="margin-top:12px;">
        {tier_badge(opp["score"])}
        {risk_badge(risk["score"])}
      </div>
    </div>
    """, unsafe_allow_html=True)

    # Tabs for organization
    tab1, tab2, tab3 = st.tabs(["📊 Overview", "🔍 Risk Analysis", "🔗 Links & Contract"])

    # ---- OVERVIEW TAB ----
    with tab1:
        # Top scores
        c1, c2, c3 = st.columns(3)
        c1.metric("Momentum", f"{mom['total']:.0f}/100")
        c2.metric("Scam Risk", f"{risk['score']}/100", help=risk["label"])
        opp_val = f"{opp['score']:.0f}/100" if opp['score'] is not None else "Hidden"
        c3.metric("Opportunity", opp_val)

        st.markdown("### Market data")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Market cap", fmt_money(coin.market_cap_usd))
        m2.metric("Liquidity", fmt_money(coin.liquidity_usd))
        m3.metric("Volume 24h", fmt_money(coin.volume_24h_usd))
        m4.metric("Age", f"{coin.token_age_days:.0f}d")

        st.markdown("### Price action")
        p1, p2, p3 = st.columns(3)
        p1.metric("1 hour", fmt_pct(coin.price_change_1h_pct))
        p2.metric("24 hours", fmt_pct(coin.price_change_24h_pct))
        if coin.price_change_7d_pct:
            p3.metric("7 days", fmt_pct(coin.price_change_7d_pct))
        else:
            p3.metric("7 days", "—", help="Not available from DexScreener")

        st.markdown("### Momentum breakdown")
        st.caption("How the momentum score of "
                  f"{mom['total']:.0f} was assembled. Each component is 0-100, then weighted.")

        # Bar-style visualization of components
        components = [
            ("Price action", mom["price"], "25%"),
            ("Volume", mom["volume"], "20%"),
            ("Social mentions", mom["social"], "15%"),
            ("Holder growth", mom["holders"], "15%"),
            ("Liquidity change", mom["liquidity"], "15%"),
            ("Exchange listings", mom["listing"], "10%"),
        ]
        for label, val, weight in components:
            cols = st.columns([2, 5, 1])
            cols[0].markdown(f"**{label}**")
            cols[0].caption(f"weight: {weight}")
            cols[1].progress(val / 100)
            cols[2].markdown(f"<div style='text-align:right; font-weight:600; font-size:18px;'>{val:.0f}</div>",
                           unsafe_allow_html=True)

        st.markdown("### Holders")
        h1, h2, h3 = st.columns(3)
        h1.metric("Holder count", f"{coin.holder_count:,}")
        if helius_configured() and coin.chain == "solana":
            h2.metric("Top wallet", f"{coin.top_wallet_pct:.1f}%",
                     help="From on-chain data via Helius")
            h3.metric("Top 10 wallets", f"{coin.top_10_holder_pct:.1f}%",
                     help="From on-chain data via Helius")
        else:
            h2.metric("Top wallet", "—", help="Helius not configured")
            h3.metric("Top 10 wallets", "—", help="Helius not configured")

    # ---- RISK ANALYSIS TAB ----
    with tab2:
        st.markdown(f"### Risk score: {risk['score']}/100 — {risk['label']}")

        if not risk["flags"]:
            st.success("No risk flags detected from available data.")
            st.caption("Absence of flags doesn't guarantee safety — it means "
                      "none of the heuristics fired. Always cross-check on "
                      "rugcheck.xyz before trusting a coin.")
        else:
            st.markdown("Each flag is explained below. Critical flags mean **do not trust** "
                       "the token without serious additional research.")
            for label, sev in risk["flags"]:
                icon = {"critical": "🔴", "major": "🟠", "minor": "🟡"}[sev]
                with st.expander(f"{icon} [{sev.upper()}] {label}", expanded=(sev == "critical")):
                    st.markdown(explain_flag(label))

        st.markdown("---")
        st.markdown("### How risk score is calculated")
        st.caption("Any single critical flag → score 100. Otherwise: 25 points per major flag, "
                  "10 per minor flag, capped at 99. We use MAX of critical rather than weighted "
                  "average because no amount of momentum compensates for a rug-able contract.")

        if not helius_configured():
            st.warning("⚠️ Helius API key not configured — on-chain risk flags "
                      "(mint authority, freeze authority, holder concentration) are using "
                      "conservative defaults. Set HELIUS_API_KEY in Streamlit secrets for real "
                      "on-chain risk detection.")

    # ---- LINKS TAB ----
    with tab3:
        st.markdown("### Contract")
        if coin.contract_address and coin.contract_address != "n/a":
            st.code(coin.contract_address, language=None)
            if coin.chain == "solana":
                st.markdown(f"[View on Solscan](https://solscan.io/token/{coin.contract_address}) · "
                           f"[View on DexScreener](https://dexscreener.com/solana/{coin.contract_address}) · "
                           f"[Risk check on rugcheck.xyz](https://rugcheck.xyz/tokens/{coin.contract_address}) · "
                           f"[Trade on Jupiter](https://jup.ag/swap/SOL-{coin.contract_address})")
        else:
            st.caption("Contract address not available")

        st.markdown("### Verify on third-party sources")
        st.markdown("Before trusting any score on this dashboard, **always** cross-check the coin "
                   "on independent sources:")
        st.markdown("- **[rugcheck.xyz](https://rugcheck.xyz)** — Solana-specific risk analysis")
        st.markdown("- **[DexScreener](https://dexscreener.com)** — Live charts and trade history")
        st.markdown("- **[Solscan](https://solscan.io)** — On-chain transaction history")

    # Footer
    st.markdown("---")
    st.caption(
        "**Not financial advice.** Scores are heuristic and frequently wrong. "
        "Crypto is high-risk — only deploy capital you can afford to lose entirely."
    )


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("## 🔍 Look up a coin")
    search = st.text_input("Symbol, name, or contract address",
                          placeholder="e.g. WIF or contract address",
                          label_visibility="collapsed")
    if st.button("Analyze", use_container_width=True, type="primary"):
        if search.strip():
            st.session_state.search_query = search.strip()
            st.rerun()

    st.markdown("---")
    st.markdown("## ⚙️ Filters")

    sort_by = st.selectbox(
        "Sort by",
        ["Opportunity", "Momentum", "Risk (low to high)", "Volume", "Price 24h"],
    )

    show_high_risk = st.checkbox("Show high-risk coins", value=False,
                                help="Coins with risk ≥ 60 are hidden by default")

    min_liquidity = st.select_slider(
        "Min liquidity",
        options=[0, 10_000, 25_000, 100_000, 500_000, 1_000_000],
        value=10_000,
        format_func=lambda x: fmt_money(x) if x else "Any",
    )

    st.markdown("---")
    if st.button("🔄 Refresh data", use_container_width=True):
        cached_discover.clear()
        cached_lookup.clear()
        st.rerun()

    st.markdown("---")
    # Connection status
    helius_status = "status-on" if helius_configured() else "status-off"
    helius_text = "Helius connected" if helius_configured() else "Helius not configured"
    st.markdown(f'<div style="font-size:12px;"><span class="status-dot {helius_status}"></span>{helius_text}</div>',
               unsafe_allow_html=True)
    st.caption("Chain: Solana only · Data refreshes every 5 min")


# ---------------------------------------------------------------------------
# Main content routing
# ---------------------------------------------------------------------------

# Initialize session state
if "detail_address" not in st.session_state:
    st.session_state.detail_address = None
if "search_query" not in st.session_state:
    st.session_state.search_query = None

# Route 1: Search result detail
if st.session_state.search_query:
    q = st.session_state.search_query
    if st.button("← Back to dashboard", key="back_from_search"):
        st.session_state.search_query = None
        st.rerun()
    with st.spinner(f"Looking up {q}..."):
        result = cached_lookup(q)
    if result is None:
        st.error(f"Couldn't find '{q}' on DexScreener. "
                "Try a Solana contract address or a more specific symbol.")
    else:
        coin, analysis = result
        render_coin_detail(coin, analysis)
    st.stop()

# Route 2: Click-through detail from a card
if st.session_state.detail_address:
    addr = st.session_state.detail_address
    with st.spinner("Loading coin details..."):
        result = cached_lookup(addr)
    if result is None:
        st.error("Couldn't load that coin's details. Try refreshing.")
        if st.button("← Back to dashboard"):
            st.session_state.detail_address = None
            st.rerun()
    else:
        coin, analysis = result
        render_coin_detail(coin, analysis)
    st.stop()

# Route 3: Main dashboard
st.markdown("# 📊 Crypto Intelligence")
st.markdown(f"<p style='opacity:0.6; margin-top:-12px;'>Solana · Auto-discovered · Updated {datetime.now().strftime('%H:%M')}</p>",
           unsafe_allow_html=True)

with st.spinner("🔍 Pulling trending Solana coins..."):
    scored = cached_discover()

if not scored:
    st.error("Couldn't pull data — APIs may be rate-limited. Try again in a minute.")
    st.stop()

# Apply filters
filtered = [
    (c, a) for c, a in scored
    if c.liquidity_usd >= min_liquidity
    and (show_high_risk or a["scam_risk"]["score"] < 60)
]

# Sort
sort_fns = {
    "Opportunity": lambda x: x[1]["opportunity"]["score"] if x[1]["opportunity"]["score"] is not None else -1,
    "Momentum": lambda x: x[1]["momentum"]["total"],
    "Risk (low to high)": lambda x: -x[1]["scam_risk"]["score"],
    "Volume": lambda x: x[0].volume_24h_usd,
    "Price 24h": lambda x: x[0].price_change_24h_pct,
}
filtered.sort(key=sort_fns[sort_by], reverse=True)

# Summary
total = len(scored)
high_signal = sum(1 for _, a in scored
                  if a["opportunity"]["score"] and a["opportunity"]["score"] >= 60)
flagged = sum(1 for _, a in scored if a["scam_risk"]["score"] >= 60)
critical = sum(1 for _, a in scored if a["scam_risk"]["score"] >= 100)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Coins scored", total)
c2.metric("🔥 High signal", high_signal)
c3.metric("🚩 Flagged", flagged)
c4.metric("☠ Critical", critical)

st.markdown("---")

# Top 10
st.markdown("### 🏆 Top 10 Opportunities Today")
top_10 = [(c, a) for c, a in filtered if a["opportunity"]["score"] is not None][:10]
if not top_10:
    st.info("No coins matching filters meet the opportunity threshold. Try adjusting filters.")
else:
    for i, (coin, analysis) in enumerate(top_10, 1):
        render_coin_card(coin, analysis, rank=i, key_prefix="top_")

# Full list
st.markdown("---")
st.markdown(f"### All discovered coins ({len(filtered)})")
st.caption(f"Sorted by: {sort_by}")

if not filtered:
    st.info("No coins match current filters.")
else:
    for i, (coin, analysis) in enumerate(filtered[10:], start=11):
        render_coin_card(coin, analysis, rank=i, key_prefix="full_")

# Footer
st.markdown("---")
st.caption(
    "**Not financial advice.** Scores are heuristic and frequently wrong. "
    "Cross-check on rugcheck.xyz before trusting any coin. "
    "Crypto is high-risk — only deploy capital you can afford to lose entirely."
)
