"""メイン分析実行スクリプト.

このスクリプトは、ビットコインのテクニカル・ファンダメンタル分析を実行し、
予測結果をWebページにアップロードする。

データソース:
- CoinGecko: 現在価格・市場データ（時価総額、24h変動など）
- Coinbase: 日足OHLCデータ（365日分、認証不要）
- CryptoCompare: 日足OHLCデータのフォールバック・仮想通貨ニュース
- Fear & Greed Index: 市場センチメント
- Alpha Vantage: 米国株式市場データ
- FRED: マクロ経済指標
- Polygon.io: 市場ステータス
- Finnhub: 金融ニュース
- Pinecone: ユーザーの過去投稿から類似分析を検索
"""

import sys
from datetime import datetime
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

from config.settings import settings
from src.analysis.fundamental import FundamentalAnalyzer
from src.analysis.predictor import Predictor
from src.analysis.technical import TechnicalAnalyzer
from src.data.ohlcv import add_technical_indicators
from src.macro_data.alpha_vantage import AlphaVantageClient
from src.macro_data.finnhub import FinnhubClient
from src.macro_data.fred import FREDClient
from src.macro_data.polygon import PolygonClient
from src.market_data.coinbase import CoinbaseClient
from src.market_data.coingecko import CoinGeckoClient
from src.market_data.cryptocompare import CryptoCompareClient
from src.market_data.fear_greed import FearGreedClient
from src.server.xserver_uploader import XServerUploader
from src.tradingview.webhook import TradingViewWebhook
from src.vector_db.pinecone_client import PineconeClient


def setup_logging() -> None:
    """ログ設定を初期化."""
    # loguru の設定
    logger.remove()
    logger.add(
        sys.stderr,
        level=settings.LOG_LEVEL,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>",
    )
    # 日付ごとのログファイル（同日は上書き）
    log_file = f"logs/analysis_{datetime.now().strftime('%Y-%m-%d')}.log"
    logger.add(
        log_file,
        mode="w",  # 上書きモード
        level="DEBUG",
    )


