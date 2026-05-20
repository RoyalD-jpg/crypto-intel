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

    /* Force the sidebar to ALWAYS stay open — hide the collapse button so it
       can't be closed, and pin the sidebar visible regardless of state. */
    [data-testid="stSidebarCollapseButton"] {display: none !important;}
    [data-testid="stSidebarCollapsedControl"] {display: none !important;}
    [data-testid="stSidebar"] {
        display: flex !important;
        visibility: visible !important;
        transform: none !important;
        min-width: 300px !important;
        width: 300px !important;
        margin-left: 0 !important;
    }
    [data-testid="stSidebar"][aria-expanded="false"] {
        transform: none !important;
        margin-left: 0 !important;
    }

    /* Clean solid dark surface — no gradients, no glows */
    .stApp {background: #0f1117; color: #e6e9ef;}
    .block-container {padding-top: 1.4rem; padding-bottom: 2rem; max-width: 1200px;}

    /* Readable system font, no fancy display fonts */
    html, body, [class*="css"] {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    }
    h1 {font-size: 26px; font-weight: 700; color: #fff;}
    h2, h3 {color: #f3f5f9; font-weight: 600;}

    /* Sidebar — clearly lighter than main so it's visible */
    [data-testid="stSidebar"] {
        background: #171a23;
        border-right: 1px solid #262a35;
    }
    [data-testid="stSidebar"] * {color: #d8dce6;}

    /* Cards — solid surface, clear border, simple */
    .coin-card {
        position: relative;
        background: #1a1d27;
        border: 1px solid #2a2e3b;
        border-left: 3px solid var(--accent, #2a2e3b);
        border-radius: 10px;
        padding: 14px 18px;
        margin-bottom: 8px;
    }
    .coin-card:hover {background: #1e222e; border-color: #3a3f4f;}
    .coin-rank {color: #6b7280; font-size: 13px; margin-right: 8px; font-weight: 600;}

    /* Badges — only two states: clear "good/safe" vs "caution/bad". Muted. */
    .badge {
        display: inline-block; padding: 3px 9px; border-radius: 6px;
        font-size: 11px; font-weight: 600; margin-right: 6px;
    }
    .badge-good {background: #14331f; color: #5ed39a; border: 1px solid #1f5436;}
    .badge-warn {background: #3a2e12; color: #e3b341; border: 1px solid #5c4a1d;}
    .badge-bad  {background: #3a1a1a; color: #f08a8a; border: 1px solid #5c2626;}
    .badge-neutral {background: #23262f; color: #aab1c0; border: 1px solid #333845;}

    .score-display {font-size: 26px; font-weight: 700; line-height: 1; color: #fff;}
    .score-display-dim {color: #6b7280;}
    .score-label {
        font-size: 10px; text-transform: uppercase; letter-spacing: 0.5px;
        color: #8b92a3; margin-bottom: 3px; font-weight: 600;
    }

    .meta-row {
        display: flex; gap: 14px; font-size: 12.5px; color: #aab1c0;
        margin-top: 6px; flex-wrap: wrap;
    }
    .meta-row strong {color: #fff;}
    .price-up {color: #5ed39a; font-weight: 600;}
    .price-down {color: #f08a8a; font-weight: 600;}

    .chain-pill {
        display: inline-block; padding: 2px 8px; border-radius: 5px;
        font-size: 10px; font-weight: 600; text-transform: uppercase;
        background: #23262f; color: #9ca3b5; margin-left: 6px;
    }
    .dex-pill {
        display: inline-block; padding: 2px 8px; border-radius: 5px;
        font-size: 10px; font-weight: 600;
        background: #1f2937; color: #7dd3fc; margin-left: 4px;
    }

    /* Buy/sell pressure bar */
    .pressure-bar {
        display: flex; height: 6px; border-radius: 3px; overflow: hidden;
        margin-top: 10px; background: #23262f;
    }
    .pressure-buy {background: #2ea96f;}
    .pressure-sell {background: #d35858;}
    .pressure-labels {
        display: flex; justify-content: space-between; font-size: 11px;
        margin-top: 4px; color: #8b92a3;
    }

    .status-dot {
        display: inline-block; width: 8px; height: 8px; border-radius: 50%;
        margin-right: 6px; vertical-align: middle;
    }
    .status-on {background: #2ea96f;}
    .status-off {background: #5b6170;}

    /* Metric tiles */
    [data-testid="stMetricValue"] {font-size: 22px; font-weight: 700; color: #fff;}
    [data-testid="stMetricLabel"] {color: #8b92a3;}
    [data-testid="stHorizontalBlock"] {gap: 0.5rem;}

    /* Tabs — simple underline style */
    .stTabs [data-baseweb="tab-list"] {gap: 4px; border-bottom: 1px solid #262a35;}
    .stTabs [data-baseweb="tab"] {
        background: transparent; padding: 8px 16px; font-weight: 600; color: #8b92a3;
    }
    .stTabs [aria-selected="true"] {color: #fff;}

    /* Buttons */
    .stButton button {
        border-radius: 8px; font-weight: 600; font-size: 13px;
        background: #23262f; color: #d8dce6; border: 1px solid #333845;
    }
    .stButton button:hover {background: #2a2e3b; border-color: #4a5160; color: #fff;}
</style>
""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Cached data
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300, show_spinner=False)
def cached_discover():
    coins = discover_trending(max_per_chain=150)
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


def momentum_1h(coin):
    """A short-window momentum score (0-100) focused on the LAST HOUR.

    Built entirely from 1h signals so it captures fresh swings that the
    blended 24h momentum score smooths over. Three parts:
      - 1h price change (most weight)
      - 1h buy pressure (are buys dominating right now?)
      - 1h volume vs the 6h average pace (is activity spiking?)
    """
    # 1h price component: +/-15% maps across the range
    pc_1h = getattr(coin, "price_change_1h_pct", 0) or 0
    price_part = max(0, min(100, 50 + pc_1h * 3.3))

    # Buy pressure component: 0.5 (balanced) = 50, 1.0 (all buys) = 100
    bp = getattr(coin, "buy_pressure_1h", 0.5)
    pressure_part = max(0, min(100, bp * 100))

    # Volume spike component: 1h volume vs the 6h hourly average
    vol_1h = getattr(coin, "vol_1h", 0) or 0
    vol_6h = getattr(coin, "vol_6h", 0) or 0
    if vol_6h > 0:
        hourly_avg = vol_6h / 6
        ratio = vol_1h / hourly_avg if hourly_avg > 0 else 1
        # ratio of 1 = normal = 50; ratio of 3+ = 100
        import math
        vol_part = max(0, min(100, 50 + math.log2(max(ratio, 0.25)) * 25))
    else:
        vol_part = 50

    score = 0.5 * price_part + 0.25 * pressure_part + 0.25 * vol_part
    return round(score, 0)


def tier_badge(score):
    if score is None: return '<span class="badge badge-bad">RISK HIDDEN</span>'
    if score >= 80: return '<span class="badge badge-good">HIGH SIGNAL</span>'
    if score >= 60: return '<span class="badge badge-warn">NOTABLE</span>'
    if score >= 40: return '<span class="badge badge-neutral">WATCH</span>'
    return '<span class="badge badge-neutral">LOW</span>'


def risk_badge(score):
    if score <= 20: return f'<span class="badge badge-good">SAFE · {score}</span>'
    if score <= 50: return f'<span class="badge badge-warn">CAUTION · {score}</span>'
    if score <= 80: return f'<span class="badge badge-bad">RISKY · {score}</span>'
    return f'<span class="badge badge-bad">AVOID · {score}</span>'


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

    # Accent: single subtle green for genuine opportunities, neutral otherwise.
    # No rainbow — keeps the list calm and scannable.
    opp_score = opp["score"]
    if opp_score is not None and opp_score >= 60:
        accent = "#2ea96f"   # notable+ : subtle green edge
    else:
        accent = "#2a2e3b"   # everything else : neutral (blends with border)

    # DEX pill — highlight PumpSwap since that's the user's focus
    dex_id = getattr(coin, "dex_id", "")
    dex_html = ""
    if dex_id:
        nice = {"pumpswap": "PumpSwap", "raydium": "Raydium", "meteora": "Meteora",
                "orca": "Orca", "fluxbeam": "FluxBeam"}.get(dex_id, dex_id.title())
        dex_html = f'<span class="dex-pill">{nice}</span>'

    # Acceleration badge — pulled from the global velocities dict if present
    accel_html = ""
    vel = velocities.get(coin.contract_address) if "velocities" in globals() else None
    if vel and vel.get("accelerating"):
        accel_html = (f'<span class="dex-pill" style="background:#14331f; color:#5ed39a;">'
                      f'&#9650; ACCELERATING +{vel["price_change_pct"]:.0f}% / {vel["minutes_span"]:.0f}m</span>')

    # Bundle warning pill if Helius flagged it
    bundle_html = ""
    if getattr(coin, "likely_bundle", False):
        bundle_html = ('<span class="dex-pill" style="background:#3a1a1a; color:#f08a8a;">'
                       '&#9888; BUNDLE RISK</span>')

    # Buy/sell pressure bar (from real DexScreener txn data if present)
    buy_pressure = getattr(coin, "buy_pressure_1h", None)
    buys = getattr(coin, "buys_1h", 0)
    sells = getattr(coin, "sells_1h", 0)
    pressure_html = ""
    if buy_pressure is not None and (buys + sells) > 0:
        buy_pct = buy_pressure * 100
        sell_pct = 100 - buy_pct
        pressure_html = (
            '<div class="pressure-bar">'
            f'<div class="pressure-buy" style="width:{buy_pct:.0f}%;"></div>'
            f'<div class="pressure-sell" style="width:{sell_pct:.0f}%;"></div>'
            '</div>'
            '<div class="pressure-labels">'
            f'<span style="color:#5ed39a;">{buys} buys</span>'
            f'<span>{buy_pct:.0f}% buy pressure · 1h</span>'
            f'<span style="color:#f08a8a;">{sells} sells</span>'
            '</div>'
        )

    # 1h price for the meta row
    pc_1h = getattr(coin, "price_change_1h_pct", 0) or 0
    pc_1h_class = "price-up" if pc_1h >= 0 else "price-down"
    m1h = momentum_1h(coin)

    # Build the whole card as one flat string (no leading whitespace per line —
    # leading indentation makes Streamlit's markdown render it as a code block)
    card_html = (
        f'<div class="coin-card" style="--accent: {accent};">'
        '<div style="display:flex; justify-content:space-between; align-items:flex-start; gap:16px;">'
        '<div style="flex:1; min-width:0;">'
        '<div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;">'
        f'<span style="font-size:17px; font-weight:700; color:#fff;">{rank_html}{watch_marker}{coin.symbol}</span>'
        f'<span style="color:#8b92a3; font-size:13px;">{safe_name}</span>'
        f'<span class="chain-pill">{coin.chain}</span>'
        f'{dex_html}'
        f'{accel_html}'
        f'{bundle_html}'
        '</div>'
        '<div class="meta-row">'
        f'<span><strong>{fmt_price(coin.price_usd)}</strong></span>'
        f'<span class="{pc_1h_class}">{fmt_pct(pc_1h)} 1h</span>'
        f'<span class="{pc_class}">{fmt_pct(pc_24h)} 24h</span>'
        f'<span>MC {fmt_money(coin.market_cap_usd)}</span>'
        f'<span>Vol {fmt_money(coin.volume_24h_usd)}</span>'
        f'<span>Liq {fmt_money(coin.liquidity_usd)}</span>'
        f'<span>{coin.token_age_days:.0f}d</span>'
        '</div>'
        f'<div style="margin-top:9px;">{tier_badge(opp["score"])}{risk_badge(risk["score"])}</div>'
        '</div>'
        '<div style="text-align:right; min-width:60px;">'
        '<div class="score-label">1h Mom</div>'
        f'<div class="score-display" style="font-size:22px; color:#7dd3fc;">{m1h:.0f}</div>'
        '</div>'
        '<div style="text-align:right; min-width:60px;">'
        '<div class="score-label">Mom 24h</div>'
        f'<div class="score-display" style="font-size:22px;">{mom["total"]:.0f}</div>'
        '</div>'
        '<div style="text-align:right; min-width:60px;">'
        '<div class="score-label">Opp</div>'
        f'<div class="score-display {opp_class}" style="font-size:22px;">{opp_display}</div>'
        '</div>'
        '</div>'
        f'{pressure_html}'
        '</div>'
    )
    st.markdown(card_html, unsafe_allow_html=True)

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

def render_coin_detail(coin, analysis, back_key: str = "detail_back"):
    mom = analysis["momentum"]
    risk = analysis["scam_risk"]
    opp = analysis["opportunity"]

    if st.button("← Back", key=back_key):
        st.session_state.detail_address = None
        st.session_state.search_query = None
        st.session_state.search_results = None
        st.rerun()

    pc_class = "price-up" if coin.price_change_24h_pct >= 0 else "price-down"
    is_w = history.is_watched(coin.contract_address)

    # Header
    st.markdown(
        '<div style="margin-bottom: 20px;">'
        '<div style="display:flex; align-items:baseline; gap:12px; flex-wrap:wrap;">'
        f'<h1 style="margin:0;">{"⭐ " if is_w else ""}{coin.symbol}</h1>'
        f'<span style="opacity:0.6; font-size:18px;">{coin.name}</span>'
        f'<span class="chain-pill">{coin.chain}</span>'
        '</div>'
        '<div style="margin-top:6px;">'
        f'<span style="font-size:28px; font-weight:600; color:#f1f5f9;">{fmt_price(coin.price_usd)}</span>'
        f'<span class="{pc_class}" style="margin-left:12px; font-size:16px;">{fmt_pct(coin.price_change_24h_pct)} 24h</span>'
        f'<span class="{pc_class}" style="margin-left:8px; font-size:13px; opacity:0.7;">{fmt_pct(coin.price_change_1h_pct)} 1h</span>'
        '</div>'
        f'<div style="margin-top:10px;">{tier_badge(opp["score"])} {risk_badge(risk["score"])}</div>'
        '</div>',
        unsafe_allow_html=True)

    # Watch toggle
    if st.button(("★ Remove from watchlist" if is_w else "☆ Add to watchlist"),
                 key=f"detail_watch_{coin.contract_address}",
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

        # Buy/sell pressure (real DexScreener data)
        buys_1h = getattr(coin, "buys_1h", 0)
        sells_1h = getattr(coin, "sells_1h", 0)
        buys_24h = getattr(coin, "buys_24h", 0)
        sells_24h = getattr(coin, "sells_24h", 0)
        if (buys_1h + sells_1h) > 0 or (buys_24h + sells_24h) > 0:
            st.markdown("### Buy / sell pressure")
            bp1, bp2 = st.columns(2)
            with bp1:
                total_1h = buys_1h + sells_1h
                buy_pct_1h = (buys_1h / total_1h * 100) if total_1h else 0
                st.markdown(f"**Last 1 hour** — {buy_pct_1h:.0f}% buys")
                st.markdown(
                    '<div class="pressure-bar" style="height:8px;">'
                    f'<div class="pressure-buy" style="width:{buy_pct_1h:.0f}%;"></div>'
                    f'<div class="pressure-sell" style="width:{100-buy_pct_1h:.0f}%;"></div>'
                    '</div><div class="pressure-labels">'
                    f'<span style="color:#4ade80;">&#9650; {buys_1h} buys</span>'
                    f'<span style="color:#f87171;">{sells_1h} sells &#9660;</span>'
                    '</div>',
                    unsafe_allow_html=True)
            with bp2:
                total_24h = buys_24h + sells_24h
                buy_pct_24h = (buys_24h / total_24h * 100) if total_24h else 0
                st.markdown(f"**Last 24 hours** — {buy_pct_24h:.0f}% buys")
                st.markdown(
                    '<div class="pressure-bar" style="height:8px;">'
                    f'<div class="pressure-buy" style="width:{buy_pct_24h:.0f}%;"></div>'
                    f'<div class="pressure-sell" style="width:{100-buy_pct_24h:.0f}%;"></div>'
                    '</div><div class="pressure-labels">'
                    f'<span style="color:#4ade80;">&#9650; {buys_24h} buys</span>'
                    f'<span style="color:#f87171;">{sells_24h} sells &#9660;</span>'
                    '</div>',
                    unsafe_allow_html=True)
            st.caption("More buys than sells suggests accumulation; the reverse suggests distribution. "
                      "Not a guarantee of direction — large players can mask intent.")

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
                st.markdown(
                    f"- [View on Solscan](https://solscan.io/token/{coin.contract_address})\n"
                    f"- [Chart on DexScreener](https://dexscreener.com/solana/{coin.contract_address})\n"
                    f"- [Risk check on rugcheck.xyz](https://rugcheck.xyz/tokens/{coin.contract_address})\n"
                    f"- [Trade on Jupiter](https://jup.ag/swap/SOL-{coin.contract_address})"
                )
        else:
            st.caption("Contract address not available")


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("## 🔍 Search")
    search = st.text_input("Coin symbol or contract address",
                          placeholder="WIF, BONK, or paste contract...",
                          label_visibility="collapsed")
    if st.button("Analyze", use_container_width=True, type="primary"):
        if search.strip():
            # Reset any prior search state
            st.session_state.search_query = search.strip()
            st.session_state.search_results = None
            st.session_state.detail_address = None
            st.rerun()
    st.caption("💡 For brand-new coins, paste the **contract address** — "
               "symbol search finds the most-liquid match, not the newest one.")

    st.markdown("---")
    st.markdown("## ⚙️ Filters")

    dex_filter = st.selectbox("DEX",
        ["All DEXes", "PumpSwap only", "Raydium only", "Meteora only"],
        help="PumpSwap is pump.fun's native DEX — where their tokens trade after bonding")
    sort_by = st.selectbox("Sort by",
        ["1h Momentum", "Price 1h", "Opportunity", "Momentum (24h)",
         "Risk (low to high)", "Volume", "Price 24h"],
        help="'1h Momentum' and 'Price 1h' surface the freshest swings — best for fast-moving PumpSwap coins")
    min_price_1h = st.select_slider("Min 1h price change",
        options=[-100, 0, 5, 10, 25, 50, 100],
        value=-100,
        format_func=lambda x: "Any" if x == -100 else f"+{x}%",
        help="Only show coins up at least this much in the last hour")
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
if "search_results" not in st.session_state:
    st.session_state.search_results = None

# Search flow: multi-result picker, then click into a specific coin
if st.session_state.search_query and not st.session_state.detail_address:
    q = st.session_state.search_query
    if st.button("← Back", key="search_back"):
        st.session_state.search_query = None
        st.session_state.search_results = None
        st.rerun()

    # Fetch results if we don't have them cached for this query yet
    if (st.session_state.search_results is None
            or st.session_state.search_results.get("query") != q):
        with st.spinner(f"Searching for '{q}'..."):
            from discovery import search_many
            matches = search_many(q, limit=10)
        st.session_state.search_results = {"query": q, "matches": matches}

    matches = st.session_state.search_results["matches"]

    if not matches:
        st.error(f"Couldn't find '{q}'.")
        st.markdown("**Tips for finding new or obscure coins:**")
        st.markdown(
            "- For brand-new coins (under a few hours old), use the **contract address**, "
            "not the symbol. Symbol search returns the most-liquid match, which won't be "
            "a new launch.\n"
            "- Find contract addresses on [pump.fun](https://pump.fun) (newest tab), "
            "[DexScreener new pairs](https://dexscreener.com/new-pairs/solana), or by "
            "right-clicking a token in your wallet.\n"
            "- For Solana addresses, paste the full 32–44 character base58 string."
        )
    elif len(matches) == 1:
        # Single result — show detail directly
        coin = matches[0]
        analysis = full_analysis(coin)
        history.record_snapshot(coin, analysis)
        render_coin_detail(coin, analysis, back_key="single_match_back")
    else:
        # Multiple results — let user pick
        st.markdown(f"### Found {len(matches)} coins matching '{q}'")
        st.caption("Sorted by exact symbol match, then liquidity. Pick the right one — "
                  "or paste a contract address for an exact lookup.")
        for i, coin in enumerate(matches):
            analysis = full_analysis(coin)
            history.record_snapshot(coin, analysis)
            render_coin_card(coin, analysis, rank=i + 1, key_prefix=f"srch_{i}")
    st.stop()

# Coin detail (clicked from card)
if st.session_state.detail_address:
    with st.spinner("Loading..."):
        result = cached_lookup(st.session_state.detail_address)
    if result is None:
        st.error("Couldn't load that coin.")
        if st.button("← Back", key="detail_err_back"):
            st.session_state.detail_address = None
            st.rerun()
    else:
        render_coin_detail(*result, back_key="detail_main_back")
    st.stop()


# ---------------------------------------------------------------------------
# Main view — three tabs
# ---------------------------------------------------------------------------

st.markdown("# 📊 Crypto Intelligence")
st.markdown(f"<p style='opacity:0.5; margin-top:-12px;'>Solana · Updated {datetime.now().strftime('%H:%M')}</p>",
           unsafe_allow_html=True)
st.caption("Filters & search are in the sidebar on the left.")

main_tab1, main_tabaccel, main_tab2, main_tab3 = st.tabs(
    ["🎯 Discover", "🚀 Accelerating", "⭐ Watchlist", "📐 Calibration"])

# Compute velocities once (cached short) — used by Discover badges + Accelerating tab
@st.cache_data(ttl=120, show_spinner=False)
def cached_velocities():
    return history.get_all_velocities(window_minutes=30, min_snapshots=2)

velocities = cached_velocities()

# ===== DISCOVER TAB =====
with main_tab1:
    with st.spinner("Pulling trending Solana coins..."):
        scored = cached_discover()

    if not scored:
        st.error("Couldn't pull data. APIs may be rate-limited — try again in a minute.")
    else:
        dex_map = {"PumpSwap only": "pumpswap", "Raydium only": "raydium",
                   "Meteora only": "meteora"}
        wanted_dex = dex_map.get(dex_filter)

        filtered = [
            (c, a) for c, a in scored
            if c.liquidity_usd >= min_liquidity
            and (show_high_risk or a["scam_risk"]["score"] < 60)
            and (wanted_dex is None or getattr(c, "dex_id", "") == wanted_dex)
            and (min_price_1h == -100 or (getattr(c, "price_change_1h_pct", 0) or 0) >= min_price_1h)
        ]
        sort_fns = {
            "1h Momentum": lambda x: momentum_1h(x[0]),
            "Price 1h": lambda x: getattr(x[0], "price_change_1h_pct", 0) or 0,
            "Opportunity": lambda x: x[1]["opportunity"]["score"] if x[1]["opportunity"]["score"] is not None else -1,
            "Momentum (24h)": lambda x: x[1]["momentum"]["total"],
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
        dex_note = f" · {dex_filter}" if dex_filter != "All DEXes" else ""
        st.markdown(f"### 🏆 Top 30{dex_note}")

        if not filtered:
            st.info("No coins match these filters. Try lowering 'Min liquidity', "
                   "enabling 'Show high-risk coins', or switching DEX to 'All DEXes'.")
        else:
            # 'filtered' is already sorted by the chosen sort key. Just take the top 30.
            top_30 = filtered[:30]
            for i, (coin, analysis) in enumerate(top_30, 1):
                render_coin_card(coin, analysis, rank=i, key_prefix="top")

            if len(filtered) > 30:
                st.markdown("---")
                with st.expander(f"More coins ({len(filtered) - 30} additional)", expanded=False):
                    for i, (coin, analysis) in enumerate(filtered[30:], 31):
                        render_coin_card(coin, analysis, rank=i, key_prefix="all")


# ===== ACCELERATING TAB =====
with main_tabaccel:
    st.markdown("### 🚀 Accelerating right now")
    st.caption("Coins climbing across recent snapshots — price up, momentum rising, holders growing. "
              "This is the early-trend signal: not what's already high, but what's *moving up* fastest. "
              "Needs at least two snapshots ~30 min apart, so it fills in as the app keeps running.")

    if not scored:
        st.info("No live data loaded yet.")
    elif not velocities:
        st.info("Not enough snapshot history yet to compute acceleration. Keep the app running — "
               "this view needs at least two snapshots per coin, roughly 30 minutes apart. "
               "Check back in an hour or two.")
    else:
        # Match velocity data to currently-live coins
        scored_by_addr = {c.contract_address: (c, a) for c, a in scored}
        accel_rows = []
        for addr, vel in velocities.items():
            if not vel.get("accelerating"):
                continue
            if addr not in scored_by_addr:
                continue
            c, a = scored_by_addr[addr]
            # Apply the same risk filter as Discover
            if not show_high_risk and a["scam_risk"]["score"] >= 60:
                continue
            accel_rows.append((c, a, vel))

        # Sort by price velocity (fastest climbers first)
        accel_rows.sort(key=lambda x: x[2]["price_change_pct"], reverse=True)

        if not accel_rows:
            st.info("Nothing is accelerating in the current set with your filters. "
                   "Try enabling 'Show high-risk coins' in the sidebar, or check back shortly.")
        else:
            st.markdown(f"**{len(accel_rows)} coins accelerating**")
            for i, (coin, analysis, vel) in enumerate(accel_rows[:30], 1):
                render_coin_card(coin, analysis, rank=i, key_prefix="accel")
                st.caption(
                    f"   ↗ Over last {vel['minutes_span']:.0f}m: "
                    f"price {vel['price_change_pct']:+.1f}%, "
                    f"momentum {vel['momentum_delta']:+.0f}, "
                    f"holders {vel['holder_change_pct']:+.1f}%"
                )


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

            st.markdown(
                '<div class="coin-card">'
                '<div style="display:flex; justify-content:space-between; align-items:flex-start; gap:16px;">'
                '<div style="flex:1;">'
                f'<div style="font-size:18px; font-weight:600; color:#f1f5f9;">⭐ {w["symbol"]} '
                f'<span style="opacity:0.6; font-size:14px; font-weight:normal;">{(w.get("name") or "")[:40]}</span>'
                '</div>'
                '<div class="meta-row">'
                f'<span style="color:#f1f5f9;"><strong>{fmt_price(latest["price_usd"])}</strong></span>'
                f'<span>Starred {hours_ago:.1f}h ago</span>'
                f'<span>at {fmt_price(w["added_at_price"])}</span>'
                '</div>'
                '<div style="margin-top:8px;">'
                f'<span class="badge badge-neutral">Was: Mom {w["added_at_momentum"]:.0f} &middot; Opp {was_opp_str} &middot; Risk {w["added_at_risk"]}</span>'
                f'<span class="badge badge-neutral">Now: Mom {latest["momentum_score"]:.0f} &middot; Opp {now_opp_str} &middot; Risk {latest["scam_risk_score"]}</span>'
                '</div>'
                '</div>'
                '<div style="text-align:right; min-width:120px;">'
                '<div class="score-label">Since starred</div>'
                f'<div class="score-display {since_class}">{since_pct:+.1f}%</div>'
                '</div>'
                '</div>'
                '</div>',
                unsafe_allow_html=True)

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
