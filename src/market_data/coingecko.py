"""CoinGecko API クライアント.

仮想通貨の市場データとトレンドを取得する。
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
import pandas as pd
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

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def get_ohlc_data(self, days: int = 365) -> list[list[float]] | None:
        """ビットコインのOHLCデータを取得.

        CoinGecko OHLC APIを使用してローソク足データを取得する。
        
        注意: CoinGeckoのOHLCは日数によって粒度が変わる
        - 1-2日: 30分足
        - 3-30日: 4時間足
        - 31-90日: 4時間足
        - 91日以上: 日足

        Args:
            days: 取得する日数 (1, 7, 14, 30, 90, 180, 365, max)

        Returns:
            OHLCデータのリスト [[timestamp, open, high, low, close], ...]
            取得失敗時はNone
        """
        try:
            with httpx.Client(timeout=30) as client:
                response = client.get(
                    f"{self._base_url}/coins/bitcoin/ohlc",
                    params={
                        "vs_currency": "usd",
                        "days": str(days),
                    },
                )
                response.raise_for_status()
                data = response.json()

            if not data or not isinstance(data, list):
                logger.warning("CoinGecko OHLC: No data returned")
                return None

            logger.info(f"Fetched {len(data)} OHLC candles from CoinGecko")
            return data

        except httpx.HTTPStatusError as e:
            logger.error(f"CoinGecko OHLC API error: {e.response.status_code}")
            return None
        except Exception as e:
            logger.error(f"Failed to fetch CoinGecko OHLC data: {e}")
            return None

    def get_ohlc_dataframe(self, days: int = 365) -> pd.DataFrame | None:
        """ビットコインのOHLCデータをDataFrame形式で取得.

        テクニカル指標計算に使える形式でOHLCデータを返す。
        
        注意: CoinGeckoのOHLCは日数によって粒度が変わる
        - 1-2日: 30分足
        - 3-30日: 4時間足
        - 31-90日: 4時間足
        - 91日以上: 日足

        Args:
            days: 取得する日数 (1, 7, 14, 30, 90, 180, 365, max)

        Returns:
            OHLCVデータを含むDataFrame (columns: timestamp, open, high, low, close, volume)
            取得失敗時はNone
        """
        ohlc_data = self.get_ohlc_data(days=days)
        if ohlc_data is None:
            return None

        try:
            # CoinGecko OHLC: [[timestamp_ms, open, high, low, close], ...]
            df = pd.DataFrame(
                ohlc_data, columns=["timestamp_ms", "open", "high", "low", "close"]
            )
            
            # タイムスタンプをdatetimeに変換
            df["timestamp"] = pd.to_datetime(df["timestamp_ms"], unit="ms", utc=True)
            df = df.drop(columns=["timestamp_ms"])
            
            # CoinGecko OHLCには出来高がないため、0で埋める
            # 出来高は後でmarket_chartから取得して補完も可能
            df["volume"] = 0.0
            
            # 列の順序を整理
            df = df[["timestamp", "open", "high", "low", "close", "volume"]]
            
            # 時系列順にソート
            df = df.sort_values("timestamp").reset_index(drop=True)
            
            logger.info(f"Created OHLC DataFrame with {len(df)} rows")
            return df

        except Exception as e:
            logger.error(f"Failed to create OHLC DataFrame: {e}")
            return None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def get_market_chart(self, days: int = 365) -> dict[str, Any] | None:
        """ビットコインの詳細価格履歴を取得.

        OHLCよりも詳細なデータ（価格、時価総額、取引量）を取得できる。

        Args:
            days: 取得する日数

        Returns:
            価格履歴データ {'prices': [...], 'market_caps': [...], 'total_volumes': [...]}
            取得失敗時はNone
        """
        try:
            with httpx.Client(timeout=60) as client:
                response = client.get(
                    f"{self._base_url}/coins/bitcoin/market_chart",
                    params={
                        "vs_currency": "usd",
                        "days": str(days),
                        "interval": "daily",
                    },
                )
                response.raise_for_status()
                data = response.json()

            prices_count = len(data.get("prices", []))
            logger.info(f"Fetched {prices_count} price points from CoinGecko market_chart")
            return data

        except httpx.HTTPStatusError as e:
            logger.error(f"CoinGecko market_chart API error: {e.response.status_code}")
            return None
        except Exception as e:
            logger.error(f"Failed to fetch CoinGecko market_chart data: {e}")
            return None

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
            parts.append("仮想通貨市場全体:")
            parts.append(f"  時価総額: ${global_data.get('total_market_cap_usd', 0) / 1e12:.2f}兆ドル")
            parts.append(f"  BTCドミナンス: {global_data.get('btc_dominance', 0):.1f}%")
            parts.append(f"  24h市場変動: {global_data.get('market_cap_change_24h', 0):+.2f}%")
            parts.append("")

        if trending:
            parts.append("トレンドコイン:")
            for coin in trending[:5]:
                parts.append(f"  - {coin.name} ({coin.symbol.upper()})")

        return "\n".join(parts)
