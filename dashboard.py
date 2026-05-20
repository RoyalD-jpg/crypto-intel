"""
dashboard.py — Crypto Intelligence Platform (v4)

This version focuses on CALIBRATION: tracking scores over time so you can
measure whether the dashboard's predictions are actually working.

New since v3:
  - Snapshot store: every refresh records all coin scores to SQLite
  - Watchlist: star any coin, see its trajectory over time
  - Calibration page: real performance stats on past dashboard calls
  - Coin detail: price/score history chart from your own snapshots
  - Cleaner three-tab navigation: Dashboard, Watchlist, Calibration
"""

import sys
import os
import streamlit as st
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'src'))
sys.path.insert(0, os.path.join(HERE, 'prompts'))
sys.path.insert(0, HERE)

# Surface Streamlit secrets as env vars BEFORE importing modules that read them
try:
    if hasattr(st, "secrets") and "HELIUS_API_KEY" in st.secrets:
        os.environ["HELIUS_API_KEY"] = st.secrets["HELIUS_API_KEY"]
except Exception:
    pass

from scoring import full_analysis
from discovery import discover_trending, lookup_one
from helius import is_configured as helius_configured
import history


# Initialize DB once per process
history.init_db()


# ---------------------------------------------------------------------------
# Page config + global styles
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="Crypto Intelligence",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    #MainMenu, footer, header {visibility: hidden;}
    .block-container {padding-top: 1.5rem; padding-bottom: 2rem; max-width: 1400px;}

    /* Cards */
    .coin-card {
        background: linear-gradient(135deg, rgba(255,255,255,0.04) 0%, rgba(255,255,255,0.01) 100%);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 12px;
        padding: 16px 20px;
        margin-bottom: 10px;
        transition: border-color 0.15s;
    }
    .coin-card:hover {border-color: rgba(255,255,255,0.18);}
    .coin-rank {opacity: 0.4; font-size: 14px; margin-right: 8px; font-weight: 500;}

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
    .badge-green {background: rgba(34,197,94,0.15); color: #4ade80;}
    .badge-yellow {background: rgba(234,179,8,0.15); color: #facc15;}
    .badge-blue {background: rgba(59,130,246,0.15); color: #60a5fa;}
    .badge-red {background: rgba(239,68,68,0.15); color: #f87171;}
    .badge-gray {background: rgba(148,163,184,0.15); color: #94a3b8;}
    .badge-purple {background: rgba(168,85,247,0.15); color: #c084fc;}

    .score-display {font-size: 30px; font-weight: 700; line-height: 1;}
    .score-display-dim {color: #94a3b8;}
    .score-label {
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        opacity: 0.55;
        margin-bottom: 3px;
    }

    .meta-row {
        display: flex; gap: 14px; font-size: 12px; opacity: 0.75;
        margin-top: 6px; flex-wrap: wrap;
    }
    .price-up {color: #4ade80;}
    .price-down {color: #f87171;}

    .chain-pill {
        display: inline-block; padding: 2px 8px; border-radius: 4px;
        font-size: 10px; font-weight: 500; text-transform: uppercase;
        background: rgba(153,69,255,0.15); color: #c084fc; margin-left: 6px;
    }

    .status-dot {
        display: inline-block; width: 8px; height: 8px; border-radius: 50%;
        margin-right: 6px; vertical-align: middle;
    }
    .status-on {background: #4ade80; box-shadow: 0 0 6px #4ade80;}
    .status-off {background: #94a3b8;}

    /* Tighten Streamlit's default padding */
    [data-testid="stMetricValue"] {font-size: 22px; font-weight: 600;}
    [data-testid="stHorizontalBlock"] {gap: 0.5rem;}

    /* Quieter tab styling */
    .stTabs [data-baseweb="tab-list"] {gap: 4px;}
    .stTabs [data-baseweb="tab"] {
        background: transparent;
        border-radius: 8px 8px 0 0;
        padding: 8px 16px;
    }
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Cached data
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
    # Snapshot to DB on every fresh discovery
    history.record_batch(scored)
    return scored


@st.cache_data(ttl=300, show_spinner=False)
def cached_lookup(query: str):
    coin = lookup_one(query)
    if not coin:
        return None
    a = full_analysis(coin)
    history.record_snapshot(coin, a)
    return coin, a


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def fmt_price(p):
    if not p or p <= 0: return "$0"
    if p >= 1: return f"${p:,.4f}"
    if p >= 0.01: return f"${p:.4f}"
    if p >= 0.0001: return f"${p:.6f}"
    s = f"${p:.10f}"
    return s.rstrip('0').rstrip('.') or "$0"


def fmt_money(m):
    if m is None or m <= 0: return "—"
    if m >= 1_000_000_000: return f"${m/1e9:.2f}B"
    if m >= 1_000_000: return f"${m/1e6:.2f}M"
    if m >= 1_000: return f"${m/1e3:.1f}K"
    return f"${m:,.0f}"


def fmt_pct(p):
    if p is None: return "—"
    return f"{p:+.2f}%"


def tier_badge(score):
    if score is None: return '<span class="badge badge-red">RISK HIDDEN</span>'
    if score >= 80: return '<span class="badge badge-green">🔥 HIGH SIGNAL</span>'
    if score >= 60: return '<span class="badge badge-yellow">⚡ NOTABLE</span>'
    if score >= 40: return '<span class="badge badge-blue">👀 WATCH</span>'
    return '<span class="badge badge-gray">LOW</span>'


def risk_badge(score):
    if score <= 20: return f'<span class="badge badge-green">✓ RISK {score}</span>'
    if score <= 50: return f'<span class="badge badge-yellow">⚠ RISK {score}</span>'
    if score <= 80: return f'<span class="badge badge-red">🚩 RISK {score}</span>'
    return f'<span class="badge badge-red">☠ RISK {score}</span>'


# ---------------------------------------------------------------------------
# Coin card
# ---------------------------------------------------------------------------

def render_coin_card(coin, analysis, rank=None, key_prefix=""):
    mom = analysis["momentum"]
    risk = analysis["scam_risk"]
    opp = analysis["opportunity"]

    pc_24h = coin.price_change_24h_pct or 0
    pc_class = "price-up" if pc_24h >= 0 else "price-down"

    rank_html = f'<span class="coin-rank">#{rank}</span>' if rank else ""
    opp_display = f'{opp["score"]:.0f}' if opp["score"] is not None else "—"
    opp_class = "score-display-dim" if opp["score"] is None else ""
    watch_marker = "⭐ " if history.is_watched(coin.contract_address) else ""

    safe_name = (coin.name or "")[:40]

    st.markdown(f"""
    <div class="coin-card">
      <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:16px;">
        <div style="flex:1; min-width:0;">
          <div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;">
            <span style="font-size:18px; font-weight:600;">{rank_html}{watch_marker}{coin.symbol}</span>
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
        <div style="text-align:right; min-width:80px;">
          <div class="score-label">Momentum</div>
          <div class="score-display">{mom["total"]:.0f}</div>
        </div>
        <div style="text-align:right; min-width:80px;">
          <div class="score-label">Opportunity</div>
          <div class="score-display {opp_class}">{opp_display}</div>
        </div>
      </div>
    </div>
    """, unsafe_allow_html=True)

    # Action buttons row
    btn_cols = st.columns([1, 1, 6])
    detail_key = f"{key_prefix}_detail_{coin.contract_address}_{rank or 0}"
    watch_key = f"{key_prefix}_watch_{coin.contract_address}_{rank or 0}"

    if btn_cols[0].button("Details →", key=detail_key, use_container_width=True):
        st.session_state.detail_address = coin.contract_address
        st.rerun()

    is_w = history.is_watched(coin.contract_address)
    watch_label = "★ Unwatch" if is_w else "☆ Watch"
    if btn_cols[1].button(watch_label, key=watch_key, use_container_width=True):
        if is_w:
            history.remove_from_watchlist(coin.contract_address)
        else:
            history.add_to_watchlist(coin, analysis)
        st.rerun()


# ---------------------------------------------------------------------------
# Flag explanations (for detail page)
# ---------------------------------------------------------------------------

FLAG_EXPLANATIONS = {
    "Mint authority not renounced": "The developer can create unlimited new tokens at any moment. If they do, the value of every existing token crashes to near zero instantly.",
    "Freeze authority active": "The developer can freeze any user's wallet, preventing them from selling. One of the most aggressive scam vectors on Solana.",
    "Contract owner has modification powers": "The deployer can change contract behavior. Could enable sell restrictions, add fees, or drain liquidity.",
    "Honeypot": "Buy transactions succeed but sells revert. You can put money in but you can't take it out.",
    "Top wallet holds": "When one wallet controls most of the supply, that holder can dump and crash the price whenever they want.",
    "Liquidity not locked": "The dev's liquidity isn't locked in a vault. They can pull it out at any moment, leaving holders unable to sell.",
    "Top 10 wallets hold": "Concentrated holdings mean a small number of wallets can coordinate to crash the price.",
    "Liquidity only": "When liquidity is tiny, even small sells crash the price. You may not be able to exit a meaningful position.",
    "Contract less than 24 hours old": "Brand-new tokens have no track record. The vast majority of <24h tokens are pump-and-dump schemes.",
    "No social presence": "Legitimate projects build communities. Total absence usually means the token has been abandoned.",
    "Contract not verified": "Without verified source code, you can't see what the contract actually does. Hidden malicious functions are common.",
    "Tax asymmetry": "When sell tax is much higher than buy tax, the dev is making it expensive to exit.",
    "Single liquidity pool": "All exit liquidity is in one pool. If that pool is drained, there's nowhere to sell.",
    "Anonymous team": "Common in crypto but worth noting — no accountability if things go wrong.",
    "of mentions look bot-driven": "Coordinated bot activity inflates apparent interest. Real organic demand may be much lower than mention counts suggest.",
    "Chart shows classic pump": "Vertical price spike followed by distribution is the textbook pump-and-dump signature.",
}


def explain_flag(text):
    for k, v in FLAG_EXPLANATIONS.items():
        if k.lower() in text.lower():
            return v
    return "Worth investigating further."


# ---------------------------------------------------------------------------
# Detail page with history chart
# ---------------------------------------------------------------------------

def render_coin_detail(coin, analysis):
    mom = analysis["momentum"]
    risk = analysis["scam_risk"]
    opp = analysis["opportunity"]

    if st.button("← Back"):
        st.session_state.detail_address = None
        st.rerun()

    pc_class = "price-up" if coin.price_change_24h_pct >= 0 else "price-down"
    is_w = history.is_watched(coin.contract_address)

    # Header
    st.markdown(f"""
    <div style="margin-bottom: 20px;">
      <div style="display:flex; align-items:baseline; gap:12px; flex-wrap:wrap;">
        <h1 style="margin:0;">{'⭐ ' if is_w else ''}{coin.symbol}</h1>
        <span style="opacity:0.6; font-size:18px;">{coin.name}</span>
        <span class="chain-pill">{coin.chain}</span>
      </div>
      <div style="margin-top:6px;">
        <span style="font-size:28px; font-weight:600;">{fmt_price(coin.price_usd)}</span>
        <span class="{pc_class}" style="margin-left:12px; font-size:16px;">{fmt_pct(coin.price_change_24h_pct)} 24h</span>
        <span class="{pc_class}" style="margin-left:8px; font-size:13px; opacity:0.7;">{fmt_pct(coin.price_change_1h_pct)} 1h</span>
      </div>
      <div style="margin-top:10px;">{tier_badge(opp["score"])} {risk_badge(risk["score"])}</div>
    </div>
    """, unsafe_allow_html=True)

    # Watch toggle
    if st.button(("★ Remove from watchlist" if is_w else "☆ Add to watchlist"),
                 type=("secondary" if is_w else "primary")):
        if is_w:
            history.remove_from_watchlist(coin.contract_address)
        else:
            history.add_to_watchlist(coin, analysis)
        st.rerun()

    tab1, tab2, tab3, tab4 = st.tabs(["📊 Overview", "📈 History", "🔍 Risk", "🔗 Links"])

    # OVERVIEW
    with tab1:
        c1, c2, c3 = st.columns(3)
        c1.metric("Momentum", f"{mom['total']:.0f}/100")
        c2.metric("Scam Risk", f"{risk['score']}/100", help=risk["label"])
        opp_val = f"{opp['score']:.0f}/100" if opp['score'] is not None else "Hidden"
        c3.metric("Opportunity", opp_val)

        st.markdown("### Market")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Market cap", fmt_money(coin.market_cap_usd))
        m2.metric("Liquidity", fmt_money(coin.liquidity_usd))
        m3.metric("Volume 24h", fmt_money(coin.volume_24h_usd))
        m4.metric("Age", f"{coin.token_age_days:.0f}d")

        st.markdown("### Momentum breakdown")
        st.caption(f"Components that built the {mom['total']:.0f} score. Each is 0–100.")
        for label, val, weight in [
            ("Price action", mom["price"], "25%"),
            ("Volume", mom["volume"], "20%"),
            ("Social mentions", mom["social"], "15%"),
            ("Holder growth", mom["holders"], "15%"),
            ("Liquidity change", mom["liquidity"], "15%"),
            ("Exchange listings", mom["listing"], "10%"),
        ]:
            cols = st.columns([2, 5, 1])
            cols[0].markdown(f"**{label}**")
            cols[0].caption(f"weight: {weight}")
            cols[1].progress(min(val / 100, 1.0))
            cols[2].markdown(f"<div style='text-align:right; font-weight:600; font-size:18px;'>{val:.0f}</div>",
                           unsafe_allow_html=True)

        st.markdown("### Holders")
        h1, h2, h3 = st.columns(3)
        h1.metric("Holder count", f"{coin.holder_count:,}")
        if helius_configured() and coin.chain == "solana":
            h2.metric("Top wallet", f"{coin.top_wallet_pct:.1f}%", help="Real on-chain data via Helius")
            h3.metric("Top 10", f"{coin.top_10_holder_pct:.1f}%", help="Real on-chain data via Helius")
        else:
            h2.metric("Top wallet", "—", help="Helius not configured")
            h3.metric("Top 10", "—", help="Helius not configured")

    # HISTORY
    with tab2:
        st.markdown("### Score history")
        st.caption("Built from snapshots taken each time this coin appeared on the dashboard.")
        snaps = history.get_history(coin.contract_address, limit=500)
        if len(snaps) < 2:
            st.info(f"Only {len(snaps)} snapshot{'s' if len(snaps) != 1 else ''} so far. "
                   "Come back after the dashboard has refreshed a few times to see the trajectory.")
        else:
            # Reverse to chronological
            snaps_ordered = list(reversed(snaps))
            import pandas as pd
            df = pd.DataFrame(snaps_ordered)
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            df = df.set_index("timestamp")

            st.markdown("#### Price")
            st.line_chart(df[["price_usd"]], height=200)

            st.markdown("#### Scores over time")
            score_df = df[["momentum_score", "scam_risk_score", "opportunity_score"]].rename(
                columns={"momentum_score": "Momentum",
                        "scam_risk_score": "Scam Risk",
                        "opportunity_score": "Opportunity"})
            st.line_chart(score_df, height=200)

            # Outcome since first seen
            first = snaps_ordered[0]
            latest = snaps_ordered[-1]
            if first["price_usd"] and first["price_usd"] > 0:
                pct = ((latest["price_usd"] - first["price_usd"]) / first["price_usd"]) * 100
                hours = (df.index[-1] - df.index[0]).total_seconds() / 3600
                st.markdown("---")
                o1, o2, o3 = st.columns(3)
                o1.metric("First seen", f"{hours:.1f}h ago")
                o2.metric("First price", fmt_price(first["price_usd"]))
                delta_color = "normal" if pct >= 0 else "inverse"
                o3.metric("Change since first seen", f"{pct:+.1f}%",
                         delta=f"{pct:+.1f}%", delta_color=delta_color)

    # RISK
    with tab3:
        st.markdown(f"### Risk score: {risk['score']}/100 — {risk['label']}")
        if not risk["flags"]:
            st.success("No risk flags detected.")
            st.caption("Absence of flags doesn't guarantee safety — always cross-check on rugcheck.xyz.")
        else:
            for label, sev in risk["flags"]:
                icon = {"critical": "🔴", "major": "🟠", "minor": "🟡"}[sev]
                with st.expander(f"{icon} [{sev.upper()}] {label}", expanded=(sev == "critical")):
                    st.markdown(explain_flag(label))
        if not helius_configured():
            st.warning("⚠ Helius not configured — on-chain flags using defaults.")

    # LINKS
    with tab4:
        st.markdown("### Contract")
        if coin.contract_address and coin.contract_address != "n/a":
            st.code(coin.contract_address, language=None)
            if coin.chain == "solana":
                st.markdown(f"""
                - [View on Solscan](https://solscan.io/token/{coin.contract_address})
                - [Chart on DexScreener](https://dexscreener.com/solana/{coin.contract_address})
                - [Risk check on rugcheck.xyz](https://rugcheck.xyz/tokens/{coin.contract_address})
                - [Trade on Jupiter](https://jup.ag/swap/SOL-{coin.contract_address})
                """)
        else:
            st.caption("Contract address not available")


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("## 🔍 Search")
    search = st.text_input("Coin symbol or contract address",
                          placeholder="e.g. WIF",
                          label_visibility="collapsed")
    if st.button("Analyze", use_container_width=True, type="primary"):
        if search.strip():
            st.session_state.search_query = search.strip()
            st.rerun()

    st.markdown("---")
    st.markdown("## ⚙️ Filters")

    sort_by = st.selectbox("Sort by",
        ["Opportunity", "Momentum", "Risk (low to high)", "Volume", "Price 24h"])
    show_high_risk = st.checkbox("Show high-risk coins", value=False,
        help="Coins with risk ≥ 60 are hidden by default")
    min_liquidity = st.select_slider("Min liquidity",
        options=[0, 10_000, 25_000, 100_000, 500_000, 1_000_000],
        value=10_000,
        format_func=lambda x: fmt_money(x) if x else "Any")

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

    # DB stats
    stats = history.stats_summary()
    st.caption(f"📚 {stats['snapshots']:,} snapshots across {stats['unique_coins']:,} coins · "
               f"{stats['watchlist']} on watchlist")


# ---------------------------------------------------------------------------
# Routing — search & detail views take precedence over tabs
# ---------------------------------------------------------------------------

if "detail_address" not in st.session_state:
    st.session_state.detail_address = None
if "search_query" not in st.session_state:
    st.session_state.search_query = None

# Search detail
if st.session_state.search_query:
    q = st.session_state.search_query
    if st.button("← Back"):
        st.session_state.search_query = None
        st.rerun()
    with st.spinner(f"Looking up {q}..."):
        result = cached_lookup(q)
    if result is None:
        st.error(f"Couldn't find '{q}'. Try a contract address or specific symbol.")
    else:
        render_coin_detail(*result)
    st.stop()

# Coin detail
if st.session_state.detail_address:
    with st.spinner("Loading..."):
        result = cached_lookup(st.session_state.detail_address)
    if result is None:
        st.error("Couldn't load that coin.")
        if st.button("← Back"):
            st.session_state.detail_address = None
            st.rerun()
    else:
        render_coin_detail(*result)
    st.stop()


# ---------------------------------------------------------------------------
# Main view — three tabs
# ---------------------------------------------------------------------------

st.markdown("# 📊 Crypto Intelligence")
st.markdown(f"<p style='opacity:0.5; margin-top:-12px;'>Solana · Updated {datetime.now().strftime('%H:%M')}</p>",
           unsafe_allow_html=True)

main_tab1, main_tab2, main_tab3 = st.tabs(["🎯 Discover", "⭐ Watchlist", "📐 Calibration"])

# ===== DISCOVER TAB =====
with main_tab1:
    with st.spinner("Pulling trending Solana coins..."):
        scored = cached_discover()

    if not scored:
        st.error("Couldn't pull data. APIs may be rate-limited — try again in a minute.")
    else:
        filtered = [
            (c, a) for c, a in scored
            if c.liquidity_usd >= min_liquidity
            and (show_high_risk or a["scam_risk"]["score"] < 60)
        ]
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
        c1.metric("Scored", total)
        c2.metric("🔥 High signal", high_signal)
        c3.metric("🚩 Flagged", flagged)
        c4.metric("☠ Critical", critical)

        st.markdown("---")
        st.markdown("### 🏆 Top 10 Opportunities")
        top_10 = [(c, a) for c, a in filtered if a["opportunity"]["score"] is not None][:10]
        if not top_10:
            st.info("No coins meet the opportunity threshold with current filters.")
        else:
            for i, (coin, analysis) in enumerate(top_10, 1):
                render_coin_card(coin, analysis, rank=i, key_prefix="top")

        if len(filtered) > 10:
            st.markdown("---")
            with st.expander(f"All discovered coins ({len(filtered)})", expanded=False):
                for i, (coin, analysis) in enumerate(filtered[10:], 11):
                    render_coin_card(coin, analysis, rank=i, key_prefix="all")


# ===== WATCHLIST TAB =====
with main_tab2:
    watchlist = history.get_watchlist()
    if not watchlist:
        st.info("Your watchlist is empty. Star coins from the Discover tab to track them here.")
    else:
        st.markdown(f"### {len(watchlist)} coins on watch")
        st.caption("Each card shows the *latest* snapshot plus how price has moved since you starred it.")

        for w in watchlist:
            # Get the most recent snapshot
            history_rows = history.get_history(w["contract"], limit=1)
            if not history_rows:
                continue
            latest = history_rows[0]

            since_pct = 0
            if w["added_at_price"] and w["added_at_price"] > 0:
                since_pct = ((latest["price_usd"] - w["added_at_price"]) / w["added_at_price"]) * 100

            try:
                added_dt = datetime.fromisoformat(w["added_at"])
                hours_ago = (datetime.utcnow() - added_dt).total_seconds() / 3600
            except Exception:
                hours_ago = 0

            since_class = "price-up" if since_pct >= 0 else "price-down"

            was_opp_str = f"{w['added_at_opp']:.0f}" if w.get('added_at_opp') is not None else "—"
            now_opp_str = f"{latest['opportunity_score']:.0f}" if latest.get('opportunity_score') is not None else "—"

            st.markdown(f"""
            <div class="coin-card">
              <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:16px;">
                <div style="flex:1;">
                  <div style="font-size:18px; font-weight:600;">⭐ {w['symbol']}
                    <span style="opacity:0.6; font-size:14px; font-weight:normal;">{(w.get('name') or '')[:40]}</span>
                  </div>
                  <div class="meta-row">
                    <span><strong>{fmt_price(latest['price_usd'])}</strong></span>
                    <span>Starred {hours_ago:.1f}h ago</span>
                    <span>at {fmt_price(w['added_at_price'])}</span>
                  </div>
                  <div style="margin-top:8px;">
                    <span class="badge badge-purple">Was: Mom {w['added_at_momentum']:.0f} · Opp {was_opp_str} · Risk {w['added_at_risk']}</span>
                    <span class="badge badge-blue">Now: Mom {latest['momentum_score']:.0f} · Opp {now_opp_str} · Risk {latest['scam_risk_score']}</span>
                  </div>
                </div>
                <div style="text-align:right; min-width:120px;">
                  <div class="score-label">Since starred</div>
                  <div class="score-display {since_class}">{since_pct:+.1f}%</div>
                </div>
              </div>
            </div>
            """, unsafe_allow_html=True)

            bcols = st.columns([1, 1, 6])
            if bcols[0].button("Details →", key=f"wd_{w['contract']}", use_container_width=True):
                st.session_state.detail_address = w["contract"]
                st.rerun()
            if bcols[1].button("★ Unwatch", key=f"wu_{w['contract']}", use_container_width=True):
                history.remove_from_watchlist(w["contract"])
                st.rerun()


# ===== CALIBRATION TAB =====
with main_tab3:
    st.markdown("### How well are the scores working?")
    st.caption("This compares opportunity scores at first sighting against actual price outcomes since. "
               "More data = more accurate calibration. Come back after a few days of dashboard usage.")

    window_hours = st.selectbox("Outcome window",
                                [6, 12, 24, 48, 168],
                                index=2,
                                format_func=lambda h: f"{h} hours" if h < 168 else "7 days")

    stats = history.get_calibration_stats(min_age_hours=window_hours)

    if stats["total"] == 0:
        st.info(f"No coins have been tracked for {window_hours}+ hours yet. "
               "Calibration data will appear once snapshots have aged enough.")
    else:
        st.markdown(f"**Based on {stats['total']} coins first seen at least {window_hours}h ago.**")

        for tier_name, tier_data in stats["tiers"].items():
            if not tier_data:
                continue
            st.markdown(f"#### {tier_name}")
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Count", tier_data["count"])
            c2.metric("% positive", f"{tier_data['pct_positive']:.0f}%")
            c3.metric("Median return", f"{tier_data['median_pct']:+.1f}%")
            c4.metric("% big winners", f"{tier_data['pct_big_winners']:.0f}%",
                     help="Coins up more than 50% since first seen")
            c5.metric("% big losers", f"{tier_data['pct_big_losers']:.0f}%",
                     help="Coins down more than 50% since first seen")
            st.caption(f"Best: {tier_data['best']:+.0f}%  ·  Worst: {tier_data['worst']:+.0f}%  ·  "
                      f"Mean: {tier_data['mean_pct']:+.1f}%")
            st.markdown("---")

        st.markdown("### What this tells you")
        st.caption(
            "If High Signal tier has >50% positive and >20% big winners, the scoring is "
            "working as intended. If it's worse than Notable tier, the scoring is broken "
            "and weights need adjustment. If both tiers look the same, the system isn't "
            "discriminating well — that's a signal to tighten thresholds."
        )


# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

st.markdown("---")
st.caption(
    "**Not financial advice.** Scores are heuristic and frequently wrong. "
    "Cross-check on rugcheck.xyz before trusting any coin. "
    "Crypto is high-risk — only deploy capital you can afford to lose entirely."
)
