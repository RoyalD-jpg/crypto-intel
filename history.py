"""
history.py — local SQLite store for tracking scores over time.

Why this exists: a scoring system you can't measure is just opinions. By
snapshotting every coin every time it appears on the dashboard, we build
ground truth — what happened *after* the dashboard called something a high
signal. That's how you calibrate.

On Streamlit Cloud the SQLite file lives in /tmp and gets wiped when the
container restarts (which happens periodically on free tier). For real
persistence we'd need an external DB — but for personal calibration over
hours/days, in-container is fine and free.

Three tables:

  snapshots     — one row per (coin, timestamp). The full score & price.
  watchlist     — coins the user starred. Get tracked extra-aggressively.
  outcomes      — derived view: what happened after each snapshot.
"""

import os
import sqlite3
import threading
from datetime import datetime, timedelta
from contextlib import contextmanager

# /tmp on Streamlit Cloud; current dir locally
DB_PATH = os.environ.get("CRYPTO_DB_PATH",
                         "/tmp/crypto_intel.db" if os.path.isdir("/tmp")
                         else "crypto_intel.db")

_lock = threading.Lock()


@contextmanager
def _connect():
    """Single connection per call. SQLite is fine with this for our scale."""
    with _lock:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def init_db():
    """Create tables if they don't exist. Idempotent."""
    with _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contract TEXT NOT NULL,
                symbol TEXT NOT NULL,
                name TEXT,
                chain TEXT,
                timestamp TEXT NOT NULL,
                price_usd REAL,
                market_cap_usd REAL,
                volume_24h_usd REAL,
                liquidity_usd REAL,
                price_change_24h_pct REAL,
                momentum_score REAL,
                scam_risk_score INTEGER,
                opportunity_score REAL,
                holder_count INTEGER,
                token_age_days REAL,
                top_wallet_pct REAL,
                top_10_holder_pct REAL
            );
            CREATE INDEX IF NOT EXISTS idx_snapshots_contract
                ON snapshots(contract, timestamp);
            CREATE INDEX IF NOT EXISTS idx_snapshots_time
                ON snapshots(timestamp);

            CREATE TABLE IF NOT EXISTS watchlist (
                contract TEXT PRIMARY KEY,
                symbol TEXT,
                name TEXT,
                added_at TEXT NOT NULL,
                added_at_price REAL,
                added_at_momentum REAL,
                added_at_opp REAL,
                added_at_risk INTEGER,
                note TEXT
            );
        """)


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------

def record_snapshot(coin, analysis):
    """Store a single (coin, analysis) snapshot."""
    if not coin.contract_address or coin.contract_address == "n/a":
        return
    mom = analysis["momentum"]
    risk = analysis["scam_risk"]
    opp = analysis["opportunity"]
    now = datetime.utcnow().isoformat()
    try:
        with _connect() as conn:
            conn.execute("""
                INSERT INTO snapshots (
                    contract, symbol, name, chain, timestamp,
                    price_usd, market_cap_usd, volume_24h_usd, liquidity_usd,
                    price_change_24h_pct, momentum_score, scam_risk_score,
                    opportunity_score, holder_count, token_age_days,
                    top_wallet_pct, top_10_holder_pct
                ) VALUES (?,?,?,?,?, ?,?,?,?, ?,?,?, ?,?,?, ?,?)
            """, (
                coin.contract_address, coin.symbol, coin.name, coin.chain, now,
                coin.price_usd, coin.market_cap_usd, coin.volume_24h_usd,
                coin.liquidity_usd, coin.price_change_24h_pct,
                mom["total"], risk["score"],
                opp["score"] if opp["score"] is not None else None,
                coin.holder_count, coin.token_age_days,
                coin.top_wallet_pct, coin.top_10_holder_pct,
            ))
    except Exception:
        pass  # never break the dashboard on a DB error


def record_batch(coin_analysis_pairs):
    """Bulk-record a list of (coin, analysis) tuples efficiently."""
    if not coin_analysis_pairs:
        return
    now = datetime.utcnow().isoformat()
    rows = []
    for coin, analysis in coin_analysis_pairs:
        if not coin.contract_address or coin.contract_address == "n/a":
            continue
        mom = analysis["momentum"]
        risk = analysis["scam_risk"]
        opp = analysis["opportunity"]
        rows.append((
            coin.contract_address, coin.symbol, coin.name, coin.chain, now,
            coin.price_usd, coin.market_cap_usd, coin.volume_24h_usd,
            coin.liquidity_usd, coin.price_change_24h_pct,
            mom["total"], risk["score"],
            opp["score"] if opp["score"] is not None else None,
            coin.holder_count, coin.token_age_days,
            coin.top_wallet_pct, coin.top_10_holder_pct,
        ))
    try:
        with _connect() as conn:
            conn.executemany("""
                INSERT INTO snapshots (
                    contract, symbol, name, chain, timestamp,
                    price_usd, market_cap_usd, volume_24h_usd, liquidity_usd,
                    price_change_24h_pct, momentum_score, scam_risk_score,
                    opportunity_score, holder_count, token_age_days,
                    top_wallet_pct, top_10_holder_pct
                ) VALUES (?,?,?,?,?, ?,?,?,?, ?,?,?, ?,?,?, ?,?)
            """, rows)
    except Exception:
        pass


def get_history(contract: str, limit: int = 200) -> list[dict]:
    """All snapshots for a single coin, newest first."""
    try:
        with _connect() as conn:
            cur = conn.execute("""
                SELECT * FROM snapshots
                WHERE contract = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (contract, limit))
            return [dict(r) for r in cur.fetchall()]
    except Exception:
        return []


