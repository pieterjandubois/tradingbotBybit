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
tp_pct = 0.02  # Take profit percentage = 2%
sl_pct = 0.025  # Stop loss percentage = 2.5% deviation from moving average
timeframe = '60'  # 1-hour timeframe
moving_avg_period = 90  # 90-day moving average period
deviation_threshold = 0.02  # 2% deviation
mode = 1  # 1 = isolated, 2 = cross margin mode
leverage = 10
qty = 500  # Quantity in USDT
max_pos = 20  # Maximum number of positions to hold
update_interval = 15 * 60  # 15 minutes in seconds

def get_balance():
    """Get wallet balance"""
    try:
        resp = session.get_wallet_balance(accountType="UNIFIED", coin="USDC")['result']['list'][0]['coin'][0]['walletBalance']
        return float(resp)
    except Exception as err:
        print(f"Error getting balance: {err}")
        return None

def get_tickers():
    """Get available trading pairs"""
    try:
        resp = session.get_tickers(category="linear")['result']['list']
        symbols = [elem['symbol'] for elem in resp if 'USDT' in elem['symbol'] and not 'USDC' in elem['symbol']]
        return symbols
    except Exception as err:
        print(f"Error getting tickers: {err}")
        return []

def klines(symbol, interval, limit=500):
    """Fetch historical price data"""
    try:
        resp = session.get_kline(
            category='linear',
            symbol=symbol,
            interval=interval,
            limit=limit
        )['result']['list']
        
        # Convert the response into a DataFrame
        df = pd.DataFrame(resp, columns=['Time', 'Open', 'High', 'Low', 'Close', 'Volume', 'Turnover'])
        
        # Ensure 'Time' is numeric and convert to datetime
        df['Time'] = pd.to_numeric(df['Time'], errors='coerce')
        df = df.dropna(subset=['Time'])
        
        if df['Time'].empty:
            return pd.DataFrame()

        df['Time'] = pd.to_datetime(df['Time'], unit='ms')
        df = df.set_index('Time')
        df = df.astype(float)[::-1]  # Reverse DataFrame
        return df
    except Exception as err:
        print(f"Error fetching historical data for {symbol}: {err}")
        return pd.DataFrame()

def calculate_moving_average(df, period):
    """Calculate moving average"""
    if 'Close' in df.columns:
        df['SMA'] = ta.trend.sma_indicator(df['Close'], window=period)
        return df
    else:
        print("Error: 'Close' column is missing in DataFrame")
        return df

def check_deviation(df):
    """Check if current price deviates more than 2% from moving average"""
    if df.empty or len(df) < moving_avg_period:
        return None
    current_price = df['Close'].iloc[-1]
    moving_avg = df['SMA'].iloc[-1]
    deviation = (current_price - moving_avg) / moving_avg

    if abs(deviation) > deviation_threshold:
        return 'sell' if deviation > 0 else 'buy'
    return None

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
    """Place a market order"""
    df = klines(symbol, timeframe)
    if df.empty:
        print(f"No data for {symbol}")
        return
    
    df = calculate_moving_average(df, moving_avg_period)
    current_price = df['Close'].iloc[-1]
    moving_avg = df['SMA'].iloc[-1]

    price_precision, qty_precision = get_precisions(symbol)
    
    # Calculate dynamic take profit and stop loss
    tp_price = round(current_price * (1 + tp_pct) if side == 'buy' else current_price * (1 - tp_pct), price_precision)
    sl_price = round(current_price * (1 - sl_pct) if side == 'buy' else current_price * (1 + sl_pct), price_precision)
    order_qty = round(qty / current_price, qty_precision)
    
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

def update_tp_sl():
    """Update TP and SL for all positions"""
    pos = get_positions()
    for symbol in pos:
        print(f"Updating TP/SL for position: {symbol}")
        close_position(symbol)

def close_position(symbol):
    """Close the position for the given symbol"""
    try:
        pos = get_positions()
        if symbol in pos:
            side = 'buy' if pos[symbol]['side'] == 'Sell' else 'sell'
            df = klines(symbol, timeframe)
            if df.empty:
                print(f"No data for {symbol}")
                return
            
            df = calculate_moving_average(df, moving_avg_period)
            current_price = df['Close'].iloc[-1]
            moving_avg = df['SMA'].iloc[-1]
            
            price_precision, qty_precision = get_precisions(symbol)
            mark_price = float(session.get_tickers(category='linear', symbol=symbol)['result']['list'][0]['markPrice'])
            order_qty = pos[symbol]['size']
            
            # Calculate dynamic take profit and stop loss
            tp_price = round(current_price * (1 + tp_pct) if side == 'buy' else current_price * (1 - tp_pct), price_precision)
            sl_price = round(current_price * (1 - sl_pct) if side == 'buy' else current_price * (1 + sl_pct), price_precision)
            
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
    balance = get_balance()  # Get the current wallet balance
    if balance is None:  # If balance is None, there's an issue connecting to the API
        print('Cannot connect to API')
        sleep(300)  # Wait 5 minutes before retrying
        return
    
    symbols = get_tickers()  # Get available trading pairs
    pos = get_positions()  # Get the current open positions
    print(f'Balance: {balance}')
    print(f'You have {len(pos)} positions: {pos}')
    
    # Loop through symbols only if the number of positions is less than max_pos
    if len(pos) < max_pos:
        for symbol in symbols:
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
                    sleep(5)  # Wait before placing the next order
    
    # Manage open positions
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
            
    # Get and print PnL summary
    get_pnl()

# Main loop
last_update_time = time()
while True:
    main_trading_logic()
    
    # Update TP/SL every 15 minutes
    current_time = time()
    if current_time - last_update_time >= update_interval:
        update_tp_sl()
        last_update_time = current_time
    
    # Wait before the next iteration
    sleep(30)  # Wait for 30 seconds before the next loop iteration
