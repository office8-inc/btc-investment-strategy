"""OHLCV データ処理モジュール.

ローソク足データの変換・テクニカル指標計算を行う。
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
import ta

logger = logging.getLogger(__name__)


@dataclass
class OHLCVData:
    """OHLCVデータを保持するクラス.

    Attributes:
        df: OHLCVデータを含むDataFrame
        symbol: 取引ペア
        timeframe: 時間足
        last_updated: 最終更新時刻
    """

    df: pd.DataFrame
    symbol: str
    timeframe: str
    last_updated: datetime

    @property
    def latest_close(self) -> float:
        """最新の終値を取得."""
        return float(self.df["close"].iloc[-1])

    @property
    def latest_timestamp(self) -> datetime:
        """最新のタイムスタンプを取得."""
        return self.df["timestamp"].iloc[-1]

    def to_dict(self) -> dict[str, Any]:
        """辞書形式に変換."""
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "last_updated": self.last_updated.isoformat(),
            "data_points": len(self.df),
            "latest_close": self.latest_close,
            "date_range": {
                "start": self.df["timestamp"].min().isoformat(),
                "end": self.df["timestamp"].max().isoformat(),
            },
        }


def add_technical_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """テクニカル指標を追加.

    Args:
        df: OHLCVデータを含むDataFrame

    Returns:
        テクニカル指標を追加したDataFrame
    """
    df = df.copy()

    # --- 移動平均線 ---
    df["sma_20"] = ta.trend.sma_indicator(df["close"], window=20)
    df["sma_50"] = ta.trend.sma_indicator(df["close"], window=50)
    df["sma_200"] = ta.trend.sma_indicator(df["close"], window=200)
    df["ema_12"] = ta.trend.ema_indicator(df["close"], window=12)
    df["ema_26"] = ta.trend.ema_indicator(df["close"], window=26)

    # --- ボリンジャーバンド ---
    bollinger = ta.volatility.BollingerBands(df["close"], window=20, window_dev=2)
    df["bb_upper"] = bollinger.bollinger_hband()
    df["bb_middle"] = bollinger.bollinger_mavg()
    df["bb_lower"] = bollinger.bollinger_lband()
    df["bb_width"] = bollinger.bollinger_wband()

    # --- RSI ---
    df["rsi_14"] = ta.momentum.rsi(df["close"], window=14)

    # --- MACD ---
    macd = ta.trend.MACD(df["close"])
    df["macd"] = macd.macd()
    df["macd_signal"] = macd.macd_signal()
    df["macd_histogram"] = macd.macd_diff()

    # --- ATR (Average True Range) ---
    df["atr_14"] = ta.volatility.average_true_range(
        df["high"], df["low"], df["close"], window=14
    )

    # --- ADX (Average Directional Index) ---
    df["adx_14"] = ta.trend.adx(df["high"], df["low"], df["close"], window=14)

    # --- ストキャスティクス ---
    stoch = ta.momentum.StochasticOscillator(
        df["high"], df["low"], df["close"], window=14, smooth_window=3
    )
    df["stoch_k"] = stoch.stoch()
    df["stoch_d"] = stoch.stoch_signal()

    # --- 出来高関連 ---
    df["volume_sma_20"] = ta.trend.sma_indicator(df["volume"], window=20)
    df["volume_ratio"] = df["volume"] / df["volume_sma_20"]

    # --- トレンド判定 ---
    df["trend_sma"] = np.where(
        df["sma_20"] > df["sma_50"],
        np.where(df["sma_50"] > df["sma_200"], "strong_bullish", "bullish"),
        np.where(df["sma_50"] < df["sma_200"], "strong_bearish", "bearish"),
    )

    logger.debug(f"Added technical indicators to DataFrame ({len(df)} rows)")

    return df


def calculate_support_resistance(
    df: pd.DataFrame, lookback: int = 50
) -> dict[str, list[float]]:
    """サポート・レジスタンスレベルを計算.

    Args:
        df: OHLCVデータを含むDataFrame
        lookback: 計算に使用する過去のローソク足数

    Returns:
        サポート・レジスタンスレベルを含む辞書
    """
    recent_df = df.tail(lookback)

    # ピボットポイントを使用
    high = recent_df["high"].max()
    low = recent_df["low"].min()
    close = recent_df["close"].iloc[-1]

    pivot = (high + low + close) / 3

    # サポート・レジスタンスレベル
    r1 = 2 * pivot - low
    r2 = pivot + (high - low)
    r3 = high + 2 * (pivot - low)

    s1 = 2 * pivot - high
    s2 = pivot - (high - low)
    s3 = low - 2 * (high - pivot)

    # 過去の高値・安値も追加
    recent_highs = recent_df.nlargest(3, "high")["high"].tolist()
    recent_lows = recent_df.nsmallest(3, "low")["low"].tolist()

    return {
        "pivot": pivot,
        "resistance": sorted([r1, r2, r3] + recent_highs, reverse=True),
        "support": sorted([s1, s2, s3] + recent_lows),
    }
