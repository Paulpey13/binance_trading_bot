from binance.client import Client
from binance.exceptions import BinanceAPIException
import time
import logging
import numpy as np
import pandas as pd
from threading import Thread

# Binance API keys (replace with your keys or environment variables for security)
API_KEY = ''
API_SECRET = ''

# Initialize Binance Client
client = Client(API_KEY, API_SECRET)

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s', handlers=[
    logging.StreamHandler(),
    logging.FileHandler('trading_bot.log', mode='a')
])

# List of selected cryptos
cryptos = [
    'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'XRPUSDT', 'ADAUSDT', 'SOLUSDT',
    'DOGEUSDT', 'DOTUSDT', 'AVAXUSDT', 'LTCUSDT', 'LINKUSDT'
]


# '1m': 1-minute candles
# '5m': 5-minute candles
# '15m': 15-minute candles
# '1h': 1-hour candles
# '1d': 1-day candles

def get_top_loss_crypto(cryptos, timeframe='1h'):
    """
    Get the crypto with the largest negative price change over the specified timeframe.
    """
    best_loss = None
    best_crypto = None

    for crypto in cryptos:
        try:
            # Fetch the historical candlestick data for the desired timeframe
            ohlcv = client.get_klines(symbol=crypto, interval=timeframe, limit=2)  # Get the last 2 candles
            opening_price = float(ohlcv[0][1])  # Opening price of the most recent candle
            closing_price = float(ohlcv[1][4])  # Closing price of the previous candle

            # Calculate the price change
            price_change_percent = ((closing_price - opening_price) / opening_price) * 100

            if best_loss is None or price_change_percent < best_loss:
                best_loss = price_change_percent
                best_crypto = crypto
        except BinanceAPIException as e:
            logging.error(f"Error fetching candlestick data for {crypto}: {e}")

    logging.info(f"Crypto with the largest loss in the last {timeframe}: {best_crypto} ({best_loss}% change)")
    return best_crypto


def kelly_criterion(win_prob, win_loss_ratio):
    """
    Calculate the optimal bet size using the Kelly Criterion.
    :param win_prob: Probability of winning
    :param win_loss_ratio: Ratio of average win to average loss
    :return: Fraction of portfolio to bet
    """
    kelly_fraction = win_prob - (1 - win_prob) / win_loss_ratio
    return kelly_fraction

def invest_using_kelly(crypto, usdt_balance, win_prob=0.6, win_loss_ratio=2):
    """
    Invest using the Kelly Criterion
    """
    kelly_fraction = kelly_criterion(win_prob, win_loss_ratio)
    amount_to_invest = usdt_balance * kelly_fraction
    return invest_in_crypto(crypto, amount_to_invest)

def invest_in_crypto(crypto, amount_to_invest):
    """
    Invest a specific amount in the chosen crypto.
    """
    current_price = float(client.get_symbol_ticker(symbol=crypto)['price'])
    amount_to_buy = amount_to_invest / current_price

    # Fetch trading rules for the symbol
    exchange_info = client.get_exchange_info()
    symbol_info = next(item for item in exchange_info['symbols'] if item['symbol'] == crypto)

    # Extract LOT_SIZE and PRECISION filters
    lot_size_filter = next(filter for filter in symbol_info['filters'] if filter['filterType'] == 'LOT_SIZE')
    precision_filter = next(filter for filter in symbol_info['filters'] if filter['filterType'] == 'PRICE_FILTER')

    # Extract LOT_SIZE parameters
    min_qty = float(lot_size_filter['minQty'])
    step_size = float(lot_size_filter['stepSize'])

    # Adjust the quantity to comply with the LOT_SIZE filter
    amount_to_buy = max(min_qty, (amount_to_buy // step_size) * step_size)

    # Round the amount_to_buy to match the precision required
    quantity_precision = int(lot_size_filter['stepSize'].find('1') - 1)
    amount_to_buy = round(amount_to_buy, quantity_precision)

    try:
        order = client.order_market_buy(
            symbol=crypto,
            quantity=amount_to_buy
        )
        logging.info(f"Bought {amount_to_buy} {crypto} for {amount_to_invest} USDT at {current_price} USDT each.")
        return order, current_price
    except BinanceAPIException as e:
        logging.error(f"Error executing buy order for {crypto}: {e}")
        return None, None

def wait_for_pump(crypto, buy_price, target_gain=1.005):
    """
    Wait for the price of the crypto to increase by a target percentage.
    """
    while True:
        try:
            current_price = float(client.get_symbol_ticker(symbol=crypto)['price'])
            if current_price >= buy_price * target_gain:
                return current_price
            time.sleep(1)
        except BinanceAPIException as e:
            logging.error(f"Error fetching price for {crypto}: {e}")
            time.sleep(1)

def sell_crypto(crypto, amount):
    """
    Sell the crypto back to USDT.
    """
    try:
        order = client.order_market_sell(
            symbol=crypto,
            quantity=round(amount, 6)
        )
        sell_price = float(order['fills'][0]['price'])
        logging.info(f"Sold {round(amount, 6)} {crypto} at {sell_price} USDT each.")
        return order
    except BinanceAPIException as e:
        logging.error(f"Error executing sell order for {crypto}: {e}")
        return None

def run_trading_bot():
    """
    Run the trading bot in an infinite loop, ensuring only one trade at a time.
    """
    active_trade = None  # Track the current active trade

    while True:
        try:
            if active_trade:
                crypto, buy_price, amount_bought = active_trade
                target_price = wait_for_pump(crypto, buy_price)

                # Attempt to sell the crypto
                sell_order = sell_crypto(crypto, amount_bought)
                if sell_order:
                    logging.info(f"Trade completed for {crypto}. Profit achieved.")
                    active_trade = None  # Clear the active trade after completion
                else:
                    logging.error(f"Failed to sell {crypto}. Holding the position for retry.")
                time.sleep(1)
                
            else:
                usdt_balance = float(client.get_asset_balance(asset='USDT')['free'])
                if usdt_balance < 10:
                    logging.warning("Insufficient USDT balance to trade. Waiting...")
                    time.sleep(1)
                    continue

                top_loss_crypto = get_top_loss_crypto(cryptos)
                order, buy_price = invest_using_kelly(top_loss_crypto, usdt_balance)

                if order is None:
                    continue

                amount_bought = float(order['fills'][0]['qty'])
                active_trade = (top_loss_crypto, buy_price, amount_bought)
                logging.info(f"Active trade started: {active_trade}")

        except Exception as e:
            logging.error(f"An unexpected error occurred: {e}")
            time.sleep(1)

        time.sleep(1)

if __name__ == "__main__":
    run_trading_bot()
