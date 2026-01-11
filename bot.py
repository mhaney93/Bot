# Periodic logger function
def periodic_logger():
    while True:
        try:
            log_status()
        except Exception as e:
            logging.error(f"Error in periodic_logger: {e}")
        time.sleep(10)
# Main trading bot for BNB/USD on binance.us


import logging
import datetime
import json
import ccxt
import os
import time
import pickle
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)

positions = []

# --- Move log_status and periodic_logger to top-level, not nested ---
def log_status():
    try:
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        try:
            order_book = exchange.fetch_order_book(symbol, {'timeout': 10000})
        except Exception as e:
            logging.error(f"Error fetching order book in log_status: {e}")
            return
        # Get USD balance
        try:
            balances = exchange.fetch_balance({'timeout': 10000})
            usd_balance = balances['total'].get('USD', 0)
            if usd_balance == 0:
                usd_balance = balances['total'].get('USD4', 0)
        except Exception as e:
            logging.error(f"Error fetching account info in log_status: {e}")
            usd_balance = 0
        # Cumulate asks
        asks = order_book['asks']
        cum_qty = 0.0
        cum_usd = 0.0
        weighted_ask_sum = 0.0
        for entry in asks:
            price = qty = None
            if isinstance(entry, (list, tuple)) and len(entry) == 2:
                price, qty = entry
            elif isinstance(entry, dict):
                # Try common keys
                price = entry.get('price')
                qty = entry.get('amount', entry.get('qty'))
            if price is None or qty is None:
                logging.debug(f"Skipping malformed ask entry: {entry}")
                continue
            try:
                price = float(price)
                qty = float(qty)
            except Exception:
                logging.debug(f"Skipping ask entry with non-numeric price/qty: {entry}")
                continue
            usd_val = price * qty
            cum_qty += qty
            cum_usd += usd_val
            weighted_ask_sum += price * usd_val
            if cum_usd >= 50:
                break
        weighted_ask = weighted_ask_sum / cum_usd if cum_usd > 0 else None
        # Cumulate bids
        bids = order_book['bids']
        bid_cum_qty = 0.0
        bid_cum_usd = 0.0
        weighted_bid_sum = 0.0
        for entry in bids:
            price = qty = None
            if isinstance(entry, (list, tuple)) and len(entry) == 2:
                price, qty = entry
            elif isinstance(entry, dict):
                price = entry.get('price')
                qty = entry.get('amount', entry.get('qty'))
            if price is None or qty is None:
                logging.debug(f"Skipping malformed bid entry: {entry}")
                continue
            try:
                price = float(price)
                qty = float(qty)
            except Exception:
                logging.debug(f"Skipping bid entry with non-numeric price/qty: {entry}")
                continue
            try:
                price = float(price)
                qty = float(qty)
            except Exception:
                logging.debug(f"Skipping bid entry with non-numeric price/qty: {entry}")
                continue
            if bid_cum_qty + qty > cum_qty:
                qty = cum_qty - bid_cum_qty
            bid_cum_qty += qty
    except Exception as e:
        logging.error(f"Error in log_status: {e}")

        asks = order_book['asks']
    while True:
        try:
            log_status()
        except Exception as e:
            logging.error(f"Error in periodic_logger: {e}")
        time.sleep(10)
        cum_qty = 0.0
        cum_usd = 0.0
        weighted_ask_sum = 0.0
        max_usd = min(usd_balance * 0.9, usd_balance)
        for entry in asks:
            price = qty = None
            if isinstance(entry, (list, tuple)) and len(entry) == 2:
                price, qty = entry
            elif isinstance(entry, dict):
                price = entry.get('price')
                qty = entry.get('amount', entry.get('qty'))
            if price is None or qty is None:
                logging.debug(f"Skipping malformed ask entry: {entry}")
                continue
            try:
                price = float(price)
                qty = float(qty)
            except Exception:
                logging.debug(f"Skipping ask entry with non-numeric price/qty: {entry}")
                continue
            usd_val = price * qty
            if cum_usd + usd_val > max_usd:
                qty = (max_usd - cum_usd) / price
                usd_val = price * qty
            cum_qty += qty
            cum_usd += usd_val
            weighted_ask_sum += price * usd_val
            if cum_usd >= max_usd:
                break
        weighted_ask = weighted_ask_sum / cum_usd if cum_usd > 0 else None
        # Cumulate bids until quantity covers cum_qty
        bids = order_book['bids']
        bid_cum_qty = 0.0
        bid_cum_usd = 0.0
        weighted_bid_sum = 0.0
        for entry in bids:
            price = qty = None
            if isinstance(entry, (list, tuple)) and len(entry) == 2:
                price, qty = entry
            elif isinstance(entry, dict):
                price = entry.get('price')
                qty = entry.get('amount', entry.get('qty'))
            if price is None or qty is None:
                logging.debug(f"Skipping malformed bid entry: {entry}")
                continue
            try:
                price = float(price)
                qty = float(qty)
            except Exception:
                logging.debug(f"Skipping bid entry with non-numeric price/qty: {entry}")
                continue
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

        # --- Price change logic ---
        price_change = 0.0
        global bid_chaser
        if not hasattr(bid_chaser, 'last_distinct_price'):
            bid_chaser.last_distinct_price = None
        if not hasattr(bid_chaser, 'last_nonzero_price_change'):
            bid_chaser.last_nonzero_price_change = 0.0
        if not hasattr(bid_chaser, 'latest_price_change'):
            bid_chaser.latest_price_change = 0.0
        # current_price must be defined; use weighted_ask as a proxy if not defined
        current_price = weighted_ask
        if bid_chaser.last_distinct_price is None:
            bid_chaser.last_distinct_price = current_price
        elif current_price != bid_chaser.last_distinct_price:
            price_change = current_price - bid_chaser.last_distinct_price
            bid_chaser.last_distinct_price = current_price
            if price_change != 0.0:
                bid_chaser.last_nonzero_price_change = price_change
        # Always use the last nonzero price change for buy logic
        bid_chaser.latest_price_change = bid_chaser.last_nonzero_price_change
        # Buy condition: latest price change > 0 and spread < 0.1%
        if bid_chaser.latest_price_change > 0 and spread_pct is not None and spread_pct < 0.1:
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
            except Exception as e:
                logging.error(f"Error placing market buy: {e}")
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
    # Only allow sending between 8:00:00 and 8:00:59
    if not (now.hour == 8 and now.minute == 0):
        return False
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
    # Define send_ntfy_notification as a placeholder if not defined elsewhere
    def send_ntfy_notification(msg):
        pass
    # Load config and set up ccxt Binance.US client
    try:
        with open("config.json") as f:
            config = json.load(f)
        exchange = ccxt.binanceus({
            "apiKey": config["binance_api_key"],
            "secret": config["binance_api_secret"],
            "enableRateLimit": True,
        })
    except Exception as e:
        logging.error(f"Error loading config or setting up exchange: {e}")
        raise

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

    # Start trading and logger threads
    import threading
    trading_thread = threading.Thread(target=log_status, daemon=True)
    logger_thread = threading.Thread(target=periodic_logger, daemon=True)
    trading_thread.start()
    logger_thread.start()
    # Keep main thread alive
    while True:
        time.sleep(60)
