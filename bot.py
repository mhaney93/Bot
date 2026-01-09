# Main trading bot for BNB/USD on binance.us


import requests
import json
import time
import sys
import ccxt

def send_ntfy_notification(message):
    with open("config.json") as f:
        config = json.load(f)
    topic = config["ntfy_topic"]
    url = f"https://ntfy.sh/{topic}"
    try:
        requests.post(url, data=message.encode("utf-8"))
    except Exception as e:
        print(f"Failed to send ntfy notification: {e}")

if __name__ == "__main__":
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

    import logging
    logging.basicConfig(filename="bot.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

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
        # Placeholder for actual status info
        logging.info(f"Bot running. USD balance: {usd_balance}")

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

    def place_maker_bid(usd_balance):
        best_bid = get_best_bid()
        if not best_bid:
            logging.error("No best bid found.")
            return None
        # Use 90% of available USD balance
        qty = round((usd_balance * 0.9) / best_bid, 3)
        if qty <= 0:
            msg = f"Insufficient USD balance to place a bid. USD balance: {usd_balance}"
            logging.warning(msg)
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

        def chase_bid(order_id, usd_balance):
            while not position_entered:
                best_bid = get_best_bid()
                if not best_bid:
                    time.sleep(0.5)
                    continue
                # Check if our order is still the best bid
                try:
                    order = exchange.fetch_order(order_id, symbol)
                    if order['status'] == 'closed':
                        logging.info("Position entered.")
                        send_ntfy_notification("Position entered.")
                        return order
                    # If our price is not the best bid, cancel and replace
                    if float(order['price']) < best_bid:
                        cancel_order(order_id)
                        order_id = place_maker_bid(usd_balance)
                except Exception as e:
                    logging.error(f"Error chasing bid: {e}")
                time.sleep(0.5)
            return None

        # Start chasing bid until position entered
        filled_order = chase_bid(bid_order_id, usd_balance)

    # --- Position Tracking and Ratchet Logic ---
    if filled_order:
        entry_price = float(filled_order['price'])
        qty = float(filled_order['amount'])
        lower_threshold = entry_price * 0.998  # -0.2%
        ratchet_increment = 0.001  # 0.1%
        highest_bid = entry_price
        position_active = True

        while position_active:
            best_bid = get_best_bid()
            if not best_bid:
                time.sleep(0.5)
                continue
            # Update highest bid
            if best_bid > highest_bid:
                highest_bid = best_bid
                # Ratchet up lower threshold
                lower_threshold = highest_bid * (1 - ratchet_increment)
                logging.info(f"Ratchet up: new lower threshold {lower_threshold:.2f}")
            # If highest bid drops to <= lower threshold, exit position
            if best_bid <= lower_threshold:
                try:
                    sell_order = exchange.create_market_sell_order(symbol, qty)
                    logging.info(f"Position exited at {best_bid}")
                    send_ntfy_notification(f"Position exited at {best_bid}")
                    position_active = False
                except Exception as e:
                    logging.error(f"Error placing market sell: {e}")
            # If highest bid rises > +0.1% above entry, ratchet up threshold
            if highest_bid > entry_price * (1 + ratchet_increment):
                entry_price = highest_bid
                lower_threshold = entry_price * (1 - ratchet_increment)
                logging.info(f"Ratchet up: new entry price {entry_price:.2f}, new lower threshold {lower_threshold:.2f}")
            time.sleep(0.5)

    try:
        while True:
            log_status()
            time.sleep(10)
    except KeyboardInterrupt:
        print("Bot shutting down.")
    finally:
        send_ntfy_notification("Bot shut down")
