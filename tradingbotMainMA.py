from keys import api, secret
from pybit.unified_trading import HTTP
import pandas as pd
import ta
from time import sleep, time

# Initialize the Bybit API client
session = HTTP(
    demo=True,
    api_key=api,
    api_secret=secret,
)

# Parameters
tp_pct = 0.025   # Take profit percentage = 2.5%
sl_pct = 0.0025  # Stop loss percentage = 0.25%
deviation_threshold = 0.03  # Deviation threshold = 3%
timeframe = '60'  # 1-hour timeframe
moving_avg_period = 90  # 90-period moving average
max_pos = 30  # Maximum number of positions to hold
update_interval = 15 * 60  # 15 minutes in seconds
qty = 500  # Quantity in USDT

def get_balance():
    """Get wallet balance"""
    try:
        resp = session.get_wallet_balance(accountType="UNIFIED", coin="USDC")['result']['list'][0]['coin'][0]['walletBalance']
        return float(resp)
    except Exception as err:
        print(f"Error getting balance: {err}")
        return None

def get_tickers():
    """Get available trading pairs and their volumes"""
    try:
        resp = session.get_tickers(category="linear")['result']['list']
        symbols = [elem for elem in resp if 'USDT' in elem['symbol'] and not 'USDC' in elem['symbol']]
        symbols = sorted(symbols, key=lambda x: float(x['volume24h']), reverse=True)
        return [(elem['symbol'], float(elem['volume24h'])) for elem in symbols]
    except Exception as err:
        print(f"Error getting tickers: {err}")
        return []

def klines(symbol, interval, limit=500):
    """Fetch historical price data"""
    try:
        resp = session.get_kline(category='linear', symbol=symbol, interval=interval, limit=limit)['result']['list']
        df = pd.DataFrame(resp, columns=['Time', 'Open', 'High', 'Low', 'Close', 'Volume', 'Turnover'])
        df['Time'] = pd.to_numeric(df['Time'], errors='coerce')
        df = df.dropna(subset=['Time'])
        if df.empty:
            return df
        df['Time'] = pd.to_datetime(df['Time'], unit='ms')
        df = df.set_index('Time').astype(float)[::-1]
        return df
    except Exception as err:
        print(f"Error fetching historical data for {symbol}: {err}")
        return pd.DataFrame()

def calculate_moving_average(df, period):
    """Calculate moving average"""
    df['SMA'] = ta.trend.sma_indicator(df['Close'], window=period)
    return df

def check_deviation(df):
    """Check if current price deviates more than threshold from moving average"""
    if df.empty or len(df) < moving_avg_period:
        return None
    current_price = df['Close'].iloc[-1]
    moving_avg = df['SMA'].iloc[-1]
    deviation = (current_price - moving_avg) / moving_avg
    return 'sell' if deviation > deviation_threshold else 'buy' if deviation < -deviation_threshold else None

def get_positions():
    """Get current open positions"""
    try:
        resp = session.get_positions(category='linear', settleCoin='USDT')['result']['list']
        return {elem['symbol']: elem for elem in resp}
    except Exception as err:
        print(f"Error getting positions: {err}")
        return {}

def get_pnl():
    """Get profit and loss summary"""
    try:
        resp = session.get_closed_pnl(category="linear", limit=50)['result']['list']
        pnl = sum(float(elem['closedPnl']) for elem in resp)
        print(f"PnL: {pnl}")
    except Exception as err:
        print(f"Error getting PnL: {err}")

def get_precisions(symbol):
    """Get price and quantity precision"""
    try:
        resp = session.get_instruments_info(category='linear', symbol=symbol)['result']['list'][0]
        price_precision = len(resp['priceFilter']['tickSize'].split('.')[1]) if '.' in resp['priceFilter']['tickSize'] else 0
        qty_precision = len(resp['lotSizeFilter']['qtyStep'].split('.')[1]) if '.' in resp['lotSizeFilter']['qtyStep'] else 0
        return price_precision, qty_precision
    except Exception as err:
        print(f"Error getting precisions for {symbol}: {err}")
        return 0, 0

