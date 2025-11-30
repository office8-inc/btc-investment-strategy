"""CoinGecko API クライアント.

仮想通貨の市場データとトレンドを取得する。
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
class MarketData:
    """市場データ.

    Attributes:
        price_usd: USD価格
        market_cap: 時価総額
        volume_24h: 24時間取引量
        price_change_24h: 24時間価格変動率
        price_change_7d: 7日間価格変動率
        price_change_30d: 30日間価格変動率
        ath: 過去最高値
        ath_date: 過去最高値日時
        atl: 過去最安値
        atl_date: 過去最安値日時
    """

    price_usd: float
    market_cap: float
    volume_24h: float
    price_change_24h: float
    price_change_7d: float
    price_change_30d: float
    ath: float
    ath_date: datetime | None
    atl: float
    atl_date: datetime | None

    def to_dict(self) -> dict[str, Any]:
        """辞書形式に変換."""
        return {
            "price_usd": self.price_usd,
            "market_cap": self.market_cap,
            "volume_24h": self.volume_24h,
            "price_change_24h": self.price_change_24h,
            "price_change_7d": self.price_change_7d,
            "price_change_30d": self.price_change_30d,
            "ath": self.ath,
            "ath_date": self.ath_date.isoformat() if self.ath_date else None,
            "atl": self.atl,
            "atl_date": self.atl_date.isoformat() if self.atl_date else None,
        }


@dataclass
class TrendingCoin:
    """トレンドコイン.

    Attributes:
        id: コインID
        name: コイン名
        symbol: シンボル
        market_cap_rank: 時価総額ランク
        score: トレンドスコア
    """

    id: str
    name: str
    symbol: str
    market_cap_rank: int | None
    score: int

    def to_dict(self) -> dict[str, Any]:
        """辞書形式に変換."""
        return {
            "id": self.id,
            "name": self.name,
            "symbol": self.symbol,
            "market_cap_rank": self.market_cap_rank,
            "score": self.score,
        }


class CoinGeckoClient:
    """CoinGecko API クライアント.

    仮想通貨の市場データとトレンドを取得する（認証不要）。
    """

    def __init__(self, base_url: str | None = None) -> None:
        """初期化.

        Args:
            base_url: API Base URL
        """
        self._base_url = base_url or settings.COINGECKO_API_URL
        logger.info("CoinGecko client initialized")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def get_bitcoin_market_data(self) -> MarketData | None:
        """ビットコインの市場データを取得.

        Returns:
            市場データ（取得失敗時はNone）
        """
        try:
            with httpx.Client(timeout=30) as client:
                response = client.get(
                    f"{self._base_url}/coins/bitcoin",
                    params={
                        "localization": "false",
                        "tickers": "false",
                        "market_data": "true",
                        "community_data": "false",
                        "developer_data": "false",
                    },
                )
                response.raise_for_status()
                data = response.json()

            market_data = data.get("market_data", {})

            # ATH/ATL日時のパース
            ath_date = None
            atl_date = None
            if market_data.get("ath_date", {}).get("usd"):
                try:
                    ath_date = datetime.fromisoformat(
                        market_data["ath_date"]["usd"].replace("Z", "+00:00")
                    )
                except (ValueError, TypeError):
                    pass
            if market_data.get("atl_date", {}).get("usd"):
                try:
                    atl_date = datetime.fromisoformat(
                        market_data["atl_date"]["usd"].replace("Z", "+00:00")
                    )
                except (ValueError, TypeError):
                    pass

            result = MarketData(
                price_usd=market_data.get("current_price", {}).get("usd", 0),
                market_cap=market_data.get("market_cap", {}).get("usd", 0),
                volume_24h=market_data.get("total_volume", {}).get("usd", 0),
                price_change_24h=market_data.get("price_change_percentage_24h", 0),
                price_change_7d=market_data.get("price_change_percentage_7d", 0),
                price_change_30d=market_data.get("price_change_percentage_30d", 0),
                ath=market_data.get("ath", {}).get("usd", 0),
                ath_date=ath_date,
                atl=market_data.get("atl", {}).get("usd", 0),
                atl_date=atl_date,
            )

            logger.info(f"Fetched BTC market data: ${result.price_usd:,.2f}")
            return result

        except httpx.HTTPStatusError as e:
            logger.error(f"CoinGecko API error: {e.response.status_code}")
            return None
        except Exception as e:
            logger.error(f"Failed to fetch CoinGecko market data: {e}")
            return None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def get_trending(self) -> list[TrendingCoin]:
        """トレンドコインを取得.

        Returns:
            トレンドコインリスト
        """
        try:
            with httpx.Client(timeout=30) as client:
                response = client.get(f"{self._base_url}/search/trending")
                response.raise_for_status()
                data = response.json()

            trending = []
            for item in data.get("coins", []):
                coin = item.get("item", {})
                trending.append(
                    TrendingCoin(
                        id=coin.get("id", ""),
                        name=coin.get("name", ""),
                        symbol=coin.get("symbol", ""),
                        market_cap_rank=coin.get("market_cap_rank"),
                        score=coin.get("score", 0),
                    )
                )

            logger.info(f"Fetched {len(trending)} trending coins")
            return trending

        except httpx.HTTPStatusError as e:
            logger.error(f"CoinGecko trending API error: {e.response.status_code}")
            return []
        except Exception as e:
            logger.error(f"Failed to fetch trending coins: {e}")
            return []

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def get_global_market_data(self) -> dict[str, Any]:
        """グローバル市場データを取得.

        Returns:
            グローバル市場データ
        """
        try:
            with httpx.Client(timeout=30) as client:
                response = client.get(f"{self._base_url}/global")
                response.raise_for_status()
                data = response.json()

            global_data = data.get("data", {})

            result = {
                "total_market_cap_usd": global_data.get("total_market_cap", {}).get(
                    "usd", 0
                ),
                "total_volume_24h_usd": global_data.get("total_volume", {}).get(
                    "usd", 0
                ),
                "btc_dominance": global_data.get("market_cap_percentage", {}).get(
                    "btc", 0
                ),
                "eth_dominance": global_data.get("market_cap_percentage", {}).get(
                    "eth", 0
                ),
                "active_cryptocurrencies": global_data.get(
                    "active_cryptocurrencies", 0
                ),
                "market_cap_change_24h": global_data.get(
                    "market_cap_change_percentage_24h_usd", 0
                ),
            }

            logger.info(f"Fetched global market data: BTC dominance {result['btc_dominance']:.1f}%")
            return result

        except httpx.HTTPStatusError as e:
            logger.error(f"CoinGecko global API error: {e.response.status_code}")
            return {}
        except Exception as e:
            logger.error(f"Failed to fetch global market data: {e}")
            return {}

    def get_market_summary(self) -> str:
        """市場サマリーを生成.

        Returns:
            市場サマリー文字列
        """
        btc_data = self.get_bitcoin_market_data()
        global_data = self.get_global_market_data()
        trending = self.get_trending()

        parts = ["【CoinGecko 市場サマリー】", ""]

        if btc_data:
            parts.append(f"BTC価格: ${btc_data.price_usd:,.2f}")
            parts.append(f"  24h変動: {btc_data.price_change_24h:+.2f}%")
            parts.append(f"  7d変動: {btc_data.price_change_7d:+.2f}%")
            parts.append(f"  30d変動: {btc_data.price_change_30d:+.2f}%")
            parts.append(f"  ATH: ${btc_data.ath:,.2f} (ATHからの乖離: {((btc_data.price_usd / btc_data.ath) - 1) * 100:.1f}%)")
            parts.append("")

        if global_data:
            parts.append(f"仮想通貨市場全体:")
            parts.append(f"  時価総額: ${global_data.get('total_market_cap_usd', 0) / 1e12:.2f}兆ドル")
            parts.append(f"  BTCドミナンス: {global_data.get('btc_dominance', 0):.1f}%")
            parts.append(f"  24h市場変動: {global_data.get('market_cap_change_24h', 0):+.2f}%")
            parts.append("")

        if trending:
            parts.append("トレンドコイン:")
            for coin in trending[:5]:
                parts.append(f"  - {coin.name} ({coin.symbol.upper()})")

        return "\n".join(parts)
