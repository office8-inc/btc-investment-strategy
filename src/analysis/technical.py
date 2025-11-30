"""テクニカル分析モジュール.

OHLCVデータからテクニカル分析を行い、パターン認識を行う。
"""

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class TechnicalAnalysisResult:
    """テクニカル分析結果.

    Attributes:
        trend: トレンド方向 (bullish/bearish/neutral)
        strength: トレンド強度 (0-100)
        patterns: 検出されたチャートパターン
        indicators: インジケーター値のサマリー
        support_resistance: サポート・レジスタンスレベル
        summary: 分析サマリー
    """

    trend: str
    strength: float
    patterns: list[dict[str, Any]]
    indicators: dict[str, Any]
    support_resistance: dict[str, list[float]]
    summary: str

    def to_dict(self) -> dict[str, Any]:
        """辞書形式に変換."""
        return {
            "trend": self.trend,
            "strength": self.strength,
            "patterns": self.patterns,
            "indicators": self.indicators,
            "support_resistance": self.support_resistance,
            "summary": self.summary,
        }


class TechnicalAnalyzer:
    """テクニカル分析を行うクラス.

    OHLCVデータからトレンド、パターン、サポート/レジスタンスを分析する。
    """

    def __init__(self) -> None:
        """初期化."""
        self.pattern_detectors = [
            self._detect_double_top_bottom,
            self._detect_head_shoulders,
            self._detect_triangle,
            self._detect_channel,
            self._detect_wedge,
        ]

    def analyze(self, df: pd.DataFrame) -> TechnicalAnalysisResult:
        """テクニカル分析を実行.

        Args:
            df: テクニカル指標を含むOHLCVデータ

        Returns:
            TechnicalAnalysisResult: 分析結果
        """
        # トレンド分析
        trend, strength = self._analyze_trend(df)

        # パターン検出
        patterns = self._detect_patterns(df)

        # インジケーターサマリー
        indicators = self._summarize_indicators(df)

        # サポート/レジスタンス
        sr_levels = self._calculate_sr_levels(df)

        # サマリー生成
        summary = self._generate_summary(trend, strength, patterns, indicators)

        return TechnicalAnalysisResult(
            trend=trend,
            strength=strength,
            patterns=patterns,
            indicators=indicators,
            support_resistance=sr_levels,
            summary=summary,
        )

    def _analyze_trend(self, df: pd.DataFrame) -> tuple[str, float]:
        """トレンドを分析.

        Args:
            df: OHLCVデータ

        Returns:
            (トレンド方向, 強度)のタプル
        """
        latest = df.iloc[-1]
        strength_factors = []

        # SMA ベースのトレンド判定
        if "sma_20" in df.columns and "sma_50" in df.columns:
            if latest["sma_20"] > latest["sma_50"]:
                strength_factors.append(("sma_cross", 1, 25))
            else:
                strength_factors.append(("sma_cross", -1, 25))

        # 価格と SMA200 の位置関係
        if "sma_200" in df.columns:
            if latest["close"] > latest["sma_200"]:
                strength_factors.append(("above_sma200", 1, 20))
            else:
                strength_factors.append(("above_sma200", -1, 20))

        # RSI
        if "rsi_14" in df.columns:
            rsi = latest["rsi_14"]
            if rsi > 70:
                strength_factors.append(("rsi", 1, 15))  # 過買い
            elif rsi < 30:
                strength_factors.append(("rsi", -1, 15))  # 過売り
            elif rsi > 50:
                strength_factors.append(("rsi", 0.5, 10))
            else:
                strength_factors.append(("rsi", -0.5, 10))

        # MACD
        if "macd" in df.columns and "macd_signal" in df.columns:
            if latest["macd"] > latest["macd_signal"]:
                strength_factors.append(("macd", 1, 20))
            else:
                strength_factors.append(("macd", -1, 20))

        # ADX (トレンド強度)
        if "adx_14" in df.columns:
            adx = latest["adx_14"]
            if adx > 25:
                strength_factors.append(("adx", 1, min(adx / 50 * 20, 20)))
            else:
                strength_factors.append(("adx", 0, 5))

        # スコア計算
        bullish_score = sum(w for _, d, w in strength_factors if d > 0)
        bearish_score = sum(w for _, d, w in strength_factors if d < 0)
        total_weight = sum(w for _, _, w in strength_factors)

        if total_weight == 0:
            return "neutral", 50.0

        net_score = (bullish_score - bearish_score) / total_weight * 100

        if net_score > 20:
            trend = "bullish"
            strength = min(50 + net_score / 2, 100)
        elif net_score < -20:
            trend = "bearish"
            strength = min(50 + abs(net_score) / 2, 100)
        else:
            trend = "neutral"
            strength = 50 - abs(net_score)

        return trend, round(strength, 1)

    def _detect_patterns(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        """チャートパターンを検出.

        Args:
            df: OHLCVデータ

        Returns:
            検出されたパターンのリスト
        """
        patterns = []
        for detector in self.pattern_detectors:
            try:
                pattern = detector(df)
                if pattern:
                    patterns.append(pattern)
            except Exception as e:
                logger.warning(f"Pattern detection failed: {e}")

        return patterns

    def _detect_double_top_bottom(self, df: pd.DataFrame) -> dict[str, Any] | None:
        """ダブルトップ/ボトムを検出."""
        if len(df) < 50:
            return None

        recent = df.tail(50)
        highs = recent["high"]
        lows = recent["low"]

        # ダブルトップの検出（簡易版）
        max_idx = highs.idxmax()
        max_val = highs.max()

        # 高値付近（2%以内）の他のピークを探す
        tolerance = max_val * 0.02
        near_peaks = recent[
            (highs > max_val - tolerance) & (highs.index != max_idx)
        ]

        if len(near_peaks) >= 1:
            return {
                "name": "Double Top",
                "direction": "bearish",
                "confidence": 0.6,
                "price_level": max_val,
                "description": "ダブルトップパターンが形成中。反転下落の可能性。",
            }

        # ダブルボトムの検出
        min_idx = lows.idxmin()
        min_val = lows.min()
        tolerance = min_val * 0.02
        near_bottoms = recent[
            (lows < min_val + tolerance) & (lows.index != min_idx)
        ]

        if len(near_bottoms) >= 1:
            return {
                "name": "Double Bottom",
                "direction": "bullish",
                "confidence": 0.6,
                "price_level": min_val,
                "description": "ダブルボトムパターンが形成中。反転上昇の可能性。",
            }

        return None

    def _detect_head_shoulders(self, df: pd.DataFrame) -> dict[str, Any] | None:
        """ヘッドアンドショルダーを検出."""
        # 簡易版: 将来的により高度なアルゴリズムを実装
        return None

    def _detect_triangle(self, df: pd.DataFrame) -> dict[str, Any] | None:
        """三角保ち合いを検出."""
        if len(df) < 30:
            return None

        recent = df.tail(30)

        # 高値と安値のトレンドラインを計算
        highs = recent["high"].values
        lows = recent["low"].values
        x = range(len(highs))

        # 線形回帰で傾きを計算
        import numpy as np

        high_slope = np.polyfit(x, highs, 1)[0]
        low_slope = np.polyfit(x, lows, 1)[0]

        # 収束パターンの判定
        if high_slope < 0 and low_slope > 0:
            # 対称三角形
            return {
                "name": "Symmetrical Triangle",
                "direction": "neutral",
                "confidence": 0.5,
                "description": "対称三角形が形成中。ブレイクアウト方向に注目。",
            }
        elif high_slope < 0 and abs(low_slope) < abs(high_slope) * 0.3:
            # 下降三角形
            return {
                "name": "Descending Triangle",
                "direction": "bearish",
                "confidence": 0.55,
                "description": "下降三角形が形成中。下方ブレイクの可能性。",
            }
        elif low_slope > 0 and abs(high_slope) < abs(low_slope) * 0.3:
            # 上昇三角形
            return {
                "name": "Ascending Triangle",
                "direction": "bullish",
                "confidence": 0.55,
                "description": "上昇三角形が形成中。上方ブレイクの可能性。",
            }

        return None

    def _detect_channel(self, df: pd.DataFrame) -> dict[str, Any] | None:
        """チャネルを検出."""
        # 将来実装
        return None

    def _detect_wedge(self, df: pd.DataFrame) -> dict[str, Any] | None:
        """ウェッジを検出."""
        # 将来実装
        return None

    def _summarize_indicators(self, df: pd.DataFrame) -> dict[str, Any]:
        """インジケーターのサマリーを生成."""
        latest = df.iloc[-1]
        summary = {}

        indicator_columns = [
            "rsi_14",
            "macd",
            "macd_signal",
            "macd_histogram",
            "adx_14",
            "bb_upper",
            "bb_middle",
            "bb_lower",
            "sma_20",
            "sma_50",
            "sma_200",
            "atr_14",
            "stoch_k",
            "stoch_d",
        ]

        for col in indicator_columns:
            if col in df.columns:
                value = latest[col]
                if pd.notna(value):
                    summary[col] = round(float(value), 2)

        # 現在価格
        summary["current_price"] = round(float(latest["close"]), 2)
        summary["volume"] = round(float(latest["volume"]), 2)

        return summary

    def _calculate_sr_levels(self, df: pd.DataFrame) -> dict[str, list[float]]:
        """サポート・レジスタンスレベルを計算."""
        from src.data.ohlcv import calculate_support_resistance

        return calculate_support_resistance(df)

    def _generate_summary(
        self,
        trend: str,
        strength: float,
        patterns: list[dict[str, Any]],
        indicators: dict[str, Any],
    ) -> str:
        """分析サマリーを生成."""
        trend_ja = {
            "bullish": "上昇トレンド",
            "bearish": "下降トレンド",
            "neutral": "レンジ相場",
        }

        summary_parts = [
            f"現在の相場状況: {trend_ja.get(trend, trend)} (強度: {strength}%)",
        ]

        # RSI状況
        if "rsi_14" in indicators:
            rsi = indicators["rsi_14"]
            if rsi > 70:
                summary_parts.append(f"RSI({rsi})が過買い圏")
            elif rsi < 30:
                summary_parts.append(f"RSI({rsi})が過売り圏")

        # パターン
        if patterns:
            pattern_names = [p["name"] for p in patterns]
            summary_parts.append(f"検出パターン: {', '.join(pattern_names)}")

        return "。".join(summary_parts) + "。"
