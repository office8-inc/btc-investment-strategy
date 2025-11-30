"""FRED (Federal Reserve Economic Data) API クライアント.

米国経済指標データを取得する。
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import settings

logger = logging.getLogger(__name__)

# 重要な経済指標のシリーズID
IMPORTANT_SERIES = {
    "DFF": "Federal Funds Rate（フェデラルファンド金利）",
    "T10Y2Y": "10年-2年国債スプレッド（逆イールド指標）",
    "UNRATE": "失業率",
    "CPIAUCSL": "消費者物価指数（CPI）",
    "M2SL": "M2マネーサプライ",
    "DTWEXBGS": "米ドル指数（広義）",
    "VIXCLS": "VIX指数（恐怖指数）",
    "SP500": "S&P 500",
}


@dataclass
class EconomicIndicator:
    """経済指標データ.

    Attributes:
        series_id: シリーズID
        name: 指標名
        value: 最新値
        date: データ日時
        units: 単位
        previous_value: 前回値
        change: 変化
    """

    series_id: str
    name: str
    value: float
    date: datetime
    units: str
    previous_value: float | None = None
    change: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """辞書形式に変換."""
        return {
            "series_id": self.series_id,
            "name": self.name,
            "value": self.value,
            "date": self.date.isoformat(),
            "units": self.units,
            "previous_value": self.previous_value,
            "change": self.change,
        }


class FREDClient:
    """FRED API クライアント.

    米国連邦準備制度理事会の経済データを取得する。
    """

    BASE_URL = "https://api.stlouisfed.org/fred"

    def __init__(self, api_key: str | None = None) -> None:
        """初期化.

        Args:
            api_key: FRED API Key
        """
        self._api_key = api_key or settings.FRED_API_KEY
        self._is_configured = bool(
            self._api_key and "your_" not in self._api_key.lower()
        )

        if not self._is_configured:
            logger.warning(
                "FRED API key not configured. "
                "Economic data features will be limited."
            )
        else:
            logger.info("FRED client initialized")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def get_series(
        self,
        series_id: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """経済指標のデータを取得.

        Args:
            series_id: シリーズID
            limit: 取得するデータ数

        Returns:
            データリスト
        """
        if not self._is_configured:
            logger.warning("FRED API key not configured")
            return []

        try:
            with httpx.Client(timeout=30) as client:
                response = client.get(
                    f"{self.BASE_URL}/series/observations",
                    params={
                        "series_id": series_id,
                        "api_key": self._api_key,
                        "file_type": "json",
                        "sort_order": "desc",
                        "limit": limit,
                    },
                )
                response.raise_for_status()
                data = response.json()

            observations = []
            for obs in data.get("observations", []):
                if obs.get("value") and obs["value"] != ".":
                    observations.append({
                        "date": obs.get("date"),
                        "value": float(obs.get("value")),
                    })

            logger.debug(f"Fetched {len(observations)} observations for {series_id}")
            return observations

        except httpx.HTTPStatusError as e:
            logger.error(f"FRED API error for {series_id}: {e.response.status_code}")
            return []
        except Exception as e:
            logger.error(f"Failed to fetch FRED series {series_id}: {e}")
            return []

    def get_federal_funds_rate(self) -> EconomicIndicator | None:
        """フェデラルファンド金利を取得.

        Returns:
            経済指標データ
        """
        data = self.get_series("DFF", limit=2)
        if not data:
            return None

        return EconomicIndicator(
            series_id="DFF",
            name="Federal Funds Rate",
            value=data[0]["value"],
            date=datetime.fromisoformat(data[0]["date"]),
            units="Percent",
            previous_value=data[1]["value"] if len(data) > 1 else None,
            change=data[0]["value"] - data[1]["value"] if len(data) > 1 else None,
        )

    def get_treasury_spread(self) -> EconomicIndicator | None:
        """10年-2年国債スプレッドを取得（逆イールド指標）.

        Returns:
            経済指標データ
        """
        data = self.get_series("T10Y2Y", limit=2)
        if not data:
            return None

        return EconomicIndicator(
            series_id="T10Y2Y",
            name="10Y-2Y Treasury Spread",
            value=data[0]["value"],
            date=datetime.fromisoformat(data[0]["date"]),
            units="Percent",
            previous_value=data[1]["value"] if len(data) > 1 else None,
            change=data[0]["value"] - data[1]["value"] if len(data) > 1 else None,
        )

    def get_unemployment_rate(self) -> EconomicIndicator | None:
        """失業率を取得.

        Returns:
            経済指標データ
        """
        data = self.get_series("UNRATE", limit=2)
        if not data:
            return None

        return EconomicIndicator(
            series_id="UNRATE",
            name="Unemployment Rate",
            value=data[0]["value"],
            date=datetime.fromisoformat(data[0]["date"]),
            units="Percent",
            previous_value=data[1]["value"] if len(data) > 1 else None,
            change=data[0]["value"] - data[1]["value"] if len(data) > 1 else None,
        )

    def get_cpi(self) -> EconomicIndicator | None:
        """消費者物価指数（CPI）を取得.

        Returns:
            経済指標データ
        """
        data = self.get_series("CPIAUCSL", limit=2)
        if not data:
            return None

        # 前年同期比の変化率を計算するために12ヶ月分取得
        data_12m = self.get_series("CPIAUCSL", limit=13)
        yoy_change = None
        if len(data_12m) >= 13:
            yoy_change = ((data_12m[0]["value"] / data_12m[12]["value"]) - 1) * 100

        return EconomicIndicator(
            series_id="CPIAUCSL",
            name="Consumer Price Index",
            value=data[0]["value"],
            date=datetime.fromisoformat(data[0]["date"]),
            units="Index",
            previous_value=data[1]["value"] if len(data) > 1 else None,
            change=yoy_change,  # 前年同期比
        )

    def get_all_indicators(self) -> list[EconomicIndicator]:
        """全ての重要指標を取得.

        Returns:
            経済指標リスト
        """
        indicators = []

        ffr = self.get_federal_funds_rate()
        if ffr:
            indicators.append(ffr)

        spread = self.get_treasury_spread()
        if spread:
            indicators.append(spread)

        unemployment = self.get_unemployment_rate()
        if unemployment:
            indicators.append(unemployment)

        cpi = self.get_cpi()
        if cpi:
            indicators.append(cpi)

        return indicators

    def get_economic_summary(self) -> str:
        """経済サマリーを生成.

        Returns:
            経済サマリー文字列
        """
        indicators = self.get_all_indicators()

        if not indicators:
            return "FRED経済データを取得できませんでした。"

        parts = ["【FRED 米国経済指標】", ""]

        for ind in indicators:
            change_str = ""
            if ind.change is not None:
                change_str = f" ({ind.change:+.2f}%)" if "CPI" in ind.name else f" ({ind.change:+.2f})"

            parts.append(f"{ind.name}: {ind.value:.2f}{ind.units[:1]}{change_str}")

            # 特別なコメント
            if ind.series_id == "T10Y2Y" and ind.value < 0:
                parts.append("  ⚠️ 逆イールド発生中（景気後退シグナル）")
            elif ind.series_id == "DFF":
                if ind.change and ind.change > 0:
                    parts.append("  📈 金利引き上げ傾向")
                elif ind.change and ind.change < 0:
                    parts.append("  📉 金利引き下げ傾向")

        return "\n".join(parts)