def run_analysis() -> None:
    """メイン分析処理を実行."""
    logger.info("=" * 60)
    logger.info("ビットコイン投資戦略分析を開始")
    logger.info(f"実行時刻: {datetime.now().isoformat()}")
    logger.info("=" * 60)

    # ==================== 1. データ収集 ====================
    logger.info("Step 1: 価格データ収集（CoinGecko + Coinbase）")

    # CoinGecko から市場データを取得（現在価格・時価総額など）
    coingecko = CoinGeckoClient()
    btc_market_data = coingecko.get_bitcoin_market_data()

    if btc_market_data:
        current_price = btc_market_data.price_usd
        logger.info(f"現在のBTC価格: ${current_price:,.2f}")
    else:
        logger.error("CoinGeckoからBTC価格を取得できませんでした")
        raise RuntimeError("BTC価格の取得に失敗しました")

    # Coinbase から OHLC データを取得（認証不要・正確な日足データ）
    # フォールバック: CryptoCompare（2026-06にAPIキー必須化されたため一次から降格）
    coinbase = CoinbaseClient()
    df_daily = coinbase.get_ohlc_dataframe(days=365)

    if df_daily is None or len(df_daily) == 0:
        logger.warning("Coinbaseから取得失敗、CryptoCompareにフォールバック")
        cryptocompare = CryptoCompareClient()
        df_daily = cryptocompare.get_ohlc_dataframe(days=365)

    if df_daily is not None and len(df_daily) >= 200:
        df_daily = add_technical_indicators(df_daily)
    logger.info(f"日足データ: {len(df_daily) if df_daily is not None else 0}本取得")

    if df_daily is None or len(df_daily) == 0:
        logger.error("OHLCデータを取得できませんでした")
        raise RuntimeError("OHLCデータの取得に失敗しました")

    # ==================== 2. 市場データ収集 ====================
    logger.info("Step 2: 市場データ収集（CoinGecko, Fear & Greed）")

    market_context_parts = []

    # CoinGecko 市場データ（既に取得済みのcoingeckoインスタンスを使用）
    market_summary = coingecko.get_market_summary()
    logger.info("CoinGecko市場データ取得完了")
    market_context_parts.append(market_summary)

    # Fear & Greed Index
    fear_greed = FearGreedClient()
    fg_summary = fear_greed.get_sentiment_summary()
    logger.info("Fear & Greed Index取得完了")
    market_context_parts.append(fg_summary)

    market_context = "\n\n".join(market_context_parts)

    # ==================== 3. マクロ経済データ収集 ====================
    logger.info("Step 3: マクロ経済データ収集（FRED, Alpha Vantage, Polygon, Finnhub）")

    macro_context_parts = []

    # FRED 経済指標
    fred = FREDClient()
    fred_summary = fred.get_economic_summary()
    if "取得できません" not in fred_summary:
        logger.info("FRED経済指標取得完了")
        macro_context_parts.append(fred_summary)
    else:
        logger.info("FRED API未設定のためスキップ")

    # Alpha Vantage 株式市場
    alpha_vantage = AlphaVantageClient()
    av_summary = alpha_vantage.get_market_summary()
    if "取得できません" not in av_summary:
        logger.info("Alpha Vantage市場データ取得完了")
        macro_context_parts.append(av_summary)
    else:
        logger.info("Alpha Vantage API未設定のためスキップ")

    # Polygon.io 市場ステータス
    polygon = PolygonClient()
    polygon_summary = polygon.get_market_summary()
    if "取得できません" not in polygon_summary:
        logger.info("Polygon.io市場データ取得完了")
        macro_context_parts.append(polygon_summary)
    else:
        logger.info("Polygon.io API未設定のためスキップ")

    # Finnhub 金融ニュース
    finnhub = FinnhubClient()
    finnhub_summary = finnhub.get_news_summary()
    if "取得できません" not in finnhub_summary:
        logger.info("Finnhub金融ニュース取得完了")
        macro_context_parts.append(finnhub_summary)
    else:
        logger.info("Finnhub API未設定のためスキップ")

    macro_context = "\n\n".join(macro_context_parts) if macro_context_parts else ""

    # ==================== 4. ニュース取得 ====================
    logger.info("Step 4: 仮想通貨ニュース取得（CryptoCompare）")

    # CryptoCompare ニュース
    cryptocompare = CryptoCompareClient()
    news_summary = cryptocompare.get_news_summary()
    if "取得できません" not in news_summary:
        logger.info("CryptoCompareニュース取得完了")
    else:
        logger.warning("CryptoCompareニュース取得失敗")
        news_summary = "最新のニュースはありません。"

    # ==================== 5. 過去類似投稿検索（Pinecone） ====================
    logger.info("Step 5: 過去の類似投稿検索（Pinecone）")

    similar_posts = []  # 口調学習用
    pinecone_client = PineconeClient()
    if pinecone_client.is_configured:
        # 価格変化率を計算
        if len(df_daily) >= 7:
            week_ago_price = df_daily.iloc[-7]["close"]
            price_change_pct = ((current_price - week_ago_price) / week_ago_price) * 100
        else:
            price_change_pct = 0.0

        # トレンド判定
        trend = "bullish" if price_change_pct > 0 else "bearish"
        if abs(price_change_pct) < 3:
            trend = "neutral"

        # Fear & Greed Index
        fg_data = fear_greed.get_current()
        fg_index = fg_data.value if fg_data else None

        # 類似投稿検索（ユーザーの過去の分析投稿から）
        similar_posts = pinecone_client.search_by_market_context(
            price_change_pct=price_change_pct,
            trend=trend,
            fear_greed_index=fg_index,
            keywords=["BTC", "ビットコイン"],
        )

        if similar_posts:
            logger.info(f"類似投稿: {len(similar_posts)}件発見")
            logger.info("→ 類似投稿から口調・スタイルを学習")
            for post in similar_posts[:5]:
                post_text = post.get("text", "")[:80]
                post_date = post.get("created_at", "")[:10]
                post_score = post.get("score", 0)
                logger.info(f"  - [{post_date}] (類似度: {post_score:.2f}) {post_text}...")
        else:
            logger.info("類似する過去投稿なし（データ蓄積中）")
    else:
        logger.info("Pinecone未設定のためスキップ")

    # ==================== 6. テクニカル分析 ====================
    logger.info("Step 6: テクニカル分析")

    tech_analyzer = TechnicalAnalyzer()
    tech_result = tech_analyzer.analyze(df_daily)

    logger.info(f"トレンド: {tech_result.trend} (強度: {tech_result.strength}%)")
    logger.info(f"検出パターン: {len(tech_result.patterns)}件")
    logger.info(f"サマリー: {tech_result.summary}")

    # ==================== 7. ファンダメンタル分析 ====================
    logger.info("Step 7: ファンダメンタル分析")

    fund_analyzer = FundamentalAnalyzer()
    news_items = cryptocompare.get_btc_news(limit=20)
    fund_result = fund_analyzer.analyze(
        news_items=[n.to_dict() for n in news_items],
        current_price=current_price,
    )

    # Fear & Greed Index からセンチメントスコアを計算 (0-100 → -1 to +1)
    fg_sentiment_data = fear_greed.get_current()
    if fg_sentiment_data:
        # Fear & Greed: 0=Extreme Fear, 50=Neutral, 100=Extreme Greed
        # センチメント: -1=Extreme Fear, 0=Neutral, +1=Extreme Greed
        fg_sentiment = (fg_sentiment_data.value - 50) / 50
        # ファンダメンタル分析の結果にセンチメントを上書き
        fund_result.sentiment = fg_sentiment
        logger.info(
            f"Fear & Greed Index: {fg_sentiment_data.value} → "
            f"センチメントスコア: {fg_sentiment:.2f}"
        )
    else:
        logger.warning("Fear & Greed データなし、センチメントはニュースから算出")

    logger.info(f"市場センチメント: {fund_result.sentiment:.2f}")
    logger.info(f"ファンダメンタル: {fund_result.analysis_summary}")

    # ==================== 8. AI予測生成 ====================
    logger.info("Step 8: AI予測パターン生成")

    # 統合コンテキストを構築（類似投稿は口調学習用なので除外）
    integrated_context = []
    if market_context:
        integrated_context.append(market_context)
    if macro_context:
        integrated_context.append(macro_context)
    if news_summary:
        integrated_context.append(news_summary)

    full_context = "\n\n---\n\n".join(integrated_context) if integrated_context else ""

    predictor = Predictor()
    patterns = predictor.generate_predictions(
        technical_analysis=tech_result,
        current_price=current_price,
        timeframes=["1week", "2weeks", "1month"],
        num_patterns=10,
        news_context=full_context,
        similar_posts=similar_posts[:5] if similar_posts else None,  # 口調学習用
    )

    if patterns:
        logger.info(f"予測パターン生成完了: {len(patterns)}パターン")
        for p in patterns[:3]:
            logger.info(
                f"  #{p.rank} {p.pattern_name}: "
                f"{p.direction} {p.probability*100:.0f}% → ${p.target_price:,.0f}"
            )
    else:
        logger.error("予測パターンを生成できませんでした")

    # ==================== 9. 結果出力 ====================
    logger.info("Step 9: 結果出力")

    # 分析サマリーを生成（見やすく整形）
    # 上位3パターンの要約を含める
    top_patterns_summary = ""
    if patterns:
        pattern_lines = []
        for p in patterns[:3]:
            direction_ja = {"bullish": "📈上昇", "bearish": "📉下落", "neutral": "➡️横ばい"}.get(
                p.direction, p.direction
            )
            pattern_lines.append(
                f"  {p.rank}. {p.pattern_name}\n"
                f"     {direction_ja} / 確率{p.probability*100:.0f}% / 目標${p.target_price:,.0f}"
            )
        top_patterns_summary = "\n".join(pattern_lines)

    # Fear & Greed 情報
    fg_info = ""
    fg_data = fear_greed.get_current()
    if fg_data:
        fg_info = f"Fear & Greed Index: {fg_data.value}（{fg_data.value_classification}）"

    # 価格変化情報
    price_change_info = ""
    if len(df_daily) >= 7:
        week_ago_price = df_daily.iloc[-7]["close"]
        price_change = ((current_price - week_ago_price) / week_ago_price) * 100
        price_change_info = f"7日間変動: {price_change:+.1f}%"

    # 市場状況を整形
    market_status = " / ".join(filter(None, [fg_info, price_change_info]))

    # マクロ経済情報を取得
    macro_info = ""
    fred_indicators = fred.get_all_indicators()
    if fred_indicators:
        macro_parts = []
        for ind in fred_indicators:
            if ind.name == "Federal Funds Rate":
                macro_parts.append(f"政策金利: {ind.value:.2f}%")
            elif ind.name == "Unemployment Rate":
                macro_parts.append(f"失業率: {ind.value:.1f}%")
        macro_info = " / ".join(macro_parts)

    # 市場全体データ
    market_data = coingecko.get_global_market_data()
    btc_dominance = ""
    total_market_cap = ""
    if market_data:
        if "btc_dominance" in market_data:
            btc_dominance = f"BTCドミナンス: {market_data['btc_dominance']:.1f}%"
        if "total_market_cap_usd" in market_data:
            cap_trillion = market_data["total_market_cap_usd"] / 1e12
            total_market_cap = f"仮想通貨時価総額: ${cap_trillion:.2f}兆"

    # サポート・レジスタンス情報
    support_levels = ""
    resistance_levels = ""
    if tech_result.support_resistance:
        supports = tech_result.support_resistance.get("support", [])
        resistances = tech_result.support_resistance.get("resistance", [])
        if supports:
            # 現在価格に近いサポート上位3つ
            close_supports = sorted([float(s) for s in supports if float(s) < current_price], reverse=True)[:3]
            if close_supports:
                support_levels = "主要サポート: " + ", ".join([f"${int(s):,}" for s in close_supports])
        if resistances:
            # 現在価格に近いレジスタンス上位3つ
            close_resistances = sorted([float(r) for r in resistances if float(r) > current_price])[:3]
            if close_resistances:
                resistance_levels = "主要レジスタンス: " + ", ".join([f"${int(r):,}" for r in close_resistances])

    # 最新ニュースサマリー（上位3件）
    news_headlines = ""
    if news_items and len(news_items) > 0:
        headlines = [n.title[:50] + "..." if len(n.title) > 50 else n.title for n in news_items[:3]]
        news_headlines = "📰 " + " | ".join(headlines)

    analysis_summary = (
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 テクニカル分析\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{tech_result.summary}\n"
        f"トレンド強度: {tech_result.strength}% / 検出パターン: {len(tech_result.patterns)}件\n"
        + (f"{support_levels}\n" if support_levels else "")
        + (f"{resistance_levels}\n" if resistance_levels else "")
        + f"\n━━━━━━━━━━━━━━━━━━━━\n"
        f"📰 ファンダメンタル分析\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{fund_result.analysis_summary}\n"
        f"センチメントスコア: {fund_result.sentiment:.2f}\n"
        + (f"{news_headlines}\n" if news_headlines else "")
        + f"\n━━━━━━━━━━━━━━━━━━━━\n"
        f"🌡️ 市場状況\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{market_status}\n"
        + (f"{btc_dominance}" + (f" / {total_market_cap}" if total_market_cap else "") + "\n" if btc_dominance else "")
        + (f"{macro_info}\n" if macro_info else "")
        + f"\n━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 AI予測トップ3\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{top_patterns_summary}"
    )

    # TradingView Webhook に送信
    tv_webhook = TradingViewWebhook()
    if tv_webhook._is_configured:
        success = tv_webhook.send_predictions(
            patterns=patterns,
            analysis_summary=analysis_summary,
            current_price=current_price,
        )
        if success:
            logger.info("TradingView Webhook 送信完了")
        else:
            logger.warning("TradingView Webhook 送信失敗")
    else:
        logger.info("TradingView Webhook 未設定のためスキップ")

    # JSONファイルに保存
    Path("data").mkdir(exist_ok=True)
    tv_webhook.save_to_json(
        patterns=patterns,
        analysis_summary=analysis_summary,
        current_price=current_price,
        filepath="data/latest_prediction.json",
    )

    # アラートメッセージを生成
    alert_message = tv_webhook.generate_alert_message(
        patterns=patterns,
        current_price=current_price,
    )
    logger.info(f"\n{alert_message}")

    # ==================== 10. XSERVER アップロード ====================
    logger.info("Step 10: XSERVER アップロード")

    public_url = None
    if settings.is_xserver_configured:
        try:
            xserver = XServerUploader()

            # 予測ページをアップロード（JSON + HTML）
            public_url = xserver.upload_prediction_page(
                patterns=patterns,
                current_price=current_price,
                analysis_summary=analysis_summary,
            )

            if public_url:
                logger.info(f"XSERVER アップロード完了: {public_url}")
            else:
                logger.warning("XSERVER アップロードに失敗しました")
        except Exception as e:
            logger.error(f"XSERVER アップロード中にエラー: {e}")
    else:
        logger.info("XSERVER 未設定のためスキップ")

    logger.info("=" * 60)
    logger.info("分析完了")
    if public_url:
        logger.info(f"結果ページ: {public_url}")
    logger.info("=" * 60)


def main() -> None:
    """エントリーポイント."""
    setup_logging()

    try:
        run_analysis()
    except KeyboardInterrupt:
        logger.info("ユーザーにより中断されました")
        sys.exit(0)
    except Exception as e:
        logger.exception(f"分析中にエラーが発生しました: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
