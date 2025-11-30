"""CryptoCompare API クライアント.

仮想通貨ニュースとOHLCデータを取得する。
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

# CryptoCompare API Base URLs
CRYPTOCOMPARE_DATA_URL = "https://min-api.cryptocompare.com/data/v2"


@dataclass
class CryptoNews:
    """仮想通貨ニュース.

    Attributes:
        id: ニュースID
        title: タイトル
        body: 本文
        published_at: 公開日時
        source: ソース名
        url: ニュースURL
        categories: カテゴリリスト
        tags: タグリスト
    """

    id: str
    title: str
    body: str
    published_at: datetime
    source: str
    url: str
    categories: list[str]
    tags: list[str]

    def to_dict(self) -> dict[str, Any]:
        """辞書形式に変換."""
        return {
            "id": self.id,
            "title": self.title,
            "body": self.body,
            "published_at": self.published_at.isoformat(),
            "source": self.source,
            "url": self.url,
            "categories": self.categories,
            "tags": self.tags,
        }


class CryptoCompareClient:
    """CryptoCompare API クライアント.

    仮想通貨関連のニュースを取得する（認証不要）。
    """

    def __init__(self, base_url: str | None = None) -> None:
        """初期化.

        Args:
            base_url: API Base URL
        """
        self._base_url = base_url or settings.CRYPTOCOMPARE_NEWS_URL
        logger.info("CryptoCompare client initialized")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def get_news(
        self,
        categories: list[str] | None = None,
        limit: int = 50,
        lang: str = "EN",
    ) -> list[CryptoNews]:
        """ニュースを取得.

        Args:
            categories: カテゴリリスト (BTC, Regulation, Trading, Mining, etc.)
            limit: 取得する最大件数
            lang: 言語コード

        Returns:
            ニュースリスト
        """
        params: dict[str, Any] = {
            "lang": lang,
        }

        if categories:
            params["categories"] = ",".join(categories)

        try:
            with httpx.Client(timeout=30) as client:
                response = client.get(self._base_url, params=params)
                response.raise_for_status()
                data = response.json()

            news_items = []
            for item in data.get("Data", [])[:limit]:
                news_items.append(
                    CryptoNews(
                        id=str(item.get("id", "")),
                        title=item.get("title", ""),
                        body=item.get("body", ""),
                        published_at=datetime.fromtimestamp(
                            item.get("published_on", 0)
                        ),
                        source=item.get("source_info", {}).get("name", "Unknown"),
                        url=item.get("url", ""),
                        categories=item.get("categories", "").split("|"),
                        tags=item.get("tags", "").split("|"),
                    )
                )

            logger.info(f"Fetched {len(news_items)} news from CryptoCompare")
            return news_items

        except httpx.HTTPStatusError as e:
            logger.error(f"CryptoCompare API error: {e.response.status_code}")
            return []
        except Exception as e:
            logger.error(f"Failed to fetch CryptoCompare news: {e}")
            return []

    def get_btc_news(self, limit: int = 30) -> list[CryptoNews]:
        """ビットコイン関連ニュースを取得.

        Args:
            limit: 取得する最大件数

        Returns:
            ニュースリスト
        """
        return self.get_news(categories=["BTC"], limit=limit)

    def get_news_summary(self, limit: int = 10) -> str:
        """ニュースサマリーを生成.

        Args:
            limit: 使用するニュース件数

        Returns:
            ニュースサマリー文字列
        """
        news = self.get_btc_news(limit=limit)

        if not news:
            return "CryptoCompareからの最新ニュースはありません。"

        summary_parts = ["【CryptoCompare ビットコインニュース】", ""]

        for item in news:
            date_str = item.published_at.strftime("%Y-%m-%d %H:%M")
            # 本文を100文字に切り詰め
            body_short = item.body[:100] + "..." if len(item.body) > 100 else item.body
            summary_parts.append(f"[{date_str}] {item.title}")
            summary_parts.append(f"  {body_short}")
            summary_parts.append("")

        return "\n".join(summary_parts)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def get_ohlc_data(self, days: int = 365) -> list[dict[str, Any]] | None:
        """ビットコインの日足OHLCデータを取得.

        CryptoCompare histoday APIを使用して日足データを取得する。
        認証不要で365日分の正確な日足データが取得可能。

        Args:
            days: 取得する日数（最大2000）

        Returns:
            OHLCデータのリスト [{time, open, high, low, close, volumefrom, volumeto}, ...]
            取得失敗時はNone
        """
        try:
            with httpx.Client(timeout=30) as client:
                response = client.get(
                    f"{CRYPTOCOMPARE_DATA_URL}/histoday",
                    params={
                        "fsym": "BTC",
                        "tsym": "USD",
                        "limit": days,
                    },
                )
                response.raise_for_status()
                result = response.json()

            if result.get("Response") != "Success":
                logger.warning(f"CryptoCompare OHLC: {result.get('Message', 'Unknown error')}")
                return None

            data = result.get("Data", {}).get("Data", [])
            if not data:
                logger.warning("CryptoCompare OHLC: No data returned")
                return None

            logger.info(f"Fetched {len(data)} OHLC candles from CryptoCompare")
            return data

        except httpx.HTTPStatusError as e:
            logger.error(f"CryptoCompare OHLC API error: {e.response.status_code}")
            return None
        except Exception as e:
            logger.error(f"Failed to fetch CryptoCompare OHLC data: {e}")
            return None

    def get_ohlc_dataframe(self, days: int = 365) -> pd.DataFrame | None:
        """ビットコインの日足OHLCデータをDataFrame形式で取得.

        テクニカル指標計算に使える形式でOHLCデータを返す。
        CoinGeckoと異なり、正確な日足データを取得可能。

        Args:
            days: 取得する日数（最大2000）

        Returns:
            OHLCVデータを含むDataFrame (columns: timestamp, open, high, low, close, volume)
            取得失敗時はNone
        """
        ohlc_data = self.get_ohlc_data(days=days)
        if ohlc_data is None:
            return None

        try:
            df = pd.DataFrame(ohlc_data)

            # タイムスタンプをdatetimeに変換
            df["timestamp"] = pd.to_datetime(df["time"], unit="s", utc=True)

            # 出来高（volumefromがBTC単位の取引量）
            df["volume"] = df["volumefrom"]

            # 列の順序を整理
            df = df[["timestamp", "open", "high", "low", "close", "volume"]]

            # 時系列順にソート
            df = df.sort_values("timestamp").reset_index(drop=True)

            logger.info(f"Created OHLC DataFrame with {len(df)} rows from CryptoCompare")
            return df

        except Exception as e:
            logger.error(f"Failed to create OHLC DataFrame: {e}")
            return None
