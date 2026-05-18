# Crypto Intelligence Platform — Starter Kit

This is the analytical core of your platform. Three things, all working:

```
crypto_intel/
├── src/scoring.py              # Scoring engine — pure Python, no deps
├── prompts/llm_prompts.py      # LLM prompts for thesis + scam analysis
├── demo/run_demo.py            # End-to-end demo with 3 realistic scenarios
└── docs/scoring_framework.md   # The thinking behind every weight
```

## Run it

```bash
python demo/run_demo.py
```

No installs, no API keys, no network. Three coin scenarios run through the
engine and print their scores plus the actual LLM prompt that would be sent
for each one.

## What's here

### 1. Three-score system, not one
Momentum, scam risk, and opportunity are kept separate. Combining them is
how platforms end up surfacing rugs as "top picks" — rugs always have the
best momentum metrics. The framework doc explains the design choices.

### 2. Scam risk uses MAX of critical flags, not weighted sum
One critical flag (active mint authority, top wallet >50%, honeypot) → score
of 100, full stop. No amount of momentum compensates.

### 3. Opportunity score is hidden when scam risk ≥ 60
The platform doesn't show a "buy" tier for dangerous coins. They surface
only with their risk flags visible.

### 4. The LLM prompts have hard guardrails
`SYSTEM_BASE` in `llm_prompts.py` is the persona contract. It bans price
predictions, hype language, and recommendations. Keep these — they're what
prevents the platform from being a pump-and-dump machine, and they're your
legal cover.

## What's NOT here yet (and what you'll need)

Honest accounting at $200/mo budget:

| Layer | Status | Realistic next step |
|---|---|---|
| Scoring engine | ✅ Done | Unit tests, then connect to real data |
| LLM prompts | ✅ Done | Test on real coins, iterate on output quality |
| **Data ingestion** | ❌ Not built | CoinGecko free tier + DexScreener (free) are your starting point |
| **On-chain checks** | ❌ Not built | Helius free tier for Solana, Alchemy free tier for EVM |
| **Social monitoring** | ❌ Hardest | X API costs $100/mo minimum. Start with Reddit (free) + Telegram bot ingestion |
| **Storage** | ❌ Not built | Supabase free tier handles hobby-scale Postgres |
| **Frontend** | ❌ Not built | Next.js + the dashboard shape you saw above |
| **Real-time updates** | ❌ Not built | Polling on a 60s cron is fine until you have users |

## Realistic 4-week MVP path

**Week 1 — Wire up data**
- Write a `data/fetchers.py` module with one function per source: `fetch_coingecko(symbol)`, `fetch_dexscreener(address)`, `fetch_helius_holders(address)`.
- Each returns a partial dict that gets merged into a `CoinData` instance.
- Set up Supabase, create `coins` and `snapshots` tables.

**Week 2 — Run scoring on real coins**
- Cron job: every 5 minutes, fetch top 200 trending from DexScreener, score them, write to DB.
- Hardcode 20 known scams and 20 known legit coins as a regression test set. Run your engine against them every change.

**Week 3 — Add the LLM layer**
- Hook up Claude API. Use Haiku for the bulk thesis generation (cheap), Sonnet only for the top 10.
- Cache thesis output — regenerate at most every 4 hours per coin.
- Track output quality manually for the first week. The prompts will need tuning against your actual data.

**Week 4 — Frontend**
- Next.js, deploy to Vercel free tier.
- One page: the dashboard mockup you saw above, populated from your DB.
- One detail page per coin: thesis + risk analysis + recharts price chart.

That's a real, shippable thing in a month. Everything else (Twitter ingestion,
mobile app, alerts, watchlists, on-chain whale tracking) is post-MVP.

## On the "AI prediction engine" framing

The original spec called for AI that "identifies potential breakout
opportunities" and "generates buy/sell alerts." I built the platform with a
deliberately different framing: the AI explains what's currently happening,
flags risks aggressively, and refuses to predict. Two reasons:

1. **Honesty.** Nobody — no model, no analyst, no on-chain wizard — reliably
   front-runs memecoin pumps. The platforms that claim to do this either
   work for the people running the pumps, or they're the ones extracting
   value from users via subscription fees.

2. **Defensibility.** "AI predicts crypto prices" gets you regulator
   attention in the US, UK, and EU. "AI surfaces on-chain risk signals" is
   research/information, which is a much safer legal category. You can
   still build a great product — Token Terminal, Nansen, and Arkham all
   thrive in this lane.

If users want predictions, you'll lose them to scammier competitors. Let
them go. The users who stay are the ones who'll pay for accurate, sober
analysis — and they're a much better customer base.

## Files to send to a developer

When you're ready to hand this off, the files in this folder plus the
mockup are a tight, complete spec. A competent Next.js + Python dev can
turn this into a working MVP in 3–4 weeks at standard contractor rates.
