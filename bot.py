# Main trading bot for BNB/USD on binance.us

import logging
logging.basicConfig(
    filename="bot.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

import requests
import json
import time
import sys
import ccxt
import threading
import datetime
import math
import os
import pickle

def send_ntfy_notification(message):
    with open("config.json") as f:
        config = json.load(f)
    topic = config["ntfy_topic"]
    url = f"https://ntfy.sh/{topic}"
    try:
        requests.post(url, data=message.encode("utf-8"))
    except Exception as e:
        print(f"Failed to send ntfy notification: {e}")

positions = []  # Track all filled positions as dicts: {'price': ..., 'qty': ...}
def bid_chaser():

    global filled_order
    notified_no_balance = False
    last_distinct_price = None
    while True:
        try:
            balances = exchange.fetch_balance()
            usd_balance = balances['total'].get('USD', 0)
            if usd_balance == 0:
                usd_balance = balances['total'].get('USD4', 0)
        except Exception as e:
            logging.error(f"Error fetching account info in bid_chaser: {e}")
            usd_balance = 0
        order_book = exchange.fetch_order_book(symbol)
        # Get current price from order book (best ask)
        current_price = float(order_book['asks'][0][0]) if order_book['asks'] else None
        # Cumulate asks up to 90% of USD balance
        asks = order_book['asks']
        cum_qty = 0
        cum_usd = 0
        weighted_ask_sum = 0
        max_usd = min(usd_balance * 0.9, usd_balance)
        for price, qty in asks:
            price = float(price)
            qty = float(qty)
            usd_val = price * qty
            if cum_usd + usd_val > max_usd:
                qty = (max_usd - cum_usd) / price
                usd_val = price * qty
            cum_qty += qty
            cum_usd += usd_val
            weighted_ask_sum += price * usd_val
            if cum_usd >= max_usd:
                break
        # No $50 minimum requirement, so skip this check
        weighted_ask = weighted_ask_sum / cum_usd if cum_usd > 0 else None
        # Cumulate bids until quantity covers cum_qty
        bids = order_book['bids']
        bid_cum_qty = 0
        bid_cum_usd = 0
        weighted_bid_sum = 0
        for price, qty in bids:
            price = float(price)
            qty = float(qty)
            if bid_cum_qty + qty > cum_qty:
                qty = cum_qty - bid_cum_qty
            bid_cum_qty += qty
            bid_cum_usd += price * qty
            weighted_bid_sum += price * qty
            if bid_cum_qty >= cum_qty:
                break
        if bid_cum_qty < cum_qty:
            time.sleep(1)
            continue
        weighted_bid = weighted_bid_sum / bid_cum_qty if bid_cum_qty > 0 else None
        spread_pct = ((weighted_ask - weighted_bid) / weighted_ask) * 100 if weighted_ask and weighted_bid else None

        # --- Distinct price logic ---
        if last_distinct_price is None:
            last_distinct_price = current_price
        elif current_price != last_distinct_price:
            if current_price > last_distinct_price:
                # Place market buy if spread <= 0.1% (no $50 minimum)
                if spread_pct is not None and spread_pct <= 0.1:
                    try:
                        order = exchange.create_market_buy_order(symbol, round(cum_qty, 3))
                        entry_price = float(order['average']) if 'average' in order else weighted_ask
                        qty = round(cum_qty, 3)
                        positions.append({'price': entry_price, 'qty': qty})
                        usd_val = entry_price * qty
                        spread_pct_entry = ((weighted_ask - weighted_bid) / weighted_ask) * 100 if weighted_ask and weighted_bid else None
                        log_msg = f"Position entered: entry={entry_price}, ${usd_val:.2f}, weighted_bid={weighted_bid:.4f}, weighted_ask={weighted_ask:.4f}, spread={spread_pct_entry:.4f}%"
                        logging.info(log_msg)
                        print(log_msg)
                        send_ntfy_notification(log_msg)
                    except Exception as e:
                        logging.error(f"Error placing market buy: {e}")
                last_distinct_price = current_price
            else:
                last_distinct_price = current_price
        # Remove historical order tracking to avoid duplicate positions
        time.sleep(1)
    return None

def get_24h_stats_file():
    return os.path.join(os.path.dirname(__file__), 'pl_24h.pkl')

def update_24h_stats(profit_loss):
    stats_file = get_24h_stats_file()
    now = time.time()
    # Load or initialize
    if os.path.exists(stats_file):
        with open(stats_file, 'rb') as f:
            stats = pickle.load(f)
    else:
        stats = []
    # Add new P/L event
    stats.append((now, profit_loss))
    # Remove events older than 24h
    stats = [(t, pl) for t, pl in stats if now - t <= 86400]
    # Save
    with open(stats_file, 'wb') as f:
        pickle.dump(stats, f)
    return stats

def get_24h_pl():
    stats_file = get_24h_stats_file()
    now = time.time()
    if os.path.exists(stats_file):
        with open(stats_file, 'rb') as f:
            stats = pickle.load(f)
        stats = [(t, pl) for t, pl in stats if now - t <= 86400]
        total = sum(pl for t, pl in stats)
        return total
    return 0.0

def should_send_24h_update():
    flag_file = os.path.join(os.path.dirname(__file__), 'last_24h_update.txt')
    now = datetime.datetime.now()
    today_8am = now.replace(hour=8, minute=0, second=0, microsecond=0)
    if now < today_8am:
        today_8am -= datetime.timedelta(days=1)
    # Check last sent time
    if os.path.exists(flag_file):
        with open(flag_file, 'r') as f:
            last_sent = float(f.read().strip())
        last_sent_dt = datetime.datetime.fromtimestamp(last_sent)
        # Only send if last sent was before today 8am
        if last_sent_dt >= today_8am:
            return False
    # Update last sent time
    with open(flag_file, 'w') as f:
        f.write(str(now.timestamp()))
    return True

if __name__ == "__main__":
    filled_order = None
    try:
        # Load config and set up ccxt Binance.US client
        with open("config.json") as f:
            config = json.load(f)
        exchange = ccxt.binanceus({
            "apiKey": config["binance_api_key"],
            "secret": config["binance_api_secret"],
            "enableRateLimit": True,
        })

        send_ntfy_notification("Bot started")

        symbol = "BNBUSD"
        print("Bot starting...")

        # Get available USD balance (ccxt)
        try:
            balances = exchange.fetch_balance()
            # Try 'USD', 'USD4', and other possible keys
            usd_balance = balances['total'].get('USD', 0)
            if usd_balance == 0:
                usd_balance = balances['total'].get('USD4', 0)
            logging.info(f"Available USD balance: {usd_balance}")
        except Exception as e:
            logging.error(f"Error fetching account info: {e}")
            usd_balance = 0

        def log_status():
            try:
                now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                order_book = exchange.fetch_order_book(symbol)
                # Get USD balance
                balances = exchange.fetch_balance()
                usd_balance = balances['total'].get('USD', 0)
                if usd_balance == 0:
                    usd_balance = balances['total'].get('USD4', 0)
                # Cumulate asks
                asks = order_book['asks']
                cum_qty = 0
                cum_usd = 0
                weighted_ask_sum = 0
                for price, qty in asks:
                    price = float(price)
                    qty = float(qty)
                    usd_val = price * qty
                    cum_qty += qty
                    cum_usd += usd_val
                    weighted_ask_sum += price * usd_val
                    if cum_usd >= 50:
                        break
                weighted_ask = weighted_ask_sum / cum_usd if cum_usd > 0 else None
                # Cumulate bids
                bids = order_book['bids']
                bid_cum_qty = 0
                bid_cum_usd = 0
                weighted_bid_sum = 0
                for price, qty in bids:
                    price = float(price)
                    qty = float(qty)
                    if bid_cum_qty + qty > cum_qty:
                        qty = cum_qty - bid_cum_qty
                    bid_cum_qty += qty
                    bid_cum_usd += price * qty
                    weighted_bid_sum += price * qty
                    if bid_cum_qty >= cum_qty:
                        break
                weighted_bid = weighted_bid_sum / bid_cum_qty if bid_cum_qty > 0 else None
                spread_pct = ((weighted_ask - weighted_bid) / weighted_ask) * 100 if weighted_ask and weighted_bid else None
                # Logger output for market info
                if weighted_bid is not None and weighted_ask is not None and spread_pct is not None:
                    market_info = f"USD: ${usd_balance:.2f}, Weighted bid: {weighted_bid:.4f}, Weighted ask: {weighted_ask:.4f}, Spread: {spread_pct:.4f}%"
                else:
                    market_info = f"USD: ${usd_balance:.2f}, Market info unavailable"
                # --- Combine all positions into one weighted position if >=2 ---
                positions_info = ''
                if positions:
                    # Combine positions if more than one
                    if len(positions) > 1:
                        total_qty = sum(p['qty'] for p in positions)
                        weighted_entry = sum(p['price'] * p['qty'] for p in positions) / total_qty
                        # Merge ratchet/floor/ceiling logic: use most conservative (lowest floor, highest ceiling)
                        ratchet_level = max(p.get('ratchet_level', 0) for p in positions)
                        floor = min(p.get('floor', weighted_entry * (1 - 0.002)) for p in positions)
                        ceiling = max(p.get('ceiling', weighted_entry * (1 + 0.001)) for p in positions)
                        positions[:] = [{
                            'price': weighted_entry,
                            'qty': total_qty,
                            'ratchet_level': ratchet_level,
                            'floor': floor,
                            'ceiling': ceiling
                        }]
                    pos = positions[0]
                    entry_price = pos['price']
                    qty = pos['qty']
                    usd_val = entry_price * qty
                    # Find the highest open bid that can cover the position
                    highest_covering_bid = None
                    for bid in order_book['bids']:
                        bid_price = float(bid[0])
                        bid_qty = float(bid[1])
                        if bid_qty >= qty:
                            highest_covering_bid = bid_price
                            break
                    # Ratcheting logic: floor only ratchets up, never down
                    ratchet_step = 0.001  # 0.1%
                    if 'ratchet_level' not in pos:
                        pos['ratchet_level'] = 0
                    if 'floor' not in pos:
                        pos['floor'] = entry_price * (1 - 0.002)
                    if 'ceiling' not in pos:
                        pos['ceiling'] = entry_price * (1 + ratchet_step)
                    # Move up ratchet if highest_covering_bid exceeds current ceiling
                    while highest_covering_bid and highest_covering_bid > pos['ceiling']:
                        pos['ratchet_level'] += 1
                        pos['floor'] = entry_price * (1 + ratchet_step * pos['ratchet_level'])
                        pos['ceiling'] = entry_price * (1 + ratchet_step * (pos['ratchet_level'] + 1))
                    # Floor never decreases
                    # Execute market sell if needed
                    if highest_covering_bid and highest_covering_bid <= pos['floor']:
                        try:
                            order = exchange.create_market_sell_order(symbol, qty)
                            exit_price = float(order['average']) if 'average' in order else highest_covering_bid
                            usd_val = exit_price * qty
                            # Calculate profit/loss using weighted entry and total qty
                            profit_loss = exit_price * qty - entry_price * qty
                            profit_loss_pct = ((exit_price - entry_price) / entry_price) * 100
                            log_msg = f"Position exited: exit={exit_price}, ${usd_val:.2f}, highest_bid={highest_covering_bid}, P/L=${profit_loss:.2f} ({profit_loss_pct:.2f}%)"
                            logging.info(log_msg)
                            print(log_msg)
                            ntfy_msg = f"Position exited: P/L ${profit_loss:.2f} ({profit_loss_pct:.2f}%)"
                            send_ntfy_notification(ntfy_msg)
                            # --- 24 hour P/L update logic ---
                            update_24h_stats(profit_loss)
                            pl_24h = get_24h_pl()
                            pl_24h_pct = (pl_24h / (entry_price * qty)) * 100 if entry_price * qty != 0 else 0
                            if should_send_24h_update():
                                pl_24h_msg = f"24 HOUR UPDATE: P/L ${pl_24h:.2f} ({pl_24h_pct:.2f}%)"
                                logging.info(pl_24h_msg)
                                send_ntfy_notification(pl_24h_msg)
                            positions.clear()
                        except Exception as e:
                            logging.error(f"Error placing market sell: {e}")
                    positions_info = f" | Position: entry={entry_price}, ${usd_val:.2f}, highest_bid={highest_covering_bid}, floor={pos['floor']:.4f}, ceiling={pos['ceiling']:.4f}"
                else:
                    positions_info = ' | Positions: None'
                msg = f"{now}: {market_info}{positions_info}"
                print(msg)
                logging.info(msg)
                for handler in logging.getLogger().handlers:
                    handler.flush()
            except Exception as e:
                logging.error(f"Error in log_status: {e}")

        def periodic_logger():
            while True:
                log_status()
                time.sleep(10)

        # --- Bid Chase Logic ---
        bid_order_id = None
        position_entered = False

        def get_best_bid():
            order_book = exchange.fetch_order_book(symbol)
            return float(order_book['bids'][0][0]) if order_book['bids'] else None

        def cancel_order(order_id):
            try:
                exchange.cancel_order(order_id, symbol)
            except Exception as e:
                logging.error(f"Error cancelling order: {e}")

        # Place initial bid
        if usd_balance <= 0:
            msg = f"No USD balance available to place a bid. USD balance: {usd_balance}"
            logging.warning(msg)
            send_ntfy_notification(msg)
            print("No USD balance available. Bot will shut down.")
            # Skip trading logic and exit gracefully
            filled_order = None

        # Start the logger thread
        logger_thread = threading.Thread(target=periodic_logger, daemon=True)
        logger_thread.start()

        # Start bid chaser thread
        bid_thread = threading.Thread(target=bid_chaser, daemon=True)
        bid_thread.start()

        while True:
            time.sleep(10)
    except (KeyboardInterrupt, SystemExit):
        print("Bot shutting down.")
        send_ntfy_notification("Bot shut down")
