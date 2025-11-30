"""Twitter/X API クライアント.

ユーザーの投稿を取得し、Pineconeに保存して分析スタイル学習に活用する。
sync_tweets_to_pinecone.py スクリプトから使用される。

※ 自動投稿機能は実装しない（Webページの結果を見て手動で投稿する）
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import tweepy
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class Tweet:
    """ツイートデータ.

    Attributes:
        id: ツイートID
        text: ツイート本文
        created_at: 投稿日時
        hashtags: ハッシュタグリスト
        metrics: エンゲージメント指標
    """

    id: str
    text: str
    created_at: datetime
    hashtags: list[str] | None = None
    metrics: dict[str, int] | None = None

    def to_dict(self) -> dict[str, Any]:
        """辞書形式に変換."""
        return {
            "id": self.id,
            "text": self.text,
            "created_at": self.created_at.isoformat(),
            "hashtags": self.hashtags or [],
            "metrics": self.metrics,
        }


@dataclass
class TweetFetchResult:
    """ツイート取得結果.

    Attributes:
        tweets: 取得したツイートのリスト
        next_token: 次のページのトークン（Noneの場合は最後のページ）
        oldest_id: 取得した中で最も古いツイートID
        newest_id: 取得した中で最新のツイートID
        token_invalid: pagination_tokenが無効だった場合True
    """

    tweets: list[dict[str, Any]] = field(default_factory=list)
    next_token: str | None = None
    oldest_id: str | None = None
    newest_id: str | None = None
    token_invalid: bool = False

    @property
    def has_more(self) -> bool:
        """さらに過去のツイートが存在するか."""
        return self.next_token is not None


class TwitterClient:
    """Twitter/X API クライアント.

    ユーザーのツイートを取得し、Pineconeへの同期に使用する。
    """

    def __init__(
        self,
        bearer_token: str | None = None,
        target_username: str | None = None,
    ) -> None:
        """初期化.

        Args:
            bearer_token: Twitter Bearer Token（読み取り用）
            target_username: 取得対象のユーザー名
        """
        self._bearer_token = bearer_token or settings.TWITTER_BEARER_TOKEN
        self.target_username = target_username or settings.TWITTER_TARGET_USERNAME

        # 読み取り用クライアント（Bearer Token）
        if self._bearer_token and "your_" not in self._bearer_token.lower():
            self.client = tweepy.Client(bearer_token=self._bearer_token)
            self._is_configured = True
            logger.info(f"Twitter read client initialized for @{self.target_username}")
        else:
            logger.warning(
                "Twitter Bearer Token not configured. "
                "Twitter read features will not work."
            )
            self.client = None
            self._is_configured = False

    @property
    def is_configured(self) -> bool:
        """クライアントが設定されているか."""
        return self._is_configured

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def get_user_tweets(
        self,
        username: str | None = None,
        max_results: int = 100,
        since_id: str | None = None,
        pagination_token: str | None = None,
    ) -> TweetFetchResult:
        """ユーザーのツイートを取得.

        Args:
            username: ユーザー名（未指定時はtarget_usernameを使用）
            max_results: 取得する最大ツイート数（最大100）
            since_id: このID以降のツイートのみ取得（新しいツイート用）
            pagination_token: ページネーショントークン（過去ツイート取得用）

        Returns:
            TweetFetchResult: ツイートと次のページトークンを含む結果
        """
        if not self.client:
            logger.error("Twitter client not initialized")
            return TweetFetchResult()

        username = username or self.target_username

        try:
            # ユーザーIDを取得
            user = self.client.get_user(username=username)
            if not user.data:
                logger.error(f"User not found: @{username}")
                return TweetFetchResult()

            user_id = user.data.id

            # ツイートを取得
            kwargs: dict[str, Any] = {
                "id": user_id,
                "max_results": min(max_results, 100),
                "tweet_fields": ["created_at", "public_metrics", "text", "entities"],
                "exclude": ["retweets", "replies"],
            }

            if since_id:
                kwargs["since_id"] = since_id

            if pagination_token:
                kwargs["pagination_token"] = pagination_token

            tweets_response = self.client.get_users_tweets(**kwargs)

            if not tweets_response.data:
                logger.info(f"No tweets found for @{username}")
                return TweetFetchResult()

            tweets = []
            oldest_id = None
            newest_id = None

            for tweet in tweets_response.data:
                # ハッシュタグを抽出
                hashtags = []
                if tweet.entities and "hashtags" in tweet.entities:
                    hashtags = [ht["tag"] for ht in tweet.entities["hashtags"]]

                tweet_id = str(tweet.id)
                tweets.append({
                    "id": tweet_id,
                    "text": tweet.text,
                    "created_at": tweet.created_at.isoformat() if tweet.created_at else "",
                    "hashtags": hashtags,
                    "metrics": dict(tweet.public_metrics) if tweet.public_metrics else None,
                })

                # oldest_id と newest_id を追跡
                if oldest_id is None or int(tweet_id) < int(oldest_id):
                    oldest_id = tweet_id
                if newest_id is None or int(tweet_id) > int(newest_id):
                    newest_id = tweet_id

            # 次のページトークンを取得
            next_token = None
            if tweets_response.meta and "next_token" in tweets_response.meta:
                next_token = tweets_response.meta["next_token"]

            logger.info(
                f"Fetched {len(tweets)} tweets from @{username}"
                f"{' (has more)' if next_token else ' (last page)'}"
            )

            return TweetFetchResult(
                tweets=tweets,
                next_token=next_token,
                oldest_id=oldest_id,
                newest_id=newest_id,
            )

        except tweepy.TweepyException as e:
            error_msg = str(e)
            # pagination_tokenが無効な場合のエラーを検出
            if "pagination_token" in error_msg.lower() or "invalid" in error_msg.lower():
                logger.warning(
                    f"Pagination token may be invalid or expired: {e}. "
                    "Returning empty result to trigger token reset."
                )
                return TweetFetchResult(token_invalid=True)
            logger.error(f"Twitter API error: {e}")
            return TweetFetchResult()
        except Exception as e:
            logger.error(f"Failed to fetch tweets: {e}")
            raise
