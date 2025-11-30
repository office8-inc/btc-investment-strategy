"""CryptoCompare API クライアント.

仮想通貨ニュースを取得する。
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
