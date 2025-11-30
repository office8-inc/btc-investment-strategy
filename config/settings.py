"""アプリケーション設定.

環境変数から設定を読み込み、型安全なアクセスを提供する。
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """アプリケーション設定クラス.

    環境変数または .env ファイルから設定を読み込む。
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # --- Bybit API ---
    BYBIT_API_KEY: str = Field(default="", description="Bybit API Key")
    BYBIT_API_SECRET: str = Field(default="", description="Bybit API Secret")
    BYBIT_BASE_URL: str = Field(
        default="https://api.bybit.com",
        description="Bybit API Base URL",
    )

    # --- OpenAI API ---
    OPENAI_API_KEY: str = Field(default="", description="OpenAI API Key")
    OPENAI_MODEL: str = Field(
        default="gpt-4o",
        description="OpenAI Model Name",
    )

    # --- Pinecone ---
    PINECONE_API_KEY: str = Field(default="", description="Pinecone API Key")
    PINECONE_ENVIRONMENT: str = Field(
        default="us-east-1-aws",
        description="Pinecone Environment",
    )
    PINECONE_INDEX_NAME: str = Field(
        default="bitcoin",
        description="Pinecone Index Name",
    )

    # --- Twitter/X API（Pinecone同期用） ---
    TWITTER_BEARER_TOKEN: str = Field(default="", description="Twitter Bearer Token")
    TWITTER_TARGET_USERNAME: str = Field(
        default="DriftSeiya",
        description="Target Twitter Username（過去投稿をPineconeに同期して分析スタイル学習に使用）",
    )

    # --- TradingView ---
    TRADINGVIEW_WEBHOOK_URL: str = Field(
        default="",
        description="TradingView Webhook URL",
    )
    TRADINGVIEW_WEBHOOK_SECRET: str = Field(
        default="",
        description="TradingView Webhook Secret",
    )

    # --- News & Market Data APIs ---

    CRYPTOCOMPARE_NEWS_URL: str = Field(
        default="https://min-api.cryptocompare.com/data/v2/news/",
        description="CryptoCompare News API URL",
    )
    FEAR_GREED_API_URL: str = Field(
        default="https://api.alternative.me/fng/",
        description="Fear & Greed Index API URL",
    )
    COINGECKO_API_URL: str = Field(
        default="https://api.coingecko.com/api/v3",
        description="CoinGecko API URL",
    )

    # --- US Financial Market Data APIs ---
    ALPHA_VANTAGE_API_KEY: str = Field(
        default="",
        description="Alpha Vantage API Key",
    )
    POLYGON_API_KEY: str = Field(
        default="",
        description="Polygon.io API Key",
    )
    FINNHUB_API_KEY: str = Field(
        default="",
        description="Finnhub API Key",
    )
    FRED_API_KEY: str = Field(
        default="",
        description="FRED API Key",
    )

    # --- XSERVER FTP ---
    XSERVER_FTP_HOST: str = Field(
        default="",
        description="XSERVER FTP Host (e.g., office8-inc.xsrv.jp)",
    )
    XSERVER_FTP_PORT: int = Field(
        default=21,
        description="XSERVER FTP Port",
    )
    XSERVER_FTP_USER: str = Field(
        default="",
        description="XSERVER FTP Username",
    )
    XSERVER_FTP_PASSWORD: str = Field(
        default="",
        description="XSERVER FTP Password",
    )
    XSERVER_REMOTE_DIR: str = Field(
        default="/office8-inc.com/public_html/btc-analysis",
        description="XSERVER Remote Directory Path",
    )
    XSERVER_PUBLIC_URL: str = Field(
        default="",
        description="Public URL for the hosted page (e.g., https://office8-inc.com/btc-analysis)",
    )

    # --- 実行設定 ---
    ANALYSIS_SCHEDULE_HOUR: int = Field(
        default=9,
        ge=0,
        le=23,
        description="Analysis Schedule Hour (0-23)",
    )
    ANALYSIS_SCHEDULE_MINUTE: int = Field(
        default=0,
        ge=0,
        le=59,
        description="Analysis Schedule Minute (0-59)",
    )
    TIMEZONE: str = Field(default="Asia/Tokyo", description="Timezone")

    # --- ログ設定 ---
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description="Log Level",
    )

    @field_validator("BYBIT_API_KEY", "OPENAI_API_KEY")
    @classmethod
    def check_not_placeholder(cls, v: str, info) -> str:
        """プレースホルダー値でないことを確認."""
        placeholders = ["your_", "sk-your_", "xxx"]
        if any(placeholder in v.lower() for placeholder in placeholders):
            # 警告を出すが、エラーにはしない（開発時のため）
            import logging

            logging.warning(
                f"{info.field_name} appears to be a placeholder value. "
                "Please set a valid API key in .env file."
            )
        return v

    @property
    def is_bybit_configured(self) -> bool:
        """Bybit APIが設定されているか."""
        return bool(self.BYBIT_API_KEY and self.BYBIT_API_SECRET)

    @property
    def is_openai_configured(self) -> bool:
        """OpenAI APIが設定されているか."""
        return bool(self.OPENAI_API_KEY) and "your_" not in self.OPENAI_API_KEY.lower()

    @property
    def is_pinecone_configured(self) -> bool:
        """Pineconeが設定されているか."""
        return bool(self.PINECONE_API_KEY)

    @property
    def is_twitter_configured(self) -> bool:
        """Twitter API（読み取り）が設定されているか."""
        return bool(self.TWITTER_BEARER_TOKEN)

    @property
    def is_xserver_configured(self) -> bool:
        """XSERVER FTPが設定されているか."""
        return bool(
            self.XSERVER_FTP_HOST
            and self.XSERVER_FTP_USER
            and self.XSERVER_FTP_PASSWORD
            and "your_" not in self.XSERVER_FTP_HOST.lower()
        )


@lru_cache
def get_settings() -> Settings:
    """設定のシングルトンインスタンスを取得.

    Returns:
        Settings: 設定インスタンス
    """
    return Settings()


# グローバルな設定インスタンス
settings = get_settings()
