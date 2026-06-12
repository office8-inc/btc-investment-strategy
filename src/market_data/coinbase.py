"""Coinbase Exchange API クライアント.

ビットコインの日足OHLCデータを取得する（認証不要のpublic API）。

CryptoCompare (min-api) が2026年6月にAPIキー必須化されたため、
認証不要で安定して日足データを取得できるCoinbase Exchange APIを
一次ソースとして使用する。
"""

import logging
from datetime import datetime, timedelta, timezone

import httpx
import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

# Coinbase Exchange API Base URL（認証不要のpublicエンドポイント）
COINBASE_API_URL = "https://api.exchange.coinbase.com"

# 1リクエストあたりの最大ローソク足数（API仕様）
MAX_CANDLES_PER_REQUEST = 300

# 日足の秒数
GRANULARITY_DAILY = 86400


class CoinbaseClient:
    """Coinbase Exchange API クライアント.

    ビットコインの日足OHLCデータを取得する（認証不要）。
    """

    def __init__(self, base_url: str | None = None) -> None:
        """初期化.

        Args:
            base_url: API Base URL
        """
        self._base_url = base_url or COINBASE_API_URL
        logger.info("Coinbase client initialized")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def _fetch_candles(
        self, start: datetime, end: datetime, product_id: str = "BTC-USD"
    ) -> list[list[float]]:
        """指定期間の日足ローソクを取得（最大300本）.

        Args:
            start: 取得開始日時（UTC）
            end: 取得終了日時（UTC）
            product_id: 取引ペア

        Returns:
            ローソク足リスト [[time, low, high, open, close, volume], ...]（新しい順）
        """
        with httpx.Client(timeout=30) as client:
            response = client.get(
                f"{self._base_url}/products/{product_id}/candles",
                params={
                    "granularity": GRANULARITY_DAILY,
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                },
            )
            response.raise_for_status()
            return response.json()

    def get_ohlc_dataframe(self, days: int = 365) -> pd.DataFrame | None:
        """ビットコインの日足OHLCデータをDataFrame形式で取得.

        1リクエスト最大300本の制限があるため、必要に応じて
        複数リクエストに分割して取得する。

        Args:
            days: 取得する日数

        Returns:
            OHLCVデータを含むDataFrame (columns: timestamp, open, high, low, close, volume)
            取得失敗時はNone
        """
        try:
            end = datetime.now(timezone.utc)
            start = end - timedelta(days=days)

            all_candles: list[list[float]] = []
            chunk_start = start
            while chunk_start < end:
                chunk_end = min(
                    chunk_start + timedelta(days=MAX_CANDLES_PER_REQUEST), end
                )
                candles = self._fetch_candles(chunk_start, chunk_end)
                all_candles.extend(candles)
                chunk_start = chunk_end

            if not all_candles:
                logger.warning("Coinbase OHLC: No data returned")
                return None

            df = pd.DataFrame(
                all_candles,
                columns=["time", "low", "high", "open", "close", "volume"],
            )

            # タイムスタンプをdatetimeに変換
            df["timestamp"] = pd.to_datetime(df["time"], unit="s", utc=True)

            # 列の順序を整理
            df = df[["timestamp", "open", "high", "low", "close", "volume"]]

            # 重複除去 + 時系列順にソート
            df = (
                df.drop_duplicates(subset="timestamp")
                .sort_values("timestamp")
                .reset_index(drop=True)
            )

            logger.info(f"Created OHLC DataFrame with {len(df)} rows from Coinbase")
            return df

        except httpx.HTTPStatusError as e:
            logger.error(f"Coinbase OHLC API error: {e.response.status_code}")
            return None
        except Exception as e:
            logger.error(f"Failed to fetch Coinbase OHLC data: {e}")
            return None
