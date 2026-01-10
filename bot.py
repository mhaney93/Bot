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
        # Cumulate asks until at least $50 or 90% of USD balance
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
            if cum_usd >= 50:
                break
        if cum_usd < 50:
            time.sleep(1)
            continue
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
        # Place market buy if spread <= 0.1%
        if spread_pct is not None and spread_pct <= 0.1 and cum_usd >= 50:
            try:
                order = exchange.create_market_buy_order(symbol, round(cum_qty, 3))
                entry_price = float(order['average']) if 'average' in order else weighted_ask
                qty = round(cum_qty, 3)
                positions.append({'price': entry_price, 'qty': qty})
                usd_val = entry_price * qty
                logging.info(f"Position entered: entry={entry_price}, ${usd_val:.2f}, weighted_bid={weighted_bid:.4f}, weighted_ask={weighted_ask:.4f}")
                print(f"Position entered: entry={entry_price}, ${usd_val:.2f}, weighted_bid={weighted_bid:.4f}, weighted_ask={weighted_ask:.4f}")
                # Only log the entry with the spread percent
                spread_pct_entry = ((weighted_ask - weighted_bid) / weighted_ask) * 100 if weighted_ask and weighted_bid else None
                log_msg = f"Position entered: entry={entry_price}, ${usd_val:.2f}, weighted_bid={weighted_bid:.4f}, weighted_ask={weighted_ask:.4f}, spread={spread_pct_entry:.4f}%"
                logging.info(log_msg)
                print(log_msg)
                logging.info(f"Market buy executed: entry={entry_price}, qty={qty}")
            except Exception as e:
                logging.error(f"Error placing market buy: {e}")
        # Remove historical order tracking to avoid duplicate positions
        time.sleep(1)
    return None

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
                # Position info: show entry price, USD value, highest covering bid, and current thresholds for each position
                positions_info = ''
                if positions:
                    positions_info = ' | Positions: '
                    pos_strs = []
                    for i, pos in enumerate(positions, 1):
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
                                logging.info(f"Market sell executed: exit={highest_covering_bid}, qty={qty}")
                                positions.remove(pos)
                            except Exception as e:
                                logging.error(f"Error placing market sell: {e}")
                        pos_strs.append(f"[{i}] entry={entry_price}, ${usd_val:.2f}, highest_covering_bid={highest_covering_bid}, floor={pos['floor']:.4f}, ceiling={pos['ceiling']:.4f}")
                    positions_info += '; '.join(pos_strs)
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
