"""Pinecone ベクトルDB クライアント.

ユーザーのX投稿を保存し、類似検索を行う。
過去の分析スタイルを学習するために使用。
"""

import logging
from datetime import datetime
from typing import Any

from openai import OpenAI
from pinecone import Pinecone, ServerlessSpec
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import settings

logger = logging.getLogger(__name__)


class PineconeClient:
    """Pinecone ベクトルDB クライアント.

    ユーザーのX投稿をベクトル化して保存し、
    類似検索を行うことで分析スタイルを学習する。
    """

    DIMENSION = 1536  # OpenAI text-embedding-3-small の次元数

    def __init__(
        self,
        api_key: str | None = None,
        index_name: str | None = None,
        openai_api_key: str | None = None,
    ) -> None:
        """初期化.

        Args:
            api_key: Pinecone API Key
            index_name: インデックス名
            openai_api_key: OpenAI API Key（埋め込み生成用）
        """
        self._api_key = api_key or settings.PINECONE_API_KEY
        self._index_name = index_name or settings.PINECONE_INDEX_NAME
        self._openai_key = openai_api_key or settings.OPENAI_API_KEY

        self._is_configured = bool(
            self._api_key and "your_" not in self._api_key.lower()
        )

        if not self._is_configured:
            logger.warning(
                "Pinecone API key not configured. "
                "Vector DB features will not work."
            )
            self.pc = None
            self.index = None
            self.openai_client = None
            return

        # Pinecone クライアントを初期化
        self.pc = Pinecone(api_key=self._api_key)

        # インデックスを取得または作成
        self._ensure_index()

        # OpenAI クライアント（埋め込み生成用）
        if self._openai_key and "your_" not in self._openai_key.lower():
            self.openai_client = OpenAI(api_key=self._openai_key)
        else:
            self.openai_client = None
            logger.warning("OpenAI API key not configured for embeddings")

    @property
    def is_configured(self) -> bool:
        """クライアントが正しく設定されているか."""
        return self._is_configured and self.index is not None

    def _ensure_index(self) -> None:
        """インデックスが存在することを確認."""
        if not self.pc:
            return

        existing_indexes = [idx.name for idx in self.pc.list_indexes()]

        if self._index_name not in existing_indexes:
            logger.info(f"Creating Pinecone index: {self._index_name}")
            self.pc.create_index(
                name=self._index_name,
                dimension=self.DIMENSION,
                metric="cosine",
                spec=ServerlessSpec(
                    cloud="aws",
                    region="us-east-1",
                ),
            )

        self.index = self.pc.Index(self._index_name)
        logger.info(f"Connected to Pinecone index: {self._index_name}")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def _get_embedding(self, text: str) -> list[float]:
        """テキストの埋め込みベクトルを取得.

        Args:
            text: 埋め込み対象テキスト

        Returns:
            埋め込みベクトル
        """
        if not self.openai_client:
            raise RuntimeError("OpenAI client not configured")

        response = self.openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=text,
        )

        return response.data[0].embedding

    def upsert_tweet(
        self,
        tweet_id: str,
        text: str,
        created_at: datetime,
        hashtags: list[str] | None = None,
        btc_price: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """X投稿をベクトルDBに保存.

        Args:
            tweet_id: ツイートID
            text: ツイート本文
            created_at: 投稿日時
            hashtags: ハッシュタグリスト
            btc_price: 投稿時のBTC価格（任意）
            metadata: 追加メタデータ

        Returns:
            成功した場合True
        """
        if not self.index or not self.openai_client:
            logger.error("Pinecone or OpenAI client not configured")
            return False

        try:
            # ツイート本文から埋め込みを生成
            embedding = self._get_embedding(text)

            # メタデータを準備
            # メタデータを準備（予測生成時に使いやすい形式）
            meta: dict[str, Any] = {
                "text": text[:1000],  # Pineconeメタデータ制限対応
                "created_at": created_at.isoformat(),
                "created_date": created_at.strftime("%Y-%m-%d"),  # 日付のみ
                "type": "tweet",
                "year": created_at.year,
                "month": created_at.month,
            }

            if hashtags:
                meta["hashtags"] = hashtags[:10]  # 最大10個
                meta["hashtags_str"] = ", ".join(hashtags[:10])  # 文字列形式

            if btc_price is not None:
                meta["btc_price"] = btc_price

            if metadata:
                meta.update(metadata)

            # Upsert
            self.index.upsert(
                vectors=[
                    {
                        "id": f"tweet_{tweet_id}",
                        "values": embedding,
                        "metadata": meta,
                    }
                ]
            )

            logger.info(f"Upserted tweet: {tweet_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to upsert tweet: {e}")
            return False

    def upsert_tweets_batch(
        self,
        tweets: list[dict[str, Any]],
        batch_size: int = 100,
    ) -> int:
        """複数のX投稿をバッチでベクトルDBに保存.

        Args:
            tweets: ツイートのリスト（各要素は以下のキーを含む）
                - tweet_id: str
                - text: str
                - created_at: datetime
                - hashtags: list[str] | None
                - btc_price: float | None
            batch_size: 一度に処理する件数

        Returns:
            保存成功した件数
        """
        if not self.index or not self.openai_client:
            logger.error("Pinecone or OpenAI client not configured")
            return 0

        success_count = 0

        for i in range(0, len(tweets), batch_size):
            batch = tweets[i : i + batch_size]
            vectors = []

            for tweet in batch:
                try:
                    embedding = self._get_embedding(tweet["text"])

                    created_at = tweet["created_at"]
                    meta: dict[str, Any] = {
                        "text": tweet["text"][:1000],
                        "created_at": created_at.isoformat(),
                        "created_date": created_at.strftime("%Y-%m-%d"),
                        "type": "tweet",
                        "year": created_at.year,
                        "month": created_at.month,
                    }

                    if tweet.get("hashtags"):
                        meta["hashtags"] = tweet["hashtags"][:10]
                        meta["hashtags_str"] = ", ".join(tweet["hashtags"][:10])

                    if tweet.get("btc_price") is not None:
                        meta["btc_price"] = tweet["btc_price"]

                    vectors.append({
                        "id": f"tweet_{tweet['tweet_id']}",
                        "values": embedding,
                        "metadata": meta,
                    })

                except Exception as e:
                    logger.error(f"Failed to process tweet {tweet.get('tweet_id')}: {e}")
                    continue

            if vectors:
                try:
                    self.index.upsert(vectors=vectors)
                    success_count += len(vectors)
                    logger.info(f"Upserted batch of {len(vectors)} tweets")
                except Exception as e:
                    logger.error(f"Failed to upsert batch: {e}")

        return success_count

    def search_similar_tweets(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.7,
    ) -> list[dict[str, Any]]:
        """類似するX投稿を検索.

        Args:
            query: 検索クエリ（現在の市場状況など）
            top_k: 取得する件数
            min_score: 最小スコア閾値

        Returns:
            類似投稿のリスト
        """
        if not self.index or not self.openai_client:
            logger.error("Pinecone or OpenAI client not configured")
            return []

        try:
            # クエリの埋め込みを生成
            query_embedding = self._get_embedding(query)

            # ツイートタイプでフィルタ
            filter_dict = {"type": {"$eq": "tweet"}}

            # 検索
            results = self.index.query(
                vector=query_embedding,
                top_k=top_k,
                include_metadata=True,
                filter=filter_dict,
            )

            similar_tweets = []
            for match in results.matches:
                if match.score >= min_score:
                    similar_tweets.append({
                        "id": match.id,
                        "score": match.score,
                        "text": match.metadata.get("text", ""),
                        "created_at": match.metadata.get("created_at", ""),
                        "hashtags": match.metadata.get("hashtags", []),
                        "btc_price": match.metadata.get("btc_price"),
                    })

            logger.info(f"Found {len(similar_tweets)} similar tweets")
            return similar_tweets

        except Exception as e:
            logger.error(f"Failed to search similar tweets: {e}")
            return []

    def search_by_market_context(
        self,
        price_change_pct: float,
        trend: str,
        fear_greed_index: int | None = None,
        keywords: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """現在の市場状況に類似する過去のX投稿を検索.

        Args:
            price_change_pct: 価格変化率
            trend: トレンド方向（bullish/bearish/neutral）
            fear_greed_index: Fear & Greed Index値（0-100）
            keywords: 追加キーワード

        Returns:
            類似投稿のリスト
        """
        # クエリを構築
        query_parts = [
            f"ビットコイン 価格{abs(price_change_pct):.1f}%{'上昇' if price_change_pct > 0 else '下落'}",
            f"トレンド: {trend}",
        ]

        if fear_greed_index is not None:
            if fear_greed_index < 25:
                sentiment = "極度の恐怖"
            elif fear_greed_index < 45:
                sentiment = "恐怖"
            elif fear_greed_index < 55:
                sentiment = "中立"
            elif fear_greed_index < 75:
                sentiment = "強欲"
            else:
                sentiment = "極度の強欲"
            query_parts.append(f"市場心理: {sentiment}")

        if keywords:
            query_parts.append(f"キーワード: {', '.join(keywords)}")

        query = " ".join(query_parts)

        return self.search_similar_tweets(query, top_k=5, min_score=0.65)

    def get_similar_posts_for_prediction(
        self,
        current_price: float,
        price_change_24h_pct: float,
        trend: str,
        fear_greed_index: int | None = None,
        top_k: int = 5,
    ) -> dict[str, Any]:
        """予測生成用に整理された類似投稿データを取得.

        Args:
            current_price: 現在のBTC価格
            price_change_24h_pct: 24時間価格変化率
            trend: トレンド方向（bullish/bearish/neutral）
            fear_greed_index: Fear & Greed Index値（0-100）
            top_k: 取得する件数

        Returns:
            予測プロンプト用に整理されたデータ:
            {
                "found": bool,
                "count": int,
                "posts": [
                    {
                        "date": "2025-01-15",
                        "text": "投稿内容...",
                        "btc_price": 95000,
                        "relevance_score": 0.85,
                    }
                ],
                "summary": "類似状況での過去分析の要約テキスト",
                "context_for_prompt": "プロンプトに挿入用の整形済みテキスト"
            }
        """
        similar_tweets = self.search_by_market_context(
            price_change_pct=price_change_24h_pct,
            trend=trend,
            fear_greed_index=fear_greed_index,
        )

        if not similar_tweets:
            return {
                "found": False,
                "count": 0,
                "posts": [],
                "summary": "",
                "context_for_prompt": "",
            }

        # 予測用に整理
        posts = []
        for tweet in similar_tweets[:top_k]:
            posts.append({
                "date": tweet.get("created_at", "")[:10],  # YYYY-MM-DD
                "text": tweet.get("text", ""),
                "btc_price": tweet.get("btc_price"),
                "relevance_score": round(tweet.get("score", 0), 3),
            })

        # プロンプト用コンテキストを生成
        context_lines = ["【過去の類似状況での分析投稿】"]
        for i, post in enumerate(posts, 1):
            price_info = f"(BTC: ${post['btc_price']:,.0f})" if post['btc_price'] else ""
            context_lines.append(
                f"{i}. [{post['date']}] {price_info}\n   {post['text'][:200]}..."
                if len(post['text']) > 200 else
                f"{i}. [{post['date']}] {price_info}\n   {post['text']}"
            )

        context_for_prompt = "\n".join(context_lines)

        # サマリー生成
        summary = (
            f"類似の市場状況で{len(posts)}件の過去投稿が見つかりました。"
            f"関連度スコア: {posts[0]['relevance_score']:.0%}～{posts[-1]['relevance_score']:.0%}"
        )

        return {
            "found": True,
            "count": len(posts),
            "posts": posts,
            "summary": summary,
            "context_for_prompt": context_for_prompt,
        }

    def get_tweet_count(self) -> int:
        """保存されているツイートの総数を取得.

        Returns:
            ツイート数
        """
        if not self.index:
            return 0

        try:
            stats = self.index.describe_index_stats()
            return stats.total_vector_count
        except Exception as e:
            logger.error(f"Failed to get tweet count: {e}")
            return 0

    def delete_tweet(self, tweet_id: str) -> bool:
        """投稿を削除.

        Args:
            tweet_id: 削除するツイートID

        Returns:
            成功した場合True
        """
        if not self.index:
            return False

        try:
            self.index.delete(ids=[f"tweet_{tweet_id}"])
            logger.info(f"Deleted tweet: {tweet_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete tweet: {e}")
            return False
