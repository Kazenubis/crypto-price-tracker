# Crypto Price Tracker

Checks a watchlist of coins against per-coin price thresholds, live via
the free CoinGecko API with an offline fallback, and logs only the
moments a coin actually *crosses* a threshold — not every check while
it's already sitting past one. Same "log transitions, not every check"
shape as this portfolio's website uptime checker, applied to price
alerts instead of up/down status.

Real output from a 2-cycle run (this environment has no live network
access, so it's using the offline fallback; the cycle-2 price move is
simulated to demonstrate a real threshold crossing):

```
--- Cycle 1 ---
BTC: $62,345.67  [within]  (offline sample)
ETH: $3,210.45  [within]  (offline sample)
SOL: $138.20  [within]  (offline sample)
DOGE: $0.12  [within]  (offline sample)

--- Cycle 2 (BTC rallies past its alert_above threshold) ---
BTC: $73,500.00  [above]  (offline sample)
ETH: $3,210.45  [within]  (offline sample)
SOL: $138.20  [within]  (offline sample)
DOGE: $0.12  [within]  (offline sample)
ALERT: BTC crossed ABOVE threshold — now $73,500.00

--- tracker_log.txt ---
2026-09-11T08:47:21.620725+00:00 BTC $73,500.00 within -> above
```

## Features

- Per-coin `alert_above` / `alert_below` thresholds, configured in a
  simple watchlist JSON — either bound is optional
- Live fetch from the CoinGecko public API, with an offline fallback
  sample so the tool still produces meaningful output with no network
- Logs only status *transitions* (within → above, above → below, etc.)
  to a persisted log file, using persisted state (`tracker_state.json`)
  so a coin that stays above threshold for 50 checks in a row doesn't
  write 50 more log lines
- A simple notification hook (defaults to printing; swap in a real
  webhook/email call by passing a different `sink`) fires on every
  threshold crossing

## Tech Stack

Python 3 · `requests`

## Getting Started

```bash
git clone https://github.com/Kazenubis/crypto-price-tracker.git
cd crypto-price-tracker
pip install -r requirements.txt
python3 crypto_tracker.py --watchlist watchlist.json --count 1
```

Run it continuously (5-minute interval, 12 checks = 1 hour):

```bash
python3 crypto_tracker.py --watchlist watchlist.json --interval 300 --count 12
```

Run the tests:

```bash
python3 -m unittest test_crypto_tracker.py -v
```

## What I Learned

The "first time seeing a coin that's already above threshold" case
needed its own explicit handling, not just "did the status change from
last time" — on a fresh run with no prior state, every coin's previous
status is unknown, and if the very first check already finds a coin
past its threshold, that's a genuine alert-worthy transition, not
something to silently record and wait for a *second* check to compare
against. `test_first_time_above_threshold_is_a_transition` is what
caught this: a first version that only alerted on an actual status
*change* would miss the very first crossing if it happened to be
already past threshold the first time the tool ever ran.
