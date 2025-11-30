"""ファンダメンタル分析モジュール.

ニュースや過去のイベントを分析し、市場への影響を評価する。
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class FundamentalEvent:
    """ファンダメンタルイベント.

    Attributes:
        title: イベントタイトル
        date: 発生日
        category: カテゴリ (halving, etf, regulation, macro, etc.)
        impact: 影響度 (-1 to 1)
        description: 説明
        source: 情報源
    """

    title: str
    date: datetime
    category: str
    impact: float
    description: str
    source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """辞書形式に変換."""
        return {
            "title": self.title,
            "date": self.date.isoformat(),
            "category": self.category,
            "impact": self.impact,
            "description": self.description,
            "source": self.source,
        }


@dataclass
class FundamentalAnalysisResult:
    """ファンダメンタル分析結果.

    Attributes:
        sentiment: 市場センチメント (-1 to 1)
        key_events: 重要イベントリスト
        similar_historical_events: 類似する過去イベント
        analysis_summary: 分析サマリー
    """

    sentiment: float
    key_events: list[FundamentalEvent]
    similar_historical_events: list[dict[str, Any]]
    analysis_summary: str

    def to_dict(self) -> dict[str, Any]:
        """辞書形式に変換."""
        return {
            "sentiment": self.sentiment,
            "key_events": [e.to_dict() for e in self.key_events],
            "similar_historical_events": self.similar_historical_events,
            "analysis_summary": self.analysis_summary,
        }


# 過去の重要イベントデータベース（将来的にPineconeに移行）
HISTORICAL_EVENTS = [
    {
        "title": "Bitcoin Halving 2024",
        "date": "2024-04-20",
        "category": "halving",
        "description": "4回目のビットコイン半減期。報酬が6.25BTCから3.125BTCに減少。",
        "price_before": 64000,
        "price_after_1m": 67000,
        "price_after_6m": None,  # 将来データ
    },
    {
        "title": "Bitcoin Spot ETF Approval",
        "date": "2024-01-10",
        "category": "etf",
        "description": "米SECがビットコイン現物ETFを承認。",
        "price_before": 46000,
        "price_after_1m": 52000,
        "price_after_6m": 67000,
    },
    {
        "title": "Bitcoin Halving 2020",
        "date": "2020-05-11",
        "category": "halving",
        "description": "3回目のビットコイン半減期。報酬が12.5BTCから6.25BTCに減少。",
        "price_before": 8500,
        "price_after_1m": 9500,
        "price_after_6m": 19000,
    },
    {
        "title": "COVID-19 Market Crash",
        "date": "2020-03-12",
        "category": "macro",
        "description": "新型コロナウイルスによる世界的な金融市場の暴落。",
        "price_before": 8000,
        "price_after_1m": 6500,
        "price_after_6m": 11500,
    },
    {
        "title": "China Crypto Ban",
        "date": "2021-05-21",
        "category": "regulation",
        "description": "中国が仮想通貨マイニングと取引を禁止。",
        "price_before": 40000,
        "price_after_1m": 35000,
        "price_after_6m": 47000,
    },
]


class FundamentalAnalyzer:
    """ファンダメンタル分析を行うクラス."""

    def __init__(self, api_key: str | None = None) -> None:
        """初期化.

        Args:
            api_key: OpenAI API Key
        """
        self._api_key = api_key or settings.OPENAI_API_KEY
        if self._api_key and "your_" not in self._api_key.lower():
            self.client = OpenAI(api_key=self._api_key)
        else:
            self.client = None

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def analyze(
        self,
        news_items: list[dict[str, Any]] | None = None,
        current_price: float | None = None,
    ) -> FundamentalAnalysisResult:
        """ファンダメンタル分析を実行.

        Args:
            news_items: ニュースアイテムのリスト
            current_price: 現在価格

        Returns:
            FundamentalAnalysisResult: 分析結果
        """
        # ニュースからイベントを抽出
        key_events = self._extract_events(news_items or [])

        # 類似する過去イベントを検索
        similar_events = self._find_similar_events(key_events)

        # センチメント分析
        sentiment = self._calculate_sentiment(key_events, news_items)

        # サマリー生成
        summary = self._generate_summary(
            key_events, similar_events, sentiment, current_price
        )

        return FundamentalAnalysisResult(
            sentiment=sentiment,
            key_events=key_events,
            similar_historical_events=similar_events,
            analysis_summary=summary,
        )

    def _extract_events(
        self, news_items: list[dict[str, Any]]
    ) -> list[FundamentalEvent]:
        """ニュースから重要イベントを抽出."""
        events = []

        for item in news_items:
            # カテゴリ判定
            title = item.get("title", "").lower()
            category = "other"

            if any(w in title for w in ["halving", "半減期"]):
                category = "halving"
            elif any(w in title for w in ["etf", "sec", "承認"]):
                category = "etf"
            elif any(w in title for w in ["regulation", "規制", "ban", "禁止"]):
                category = "regulation"
            elif any(w in title for w in ["fed", "fomc", "金利", "利下げ", "利上げ"]):
                category = "macro"

            # 影響度を推定（簡易版）
            impact = 0.0
            if "bullish" in str(item.get("sentiment", "")).lower():
                impact = 0.3
            elif "bearish" in str(item.get("sentiment", "")).lower():
                impact = -0.3

            event = FundamentalEvent(
                title=item.get("title", "Unknown"),
                date=datetime.fromisoformat(
                    item.get("published_at", datetime.now().isoformat())
                ),
                category=category,
                impact=impact,
                description=item.get("description", ""),
                source=item.get("source", None),
            )
            events.append(event)

        return events

    def _find_similar_events(
        self, current_events: list[FundamentalEvent]
    ) -> list[dict[str, Any]]:
        """類似する過去イベントを検索."""
        similar = []

        current_categories = {e.category for e in current_events}

        for hist_event in HISTORICAL_EVENTS:
            if hist_event["category"] in current_categories:
                similar.append(hist_event)

        return similar[:5]  # 最大5件

    def _calculate_sentiment(
        self,
        events: list[FundamentalEvent],
        news_items: list[dict[str, Any]] | None,
    ) -> float:
        """市場センチメントを計算."""
        if not events and not news_items:
            return 0.0

        impacts = [e.impact for e in events]
        if impacts:
            return sum(impacts) / len(impacts)

        return 0.0

    def _generate_summary(
        self,
        events: list[FundamentalEvent],
        similar_events: list[dict[str, Any]],
        sentiment: float,
        current_price: float | None,
    ) -> str:
        """分析サマリーを生成."""
        parts = []

        # センチメント
        if sentiment > 0.2:
            parts.append("市場センチメントは楽観的")
        elif sentiment < -0.2:
            parts.append("市場センチメントは悲観的")
        else:
            parts.append("市場センチメントは中立")

        # 重要イベント
        if events:
            parts.append(f"直近の重要イベント: {len(events)}件")

        # 類似過去イベント
        if similar_events:
            event_names = [e["title"] for e in similar_events[:2]]
            parts.append(f"類似する過去イベント: {', '.join(event_names)}")

        return "。".join(parts) + "。" if parts else "特筆すべき情報なし。"

    def get_historical_context(self, category: str) -> list[dict[str, Any]]:
        """特定カテゴリの過去イベントを取得.

        Args:
            category: イベントカテゴリ

        Returns:
            過去イベントのリスト
        """
        return [e for e in HISTORICAL_EVENTS if e["category"] == category]
