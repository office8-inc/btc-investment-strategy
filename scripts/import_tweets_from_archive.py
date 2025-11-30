"""Twitter ArchiveからX投稿をPineconeにインポートするスクリプト.

Twitter設定からダウンロードしたアーカイブZIPの tweets.js を読み込み、
#ビットコイン 関連の投稿をPineconeに一括登録する。

使用方法:
    # ZIPを解凍後、tweets.js のパスを指定
    python scripts/import_tweets_from_archive.py path/to/tweets.js

    # プレビューのみ（Pineconeに保存しない）
    python scripts/import_tweets_from_archive.py path/to/tweets.js --preview

    # ハッシュタグを変更
    python scripts/import_tweets_from_archive.py path/to/tweets.js --hashtag "#BTC"
"""

import argparse
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.vector_db.pinecone_client import PineconeClient

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# 同期状態ファイル
SYNC_STATE_FILE = project_root / "data" / "tweet_sync_state.json"


def load_tweets_js(file_path: str) -> list[dict]:
    """tweets.js ファイルを読み込む.

    tweets.js は以下の形式:
    window.YTD.tweets.part0 = [ {...}, {...}, ... ]

    Args:
        file_path: tweets.js のパス

    Returns:
        ツイートデータのリスト
    """
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # "window.YTD.tweets.part0 = " を除去してJSONとしてパース
    # 複数のパートがある場合も対応
    json_match = re.search(r"=\s*(\[.*\])\s*$", content, re.DOTALL)
    if not json_match:
        raise ValueError("tweets.js の形式が不正です")

    tweets_data = json.loads(json_match.group(1))
    return tweets_data


def parse_tweet(tweet_data: dict) -> dict:
    """ツイートデータをパースして統一形式に変換.

    Args:
        tweet_data: アーカイブのツイートデータ

    Returns:
        統一形式のツイートデータ
    """
    tweet = tweet_data.get("tweet", tweet_data)

    # created_at をパース（例: "Sat Nov 30 12:34:56 +0000 2025"）
    created_at_str = tweet.get("created_at", "")
    try:
        created_at = datetime.strptime(created_at_str, "%a %b %d %H:%M:%S %z %Y")
    except ValueError:
        # 別の形式を試す
        try:
            created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
        except ValueError:
            created_at = datetime.now()

    # ハッシュタグを抽出
    hashtags = []
    entities = tweet.get("entities", {})
    if "hashtags" in entities:
        hashtags = [ht.get("text", "") for ht in entities["hashtags"]]

    return {
        "id": tweet.get("id_str", tweet.get("id", "")),
        "text": tweet.get("full_text", tweet.get("text", "")),
        "created_at": created_at,
        "hashtags": hashtags,
    }


def filter_by_hashtag(
    tweets: list[dict],
    hashtag: str = "#ビットコイン",
    include_btc: bool = True,
) -> list[dict]:
    """ハッシュタグでフィルタリング.

    Args:
        tweets: ツイートリスト
        hashtag: 対象ハッシュタグ
        include_btc: #BTC, #Bitcoin も含めるか

    Returns:
        フィルタリング後のツイートリスト
    """
    target_tags = [hashtag.lower().replace("#", "")]
    if include_btc:
        target_tags.extend(["btc", "bitcoin"])

    filtered = []
    for tweet in tweets:
        text_lower = tweet["text"].lower()
        tweet_tags = [tag.lower() for tag in tweet.get("hashtags", [])]

        # ハッシュタグまたはテキストに含まれるかチェック
        has_target = any(
            tag in tweet_tags or f"#{tag}" in text_lower
            for tag in target_tags
        )

        if has_target:
            filtered.append(tweet)

    return filtered


