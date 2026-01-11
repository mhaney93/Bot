import logging
import json
import ccxt
import time
import threading
import traceback

# --- CONFIG ---
PAIR = 'BNB/USD'
SPREAD_BUY_THRESHOLD = 0.1  # percent
SPREAD_SELL_THRESHOLD = 0.2  # percent
RATCHET_INCREMENT = 0.1  # percent
LOG_INTERVAL = 10  # seconds
USD_TRADE_PCT = 0.9  # 90%

# --- LOGGING SETUP ---
logger = logging.getLogger("new_bot")
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s %(message)s')
file_handler = logging.FileHandler("new_bot.log")
file_handler.setFormatter(formatter)
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)
logger.handlers.clear()
logger.addHandler(file_handler)
logger.addHandler(stream_handler)

# --- GLOBALS ---
position = None  # {'entry': float, 'amount': float, 'ratchet': float}
last_price = None

# --- NOTIFICATION (stub) ---
def send_ntfy_notification(msg):
    # Implement ntfy notification if needed
    pass

# --- LOGGER THREAD ---
def log_status():
    while True:
        try:
            order_book = exchange.fetch_order_book(PAIR)
            asks = order_book['asks']
            bids = order_book['bids']
            top_ask = asks[0][0] if asks else None
            top_bid = bids[0][0] if bids else None
            spread = ((top_ask - top_bid) / top_ask * 100) if (top_ask and top_bid) else None
            pos_str = (
                f"ENTRY: {position['entry']:.2f}, AMT: {position['amount']:.4f}, RATCHET: {position['ratchet']:.2f}" if position else 'None'
            )
            logger.info(f"bid: {top_bid}, ask: {top_ask}, spread: {spread:.3f}%, position: {pos_str}")
        except Exception as e:
            logger.error(f"Error in log_status: {e}")
        time.sleep(LOG_INTERVAL)

# --- MAIN TRADING LOOP ---
def main():
    global position, last_price
    while True:
        try:
            order_book = exchange.fetch_order_book(PAIR)
            asks = order_book['asks']
            bids = order_book['bids']
            top_ask = asks[0][0] if asks else None
            top_bid = bids[0][0] if bids else None
            spread = ((top_ask - top_bid) / top_ask * 100) if (top_ask and top_bid) else None
            # --- BUY LOGIC ---
            if not position and top_ask and top_bid and spread is not None:
                # Find last different price
                if last_price is None or top_bid != last_price:
                    if last_price is not None and top_bid > last_price and spread <= SPREAD_BUY_THRESHOLD:
                        # Buy with 90% of USD
                        balance = exchange.fetch_balance()
                        usd = balance['total'].get('USD', 0)
                        buy_usd = usd * USD_TRADE_PCT
                        amount = buy_usd / top_ask if top_ask else 0
                        if amount > 0:
                            order = exchange.create_market_buy_order(PAIR, amount)
                            position = {
                                'entry': float(order['average'] or top_ask),
                                'amount': float(order['filled']),
                                'ratchet': float(order['average'] or top_ask) * (1 + RATCHET_INCREMENT / 100)
                            }
                            logger.info(f"ENTER POSITION: {position}")
                            send_ntfy_notification(f"Entered position: {position}")
                    last_price = top_bid
            # --- SELL LOGIC ---
            if position:
                # Find the price that would fill our position (simulate market sell)
                qty = position['amount']
                cum_qty = 0
                best_bid = None
                for price, size in bids:
                    cum_qty += size
                    if cum_qty >= qty:
                        best_bid = price
                        break
                if best_bid is None:
                    best_bid = bids[0][0] if bids else None
                entry = position['entry']
                ratchet = position['ratchet']
                # If price drops to <= 0.2% above entry, sell
                if best_bid is not None and best_bid <= entry * (1 + SPREAD_SELL_THRESHOLD / 100):
                    order = exchange.create_market_sell_order(PAIR, position['amount'])
                    logger.info(f"EXIT POSITION: {order}")
                    send_ntfy_notification(f"Exited position: {order}")
                    position = None
                # If price rises above ratchet, move ratchet up
                elif best_bid is not None and best_bid > ratchet:
                    new_ratchet = entry * (1 + ((int((best_bid/entry - 1) * 1000) // int(RATCHET_INCREMENT*10)) * RATCHET_INCREMENT) / 100)
                    if new_ratchet > position['ratchet']:
                        position['ratchet'] = new_ratchet
                        logger.info(f"RATCHET UP: {position['ratchet']:.4f}")
            time.sleep(2)
        except Exception as e:
            logger.error(f"Error in main loop: {e}")
            traceback.print_exc()
            time.sleep(10)

if __name__ == "__main__":
    try:
        with open("config.json") as f:
            config = json.load(f)
        exchange = ccxt.binanceus({
            "apiKey": config["binance_api_key"],
            "secret": config["binance_api_secret"],
            "enableRateLimit": True,
        })
        logger.info("Bot started.")
        send_ntfy_notification("Bot started.")
        threading.Thread(target=log_status, daemon=True).start()
        main()
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        traceback.print_exc()
