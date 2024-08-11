from keys import api, secret
from pybit.unified_trading import HTTP
import pandas as pd
import ta
from time import sleep

session = HTTP(
    demo=True,
    api_key=api,
    api_secret=secret,
)

tp = 0.02  # Take profit = 2%
sl = 0.01  # Stop loss = 1%
timeframe = 15  # 15m
mode = 1  # 1 = isolated, 2 = cross margin mode
leverage = 10 
qty = 500  # = 50 usdt wallet balance (qty/lev)

def get_balance():
    try:
        resp = session.get_wallet_balance(accountType="UNIFIED", coin="USDC")['result']['list'][0]['coin'][0]['walletBalance']
        return float(resp)
    except Exception as err:
        print(f"Error: {err}")
        return None

balance = get_balance()
print(f'Balance: {balance}')

def get_tickers():
    try:
        resp = session.get_tickers(category="linear")['result']['list']
        symbols = [elem['symbol'] for elem in resp if 'USDT' in elem['symbol'] and not 'USDC' in elem['symbol']]
        return symbols
    except Exception as err:
        print(err)
        return []

def klines(symbol):
    try:
        resp = session.get_kline(
            category='linear',
            symbol=symbol,
            interval=timeframe,
            limit=500
        )['result']['list']
        df = pd.DataFrame(resp, columns=['Time', 'Open', 'High', 'Low', 'Close', 'Volume', 'Turnover'])
        df = df.set_index('Time').astype(float)[::-1]
        return df
    except Exception as err:
        print(err)
        return pd.DataFrame()

def get_positions():
    try:
        resp = session.get_positions(category='linear', settleCoin='USDT')['result']['list']
        return [elem['symbol'] for elem in resp]
    except Exception as err:
        print(err)
        return []

def get_pnl():
    try:
        resp = session.get_closed_pnl(category="linear", limit=50)['result']['list']
        print(f" pnl: {sum(float(elem['closedPnl']) for elem in resp)}")
    except Exception as err:
        print(err)
        return 0


def get_precisions(symbol):
    try:
        resp = session.get_instruments_info(category='linear', symbol=symbol)['result']['list'][0]
        price_precision = len(resp['priceFilter']['tickSize'].split('.')[1]) if '.' in resp['priceFilter']['tickSize'] else 0
        qty_precision = len(resp['lotSizeFilter']['qtyStep'].split('.')[1]) if '.' in resp['lotSizeFilter']['qtyStep'] else 0
        return price_precision, qty_precision
    except Exception as err:
        print(err)
        return 0, 0

def place_order_market(symbol, side):
    price_precision, qty_precision = get_precisions(symbol)
    mark_price = float(session.get_tickers(category='linear', symbol=symbol)['result']['list'][0]['markPrice'])
    print(f'Placing {side} order for {symbol}. Mark price: {mark_price}')
    order_qty = round(qty / mark_price, qty_precision)
    
    tp_price = round(mark_price * (1 + tp) if side == 'buy' else mark_price * (1 - tp), price_precision)
    sl_price = round(mark_price * (1 - sl) if side == 'buy' else mark_price * (1 + sl), price_precision)
    
    try:
        resp = session.place_order(
            category='linear',
            symbol=symbol,
            side=side.capitalize(),
            orderType='Market',
            qty=order_qty,
            takeProfit=tp_price,
            stopLoss=sl_price,
            tpTriggerBy='LastPrice',  # Adjusted to 'LastPrice'
            slTriggerBy='LastPrice'   # Adjusted to 'LastPrice'
        )
        print(resp)
    except Exception as err:
        print(err)

def rsi_signal(symbol):
    kl = klines(symbol)
    ema = ta.trend.ema_indicator(kl.Close, window=200)
    rsi = ta.momentum.RSIIndicator(kl.Close).rsi()
    if rsi.iloc[-3] < 30 and rsi.iloc[-2] < 30 and rsi.iloc[-1] > 30:
        return 'up'
    if rsi.iloc[-3] > 70 and rsi.iloc[-2] > 70 and rsi.iloc[-1] < 70:
        return 'down'
    return 'none'

max_pos = 20    # Max current orders
symbols = get_tickers()     # getting all symbols from the Bybit Derivatives

while True:
    balance = get_balance()  # Get the current wallet balance
    if balance is None:  # If balance is None, there's an issue connecting to the API
        print('Cannot connect to API')
    else:
        print(f'Balance: {balance}')  # Print the balance
        pos = get_positions()  # Get the current open positions
        print(f'You have {len(pos)} positions: {pos}')  # Print the number of open positions

        # Loop through symbols only if the number of positions is less than max_pos
        if len(pos) < max_pos:
            for elem in symbols:
                pos = get_positions()  # Re-check the number of open positions
                if len(pos) >= max_pos:  # If max positions reached, stop opening new positions
                    print(f'Maximum positions reached: {len(pos)}')
                    break  # Exit the loop to prevent opening more positions

                signal = rsi_signal(elem)  # Get trading signal for the symbol
                if signal == 'up':
                    print(f'Found BUY signal for {elem}')
                    sleep(2)
                    place_order_market(elem, 'buy')
                    sleep(5)
                elif signal == 'down':
                    print(f'Found SELL signal for {elem}')
                    sleep(2)
                    place_order_market(elem, 'sell')
                    sleep(5)

        get_pnl()  # Print the profit and loss (PnL) summary
    print('Waiting 2 mins')
    sleep(120)  # Pause for 2 minutes before the next iteration