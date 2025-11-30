"""Polygon.io API クライアント.

金融市場データを取得する。
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
class MarketStatus:
    """市場ステータス.

    Attributes:
        market: 市場名
        is_open: 開場中かどうか
        early_close: 早期終了日かどうか
        next_open: 次の開場時刻
        next_close: 次の閉場時刻
    """

    market: str
    is_open: bool
    early_close: bool
    next_open: datetime | None
    next_close: datetime | None

    def to_dict(self) -> dict[str, Any]:
        """辞書形式に変換."""
        return {
            "market": self.market,
            "is_open": self.is_open,
            "early_close": self.early_close,
            "next_open": self.next_open.isoformat() if self.next_open else None,
            "next_close": self.next_close.isoformat() if self.next_close else None,
        }


@dataclass
class TickerDetail:
    """ティッカー詳細.

    Attributes:
        ticker: ティッカーシンボル
        name: 銘柄名
        market_cap: 時価総額
        primary_exchange: 主要取引所
        type: タイプ
    """

    ticker: str
    name: str
    market_cap: float | None
    primary_exchange: str
    type: str

    def to_dict(self) -> dict[str, Any]:
        """辞書形式に変換."""
        return {
            "ticker": self.ticker,
            "name": self.name,
            "market_cap": self.market_cap,
            "primary_exchange": self.primary_exchange,
            "type": self.type,
        }


class PolygonClient:
    """Polygon.io API クライアント.

    金融市場データを取得する。
    無料tierは5 API呼び出し/分の制限あり。
    """

    BASE_URL = "https://api.polygon.io"

    def __init__(self, api_key: str | None = None) -> None:
        """初期化.

        Args:
            api_key: Polygon.io API Key
        """
        self._api_key = api_key or settings.POLYGON_API_KEY
        self._is_configured = bool(
            self._api_key and "your_" not in self._api_key.lower()
        )

        if not self._is_configured:
            logger.warning(
                "Polygon.io API key not configured. "
                "Market data features will be limited."
            )
        else:
            logger.info("Polygon.io client initialized")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def get_market_status(self) -> MarketStatus | None:
        """市場ステータスを取得.

        Returns:
            市場ステータス
        """
        if not self._is_configured:
            logger.warning("Polygon.io API key not configured")
            return None

        try:
            with httpx.Client(timeout=30) as client:
                response = client.get(
                    f"{self.BASE_URL}/v1/marketstatus/now",
                    params={"apiKey": self._api_key},
                )
                response.raise_for_status()
                data = response.json()

            exchanges = data.get("exchanges", {})
            nyse_status = exchanges.get("nyse", "closed")

            return MarketStatus(
                market="NYSE",
                is_open=nyse_status == "open",
                early_close=data.get("early_close", False),
                next_open=None,  # 詳細APIで取得可能
                next_close=None,
            )

        except httpx.HTTPStatusError as e:
            logger.error(f"Polygon.io API error: {e.response.status_code}")
            return None
        except Exception as e:
            logger.error(f"Failed to fetch market status: {e}")
            return None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def get_previous_close(self, ticker: str) -> dict[str, Any] | None:
        """前日終値を取得.

        Args:
            ticker: ティッカーシンボル

        Returns:
            前日終値データ
        """
        if not self._is_configured:
            logger.warning("Polygon.io API key not configured")
            return None

        try:
            with httpx.Client(timeout=30) as client:
                response = client.get(
                    f"{self.BASE_URL}/v2/aggs/ticker/{ticker}/prev",
                    params={"apiKey": self._api_key},
                )
                response.raise_for_status()
                data = response.json()

            results = data.get("results", [])
            if not results:
                return None

            result = results[0]
            return {
                "ticker": ticker,
                "open": result.get("o"),
                "high": result.get("h"),
                "low": result.get("l"),
                "close": result.get("c"),
                "volume": result.get("v"),
                "vwap": result.get("vw"),
            }

        except httpx.HTTPStatusError as e:
            logger.error(f"Polygon.io API error for {ticker}: {e.response.status_code}")
            return None
        except Exception as e:
            logger.error(f"Failed to fetch previous close for {ticker}: {e}")
            return None

    def get_crypto_previous_close(self, symbol: str = "BTC") -> dict[str, Any] | None:
        """仮想通貨の前日終値を取得.

        Args:
            symbol: 仮想通貨シンボル

        Returns:
            前日終値データ
        """
        return self.get_previous_close(f"X:{symbol}USD")

    def get_market_summary(self) -> str:
        """市場サマリーを生成.

        Returns:
            市場サマリー文字列
        """
        parts = ["【Polygon.io 市場データ】", ""]

        # 市場ステータス
        status = self.get_market_status()
        if status:
            status_str = "🟢 開場中" if status.is_open else "🔴 閉場中"
            parts.append(f"NYSE: {status_str}")
            if status.early_close:
                parts.append("  ⚠️ 本日は早期終了日です")
            parts.append("")

        # 主要指数の前日終値
        spy = self.get_previous_close("SPY")
        if spy:
            parts.append(f"SPY (前日終値): ${spy['close']:.2f}")
            parts.append(f"  高値: ${spy['high']:.2f} / 安値: ${spy['low']:.2f}")

        vix = self.get_previous_close("VIX")
        if vix:
            vix_val = vix['close']
            emoji = "😱" if vix_val > 30 else "😰" if vix_val > 20 else "😐"
            parts.append(f"VIX: {vix_val:.2f} {emoji}")
            if vix_val > 30:
                parts.append("  ⚠️ 高ボラティリティ（市場の恐怖が高い）")

        if len(parts) == 2:
            return "Polygon.io市場データを取得できませんでした。"

        return "\n".join(parts)