def place_order_market(symbol, side):
    """Place a market order with fixed TP and SL"""
    df = klines(symbol, timeframe)
    if df.empty:
        print(f"No data for {symbol}")
        return
    
    current_price = df['Close'].iloc[-1]
    price_precision, qty_precision = get_precisions(symbol)
    
    if side == 'buy':
        tp_price = round(current_price * (1 + tp_pct), price_precision)
        sl_price = round(current_price * (1 - sl_pct), price_precision)
    elif side == 'sell':
        tp_price = round(current_price * (1 - tp_pct), price_precision)
        sl_price = round(current_price * (1 + sl_pct), price_precision)
    else:
        print("Invalid side provided. Must be 'buy' or 'sell'.")
        return

    order_qty = round(qty / current_price, qty_precision)
       # Get 24-hour volume for the symbol
    tickers = get_tickers()  # Fetch the updated list of tickers
    volume = next((vol for sym, vol in tickers if sym == symbol), None)
    if volume:
        print(f"24-hour volume for {symbol}: {volume} USDT")
        
    try:
        resp = session.place_order(
            category='linear',
            symbol=symbol,
            side=side.capitalize(),
            orderType='Market',
            qty=order_qty,
            takeProfit=tp_price,
            stopLoss=sl_price,
            tpTriggerBy='LastPrice',
            slTriggerBy='LastPrice'
        )
        print(f"Order response: {resp}")
    except Exception as err:
        print(f"Error placing order for {symbol}: {err}")

def close_position(symbol):
    """Close the position for the given symbol"""
    pos = get_positions()
    if symbol in pos:
        side = 'buy' if pos[symbol]['side'] == 'Sell' else 'sell'
        df = klines(symbol, timeframe)
        if df.empty:
            print(f"No data for {symbol}")
            return
        
        current_price = df['Close'].iloc[-1]
        price_precision, qty_precision = get_precisions(symbol)
        order_qty = pos[symbol]['size']
        
        tp_price = round(current_price * (1 + tp_pct) if side == 'buy' else current_price * (1 - tp_pct), price_precision)
        sl_price = round(current_price * (1 - sl_pct) if side == 'buy' else current_price * (1 + sl_pct), price_precision)
        
        try:
            resp = session.place_order(
                category='linear',
                symbol=symbol,
                side=side.capitalize(),
                orderType='Market',
                qty=order_qty,
                takeProfit=tp_price,
                stopLoss=sl_price,
                tpTriggerBy='LastPrice',
                slTriggerBy='LastPrice'
            )
            print(f"Position close response: {resp}")
        except Exception as err:
            print(f"Error closing position for {symbol}: {err}")

def main_trading_logic():
    """Main trading logic"""
    balance = get_balance()
    if balance is None:
        print('Cannot connect to API')
        sleep(300)
        return
    
    tickers = get_tickers()
    symbols = [sym for sym, _ in tickers]
    pos = get_positions()
    
    # Print current positions and their 24-hour volume
    position_info = [(symbol, next((vol for sym, vol in tickers if sym == symbol), 'N/A')) for symbol in pos.keys()]
    for symbol, volume in position_info:
        print(f'{symbol}: 24h Volume = {volume} USDT')
    
    if len(pos) < max_pos:
        available_positions = max_pos - len(pos)
        for symbol in symbols[:available_positions]:
            df = klines(symbol, timeframe)
            if not df.empty:
                df = calculate_moving_average(df, moving_avg_period)
                signal = check_deviation(df)
                
                if signal:
                    if symbol in pos:
                        print(f'Already have a position in {symbol}. Skipping.')
                        continue
                    
                    print(f"Signal detected for {symbol}: {signal}")
                    place_order_market(symbol, signal)
                    sleep(5)
    
    pos = get_positions()
    for symbol in pos:
        df = klines(symbol, timeframe)
        if not df.empty:
            df = calculate_moving_average(df, moving_avg_period)
            current_price = df['Close'].iloc[-1]
            moving_avg = df['SMA'].iloc[-1]
            
            if signal := check_deviation(df):
                if signal == 'sell' and current_price <= moving_avg:
                    close_position(symbol)
                    print(f"Position closed for {symbol} as price reached moving average")
    
    get_pnl()

# Main loop
last_update_time = time()
while True:
    main_trading_logic()
    current_time = time()
    if current_time - last_update_time >= update_interval:
        last_update_time = current_time
    sleep(30)
