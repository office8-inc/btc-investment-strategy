"""Finnhub API クライアント.

金融ニュースと市場センチメントを取得する。
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
class FinancialNews:
    """金融ニュース.

    Attributes:
        headline: 見出し
        summary: 概要
        source: ソース
        url: URL
        published_at: 公開日時
        category: カテゴリー
        related: 関連シンボル
        sentiment: センチメント値（あれば）
    """

    headline: str
    summary: str
    source: str
    url: str
    published_at: datetime
    category: str
    related: str
    sentiment: float | None

    def to_dict(self) -> dict[str, Any]:
        """辞書形式に変換."""
        return {
            "headline": self.headline,
            "summary": self.summary,
            "source": self.source,
            "url": self.url,
            "published_at": self.published_at.isoformat(),
            "category": self.category,
            "related": self.related,
            "sentiment": self.sentiment,
        }


@dataclass
class SentimentData:
    """センチメントデータ.

    Attributes:
        symbol: シンボル
        buzz_score: バズスコア（ニュース量）
        sentiment_score: センチメントスコア（-1〜1）
        articles_this_week: 今週の記事数
        positive_count: ポジティブ記事数
        negative_count: ネガティブ記事数
    """

    symbol: str
    buzz_score: float
    sentiment_score: float
    articles_this_week: int
    positive_count: int
    negative_count: int

    def to_dict(self) -> dict[str, Any]:
        """辞書形式に変換."""
        return {
            "symbol": self.symbol,
            "buzz_score": self.buzz_score,
            "sentiment_score": self.sentiment_score,
            "articles_this_week": self.articles_this_week,
            "positive_count": self.positive_count,
            "negative_count": self.negative_count,
        }


class FinnhubClient:
    """Finnhub API クライアント.

    金融ニュースとセンチメントを取得する。
    無料tierは60 API呼び出し/分の制限あり。
    """

    BASE_URL = "https://finnhub.io/api/v1"

    def __init__(self, api_key: str | None = None) -> None:
        """初期化.

        Args:
            api_key: Finnhub API Key
        """
        self._api_key = api_key or settings.FINNHUB_API_KEY
        self._is_configured = bool(
            self._api_key and "your_" not in self._api_key.lower()
        )

        if not self._is_configured:
            logger.warning(
                "Finnhub API key not configured. "
                "Financial news features will be limited."
            )
        else:
            logger.info("Finnhub client initialized")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def get_general_news(self, category: str = "general") -> list[FinancialNews]:
        """一般ニュースを取得.

        Args:
            category: カテゴリー（general, forex, crypto, merger）

        Returns:
            ニュースリスト
        """
        if not self._is_configured:
            logger.warning("Finnhub API key not configured")
            return []

        try:
            with httpx.Client(timeout=30) as client:
                response = client.get(
                    f"{self.BASE_URL}/news",
                    params={
                        "category": category,
                        "token": self._api_key,
                    },
                )
                response.raise_for_status()
                data = response.json()

            news_list = []
            for item in data[:10]:  # 最新10件
                news_list.append(
                    FinancialNews(
                        headline=item.get("headline", ""),
                        summary=item.get("summary", ""),
                        source=item.get("source", ""),
                        url=item.get("url", ""),
                        published_at=datetime.fromtimestamp(item.get("datetime", 0)),
                        category=item.get("category", category),
                        related=item.get("related", ""),
                        sentiment=None,  # 一般ニュースにはセンチメントなし
                    )
                )

            logger.info(f"Fetched {len(news_list)} general news articles")
            return news_list

        except httpx.HTTPStatusError as e:
            logger.error(f"Finnhub API error: {e.response.status_code}")
            return []
        except Exception as e:
            logger.error(f"Failed to fetch general news: {e}")
            return []

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def get_crypto_news(self) -> list[FinancialNews]:
        """仮想通貨ニュースを取得.

        Returns:
            ニュースリスト
        """
        return self.get_general_news(category="crypto")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def get_sentiment(self, symbol: str) -> SentimentData | None:
        """ソーシャルセンチメントを取得.

        Args:
            symbol: ティッカーシンボル

        Returns:
            センチメントデータ
        """
        if not self._is_configured:
            logger.warning("Finnhub API key not configured")
            return None

        try:
            with httpx.Client(timeout=30) as client:
                response = client.get(
                    f"{self.BASE_URL}/news-sentiment",
                    params={
                        "symbol": symbol,
                        "token": self._api_key,
                    },
                )
                response.raise_for_status()
                data = response.json()

            buzz = data.get("buzz", {})
            sentiment = data.get("sentiment", {})

            return SentimentData(
                symbol=symbol,
                buzz_score=buzz.get("buzz", 0.0),
                sentiment_score=sentiment.get("score", 0.0),
                articles_this_week=buzz.get("articlesInLastWeek", 0),
                positive_count=sentiment.get("positiveCount", 0),
                negative_count=sentiment.get("negativeCount", 0),
            )

        except httpx.HTTPStatusError as e:
            logger.error(f"Finnhub API error: {e.response.status_code}")
            return None
        except Exception as e:
            logger.error(f"Failed to fetch sentiment for {symbol}: {e}")
            return None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def get_market_holidays(self, exchange: str = "US") -> list[dict[str, Any]]:
        """市場の休日を取得.

        Args:
            exchange: 取引所コード

        Returns:
            休日リスト
        """
        if not self._is_configured:
            logger.warning("Finnhub API key not configured")
            return []

        try:
            with httpx.Client(timeout=30) as client:
                response = client.get(
                    f"{self.BASE_URL}/stock/market-holiday",
                    params={
                        "exchange": exchange,
                        "token": self._api_key,
                    },
                )
                response.raise_for_status()
                data = response.json()

            return data.get("data", [])

        except httpx.HTTPStatusError as e:
            logger.error(f"Finnhub API error: {e.response.status_code}")
            return []
        except Exception as e:
            logger.error(f"Failed to fetch market holidays: {e}")
            return []

    def get_news_summary(self) -> str:
        """ニュースサマリーを生成.

        Returns:
            ニュースサマリー文字列
        """
        parts = ["【Finnhub 金融ニュース】", ""]

        # 仮想通貨ニュース
        crypto_news = self.get_crypto_news()
        if crypto_news:
            parts.append("🪙 仮想通貨関連ニュース:")
            for news in crypto_news[:5]:
                parts.append(f"  • {news.headline[:60]}...")
                parts.append(f"    📰 {news.source}")
            parts.append("")

        # 一般金融ニュース
        general_news = self.get_general_news()
        if general_news:
            parts.append("📊 一般金融ニュース:")
            for news in general_news[:3]:
                parts.append(f"  • {news.headline[:60]}...")
            parts.append("")

        if len(parts) == 2:
            return "Finnhub金融ニュースを取得できませんでした。"

        return "\n".join(parts)
