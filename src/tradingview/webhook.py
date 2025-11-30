"""TradingView Webhook クライアント.

AI分析結果をTradingViewのPine Scriptインジケーターに送信する。
"""

import hashlib
import hmac
import json
import logging
from datetime import datetime
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import settings
from src.analysis.predictor import PredictionPattern

logger = logging.getLogger(__name__)


class TradingViewWebhook:
    """TradingView Webhook クライアント.

    AI分析結果をWebhook経由でTradingViewに送信する。
    """

    def __init__(
        self,
        webhook_url: str | None = None,
        webhook_secret: str | None = None,
    ) -> None:
        """初期化.

        Args:
            webhook_url: Webhook URL
            webhook_secret: Webhook シークレット
        """
        self._webhook_url = webhook_url or settings.TRADINGVIEW_WEBHOOK_URL
        self._webhook_secret = webhook_secret or settings.TRADINGVIEW_WEBHOOK_SECRET

        self._is_configured = bool(
            self._webhook_url
            and "your-webhook" not in self._webhook_url.lower()
        )

        if not self._is_configured:
            logger.warning(
                "TradingView Webhook URL not configured. "
                "Webhook features will not work."
            )

    def _generate_signature(self, payload: str) -> str:
        """ペイロードの署名を生成.

        Args:
            payload: JSON文字列

        Returns:
            HMAC署名
        """
        if not self._webhook_secret:
            return ""

        return hmac.new(
            self._webhook_secret.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()

    def _format_patterns_for_pine(
        self, patterns: list[PredictionPattern]
    ) -> list[dict[str, Any]]:
        """パターンをPine Script用にフォーマット.

        Args:
            patterns: 予測パターンリスト

        Returns:
            Pine Script用にフォーマットされたパターン
        """
        formatted = []

        for pattern in patterns[:10]:  # 最大10パターン
            formatted.append({
                "rank": pattern.rank,
                "probability": round(pattern.probability * 100, 1),  # %表記
                "direction": pattern.direction,
                "target": pattern.target_price,
                "timeframe": pattern.timeframe,
                "name": pattern.pattern_name,
                "entry": pattern.key_levels.entry,
                "stop": pattern.key_levels.stop_loss,
                "tp1": pattern.key_levels.take_profit[0] if pattern.key_levels.take_profit else None,
                "tp2": pattern.key_levels.take_profit[1] if len(pattern.key_levels.take_profit) > 1 else None,
                "tp3": pattern.key_levels.take_profit[2] if len(pattern.key_levels.take_profit) > 2 else None,
                "reasoning": pattern.reasoning[:200],  # 200文字に制限
            })

        return formatted

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def send_predictions(
        self,
        patterns: list[PredictionPattern],
        analysis_summary: str,
        current_price: float,
    ) -> bool:
        """予測パターンをWebhookに送信.

        Args:
            patterns: 予測パターンリスト
            analysis_summary: 分析サマリー
            current_price: 現在価格

        Returns:
            成功した場合True
        """
        if not self._is_configured:
            logger.error("Webhook not configured")
            return False

        # ペイロードを構築
        payload = {
            "timestamp": datetime.now().isoformat(),
            "current_price": current_price,
            "patterns": self._format_patterns_for_pine(patterns),
            "summary": analysis_summary[:500],  # 500文字に制限
        }

        # 署名を追加
        payload_json = json.dumps(payload, ensure_ascii=False)
        signature = self._generate_signature(payload_json)

        headers = {
            "Content-Type": "application/json",
            "X-Webhook-Signature": signature,
        }

        try:
            with httpx.Client(timeout=30) as client:
                response = client.post(
                    self._webhook_url,
                    content=payload_json,
                    headers=headers,
                )
                response.raise_for_status()

            logger.info(
                f"Successfully sent {len(patterns)} patterns to TradingView webhook"
            )
            return True

        except httpx.HTTPStatusError as e:
            logger.error(f"Webhook HTTP error: {e.response.status_code}")
            return False
        except Exception as e:
            logger.error(f"Failed to send webhook: {e}")
            return False

    def generate_alert_message(
        self,
        patterns: list[PredictionPattern],
        current_price: float,
    ) -> str:
        """TradingViewアラート用のメッセージを生成.

        Args:
            patterns: 予測パターンリスト
            current_price: 現在価格

        Returns:
            アラートメッセージ
        """
        lines = [
            f"🪙 BTC AI分析レポート",
            f"現在価格: ${current_price:,.0f}",
            f"分析日時: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            "",
            "📊 予測パターン (上位3件):",
        ]

        for pattern in patterns[:3]:
            direction_emoji = "📈" if pattern.direction == "bullish" else "📉"
            lines.append(
                f"{pattern.rank}. {direction_emoji} {pattern.pattern_name} "
                f"({pattern.probability*100:.0f}%)"
            )
            lines.append(
                f"   目標: ${pattern.target_price:,.0f} / "
                f"SL: ${pattern.key_levels.stop_loss:,.0f}"
            )

        return "\n".join(lines)

    def save_to_json(
        self,
        patterns: list[PredictionPattern],
        analysis_summary: str,
        current_price: float,
        filepath: str = "data/latest_prediction.json",
    ) -> bool:
        """予測結果をJSONファイルに保存.

        Args:
            patterns: 予測パターンリスト
            analysis_summary: 分析サマリー
            current_price: 現在価格
            filepath: 保存先ファイルパス

        Returns:
            成功した場合True
        """
        try:
            output = {
                "timestamp": datetime.now().isoformat(),
                "current_price": current_price,
                "summary": analysis_summary,
                "patterns": [p.to_dict() for p in patterns],
            }

            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(output, f, ensure_ascii=False, indent=2)

            logger.info(f"Saved predictions to {filepath}")
            return True

        except Exception as e:
            logger.error(f"Failed to save predictions: {e}")
            return False