def update_sync_state(newest_tweet_id: str, oldest_tweet_id: str, count: int) -> None:
    """同期状態を更新.

    Args:
        newest_tweet_id: 最新のツイートID
        oldest_tweet_id: 最古のツイートID
        count: インポートした件数
    """
    state = {}
    if SYNC_STATE_FILE.exists():
        with open(SYNC_STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)

    # 最新IDを更新（既存より新しい場合）
    current_newest = state.get("newest_synced_tweet_id")
    if current_newest is None or int(newest_tweet_id) > int(current_newest):
        state["newest_synced_tweet_id"] = newest_tweet_id

    # 最古IDを更新（既存より古い場合）
    current_oldest = state.get("oldest_synced_tweet_id")
    if current_oldest is None or int(oldest_tweet_id) < int(current_oldest):
        state["oldest_synced_tweet_id"] = oldest_tweet_id

    # その他の状態を更新
    state["all_historical_collected"] = True  # アーカイブからインポート完了
    state["total_synced_count"] = state.get("total_synced_count", 0) + count
    state["last_sync_date"] = datetime.now().isoformat()
    state["archive_imported"] = True
    state["archive_import_date"] = datetime.now().isoformat()

    # 月間カウントは維持（API経由ではないのでカウントしない）
    if "api_call_month" not in state:
        state["api_call_month"] = datetime.now().strftime("%Y-%m")
    if "monthly_api_calls" not in state:
        state["monthly_api_calls"] = 0

    SYNC_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SYNC_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def import_tweets(
    file_path: str,
    hashtag: str = "#ビットコイン",
    include_btc: bool = True,
    preview: bool = False,
    batch_size: int = 50,
) -> dict:
    """アーカイブからツイートをインポート.

    Args:
        file_path: tweets.js のパス
        hashtag: 対象ハッシュタグ
        include_btc: #BTC, #Bitcoin も含めるか
        preview: プレビューのみ（保存しない）
        batch_size: バッチサイズ

    Returns:
        インポート結果
    """
    logger.info(f"📂 ファイル読み込み中: {file_path}")

    # tweets.js を読み込み
    try:
        raw_tweets = load_tweets_js(file_path)
    except Exception as e:
        logger.error(f"ファイル読み込みエラー: {e}")
        return {"success": False, "error": str(e)}

    logger.info(f"📊 総ツイート数: {len(raw_tweets)}")

    # パースして統一形式に変換
    tweets = [parse_tweet(t) for t in raw_tweets]

    # ハッシュタグでフィルタ
    filtered = filter_by_hashtag(tweets, hashtag, include_btc)
    logger.info(f"🏷️  {hashtag} に一致: {len(filtered)} 件")

    if not filtered:
        return {
            "success": True,
            "total_tweets": len(raw_tweets),
            "filtered_count": 0,
            "imported_count": 0,
            "message": "対象ハッシュタグの投稿が見つかりませんでした",
        }

    # 日付順にソート（新しい順）
    filtered.sort(key=lambda x: x["created_at"], reverse=True)

    # プレビュー表示
    if preview:
        print("\n" + "=" * 60)
        print(f"📋 プレビュー（最新10件 / 全{len(filtered)}件）")
        print("=" * 60)
        for i, tweet in enumerate(filtered[:10], 1):
            date_str = tweet["created_at"].strftime("%Y-%m-%d")
            text_preview = tweet["text"][:50].replace("\n", " ")
            print(f"{i:2}. [{date_str}] {text_preview}...")
        print("=" * 60)

        return {
            "success": True,
            "total_tweets": len(raw_tweets),
            "filtered_count": len(filtered),
            "imported_count": 0,
            "preview": True,
        }

    # Pinecone に保存
    pinecone_client = PineconeClient()
    if not pinecone_client.is_configured:
        logger.error("Pinecone client not configured")
        return {"success": False, "error": "Pinecone client not configured"}

    # バッチ処理
    tweets_for_pinecone = []
    for tweet in filtered:
        tweets_for_pinecone.append({
            "tweet_id": tweet["id"],
            "text": tweet["text"],
            "created_at": tweet["created_at"],
            "hashtags": tweet.get("hashtags", []),
            "btc_price": None,
        })

    logger.info(f"📤 Pineconeへ保存中... ({len(tweets_for_pinecone)} 件)")

    imported_count = 0
    for i in range(0, len(tweets_for_pinecone), batch_size):
        batch = tweets_for_pinecone[i:i + batch_size]
        count = pinecone_client.upsert_tweets_batch(batch)
        imported_count += count
        logger.info(f"  バッチ {i // batch_size + 1}: {count} 件保存")

    # 同期状態を更新
    newest_id = filtered[0]["id"]  # 最新
    oldest_id = filtered[-1]["id"]  # 最古
    update_sync_state(newest_id, oldest_id, imported_count)

    total_in_db = pinecone_client.get_tweet_count()

    return {
        "success": True,
        "total_tweets": len(raw_tweets),
        "filtered_count": len(filtered),
        "imported_count": imported_count,
        "total_in_db": total_in_db,
        "newest_id": newest_id,
        "oldest_id": oldest_id,
        "date_range": {
            "newest": filtered[0]["created_at"].strftime("%Y-%m-%d"),
            "oldest": filtered[-1]["created_at"].strftime("%Y-%m-%d"),
        },
    }


def main() -> None:
    """メイン処理."""
    parser = argparse.ArgumentParser(
        description="Twitter ArchiveからX投稿をPineconeにインポート"
    )
    parser.add_argument(
        "file_path",
        type=str,
        help="tweets.js ファイルのパス",
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
        help="#BTC, #Bitcoin を除外",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="プレビューのみ（Pineconeに保存しない）",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="バッチサイズ（デフォルト: 50）",
    )

    args = parser.parse_args()

    # ファイル存在確認
    if not Path(args.file_path).exists():
        print(f"❌ ファイルが見つかりません: {args.file_path}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("📥 Twitter Archive インポート")
    print("=" * 60)
    print(f"ファイル: {args.file_path}")
    print(f"ハッシュタグ: {args.hashtag}")
    print(f"モード: {'プレビュー' if args.preview else '本番インポート'}")
    print("=" * 60 + "\n")

    result = import_tweets(
        file_path=args.file_path,
        hashtag=args.hashtag,
        include_btc=not args.no_btc,
        preview=args.preview,
        batch_size=args.batch_size,
    )

    if result["success"]:
        print("\n" + "=" * 60)
        print("✅ インポート完了")
        print("=" * 60)
        print(f"総ツイート数: {result['total_tweets']} 件")
        print(f"対象ハッシュタグ: {result['filtered_count']} 件")
        if not result.get("preview"):
            print(f"Pineconeに保存: {result['imported_count']} 件")
            print(f"DB内合計: {result.get('total_in_db', 'N/A')} 件")
            if "date_range" in result:
                print(f"期間: {result['date_range']['oldest']} ～ {result['date_range']['newest']}")
        print("=" * 60)
    else:
        print(f"\n❌ インポート失敗: {result.get('error', 'Unknown error')}")
        sys.exit(1)


if __name__ == "__main__":
    main()
