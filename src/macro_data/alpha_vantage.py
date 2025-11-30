"""Alpha Vantage API クライアント.

米国株式・市場データを取得する。
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class StockQuote:
    """株式クォート.

    Attributes:
        symbol: シンボル
        price: 現在価格
        change: 変動額
        change_percent: 変動率
        volume: 取引量
        timestamp: タイムスタンプ
    """

    symbol: str
    price: float
    change: float
    change_percent: float
    volume: int
    timestamp: datetime

    def to_dict(self) -> dict[str, Any]:
        """辞書形式に変換."""
        return {
            "symbol": self.symbol,
            "price": self.price,
            "change": self.change,
            "change_percent": self.change_percent,
            "volume": self.volume,
            "timestamp": self.timestamp.isoformat(),
        }


class AlphaVantageClient:
    """Alpha Vantage API クライアント.

    米国株式・市場データを取得する。
    """

    BASE_URL = "https://www.alphavantage.co/query"

    def __init__(self, api_key: str | None = None) -> None:
        """初期化.

        Args:
            api_key: Alpha Vantage API Key
        """
        self._api_key = api_key or settings.ALPHA_VANTAGE_API_KEY
        self._is_configured = bool(
            self._api_key and "your_" not in self._api_key.lower()
        )

        if not self._is_configured:
            logger.warning(
                "Alpha Vantage API key not configured. "
                "Stock data features will be limited."
            )
        else:
            logger.info("Alpha Vantage client initialized")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def get_quote(self, symbol: str) -> StockQuote | None:
        """株式のクォートを取得.

        Args:
            symbol: 株式シンボル (e.g., "SPY", "QQQ")

        Returns:
            株式クォート
        """
        if not self._is_configured:
            logger.warning("Alpha Vantage API key not configured")
            return None

        try:
            with httpx.Client(timeout=30) as client:
                response = client.get(
                    self.BASE_URL,
                    params={
                        "function": "GLOBAL_QUOTE",
                        "symbol": symbol,
                        "apikey": self._api_key,
                    },
                )
                response.raise_for_status()
                data = response.json()

            quote_data = data.get("Global Quote", {})
            if not quote_data:
                logger.warning(f"No quote data for {symbol}")
                return None

            return StockQuote(
                symbol=symbol,
                price=float(quote_data.get("05. price", 0)),
                change=float(quote_data.get("09. change", 0)),
                change_percent=float(
                    quote_data.get("10. change percent", "0%").rstrip("%")
                ),
                volume=int(quote_data.get("06. volume", 0)),
                timestamp=datetime.now(),
            )

        except httpx.HTTPStatusError as e:
            logger.error(f"Alpha Vantage API error for {symbol}: {e.response.status_code}")
            return None
        except Exception as e:
            logger.error(f"Failed to fetch quote for {symbol}: {e}")
            return None

    def get_sp500(self) -> StockQuote | None:
        """S&P 500 ETF (SPY) のクォートを取得.

        Returns:
            株式クォート
        """
        return self.get_quote("SPY")

    def get_nasdaq(self) -> StockQuote | None:
        """NASDAQ ETF (QQQ) のクォートを取得.

        Returns:
            株式クォート
        """
        return self.get_quote("QQQ")

    def get_gold(self) -> StockQuote | None:
        """金ETF (GLD) のクォートを取得.

        Returns:
            株式クォート
        """
        return self.get_quote("GLD")

    def get_market_summary(self) -> str:
        """市場サマリーを生成.

        Returns:
            市場サマリー文字列
        """
        parts = ["【Alpha Vantage 米国市場】", ""]

        # S&P 500
        spy = self.get_sp500()
        if spy:
            emoji = "📈" if spy.change >= 0 else "📉"
            parts.append(f"S&P 500 (SPY): ${spy.price:.2f} {emoji} {spy.change_percent:+.2f}%")

        # NASDAQ
        qqq = self.get_nasdaq()
        if qqq:
            emoji = "📈" if qqq.change >= 0 else "📉"
            parts.append(f"NASDAQ (QQQ): ${qqq.price:.2f} {emoji} {qqq.change_percent:+.2f}%")

        # Gold
        gld = self.get_gold()
        if gld:
            emoji = "📈" if gld.change >= 0 else "📉"
            parts.append(f"Gold (GLD): ${gld.price:.2f} {emoji} {gld.change_percent:+.2f}%")

        if len(parts) == 2:
            return "Alpha Vantage市場データを取得できませんでした。"

        # 市場の傾向を分析
        parts.append("")
        if spy and qqq:
            if spy.change_percent > 1 and qqq.change_percent > 1:
                parts.append("📊 米国市場は上昇傾向（リスクオン）")
            elif spy.change_percent < -1 and qqq.change_percent < -1:
                parts.append("📊 米国市場は下落傾向（リスクオフ）")
            else:
                parts.append("📊 米国市場は横ばい")

        return "\n".join(parts)
