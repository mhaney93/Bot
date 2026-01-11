import logging
import datetime
import json
import ccxt
import os
import time
import pickle
import traceback
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler("bot.log"),
        logging.StreamHandler()
    ]
)

positions = []

def log_status():
    while True:
        try:
            now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            try:
                order_book = exchange.fetch_order_book(symbol)
            except Exception as e:
                logging.error(f"Error fetching order book in log_status: {e}")
                time.sleep(10)
                continue
            # Get USD balance
            try:
                balances = exchange.fetch_balance()
                usd_balance = balances['total'].get('USD', 0)
                if usd_balance == 0:
                    usd_balance = balances['total'].get('USD4', 0)
            except Exception as e:
                logging.error(f"Error fetching account info in log_status: {e}")
                usd_balance = 0

            # ...existing code for asks and bids processing...
            asks = order_book['asks']
            cum_qty = 0.0
            cum_usd = 0.0
            weighted_ask_sum = 0.0
            for entry in asks:
                try:
                    price = qty = None
                    if isinstance(entry, (list, tuple)) and len(entry) == 2:
                        price, qty = entry
                    elif isinstance(entry, dict):
                        # Try common keys
                        price = entry.get('price')
                        qty = entry.get('amount', entry.get('qty'))
                    if price is None or qty is None:
                        continue
                    try:
                        price = float(price)
                        qty = float(qty)
                    except Exception:
                        continue
                    usd_val = price * qty
                    cum_qty += qty
                    cum_usd += usd_val
                    weighted_ask_sum += price * usd_val
                    try:
                        if cum_usd >= 50:
                            break
                    except Exception:
                        continue
                except Exception:
                    continue
            weighted_ask = weighted_ask_sum / cum_usd if cum_usd > 0 else None
            # Cumulate bids
            bids = order_book['bids']
            bid_cum_qty = 0.0
            bid_cum_usd = 0.0
            weighted_bid_sum = 0.0
            for entry in bids:
                try:
                    price = qty = None
                    if isinstance(entry, (list, tuple)) and len(entry) == 2:
                        price, qty = entry
                    elif isinstance(entry, dict):
                        price = entry.get('price')
                        qty = entry.get('amount', entry.get('qty'))
                    if price is None or qty is None:
                        continue
                    try:
                        price = float(price)
                        qty = float(qty)
                    except Exception:
                        continue
                    if not all(isinstance(x, (int, float)) for x in [bid_cum_qty, qty, cum_qty]):
                        continue
                    try:
                        if bid_cum_qty + qty > cum_qty:
                            qty = cum_qty - bid_cum_qty
                    except Exception:
                        continue
                    bid_cum_qty += qty
                except Exception:
                    continue

            # Calculate spread and price change
            top_ask = asks[0][0] if asks else None
            top_bid = bids[0][0] if bids else None
            spread = ((top_ask - top_bid) / top_ask * 100) if (top_ask and top_bid) else None

            # Track last price for price change
            if not hasattr(log_status, 'last_price'):
                log_status.last_price = top_bid if top_bid else 0
            price_change = ((top_bid - log_status.last_price) / log_status.last_price * 100) if (top_bid and log_status.last_price) else 0
            log_status.last_price = top_bid if top_bid else log_status.last_price

            # Format positions
            pos_str = 'None'
            if positions:
                pos_str = ', '.join([f"{p['side']} {p['amount']} @ {p['price']}" for p in positions])

            # Format log line
            log_line = f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S}: ${usd_balance:,.2f}, bid: {top_bid if top_bid else 'N/A'}, ask: {top_ask if top_ask else 'N/A'}, Spread: {spread:.2f}% price change: {price_change:+.2f} | Positions: {pos_str}"
            logging.info(log_line)
        except Exception as e:
            logging.error(f"Error in log_status: {e}")
            traceback.print_exc()
        time.sleep(10)
def get_24h_stats_file():
    return os.path.join(os.path.dirname(__file__), 'pl_24h.pkl')
    # Remove events older than 24h
    stats = [(t, pl) for t, pl in stats if now - t <= 86400]
    # Save
    with open(stats_file, 'wb') as f:
        pickle.dump(stats, f)
    return stats

def get_24h_pl():
    stats_file = get_24h_stats_file()  # Ensure stats_file is defined correctly
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
    trading_thread.start()
    # Keep main thread alive and print heartbeat
    while True:
        print("[Main] Bot heartbeat - still running...")
        time.sleep(60)
