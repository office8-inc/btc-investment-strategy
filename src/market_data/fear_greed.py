"""Fear & Greed Index API クライアント.

仮想通貨市場のセンチメント指標を取得する。
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
class FearGreedData:
    """Fear & Greed Index データ.

    Attributes:
        value: インデックス値 (0-100)
        value_classification: 分類 (Extreme Fear, Fear, Neutral, Greed, Extreme Greed)
        timestamp: タイムスタンプ
    """

    value: int
    value_classification: str
    timestamp: datetime

    def to_dict(self) -> dict[str, Any]:
        """辞書形式に変換."""
        return {
            "value": self.value,
            "value_classification": self.value_classification,
            "timestamp": self.timestamp.isoformat(),
        }

    @property
    def sentiment_ja(self) -> str:
        """日本語のセンチメント."""
        mapping = {
            "Extreme Fear": "極度の恐怖",
            "Fear": "恐怖",
            "Neutral": "中立",
            "Greed": "貪欲",
            "Extreme Greed": "極度の貪欲",
        }
        return mapping.get(self.value_classification, self.value_classification)

    @property
    def emoji(self) -> str:
        """センチメントに対応する絵文字."""
        if self.value <= 25:
            return "😱"  # Extreme Fear
        elif self.value <= 45:
            return "😰"  # Fear
        elif self.value <= 55:
            return "😐"  # Neutral
        elif self.value <= 75:
            return "😀"  # Greed
        else:
            return "🤑"  # Extreme Greed


class FearGreedClient:
    """Fear & Greed Index API クライアント.

    Alternative.me の Fear & Greed Index を取得する（認証不要）。
    """

    def __init__(self, base_url: str | None = None) -> None:
        """初期化.

        Args:
            base_url: API Base URL
        """
        self._base_url = base_url or settings.FEAR_GREED_API_URL
        logger.info("Fear & Greed Index client initialized")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def get_current(self) -> FearGreedData | None:
        """現在のFear & Greed Indexを取得.

        Returns:
            Fear & Greed データ（取得失敗時はNone）
        """
        try:
            with httpx.Client(timeout=30) as client:
                response = client.get(self._base_url)
                response.raise_for_status()
                data = response.json()

            if not data.get("data"):
                logger.warning("No Fear & Greed data returned")
                return None

            item = data["data"][0]
            result = FearGreedData(
                value=int(item.get("value", 0)),
                value_classification=item.get("value_classification", "Unknown"),
                timestamp=datetime.fromtimestamp(int(item.get("timestamp", 0))),
            )

            logger.info(
                f"Fear & Greed Index: {result.value} ({result.value_classification})"
            )
            return result

        except httpx.HTTPStatusError as e:
            logger.error(f"Fear & Greed API error: {e.response.status_code}")
            return None
        except Exception as e:
            logger.error(f"Failed to fetch Fear & Greed Index: {e}")
            return None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def get_historical(self, limit: int = 30) -> list[FearGreedData]:
        """過去のFear & Greed Indexを取得.

        Args:
            limit: 取得する日数

        Returns:
            Fear & Greed データリスト
        """
        try:
            with httpx.Client(timeout=30) as client:
                response = client.get(
                    self._base_url,
                    params={"limit": limit},
                )
                response.raise_for_status()
                data = response.json()

            results = []
            for item in data.get("data", []):
                results.append(
                    FearGreedData(
                        value=int(item.get("value", 0)),
                        value_classification=item.get("value_classification", "Unknown"),
                        timestamp=datetime.fromtimestamp(int(item.get("timestamp", 0))),
                    )
                )

            logger.info(f"Fetched {len(results)} days of Fear & Greed history")
            return results

        except httpx.HTTPStatusError as e:
            logger.error(f"Fear & Greed historical API error: {e.response.status_code}")
            return []
        except Exception as e:
            logger.error(f"Failed to fetch Fear & Greed history: {e}")
            return []

    def get_sentiment_summary(self) -> str:
        """センチメントサマリーを生成.

        Returns:
            センチメントサマリー文字列
        """
        current = self.get_current()
        history = self.get_historical(limit=7)

        parts = ["【Fear & Greed Index】", ""]

        if current:
            parts.append(
                f"現在のインデックス: {current.value} {current.emoji} ({current.sentiment_ja})"
            )
            parts.append("")

        if history and len(history) >= 7:
            # 7日間の平均
            avg_7d = sum(h.value for h in history[:7]) / 7
            parts.append(f"7日間平均: {avg_7d:.1f}")

            # トレンド判定
            if len(history) >= 2:
                trend = history[0].value - history[1].value
                if trend > 5:
                    parts.append("トレンド: 📈 上昇傾向（楽観的に変化）")
                elif trend < -5:
                    parts.append("トレンド: 📉 下降傾向（悲観的に変化）")
                else:
                    parts.append("トレンド: ➡️ 横ばい")

            parts.append("")
            parts.append("過去7日間:")
            for h in history[:7]:
                date_str = h.timestamp.strftime("%m/%d")
                parts.append(f"  {date_str}: {h.value} {h.emoji}")

        return "\n".join(parts)
