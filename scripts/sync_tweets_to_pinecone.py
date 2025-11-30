"""X投稿をPineconeに同期するスクリプト.

ユーザーの#ビットコイン投稿を取得し、Pineconeに保存する。
X API Free Tier制限（1500 tweets/月）のため、手動実行を推奨。

※ Twitter APIはデフォルトで新しい順に取得されます。

動作モード:
1. 初回/過去取得モード: pagination_tokenを使って過去投稿を遡って取得
2. 差分取得モード: 全過去投稿取得完了後、since_idで新規投稿のみ取得

使用方法:
    # 状態確認
    python scripts/sync_tweets_to_pinecone.py --status

    # 過去投稿を100件取得（新しい順）
    python scripts/sync_tweets_to_pinecone.py --max-tweets 100

    # すべての過去投稿を一括取得（API制限に注意）
    python scripts/sync_tweets_to_pinecone.py --fetch-all
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config.settings import settings
from src.twitter.client import TwitterClient
from src.vector_db.pinecone_client import PineconeClient

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# 同期状態ファイル
SYNC_STATE_FILE = project_root / "data" / "tweet_sync_state.json"


def load_sync_state() -> dict:
    """同期状態を読み込む.

    Returns:
        同期状態の辞書。以下のキーを含む:
        - newest_synced_tweet_id: 同期済み最新ツイートID（差分取得用）
        - oldest_synced_tweet_id: 同期済み最古ツイートID（重複防止用）
        - pagination_token: 次の過去ページ取得用トークン
        - all_historical_collected: 過去投稿をすべて取得済みか
        - total_synced_count: 累計同期数
        - last_sync_date: 最終同期日時
        - monthly_api_calls: 月間API呼び出し数
        - api_call_month: API呼び出しカウントの対象月
    """
    if SYNC_STATE_FILE.exists():
        with open(SYNC_STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
            # 月が変わったらAPI呼び出しカウントをリセット
            current_month = datetime.now().strftime("%Y-%m")
            if state.get("api_call_month") != current_month:
                state["monthly_api_calls"] = 0
                state["api_call_month"] = current_month
            return state
    return {
        "newest_synced_tweet_id": None,
        "oldest_synced_tweet_id": None,
        "pagination_token": None,
        "all_historical_collected": False,
        "total_synced_count": 0,
        "last_sync_date": None,
        "monthly_api_calls": 0,
        "api_call_month": datetime.now().strftime("%Y-%m"),
    }


def save_sync_state(state: dict) -> None:
    """同期状態を保存する."""
    SYNC_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SYNC_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def filter_tweets_by_hashtag(
    tweets: list[dict],
    hashtag: str = "#ビットコイン",
    include_btc: bool = True,
) -> list[dict]:
    """ハッシュタグでツイートをフィルタリング.

    Args:
        tweets: ツイートのリスト
        hashtag: 対象ハッシュタグ
        include_btc: #BTC, #Bitcoinも含めるか

    Returns:
        フィルタリング後のツイートリスト
    """
    target_tags = [hashtag.lower()]
    if include_btc:
        target_tags.extend(["#btc", "#bitcoin"])

    filtered_tweets = []
    for tweet in tweets:
        tweet_text_lower = tweet.get("text", "").lower()
        tweet_hashtags = [
            f"#{tag.lower()}" for tag in tweet.get("hashtags", [])
        ]

        # ハッシュタグが含まれているかチェック
        has_target_tag = any(
            tag in tweet_text_lower or tag in tweet_hashtags
            for tag in target_tags
        )

        if has_target_tag:
            filtered_tweets.append(tweet)

    return filtered_tweets


def sync_tweets(
    max_tweets: int = 100,
    hashtag: str = "#ビットコイン",
    include_btc: bool = True,
    fetch_all: bool = False,
) -> dict:
    """X投稿をPineconeに同期.

    Twitter APIはデフォルトで新しい順に返すため、
    pagination_tokenを使って過去へ遡ることができます。

    Args:
        max_tweets: 1回の実行で取得する最大ツイート数
        hashtag: 対象ハッシュタグ
        include_btc: #BTCタグも含めるか
        fetch_all: すべての過去投稿を一括取得するか

    Returns:
        同期結果
    """
    # クライアント初期化
    twitter_client = TwitterClient()
    pinecone_client = PineconeClient()

    if not twitter_client.is_configured:
        logger.error("Twitter client not configured")
        return {"success": False, "error": "Twitter client not configured"}

    if not pinecone_client.is_configured:
        logger.error("Pinecone client not configured")
        return {"success": False, "error": "Pinecone client not configured"}

    # 同期状態を読み込み
    state = load_sync_state()
    logger.info(f"Current sync state: {json.dumps(state, ensure_ascii=False, indent=2)}")

    all_historical_collected = state.get("all_historical_collected", False)
    total_synced_this_run = 0
    total_api_calls_this_run = 0

    if all_historical_collected and not fetch_all:
        # 差分取得モード: 新しいツイートのみ取得
        logger.info("📥 差分取得モード: 新しいツイートのみ取得します")
        result = twitter_client.get_user_tweets(
            username=settings.TWITTER_TARGET_USERNAME,
            max_results=min(max_tweets, 100),
            since_id=state.get("newest_synced_tweet_id"),
        )
        total_api_calls_this_run += len(result.tweets) if result.tweets else 0

        if not result.tweets:
            logger.info("新しいツイートはありません")
            state["last_sync_date"] = datetime.now().isoformat()
            save_sync_state(state)
            return {
                "success": True,
                "synced_count": 0,
                "message": "No new tweets found",
                "all_historical_collected": True,
            }

        # フィルタリング
        filtered = filter_tweets_by_hashtag(result.tweets, hashtag, include_btc)
        if filtered:
            synced = _save_tweets_to_pinecone(filtered, pinecone_client)
            total_synced_this_run = synced

            # 最新IDを更新
            if result.newest_id:
                state["newest_synced_tweet_id"] = result.newest_id

    else:
        # 過去取得モード: pagination_tokenを使って過去へ遡る
        logger.info("📚 過去取得モード: 過去のツイートを取得します")

        pages_fetched = 0
        max_pages = (max_tweets // 100) + 1 if not fetch_all else 100  # 最大100ページ

        while pages_fetched < max_pages:
            result = twitter_client.get_user_tweets(
                username=settings.TWITTER_TARGET_USERNAME,
                max_results=100,  # 1ページ最大100件
                pagination_token=state.get("pagination_token"),
            )
            pages_fetched += 1

            # pagination_tokenが無効な場合、トークンをリセットして最初から
            if result.token_invalid:
                logger.warning(
                    "⚠️ Pagination tokenが無効です。トークンをリセットして継続します。\n"
                    "   注意: 一部の投稿が重複する可能性がありますが、Pineconeで自動的に上書きされます。"
                )
                state["pagination_token"] = None
                # トークンなしで再取得を試みる
                result = twitter_client.get_user_tweets(
                    username=settings.TWITTER_TARGET_USERNAME,
                    max_results=100,
                )

            total_api_calls_this_run += len(result.tweets) if result.tweets else 0

            if not result.tweets:
                # すべて取得完了
                logger.info("✅ すべての過去ツイートを取得しました！")
                state["all_historical_collected"] = True
                state["pagination_token"] = None
                break

            # 最新IDを更新（初回のみ）
            if result.newest_id and not state.get("newest_synced_tweet_id"):
                state["newest_synced_tweet_id"] = result.newest_id

            # フィルタリング
            filtered = filter_tweets_by_hashtag(result.tweets, hashtag, include_btc)
            logger.info(
                f"  ページ {pages_fetched}: {len(result.tweets)}件取得 → "
                f"{len(filtered)}件がハッシュタグに一致"
            )

            if filtered:
                synced = _save_tweets_to_pinecone(filtered, pinecone_client)
                total_synced_this_run += synced

            # oldest_idを更新（重複防止用）
            if result.oldest_id:
                current_oldest = state.get("oldest_synced_tweet_id")
                if current_oldest is None or int(result.oldest_id) < int(current_oldest):
                    state["oldest_synced_tweet_id"] = result.oldest_id

            # 次のページトークンを保存
            if result.has_more:
                state["pagination_token"] = result.next_token
            else:
                logger.info("✅ すべての過去ツイートを取得しました！")
                state["all_historical_collected"] = True
                state["pagination_token"] = None
                break

            # fetch_allでない場合、max_tweetsに達したら終了
            if not fetch_all and total_api_calls_this_run >= max_tweets:
                logger.info(f"⏸️ {max_tweets}件の制限に達しました。次回実行で継続します。")
                break

    # 同期状態を更新
    state["total_synced_count"] = state.get("total_synced_count", 0) + total_synced_this_run
    state["monthly_api_calls"] = state.get("monthly_api_calls", 0) + total_api_calls_this_run
    state["last_sync_date"] = datetime.now().isoformat()
    save_sync_state(state)

    total_in_db = pinecone_client.get_tweet_count()

    logger.info(
        f"\n{'='*50}\n"
        f"同期完了サマリー:\n"
        f"  今回同期: {total_synced_this_run} 件\n"
        f"  今回API呼び出し: {total_api_calls_this_run} 件\n"
        f"  DB内合計: {total_in_db} 件\n"
        f"  過去取得完了: {state.get('all_historical_collected', False)}\n"
        f"{'='*50}"
    )

    return {
        "success": True,
        "synced_count": total_synced_this_run,
        "api_calls_this_run": total_api_calls_this_run,
        "total_in_db": total_in_db,
        "all_historical_collected": state.get("all_historical_collected", False),
        "monthly_api_calls": state.get("monthly_api_calls", 0),
    }


def _save_tweets_to_pinecone(
    tweets: list[dict],
    pinecone_client: PineconeClient,
) -> int:
    """ツイートをPineconeに保存.

    Args:
        tweets: 保存するツイートのリスト
        pinecone_client: Pineconeクライアント

    Returns:
        保存されたツイート数
    """
    tweets_for_pinecone = []
    for tweet in tweets:
        # created_at を datetime に変換
        created_at_str = tweet.get("created_at", "")
        try:
            created_at = datetime.fromisoformat(
                created_at_str.replace("Z", "+00:00")
            )
        except ValueError:
            created_at = datetime.now()

        tweets_for_pinecone.append({
            "tweet_id": tweet["id"],
            "text": tweet["text"],
            "created_at": created_at,
            "hashtags": tweet.get("hashtags", []),
            "btc_price": None,  # オプション: 投稿時のBTC価格
        })

    return pinecone_client.upsert_tweets_batch(tweets_for_pinecone)


def main() -> None:
    """メイン処理."""
    parser = argparse.ArgumentParser(
        description="X投稿をPineconeに同期（手動実行用）"
    )
    parser.add_argument(
        "--max-tweets",
        type=int,
        default=100,
        help="取得する最大ツイート数（デフォルト: 100）",
    )
    parser.add_argument(
        "--hashtag",
        type=str,
        default="#ビットコイン",
        help="対象ハッシュタグ（デフォルト: #ビットコイン）",
    )
    parser.add_argument(
        "--no-btc",
        action="store_true",
        help="#BTC, #Bitcoinを除外",
    )
    parser.add_argument(
        "--fetch-all",
        action="store_true",
        help="すべての過去投稿を一括取得（API制限に注意）",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="同期状態を表示して終了",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="同期状態をリセット（最初からやり直し）",
    )

    args = parser.parse_args()

    if args.reset:
        # 同期状態をリセット
        if SYNC_STATE_FILE.exists():
            SYNC_STATE_FILE.unlink()
            print("✅ 同期状態をリセットしました")
        else:
            print("同期状態ファイルは存在しません")
        return

    if args.status:
        # 同期状態を表示
        state = load_sync_state()
        pinecone_client = PineconeClient()
        total_in_db = (
            pinecone_client.get_tweet_count()
            if pinecone_client.is_configured
            else "N/A"
        )

        print("\n" + "=" * 50)
        print("📊 X投稿同期ステータス")
        print("=" * 50)
        print(f"過去投稿取得完了: {'✅ Yes' if state.get('all_historical_collected', False) else '⏳ No'}")
        print(f"最新同期済みID: {state.get('newest_synced_tweet_id', 'なし')}")
        print(f"ページネーション: {'継続あり' if state.get('pagination_token') else 'なし'}")
        print(f"累計同期数: {state.get('total_synced_count', 0)} 件")
        print(f"月間API呼び出し: {state.get('monthly_api_calls', 0)} 件")
        print(f"対象月: {state.get('api_call_month', 'N/A')}")
        print(f"最終同期日: {state.get('last_sync_date', 'なし')}")
        print(f"Pinecone内合計: {total_in_db} 件")
        print("=" * 50)

        if not state.get("all_historical_collected", False):
            print("\n💡 ヒント: --fetch-all で全過去投稿を一括取得できます")
        return

    # 同期実行
    print("\n🚀 X投稿の同期を開始します...")
    print(f"   対象ユーザー: @{settings.TWITTER_TARGET_USERNAME}")
    print(f"   ハッシュタグ: {args.hashtag}")
    if args.fetch_all:
        print("   モード: 全過去投稿を一括取得")
    else:
        print(f"   最大取得数: {args.max_tweets}")
    print()

    result = sync_tweets(
        max_tweets=args.max_tweets,
        hashtag=args.hashtag,
        include_btc=not args.no_btc,
        fetch_all=args.fetch_all,
    )

    if result["success"]:
        print("\n" + "=" * 50)
        print("✅ 同期完了")
        print("=" * 50)
        print(f"今回同期: {result['synced_count']} 件")
        print(f"今回API呼び出し: {result.get('api_calls_this_run', 0)} 件")
        print(f"DB内合計: {result.get('total_in_db', 'N/A')} 件")
        print(f"過去投稿取得完了: {'✅ Yes' if result.get('all_historical_collected', False) else '⏳ No'}")
        print(f"月間API累計: {result.get('monthly_api_calls', 0)} 件")
        print("=" * 50)
    else:
        print(f"\n❌ 同期失敗: {result.get('error', 'Unknown error')}")
        sys.exit(1)


if __name__ == "__main__":
    main()
