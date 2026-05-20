"""
dashboard.py — Crypto Intelligence Platform

Live, auto-discovering dashboard. Pulls trending coins from DexScreener and
CoinGecko on every load (cached 5 min), scores them all, surfaces the top
opportunities with filtering and detail views.

Run locally:
    streamlit run dashboard.py

Deployed:
    Pushed to GitHub → Streamlit Community Cloud auto-redeploys.
"""

import sys
import os
import streamlit as st
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'src'))
sys.path.insert(0, os.path.join(HERE, 'prompts'))
sys.path.insert(0, HERE)

from scoring import full_analysis
from discovery import discover_trending, lookup_one


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
    /* Hide Streamlit branding */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}

    /* Tighter spacing */
    .block-container {padding-top: 2rem; padding-bottom: 2rem; max-width: 1400px;}

    /* Coin card styling */
    .coin-card {
        background: linear-gradient(135deg, rgba(255,255,255,0.04) 0%, rgba(255,255,255,0.01) 100%);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 12px;
        padding: 16px 20px;
        margin-bottom: 12px;
        transition: all 0.15s;
    }
    .coin-card:hover {
        border-color: rgba(255,255,255,0.18);
    }

    /* Tier badges */
    .badge {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 999px;
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.3px;
        text-transform: uppercase;
    }
    .badge-green {background: rgba(34, 197, 94, 0.15); color: #4ade80;}
    .badge-yellow {background: rgba(234, 179, 8, 0.15); color: #facc15;}
    .badge-blue {background: rgba(59, 130, 246, 0.15); color: #60a5fa;}
    .badge-red {background: rgba(239, 68, 68, 0.15); color: #f87171;}
    .badge-gray {background: rgba(148, 163, 184, 0.15); color: #94a3b8;}

    /* Big score display */
    .score-display {
        font-size: 32px;
        font-weight: 700;
        line-height: 1;
    }
    .score-label {
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        opacity: 0.6;
        margin-bottom: 4px;
    }

    /* Coin meta row */
    .meta-row {
        display: flex;
        gap: 16px;
        font-size: 12px;
        opacity: 0.7;
        margin-top: 4px;
    }
    .meta-row span {white-space: nowrap;}

    /* Price change colors */
    .price-up {color: #4ade80;}
    .price-down {color: #f87171;}

    /* Chain pills */
    .chain-pill {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 10px;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.3px;
        background: rgba(255,255,255,0.06);
        margin-left: 8px;
    }

    /* Stat tiles */
    [data-testid="stMetricValue"] {font-size: 24px; font-weight: 600;}

    /* Make expanders less visually heavy */
    .streamlit-expanderHeader {
        background: transparent !important;
        border: none !important;
    }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Data fetching (cached)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)  # 5 minutes
def cached_discover():
    """Run discovery and score everything. Cached so it only runs once per 5min."""
    coins = discover_trending(max_per_chain=25)
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
    return f"${p:.10f}".rstrip('0').rstrip('.')


def fmt_money(m: float) -> str:
    if m >= 1_000_000_000: return f"${m/1e9:.2f}B"
    if m >= 1_000_000: return f"${m/1e6:.2f}M"
    if m >= 1_000: return f"${m/1e3:.1f}K"
    return f"${m:,.0f}"


def fmt_pct(p: float) -> str:
    return f"{p:+.2f}%"


def tier_badge(score: float | None) -> str:
    if score is None:
        return '<span class="badge badge-red">HIDDEN</span>'
    if score >= 80:
        return '<span class="badge badge-green">🔥 HIGH SIGNAL</span>'
    if score >= 60:
        return '<span class="badge badge-yellow">⚡ NOTABLE</span>'
    if score >= 40:
        return '<span class="badge badge-blue">👀 WATCH</span>'
    return '<span class="badge badge-gray">LOW</span>'


def risk_badge(score: int) -> str:
    if score <= 20:
        return f'<span class="badge badge-green">✓ RISK {score}</span>'
    if score <= 50:
        return f'<span class="badge badge-yellow">⚠ RISK {score}</span>'
    if score <= 80:
        return f'<span class="badge badge-red">🚩 RISK {score}</span>'
    return f'<span class="badge badge-red">☠ RISK {score}</span>'


# ---------------------------------------------------------------------------
# Coin card rendering
# ---------------------------------------------------------------------------

def render_coin_card(coin, analysis, rank: int | None = None):
    mom = analysis["momentum"]
    risk = analysis["scam_risk"]
    opp = analysis["opportunity"]

    pc_24h = coin.price_change_24h_pct
    pc_class = "price-up" if pc_24h >= 0 else "price-down"

    rank_html = f'<span style="opacity:0.4; font-size:14px; margin-right:8px;">#{rank}</span>' if rank else ""

    opp_display = f'{opp["score"]:.0f}' if opp["score"] is not None else "—"
    opp_color = "color: #94a3b8;" if opp["score"] is None else ""

    card_html = f"""
    <div class="coin-card">
      <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:16px;">
        <div style="flex:1; min-width:0;">
          <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
            <span style="font-size:18px; font-weight:600;">{rank_html}{coin.symbol}</span>
            <span style="opacity:0.6; font-size:14px;">{coin.name[:40]}</span>
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
          <div class="score-display" style="{opp_color}">{opp_display}</div>
        </div>
      </div>
    </div>
    """
    st.markdown(card_html, unsafe_allow_html=True)


def render_coin_detail(coin, analysis):
    """Expanded detail view for a single coin."""
    mom = analysis["momentum"]
    risk = analysis["scam_risk"]
    opp = analysis["opportunity"]

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

    # Score tiles
    c1, c2, c3 = st.columns(3)
    c1.metric("Momentum", f"{mom['total']:.0f}/100")
    c2.metric("Scam Risk", f"{risk['score']}/100")
    opp_val = f"{opp['score']:.0f}/100" if opp['score'] is not None else "Hidden"
    c3.metric("Opportunity", opp_val)

    # Market data
    st.markdown("### Market data")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Market cap", fmt_money(coin.market_cap_usd))
    m2.metric("Liquidity", fmt_money(coin.liquidity_usd))
    m3.metric("Volume 24h", fmt_money(coin.volume_24h_usd))
    m4.metric("Age", f"{coin.token_age_days:.0f} days")

    # Momentum breakdown
    st.markdown("### Momentum breakdown")
    cols = st.columns(6)
    components = [
        ("Price", mom["price"]),
        ("Volume", mom["volume"]),
        ("Social", mom["social"]),
        ("Holders", mom["holders"]),
        ("Liquidity", mom["liquidity"]),
        ("Listing", mom["listing"]),
    ]
    for col, (label, val) in zip(cols, components):
        col.metric(label, f"{val:.0f}")

    # Risk flags
    if risk["flags"]:
        st.markdown("### Risk flags detected")
        for label, sev in risk["flags"]:
            icon = {"critical": "🔴", "major": "🟠", "minor": "🟡"}[sev]
            st.markdown(f"{icon} **[{sev.upper()}]** {label}")
    else:
        st.markdown("### Risk flags")
        st.success("No flags detected from available data.")

    # Caveats
    st.markdown("---")
    st.caption(
        "⚠️ Holder concentration and on-chain authority flags are not yet "
        "wired in — scam risk score is conservative and may miss serious "
        "problems. Cross-check on rugcheck.xyz (Solana) or tokensniffer.com (EVM) "
        "before trusting any coin. Not financial advice."
    )

    # Contract address
    if coin.contract_address and coin.contract_address != "n/a":
        st.caption(f"Contract: `{coin.contract_address}`")


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("## 🔍 Look up a coin")
    search = st.text_input("Symbol, name, or contract address",
                          placeholder="e.g. PEPE or 0x...",
                          label_visibility="collapsed")
    if st.button("Analyze", use_container_width=True, type="primary"):
        st.session_state.search_query = search.strip()

    st.markdown("---")
    st.markdown("## ⚙️ Filters")

    chain_filter = st.multiselect(
        "Chains",
        options=["solana", "ethereum", "base", "bsc"],
        default=["solana", "ethereum", "base", "bsc"],
    )

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

    st.caption(f"Data refreshes every 5 min · Cached for performance")
    st.caption(f"Sources: DexScreener · CoinGecko")


# ---------------------------------------------------------------------------
# Main content
# ---------------------------------------------------------------------------

# If a search query was submitted, show that detail view
if "search_query" in st.session_state and st.session_state.search_query:
    q = st.session_state.search_query
    if st.button("← Back to dashboard"):
        st.session_state.search_query = ""
        st.rerun()

    with st.spinner(f"Looking up {q}..."):
        result = cached_lookup(q)

    if result is None:
        st.error(f"Couldn't find '{q}' on DexScreener or CoinGecko. "
                "Try a contract address or a more specific symbol.")
    else:
        coin, analysis = result
        render_coin_detail(coin, analysis)
    st.stop()


# Header
st.markdown("# 📊 Crypto Intelligence")
st.markdown(f"<p style='opacity:0.6; margin-top:-12px;'>Auto-discovering trending coins · Updated {datetime.now().strftime('%H:%M')}</p>",
           unsafe_allow_html=True)

# Discover trending coins
with st.spinner("🔍 Pulling trending coins from DexScreener and CoinGecko..."):
    scored = cached_discover()

if not scored:
    st.error("Couldn't pull data from sources. APIs may be rate-limited — try again in a minute.")
    st.stop()

# Apply filters
filtered = [
    (c, a) for c, a in scored
    if c.chain in chain_filter
    and c.liquidity_usd >= min_liquidity
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

# Summary tiles
total = len(scored)
high_signal = sum(1 for _, a in scored
                  if a["opportunity"]["score"] and a["opportunity"]["score"] >= 60)
flagged = sum(1 for _, a in scored if a["scam_risk"]["score"] >= 60)
chains_active = len(set(c.chain for c, _ in scored))

c1, c2, c3, c4 = st.columns(4)
c1.metric("Coins scored", total)
c2.metric("🔥 High signal", high_signal)
c3.metric("🚩 Flagged", flagged)
c4.metric("Chains", chains_active)

st.markdown("---")

# Top 10
st.markdown("### 🏆 Top 10 Opportunities Today")
top_10 = [(c, a) for c, a in filtered if a["opportunity"]["score"] is not None][:10]
if not top_10:
    st.info("No coins matching current filters meet the opportunity threshold. Try adjusting filters.")
else:
    for i, (coin, analysis) in enumerate(top_10, 1):
        render_coin_card(coin, analysis, rank=i)

# Full list
st.markdown("---")
st.markdown(f"### All discovered coins ({len(filtered)})")
st.caption(f"Sorted by: {sort_by}")

if not filtered:
    st.info("No coins match current filters.")
else:
    for coin, analysis in filtered[10:]:
        render_coin_card(coin, analysis)

# Footer
st.markdown("---")
st.caption(
    "**Not financial advice.** Scores are heuristic, based on currently "
    "observable data, and frequently wrong. On-chain authority flags and "
    "holder concentration are not yet connected — scam risk is conservative "
    "and may miss problems. Always cross-check on rugcheck.xyz or tokensniffer.com "
    "before trusting any coin. Crypto is high-risk — only deploy capital you "
    "can afford to lose entirely."
)
