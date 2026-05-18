# Crypto Scoring Framework

The scoring system has three independent scores. Keep them separate — combining them into a single "should I buy" number hides the tradeoffs that matter most.

| Score | Range | What it measures |
|---|---|---|
| **Momentum** | 0–100 | Is this coin actually moving right now? |
| **Scam Risk** | 0–100 | How likely is this a rug, honeypot, or pump-and-dump? |
| **Opportunity** | 0–100 | Composite — only computed when scam risk is below threshold |

## Why three scores, not one

A coin can have insane momentum and still be a scam (most do). A coin can be legitimate and have zero momentum (most are). Surfacing them separately forces the user to look at risk before chasing the pump. If you collapse to one number, your "top opportunities" list will be 80% rugs in a bull cycle because rugs always have the best momentum metrics — that's the whole point of a rug.

## 1. Momentum Score (0–100)

Weighted sum, each component normalized to 0–100 before weighting:

```
momentum = (
    0.25 * price_momentum +
    0.20 * volume_momentum +
    0.15 * social_momentum +
    0.15 * holder_growth +
    0.15 * liquidity_change +
    0.10 * exchange_listing_signal
)
```

### Component definitions

**price_momentum** — Look at 1h, 24h, 7d price changes. Reward sustained moves over flash spikes.
- `score = 50 + clamp(change_1h * 2, -25, 25) + clamp(change_24h, -25, 25)`
- A coin up 10% over 24h with 3% in the last hour scores higher than one up 30% in the last hour (which is more often a pump than a trend).

**volume_momentum** — Volume relative to its own recent baseline, not absolute volume.
- `vol_ratio = volume_24h / avg_volume_7d`
- `score = clamp(log2(vol_ratio) * 20 + 50, 0, 100)`
- A 2x volume spike → 70. A 4x → 90. A 10x → 100 (and probably suspicious — let scam risk handle that).

**social_momentum** — Mention count growth rate across X, Reddit, Telegram. Acceleration matters more than absolute volume.
- `score = clamp((mentions_24h / mentions_prev_24h - 1) * 50 + 50, 0, 100)`
- Going from 10 mentions/day to 100 (10x) scores the same as 1000 → 10000. That's correct — early viral inflection is the signal.

**holder_growth** — New unique holders in the last 24h as a percentage of total holders.
- `score = clamp(new_holder_pct * 500, 0, 100)`
- 5% new holders in a day → score 25. 20% → score 100. Very strong signal for early-stage tokens.

**liquidity_change** — Liquidity pool depth change over 24h.
- `score = clamp(liquidity_change_pct * 2 + 50, 0, 100)`
- Rising liquidity = real money entering. Falling liquidity = exit signal.

**exchange_listing_signal** — Binary boosters.
- New CEX listing in last 7d: +40
- New CEX listing in last 24h: +60
- Upcoming announced listing: +30
- Otherwise: 0 (clamped to 0–100)

## 2. Scam Risk Score (0–100)

Higher = more dangerous. This is the most important score. Compute as **max** of individual risk flags, not weighted sum — a single critical red flag (honeypot, mint authority) should dominate.

### Critical flags (each sets score to 100)

These mean "do not touch." If any are true, score = 100 and you're done.

- **Mint authority not renounced** (Solana) — dev can print infinite tokens
- **Freeze authority active** (Solana) — dev can freeze user wallets
- **Owner can modify contract** (EVM) — proxy contract or owner functions still active
- **Honeypot detected** — sell function reverts in simulation
- **Top wallet holds >50%** of supply (excluding burn address and locked LP)
- **Liquidity not locked** AND token age < 30 days

### Major flags (each adds 25 to score, cap at 99)

- Top 10 wallets hold >40% of supply
- Liquidity pool < $20k (under this you can't exit a meaningful position)
- Token contract less than 24 hours old
- Dev wallet has rugged before (requires historical dev wallet database)
- No social presence at all (zero Twitter, zero Telegram) — usually means abandonment
- Contract not verified on Etherscan/Solscan
- High sell tax (>10%) or buy/sell tax asymmetry

### Minor flags (each adds 10)

- Single liquidity pool only
- Anonymous team (acknowledged in thesis, not auto-disqualifying)
- Heavy bot-like social mention patterns (same message reposted, low-quality accounts)
- Price chart shows classic pump pattern (vertical candle followed by distribution)

```
scam_risk = min(
    100,
    max(
        100 if any_critical_flag else 0,
        25 * count_major_flags + 10 * count_minor_flags
    )
)
```

## 3. Opportunity Score (0–100)

Only computed when `scam_risk < 60`. Otherwise return null and surface the risk score instead.

```
if scam_risk >= 60:
    opportunity = None  # show risk score, hide opportunity
else:
    risk_penalty = scam_risk / 100  # 0.0 to 0.6
    opportunity = momentum * (1 - risk_penalty * 0.7)
```

This means a coin with momentum 90 and scam_risk 50 gets opportunity = 90 * (1 - 0.35) = 58.5. The penalty is real but not crushing — some risk is inherent to the space.

## Tier thresholds (for the dashboard)

| Opportunity | Label | Color |
|---|---|---|
| 80–100 | 🔥 High signal | Green |
| 60–79 | ⚡ Notable | Yellow |
| 40–59 | 👀 Watch | Blue |
| <40 | — | Hidden by default |

| Scam Risk | Label |
|---|---|
| 0–20 | ✅ Low risk |
| 21–50 | ⚠️ Moderate — DYOR |
| 51–80 | 🚩 High risk |
| 81–100 | ☠️ Avoid |

## Things this framework deliberately doesn't do

- **No "AI predicts breakout"** — every score is grounded in observable, current state. The LLM's job (covered in the prompts doc) is to *explain* what's happening, not to forecast.
- **No backtested win-rate claims** — meme cycles aren't stationary; what worked in 2021 doesn't in 2025.
- **No combining into a buy/sell signal** — the platform surfaces information; the user decides.

## Calibration notes

When you start running this on real data:

1. **Sanity-check the top 10** daily for the first two weeks. If obvious rugs are scoring high opportunity, your scam detection is missing something — add a flag.
2. **Track false negatives**: coins you scored low that pumped legitimately. Were you missing a data source, or was it actually unpredictable?
3. **Don't tune to match past pumps**. That's overfitting to noise. Tune to match what a careful human analyst would have flagged in advance.
4. Weights here are starting points based on what experienced on-chain analysts emphasize. Adjust based on what your data actually shows you, not based on what would have caught last week's winner.
