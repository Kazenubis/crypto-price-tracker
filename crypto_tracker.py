"""
Crypto Price Tracker — checks a watchlist of coins against per-coin
price thresholds, live via the free CoinGecko API with an offline
fallback, and logs only the moments a coin actually *crosses* a
threshold (not every check while it's already past one) — the same
"log transitions, not every check" shape as this portfolio's website
uptime checker, applied to price alerts instead of up/down status.
"""

import argparse
import json
import os
import time
from datetime import datetime, timezone

import requests

COINGECKO_API = "https://api.coingecko.com/api/v3/simple/price"
DEFAULT_TIMEOUT = 5
DEFAULT_STATE_PATH = "tracker_state.json"
DEFAULT_LOG_PATH = "tracker_log.txt"

# Used only when the live API is unreachable — a plausible-but-fixed
# reference point, clearly labeled as a fallback rather than a live
# quote, so a demo run still produces meaningful output offline.
OFFLINE_SAMPLE_PRICES = {
    "bitcoin": 62345.67,
    "ethereum": 3210.45,
    "solana": 138.20,
    "dogecoin": 0.1234,
}


def load_watchlist(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data["coins"]


def load_state(path):
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(path, state):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def fetch_prices_live(coin_ids, timeout=DEFAULT_TIMEOUT):
    """Raises requests.RequestException on any network problem —
    callers should catch it and fall back to the offline sample."""
    params = {"ids": ",".join(coin_ids), "vs_currencies": "usd"}
    response = requests.get(COINGECKO_API, params=params, timeout=timeout)
    response.raise_for_status()
    data = response.json()
    return {coin_id: data[coin_id]["usd"] for coin_id in coin_ids if coin_id in data}


def get_prices(coin_ids, timeout=DEFAULT_TIMEOUT):
    """Returns (prices, source_label). Falls back to whatever subset of
    `coin_ids` the offline sample has data for — a coin missing from
    both the live response and the sample just isn't in the result,
    same as a real API that doesn't recognize an id."""
    try:
        prices = fetch_prices_live(coin_ids, timeout=timeout)
        if prices:
            return prices, "live"
    except requests.RequestException:
        pass

    offline_prices = {cid: OFFLINE_SAMPLE_PRICES[cid] for cid in coin_ids if cid in OFFLINE_SAMPLE_PRICES}
    return offline_prices, "offline sample"


def classify_status(price, alert_above=None, alert_below=None):
    """Returns 'above', 'below', or 'within' relative to this coin's
    configured thresholds. A coin with only one threshold configured
    is only ever checked against that one."""
    if alert_above is not None and price >= alert_above:
        return "above"
    if alert_below is not None and price <= alert_below:
        return "below"
    return "within"


def run_check_cycle(watchlist, state, timeout=DEFAULT_TIMEOUT):
    """Checks every coin once. Returns (results, transitions, new_state,
    source_label). A transition is recorded only when a coin's status
    differs from its last recorded status (or it's being seen for the
    first time and is already above/below a threshold)."""
    coin_ids = [coin["id"] for coin in watchlist]
    prices, source_label = get_prices(coin_ids, timeout=timeout)

    checked_at = datetime.now(timezone.utc).isoformat()
    results = []
    transitions = []
    new_state = dict(state)

    for coin in watchlist:
        coin_id = coin["id"]
        if coin_id not in prices:
            continue
        price = prices[coin_id]
        status = classify_status(price, coin.get("alert_above"), coin.get("alert_below"))
        previous_status = state.get(coin_id)

        results.append({"id": coin_id, "symbol": coin.get("symbol", coin_id), "price": price, "status": status})

        if status != previous_status and status != "within":
            transitions.append({
                "id": coin_id,
                "symbol": coin.get("symbol", coin_id),
                "price": price,
                "from_status": previous_status or "unknown",
                "to_status": status,
                "checked_at": checked_at,
            })
        new_state[coin_id] = status

    return results, transitions, new_state, source_label


def format_transition_line(transition):
    return (
        f"{transition['checked_at']} {transition['symbol']} "
        f"${transition['price']:,.2f} {transition['from_status']} -> {transition['to_status']}"
    )


def log_transitions(log_path, transitions):
    if not transitions:
        return
    with open(log_path, "a", encoding="utf-8") as f:
        for transition in transitions:
            f.write(format_transition_line(transition) + "\n")


def notify(transition, sink=print):
    direction = "crossed ABOVE" if transition["to_status"] == "above" else "dropped BELOW"
    sink(f"ALERT: {transition['symbol']} {direction} threshold — now ${transition['price']:,.2f}")


def main():
    parser = argparse.ArgumentParser(description="Crypto Price Tracker")
    parser.add_argument("--watchlist", default="watchlist.json")
    parser.add_argument("--state", default=DEFAULT_STATE_PATH)
    parser.add_argument("--log", default=DEFAULT_LOG_PATH)
    parser.add_argument("--interval", type=int, default=60, help="Seconds between checks")
    parser.add_argument("--count", type=int, default=1, help="Number of check cycles to run")
    args = parser.parse_args()

    watchlist = load_watchlist(args.watchlist)
    state = load_state(args.state)

    for cycle in range(args.count):
        results, transitions, state, source_label = run_check_cycle(watchlist, state)
        for result in results:
            print(f"{result['symbol']}: ${result['price']:,.2f}  [{result['status']}]  ({source_label})")
        for transition in transitions:
            notify(transition)
        log_transitions(args.log, transitions)
        save_state(args.state, state)

        if cycle < args.count - 1:
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
