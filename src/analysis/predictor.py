"""予測パターン生成モジュール.

OpenAI GPT-4を使用してチャート予測パターンを生成する。
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from loguru import logger
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import settings
from src.analysis.technical import TechnicalAnalysisResult


@dataclass
class KeyLevels:
    """重要価格レベル."""

    entry: float
    stop_loss: float
    take_profit: list[float]


@dataclass
class PredictionPattern:
    """予測パターン.

    Attributes:
        rank: 確率順位 (1-10)
        probability: 発生確率 (0-1)
        direction: 方向 (bullish/bearish/neutral)
        target_price: 目標価格
        timeframe: 予測期間
        pattern_name: パターン名
        reasoning: 根拠
        key_levels: 重要価格レベル
    """

    rank: int
    probability: float
    direction: str
    target_price: float
    timeframe: str
    pattern_name: str
    reasoning: str
    key_levels: KeyLevels
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """辞書形式に変換."""
        return {
            "rank": self.rank,
            "probability": self.probability,
            "direction": self.direction,
            "target_price": self.target_price,
            "timeframe": self.timeframe,
            "pattern_name": self.pattern_name,
            "reasoning": self.reasoning,
            "key_levels": {
                "entry": self.key_levels.entry,
                "stop_loss": self.key_levels.stop_loss,
                "take_profit": self.key_levels.take_profit,
            },
            "created_at": self.created_at.isoformat(),
        }


class Predictor:
    """AI予測パターン生成クラス.

    OpenAI GPT-4を使用してテクニカル分析結果から
    確率付きの予測パターンを生成する。
    """

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        """初期化.

        Args:
            api_key: OpenAI API Key（未指定時は環境変数から取得）
            model: 使用するモデル名
        """
        self._api_key = api_key or settings.OPENAI_API_KEY
        self._model = model or settings.OPENAI_MODEL

        if not self._api_key or "your_" in self._api_key.lower():
            logger.warning(
                "OpenAI API key not configured. "
                "Prediction features will not work."
            )
            self.client = None
        else:
            self.client = OpenAI(api_key=self._api_key)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def generate_predictions(
        self,
        technical_analysis: TechnicalAnalysisResult,
        current_price: float,
        timeframes: list[str] | None = None,
        num_patterns: int = 10,
        news_context: str | None = None,
    ) -> list[PredictionPattern]:
        """予測パターンを生成.

        Args:
            technical_analysis: テクニカル分析結果
            current_price: 現在価格
            timeframes: 予測対象の時間足リスト
            num_patterns: 生成するパターン数
            news_context: ニュース・ファンダメンタル情報（類似投稿含む）

        Returns:
            確率順にソートされた予測パターンのリスト
        """
        if not self.client:
            logger.error("OpenAI client not initialized. Cannot generate predictions.")
            return []

        if timeframes is None:
            timeframes = ["1week", "2weeks", "1month"]

        # プロンプトを構築
        prompt = self._build_prompt(
            technical_analysis=technical_analysis,
            current_price=current_price,
            timeframes=timeframes,
            num_patterns=num_patterns,
            news_context=news_context,
        )

        # プロンプトをログに出力（デバッグ用）
        system_prompt = self._get_system_prompt()
        logger.info("=" * 80)
        logger.info("【AIプロンプト - システム】")
        logger.info("=" * 80)
        logger.info(f"\n{system_prompt}")
        logger.info("=" * 80)
        logger.info("【AIプロンプト - ユーザー】")
        logger.info("=" * 80)
        logger.info(f"\n{prompt}")
        logger.info("=" * 80)

        try:
            response = self.client.chat.completions.create(
                model=self._model,
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt,
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                temperature=0.7,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content
            if not content:
                logger.error("Empty response from OpenAI")
                return []

            result = json.loads(content)
            patterns = self._parse_patterns(result, current_price)

            logger.info(f"Generated {len(patterns)} prediction patterns")
            return patterns

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse OpenAI response as JSON: {e}")
            return []
        except Exception as e:
            logger.error(f"Failed to generate predictions: {e}")
            raise

    def _get_system_prompt(self) -> str:
        """システムプロンプトを取得."""
        return """あなたは、ビットコインのテクニカル分析とチャートパターン予測の専門家です。

