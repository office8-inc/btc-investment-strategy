"""Bybit API クライアント.

Bybit V5 APIを使用してBTC価格データを取得する。
"""

import logging
from datetime import datetime, timedelta
from typing import Literal

import pandas as pd
from pybit.unified_trading import HTTP
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config.settings import settings

logger = logging.getLogger(__name__)

# 時間足の定義
TimeframeType = Literal["D", "W", "M"]

# Bybit APIの時間足マッピング
TIMEFRAME_MAP = {
    "1d": "D",
    "D": "D",
    "3d": "D",  # 3日足はAPIにないため、日足を取得して集約
    "1w": "W",
    "W": "W",
    "1M": "M",
    "M": "M",
}

# 時間足ごとのデフォルト取得期間（日数）
DEFAULT_LOOKBACK_DAYS = {
    "D": 365,  # 日足: 1年
    "W": 365 * 2,  # 週足: 2年
    "M": 365 * 5,  # 月足: 5年
}


class BybitClient:
    """Bybit API クライアント.

    Bybit V5 APIを使用してBTCの価格データを取得する。

    Attributes:
        session: Bybit HTTP セッション
        symbol: 取引ペア（デフォルト: BTCUSDT）
    """

    def __init__(
        self,
        api_key: str | None = None,
        api_secret: str | None = None,
        testnet: bool = False,
        symbol: str = "BTCUSDT",
    ) -> None:
        """初期化.

        Args:
            api_key: Bybit API Key（未指定時は環境変数から取得）
            api_secret: Bybit API Secret（未指定時は環境変数から取得）
            testnet: テストネットを使用するか
            symbol: 取引ペア
        """
        self.symbol = symbol
        self._api_key = api_key or settings.BYBIT_API_KEY
        self._api_secret = api_secret or settings.BYBIT_API_SECRET

        # HTTP セッションを作成
        self.session = HTTP(
            testnet=testnet,
            api_key=self._api_key if self._api_key else None,
            api_secret=self._api_secret if self._api_secret else None,
        )
        logger.info(
            f"Bybit client initialized for {symbol} "
            f"(testnet={testnet}, authenticated={bool(self._api_key)})"
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
    )
    def get_kline(
        self,
        timeframe: str = "D",
        limit: int = 200,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> pd.DataFrame:
        """ローソク足データを取得.

        Args:
            timeframe: 時間足 ("D", "W", "M")
            limit: 取得する足の数（最大1000）
            start_time: 開始時刻（ミリ秒タイムスタンプ）
            end_time: 終了時刻（ミリ秒タイムスタンプ）

        Returns:
            OHLCVデータを含むDataFrame

        Raises:
            ValueError: 無効な時間足が指定された場合
            ConnectionError: API接続エラー
        """
        # 時間足を変換
        interval = TIMEFRAME_MAP.get(timeframe)
        if not interval:
            raise ValueError(
                f"Invalid timeframe: {timeframe}. "
                f"Valid options: {list(TIMEFRAME_MAP.keys())}"
            )

        logger.debug(
            f"Fetching {self.symbol} kline data: "
            f"interval={interval}, limit={limit}"
        )

        try:
            response = self.session.get_kline(
                category="spot",
                symbol=self.symbol,
                interval=interval,
                limit=limit,
                start=start_time,
                end=end_time,
            )

            if response["retCode"] != 0:
                raise ConnectionError(
                    f"Bybit API error: {response['retMsg']} "
                    f"(code: {response['retCode']})"
                )

            # データをDataFrameに変換
            data = response["result"]["list"]
            if not data:
                logger.warning(f"No data returned for {self.symbol}")
                return pd.DataFrame()

            df = pd.DataFrame(
                data,
                columns=[
                    "timestamp",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "turnover",
                ],
            )

            # データ型を変換
            df["timestamp"] = pd.to_datetime(df["timestamp"].astype(int), unit="ms")
            for col in ["open", "high", "low", "close", "volume", "turnover"]:
                df[col] = df[col].astype(float)

            # 時間順にソート（APIは新しい順で返す）
            df = df.sort_values("timestamp").reset_index(drop=True)

            logger.info(
                f"Fetched {len(df)} {interval} candles for {self.symbol} "
                f"({df['timestamp'].min()} to {df['timestamp'].max()})"
            )

            return df

        except Exception as e:
            logger.error(f"Failed to fetch kline data: {e}")
            raise

    def get_multi_timeframe_data(
        self,
        timeframes: list[str] | None = None,
        lookback_days: int | None = None,
    ) -> dict[str, pd.DataFrame]:
        """複数の時間足データを取得.

        Args:
            timeframes: 取得する時間足のリスト（デフォルト: ["D", "W", "M"]）
            lookback_days: 過去何日分のデータを取得するか

        Returns:
            時間足をキー、DataFrameを値とする辞書
        """
        if timeframes is None:
            timeframes = ["D", "W", "M"]

        result = {}
        for tf in timeframes:
            interval = TIMEFRAME_MAP.get(tf, tf)
            days = lookback_days or DEFAULT_LOOKBACK_DAYS.get(interval, 365)

            # 期間を計算
            end_time = int(datetime.now().timestamp() * 1000)
            start_time = int(
                (datetime.now() - timedelta(days=days)).timestamp() * 1000
            )

            # limitを計算（余裕を持って取得）
            if interval == "D":
                limit = min(days + 10, 1000)
            elif interval == "W":
                limit = min(days // 7 + 10, 1000)
            else:  # M
                limit = min(days // 30 + 10, 200)

            df = self.get_kline(
                timeframe=tf,
                limit=limit,
                start_time=start_time,
                end_time=end_time,
            )
            result[tf] = df

        return result

    def get_current_price(self) -> float:
        """現在価格を取得.

        Returns:
            現在のBTC価格（USD）
        """
        try:
            response = self.session.get_tickers(
                category="spot",
                symbol=self.symbol,
            )

            if response["retCode"] != 0:
                raise ConnectionError(f"Bybit API error: {response['retMsg']}")

            price = float(response["result"]["list"][0]["lastPrice"])
            logger.debug(f"Current {self.symbol} price: ${price:,.2f}")
            return price

        except Exception as e:
            logger.error(f"Failed to get current price: {e}")
            raise