def get_first_seen(contract: str) -> dict | None:
    """The earliest snapshot we have for a coin — used to compute outcomes."""
    try:
        with _connect() as conn:
            cur = conn.execute("""
                SELECT * FROM snapshots
                WHERE contract = ?
                ORDER BY timestamp ASC
                LIMIT 1
            """, (contract,))
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------

def add_to_watchlist(coin, analysis, note: str = ""):
    mom = analysis["momentum"]
    risk = analysis["scam_risk"]
    opp = analysis["opportunity"]
    try:
        with _connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO watchlist (
                    contract, symbol, name, added_at,
                    added_at_price, added_at_momentum, added_at_opp,
                    added_at_risk, note
                ) VALUES (?,?,?,?, ?,?,?, ?,?)
            """, (
                coin.contract_address, coin.symbol, coin.name,
                datetime.utcnow().isoformat(),
                coin.price_usd, mom["total"],
                opp["score"] if opp["score"] is not None else None,
                risk["score"], note,
            ))
    except Exception:
        pass


def remove_from_watchlist(contract: str):
    try:
        with _connect() as conn:
            conn.execute("DELETE FROM watchlist WHERE contract = ?", (contract,))
    except Exception:
        pass


def get_watchlist() -> list[dict]:
    try:
        with _connect() as conn:
            cur = conn.execute("""
                SELECT * FROM watchlist ORDER BY added_at DESC
            """)
            return [dict(r) for r in cur.fetchall()]
    except Exception:
        return []


def is_watched(contract: str) -> bool:
    try:
        with _connect() as conn:
            cur = conn.execute("SELECT 1 FROM watchlist WHERE contract = ?", (contract,))
            return cur.fetchone() is not None
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Outcomes / calibration analytics
# ---------------------------------------------------------------------------

def compute_outcomes(min_age_hours: float = 24) -> list[dict]:
    """For every coin first seen at least N hours ago that we have a recent
    snapshot for, compute the outcome.

    Returns: list of {symbol, contract, first_seen_at, first_score, latest_price,
                      first_price, pct_change, hours_since}
    """
    cutoff = (datetime.utcnow() - timedelta(hours=min_age_hours)).isoformat()
    try:
        with _connect() as conn:
            # Find all coins where we have a snapshot older than cutoff
            cur = conn.execute("""
                SELECT contract, MIN(timestamp) as first_seen, MIN(id) as first_id
                FROM snapshots
                GROUP BY contract
                HAVING first_seen < ?
            """, (cutoff,))
            firsts = cur.fetchall()

            outcomes = []
            for row in firsts:
                contract = row["contract"]
                # Get the first snapshot
                cur = conn.execute("SELECT * FROM snapshots WHERE id = ?", (row["first_id"],))
                first = cur.fetchone()
                # Get the most recent snapshot
                cur = conn.execute("""
                    SELECT * FROM snapshots WHERE contract = ?
                    ORDER BY timestamp DESC LIMIT 1
                """, (contract,))
                latest = cur.fetchone()
                if not first or not latest:
                    continue
                if not first["price_usd"] or first["price_usd"] <= 0:
                    continue
                pct = ((latest["price_usd"] - first["price_usd"]) / first["price_usd"]) * 100
                hours = (datetime.fromisoformat(latest["timestamp"])
                         - datetime.fromisoformat(first["timestamp"])).total_seconds() / 3600
                outcomes.append({
                    "symbol": first["symbol"],
                    "contract": contract,
                    "first_seen_at": first["timestamp"],
                    "first_momentum": first["momentum_score"],
                    "first_opportunity": first["opportunity_score"],
                    "first_risk": first["scam_risk_score"],
                    "first_price": first["price_usd"],
                    "latest_price": latest["price_usd"],
                    "pct_change": pct,
                    "hours_since": hours,
                })
            return outcomes
    except Exception:
        return []


def get_calibration_stats(min_age_hours: float = 24) -> dict:
    """Aggregate stats by tier:
       - of coins called "High Signal" (opp >= 60), what % are up?
       - same for Notable, Watch, etc."""
    outcomes = compute_outcomes(min_age_hours)
    if not outcomes:
        return {"total": 0, "tiers": {}}

    tiers = {
        "High signal (60+)": [],
        "Notable (40-59)": [],
        "Watch (20-39)": [],
        "Low (<20)": [],
    }
    for o in outcomes:
        score = o["first_opportunity"]
        if score is None:
            continue
        if score >= 60:
            tiers["High signal (60+)"].append(o)
        elif score >= 40:
            tiers["Notable (40-59)"].append(o)
        elif score >= 20:
            tiers["Watch (20-39)"].append(o)
        else:
            tiers["Low (<20)"].append(o)

    stats = {}
    for tier_name, items in tiers.items():
        if not items:
            stats[tier_name] = None
            continue
        pcts = [i["pct_change"] for i in items]
        winners = sum(1 for p in pcts if p > 0)
        big_winners = sum(1 for p in pcts if p > 50)
        big_losers = sum(1 for p in pcts if p < -50)
        stats[tier_name] = {
            "count": len(items),
            "median_pct": _median(pcts),
            "mean_pct": sum(pcts) / len(pcts),
            "pct_positive": (winners / len(items)) * 100,
            "pct_big_winners": (big_winners / len(items)) * 100,
            "pct_big_losers": (big_losers / len(items)) * 100,
            "best": max(pcts),
            "worst": min(pcts),
        }
    return {"total": len(outcomes), "tiers": stats, "min_age_hours": min_age_hours}


def _median(nums):
    s = sorted(nums)
    n = len(s)
    if n == 0:
        return 0
    if n % 2:
        return s[n // 2]
    return (s[n // 2 - 1] + s[n // 2]) / 2


# ---------------------------------------------------------------------------
# Housekeeping
# ---------------------------------------------------------------------------

def prune_old(keep_days: int = 14):
    """Drop snapshots older than N days. Streamlit free tier has ~1GB disk
    in /tmp, but we don't need history beyond a couple weeks for calibration."""
    cutoff = (datetime.utcnow() - timedelta(days=keep_days)).isoformat()
    try:
        with _connect() as conn:
            conn.execute("DELETE FROM snapshots WHERE timestamp < ?", (cutoff,))
    except Exception:
        pass


def stats_summary() -> dict:
    """Quick health check — used in the sidebar."""
    try:
        with _connect() as conn:
            cur = conn.execute("SELECT COUNT(*) as n FROM snapshots")
            total_snaps = cur.fetchone()["n"]
            cur = conn.execute("SELECT COUNT(DISTINCT contract) as n FROM snapshots")
            unique_coins = cur.fetchone()["n"]
            cur = conn.execute("SELECT COUNT(*) as n FROM watchlist")
            watch_count = cur.fetchone()["n"]
            cur = conn.execute("SELECT MIN(timestamp) as t FROM snapshots")
            earliest = cur.fetchone()["t"]
            return {
                "snapshots": total_snaps,
                "unique_coins": unique_coins,
                "watchlist": watch_count,
                "earliest": earliest,
            }
    except Exception:
        return {"snapshots": 0, "unique_coins": 0, "watchlist": 0, "earliest": None}