以下の役割を担います：
1. 提供されたテクニカル分析データを解釈する
2. 過去のパターンと類似性を分析する
3. 複数の将来シナリオを確率付きで提示する
4. 各シナリオの具体的な価格レベルと根拠を説明する

重要な注意事項：
- 確率の合計が100%を超えないようにする
- 楽観的・悲観的両方のシナリオを含める
- 具体的な数値（価格レベル、期間）を必ず含める
- 根拠は明確かつ具体的に記述する
- JSONフォーマットで出力する"""

    def _build_prompt(
        self,
        technical_analysis: TechnicalAnalysisResult,
        current_price: float,
        timeframes: list[str],
        num_patterns: int,
        news_context: str | None,
    ) -> str:
        """ユーザープロンプトを構築."""
        prompt_parts = [
            "# ビットコイン価格予測リクエスト",
            "",
            f"## 現在価格: ${current_price:,.2f}",
            "",
            "## テクニカル分析サマリー",
            f"- トレンド: {technical_analysis.trend} (強度: {technical_analysis.strength}%)",
            f"- 分析: {technical_analysis.summary}",
            "",
            "## インジケーター値",
        ]

        for key, value in technical_analysis.indicators.items():
            prompt_parts.append(f"- {key}: {value}")

        prompt_parts.extend([
            "",
            "## サポート・レジスタンス",
            f"- レジスタンス: {technical_analysis.support_resistance.get('resistance', [])}",
            f"- サポート: {technical_analysis.support_resistance.get('support', [])}",
        ])

        if technical_analysis.patterns:
            prompt_parts.extend([
                "",
                "## 検出されたチャートパターン",
            ])
            for pattern in technical_analysis.patterns:
                prompt_parts.append(
                    f"- {pattern['name']}: {pattern.get('description', '')}"
                )

        if news_context:
            prompt_parts.extend([
                "",
                "## ファンダメンタル・ニュース情報（過去の類似投稿含む）",
                news_context,
            ])

        prompt_parts.extend([
            "",
            "## 出力要件",
            f"- **必ず{num_patterns}個**の異なる価格シナリオを生成してください（{num_patterns}個未満は不可）",
            f"- 予測期間: {', '.join(timeframes)}",
            "- 各シナリオには確率、目標価格、根拠、重要価格レベルを含める",
            "- 上昇・下落・横ばいのシナリオをバランスよく含める",
            "- 確率の合計が100%以下になるようにする",
            "",
            "以下のJSON形式で出力してください：",
            """```json
{
  "patterns": [
    {
      "rank": 1,
      "probability": 0.35,
      "direction": "bullish",
      "target_price": 105000,
      "timeframe": "2weeks",
      "pattern_name": "Ascending Triangle Breakout",
      "reasoning": "上昇三角形のブレイクアウトが進行中...",
      "key_levels": {
        "entry": 98000,
        "stop_loss": 95000,
        "take_profit": [102000, 105000, 110000]
      }
    }
  ]
}
```""",
        ])

        return "\n".join(prompt_parts)

    def _parse_patterns(
        self, response: dict[str, Any], current_price: float
    ) -> list[PredictionPattern]:
        """APIレスポンスをパースしてPredictionPatternリストに変換."""
        patterns = []

        for item in response.get("patterns", []):
            try:
                key_levels = KeyLevels(
                    entry=float(item["key_levels"]["entry"]),
                    stop_loss=float(item["key_levels"]["stop_loss"]),
                    take_profit=[
                        float(tp) for tp in item["key_levels"]["take_profit"]
                    ],
                )

                pattern = PredictionPattern(
                    rank=int(item["rank"]),
                    probability=float(item["probability"]),
                    direction=str(item["direction"]),
                    target_price=float(item["target_price"]),
                    timeframe=str(item["timeframe"]),
                    pattern_name=str(item["pattern_name"]),
                    reasoning=str(item["reasoning"]),
                    key_levels=key_levels,
                )
                patterns.append(pattern)

            except (KeyError, ValueError, TypeError) as e:
                logger.warning(f"Failed to parse pattern: {e}")
                continue

        # 確率順にソート
        patterns.sort(key=lambda x: x.probability, reverse=True)

        # ランクを再割り当て
        for i, pattern in enumerate(patterns, 1):
            pattern.rank = i

        return patterns
