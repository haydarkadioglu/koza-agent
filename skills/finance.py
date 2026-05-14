"""Finance skill — crypto prices, stock prices (no API key needed for basics)."""
import urllib.request
import json

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "crypto_price",
            "description": "Get current cryptocurrency price(s) using CoinGecko API (no key required).",
            "parameters": {
                "type": "object",
                "properties": {
                    "coins": {"type": "string", "description": "Comma-separated coin ids, e.g. 'bitcoin,ethereum,solana'"},
                    "currency": {"type": "string", "default": "usd"},
                },
                "required": ["coins"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stock_price",
            "description": "Get current stock price using Yahoo Finance (no key required).",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbol": {"type": "string", "description": "Stock ticker, e.g. AAPL, TSLA, MSFT"},
                },
                "required": ["symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "crypto_top",
            "description": "Get top N cryptocurrencies by market cap.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 10},
                    "currency": {"type": "string", "default": "usd"},
                },
                "required": [],
            },
        },
    },
]


def _fetch(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "KozaAgent/1.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def crypto_price(coins: str, currency: str = "usd") -> str:
    try:
        ids = coins.replace(" ", "").lower()
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies={currency}&include_24hr_change=true"
        data = _fetch(url)
        lines = []
        for coin, info in data.items():
            price = info.get(currency, "N/A")
            change = info.get(f"{currency}_24h_change", 0)
            arrow = "▲" if change >= 0 else "▼"
            lines.append(f"{coin.upper():15} {currency.upper()} {price:>12,.4f}  {arrow} {abs(change):.2f}%")
        return "\n".join(lines) if lines else "No data found."
    except Exception as e:
        return f"ERROR: {e}"


def stock_price(symbol: str) -> str:
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol.upper())
        info = ticker.fast_info
        price = info.last_price
        prev = info.previous_close
        change = ((price - prev) / prev * 100) if prev else 0
        arrow = "▲" if change >= 0 else "▼"
        return f"{symbol.upper()}: ${price:.2f}  {arrow} {abs(change):.2f}% (prev close: ${prev:.2f})"
    except ImportError:
        # Fallback: Yahoo Finance JSON API
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol.upper()}?range=1d&interval=1m"
            data = _fetch(url)
            meta = data["chart"]["result"][0]["meta"]
            price = meta.get("regularMarketPrice", "N/A")
            prev = meta.get("previousClose", "N/A")
            return f"{symbol.upper()}: ${price}  (prev close: ${prev})"
        except Exception as e2:
            return f"ERROR: {e2}"
    except Exception as e:
        return f"ERROR: {e}"


def crypto_top(limit: int = 10, currency: str = "usd") -> str:
    try:
        url = f"https://api.coingecko.com/api/v3/coins/markets?vs_currency={currency}&order=market_cap_desc&per_page={limit}&page=1"
        data = _fetch(url)
        lines = [f"{'#':>3}  {'COIN':<15} {'PRICE':>12}  {'24H':>8}  MARKET CAP"]
        for i, coin in enumerate(data, 1):
            price = coin.get("current_price", 0)
            change = coin.get("price_change_percentage_24h", 0) or 0
            mcap = coin.get("market_cap", 0)
            arrow = "▲" if change >= 0 else "▼"
            lines.append(f"{i:>3}  {coin['symbol'].upper():<15} ${price:>11,.4f}  {arrow}{abs(change):>6.2f}%  ${mcap:,.0f}")
        return "\n".join(lines)
    except Exception as e:
        return f"ERROR: {e}"


HANDLERS = {"crypto_price": crypto_price, "stock_price": stock_price, "crypto_top": crypto_top}
