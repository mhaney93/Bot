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

def bid_chaser():
    global filled_order
    notified_no_balance = False
    while True:
        # Always fetch the latest USD balance
        try:
            balances = exchange.fetch_balance()
            usd_balance = balances['total'].get('USD', 0)
            if usd_balance == 0:
                usd_balance = balances['total'].get('USD4', 0)
        except Exception as e:
            logging.error(f"Error fetching account info in bid_chaser: {e}")
            usd_balance = 0
        # Always fetch your current open buy order (if any)
        open_orders = exchange.fetch_open_orders(symbol)
        my_bid_order = None
        for order in open_orders:
            if order['side'].upper() == 'BUY' and order['status'] in ('open', 'new'):
                my_bid_order = order
                break
        # Always define next_highest_bid
        next_highest_bid = None
        order_book = exchange.fetch_order_book(symbol)
        if order_book['bids']:
            import math
            for bid in order_book['bids']:
                bid_price = float(bid[0])
                if my_bid_order and math.isclose(bid_price, float(my_bid_order['price']), abs_tol=0.0001):
                    continue  # skip our own bid
                next_highest_bid = bid_price
                break
        # If no open bid, place one
        if not my_bid_order:
            if next_highest_bid is None:
                time.sleep(3)
                continue
            target_price = round(next_highest_bid + 0.01, 2)
            qty = round((usd_balance * 0.9) / target_price, 3) if target_price > 0 else 0
            if qty > 0:
                place_maker_bid(usd_balance, suppress_insufficient=True)
            time.sleep(3)
            continue
        # If we have an open bid, check if it's stale or outbid
        my_price = float(my_bid_order['price'])
        if next_highest_bid is None:
            time.sleep(3)
            continue
        target_price = round(next_highest_bid + 0.01, 2)
        # Debug print
        print(f"[DEBUG] my_price: {my_price}, next_highest_bid: {next_highest_bid}, target_price: {target_price}")
        if (my_price < target_price - 0.0001 or my_price > target_price + 0.0001):
            print(f"[DEBUG] Cancelling and rebidding: my_price={my_price}, target_price={target_price}")
            cancel_order(my_bid_order['id'])
            # Fetch latest balance before rebidding
            try:
                balances = exchange.fetch_balance()
                usd_balance = balances['total'].get('USD', 0)
                if usd_balance == 0:
                    usd_balance = balances['total'].get('USD4', 0)
            except Exception as e:
                logging.error(f"Error fetching account info in chase_bid: {e}")
                usd_balance = 0
            place_maker_bid(usd_balance, suppress_insufficient=True)
            time.sleep(3)
            continue
        # Check if our order is filled
        try:
            order = exchange.fetch_order(my_bid_order['id'], symbol)
            filled_amt = float(order.get('filled', 0))
            status = order.get('status', '').lower()
            if status in ('closed', 'filled') or filled_amt > 0:
                logging.info("Position entered.")
                send_ntfy_notification("Position entered.")
                filled_order = order
                return
        except Exception as e:
            logging.error(f"Error checking fill status: {e}")
        time.sleep(3)
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
                # Get order book
                order_book = exchange.fetch_order_book(symbol)
                # Get your open bid (if any)
                open_bid_price = None
                open_bid_value = None
                open_orders = exchange.fetch_open_orders(symbol)
                for order in open_orders:
                    if order['side'].upper() == 'BUY' and order['status'] in ('open', 'new'):
                        open_bid_price = float(order['price'])
                        open_bid_value = float(order['amount']) * open_bid_price
                        break
                # Find next highest open bid (not your own)
                next_highest_bid = None
                for bid in order_book['bids']:
                    bid_price = float(bid[0])
                    if open_bid_price is not None and math.isclose(bid_price, open_bid_price, abs_tol=0.0001):
                        continue  # skip your own bid
                    next_highest_bid = bid_price
                    break
                lowest_ask = float(order_book['asks'][0][0]) if order_book['asks'] else None
                # Position info
                position_info = ''
                if filled_order:
                    entry_price = float(filled_order['price'])
                    qty = float(filled_order['amount'])
                    position_info = f" | Position: entry={entry_price}, qty={qty}"
                usd_value_str = f"{open_bid_value:.2f}" if open_bid_value is not None else "None"
                msg = f"{now}: Open bid: ${usd_value_str}, {open_bid_price}, Next highest: {next_highest_bid}, Lowest ask: {lowest_ask}{position_info}"
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

        def place_maker_bid(usd_balance, suppress_insufficient=False):
            best_bid = get_best_bid()
            if not best_bid:
                logging.error("No best bid found.")
                return None
            # Use 90% of available USD balance
            qty = round((usd_balance * 0.9) / best_bid, 3)
            if qty <= 0:
                msg = f"Insufficient USD balance to place a bid. USD balance: {usd_balance}"
                logging.warning(msg)
                if not suppress_insufficient:
                    send_ntfy_notification(msg)
                return None
            # Place limit order just above best bid to be a maker
            price = round(best_bid + 0.01, 2)
            try:
                order = exchange.create_limit_buy_order(symbol, qty, price)
                logging.info(f"Placed maker bid: qty={qty}, price={price}")
                # No notification for placing a bid
                return order['id']
            except Exception as e:
                logging.error(f"Error placing maker bid: {e}")
                if not suppress_insufficient:
                    send_ntfy_notification(f"Error placing maker bid: {e}")
                return None

        # Place initial bid
        if usd_balance <= 0:
            msg = f"No USD balance available to place a bid. USD balance: {usd_balance}"
            logging.warning(msg)
            send_ntfy_notification(msg)
            print("No USD balance available. Bot will shut down.")
            # Skip trading logic and exit gracefully
            filled_order = None
        else:
            bid_order_id = place_maker_bid(usd_balance)

        # Start the logger thread
        logger_thread = threading.Thread(target=periodic_logger, daemon=True)
        logger_thread.start()

        # Start bid chaser thread
        bid_thread = threading.Thread(target=bid_chaser, daemon=True)
        bid_thread.start()

        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        print("Bot shutting down.")
        send_ntfy_notification("Bot shut down")
