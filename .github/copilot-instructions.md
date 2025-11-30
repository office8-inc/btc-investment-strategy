# Copilot Instructions - ビットコイン投資戦略自動化

## プロジェクト概要

このプロジェクトは、AIを使用してビットコインのテクニカル・ファンダメンタル分析を行い、Webページに予想チャートを表示するシステムです。

X/Twitterの過去投稿はPineconeに保存し、類似状況での分析スタイルを学習。Webページの結果を見て手動でXに投稿します。

## 技術スタック

- **言語**: Python 3.11+
- **価格データ**: CoinGecko API（現在価格・市場データ）、CryptoCompare API（日足OHLC）
- **AI分析**: OpenAI API (GPT-4o)
- **ベクトルDB**: Pinecone（ユーザーのX投稿類似検索・分析スタイル学習）
- **X投稿取得**: Twitter/X API (tweepy) - 読み取りのみ
- **チャート表示**: TradingView Lightweight Charts + CryptoCompare API（PHPプロキシ経由）
- **ホスティング**: XSERVER (FTP経由)
- **市場データ**: CryptoCompare, CoinGecko, Fear & Greed Index
- **マクロ経済**: Alpha Vantage, Polygon.io, Finnhub, FRED

## コーディング規約

### Python スタイル

- **フォーマッター**: Black (line-length: 88)
- **リンター**: Ruff
- **型ヒント**: 必須（すべての関数に型アノテーション）
- **Docstring**: Google Style

```python
def analyze_pattern(
    ohlcv_data: pd.DataFrame,
    timeframe: str = "1d"
) -> dict[str, Any]:
    """テクニカルパターンを分析する。

    Args:
        ohlcv_data: OHLCVデータフレーム
        timeframe: 時間足 ("1d", "3d", "1w", "1M")

    Returns:
        分析結果を含む辞書

    Raises:
        ValueError: 無効な時間足が指定された場合
    """
    pass
```

### ファイル構成

- 1ファイル1クラス/1機能を原則とする
- `__init__.py` でモジュールの公開インターフェースを定義
- 設定値は `config/settings.py` に集約

### 環境変数

- すべてのAPIキー・シークレットは環境変数で管理
- `python-dotenv` を使用して `.env` から読み込み
- ハードコードされた認証情報は絶対に禁止

```python
from config.settings import settings

# Good
api_key = settings.OPENAI_API_KEY

# Bad - 絶対にしない
api_key = "sk-xxxxx"
```

### エラーハンドリング

- API呼び出しには必ずリトライロジックを実装
- 具体的な例外をキャッチ（`except Exception` は避ける）
- ログ出力を適切に行う

```python
import logging
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
async def fetch_price_data():
    try:
        # API呼び出し
        pass
    except httpx.HTTPStatusError as e:
        logger.error(f"API error: {e.response.status_code}")
        raise
```

## AI分析プロンプト設計

### テクニカル分析プロンプトの構造

```
1. コンテキスト設定（役割、専門性）
2. 入力データの説明（OHLCV、インジケーター値）
3. 分析観点の指定（トレンド、パターン、サポレジ）
4. 出力フォーマットの指定（JSON構造）
5. 確率・根拠の明記を要求
```

### 予測パターン出力形式

```json
{
  "patterns": [
    {
      "rank": 1,
      "probability": 0.35,
      "direction": "bullish",
      "target_price": 105000,
      "timeframe": "2weeks",
      "pattern_name": "Ascending Triangle Breakout",
      "reasoning": "...",
      "key_levels": {
        "entry": 98000,
        "stop_loss": 95000,
        "take_profit": [102000, 105000, 110000]
      }
    }
  ]
}
```

## TradingView連携

### Webhook ペイロード形式（将来実装予定）

```json
{
  "secret": "{{webhook_secret}}",
  "timestamp": "2025-11-30T09:00:00+09:00",
  "patterns": [...],
  "analysis_summary": "..."
}
```

## XSERVER FTP アップロード

- FTPでセキュアに接続（ftplib使用）
- JSON + HTMLを自動アップロード
- TradingView Lightweight Chartsでチャート描画
- 日付別アーカイブ機能付き（predictions/YYYY-MM-DD.json）

## テスト

- `pytest` を使用
- カバレッジ目標: 80%以上
- API呼び出しはモック化

```bash
pytest tests/ -v --cov=src --cov-report=html
```

## Git ワークフロー

- ブランチ: `feature/xxx`, `fix/xxx`, `refactor/xxx`
- コミットメッセージ: Conventional Commits形式
  - `feat:`, `fix:`, `docs:`, `refactor:`, `test:`
- PR前にローカルでテスト実行

## 🔒 セキュリティ（必須遵守事項）

> **Copilotは以下のルールを絶対に守ること**

### 禁止事項

1. **APIキー・シークレットのハードコード禁止**
   - コード内に直接APIキーを書かない
   - すべて `config/settings.py` 経由で環境変数から取得

2. **`.env` ファイルの操作禁止**
   - `.env` の内容を出力・表示しない
   - `.env` をコミット対象に含めない
   - `.env` の内容をログに出力しない

3. **センシティブ情報のログ出力禁止**
   - APIキー、トークン、パスワードをログに出力しない
   - エラーメッセージにも含めない

### 必須チェック

コード変更時は以下を確認：
- [ ] `.gitignore` に `.env` が含まれているか
- [ ] 新しいAPIキーは `settings.py` で環境変数から取得しているか
- [ ] ログ出力にセンシティブ情報が含まれていないか

### 安全なコード例

```python
# ✅ Good - 環境変数から取得
from config.settings import settings
api_key = settings.OPENAI_API_KEY

# ❌ Bad - ハードコード（絶対禁止）
api_key = "sk-xxxxx"

# ✅ Good - 安全なログ
logger.info("API call successful")

# ❌ Bad - センシティブ情報をログ出力（禁止）
logger.info(f"Using API key: {api_key}")
```

## 🔄 大きな変更後のルーティン（自動実行）

> **Copilotは以下の条件に該当する場合、ユーザーの依頼を待たずに自主的にこのルーティンを実行すること**

### 実行条件（いずれかに該当する場合）

- 複数ファイル（3ファイル以上）を変更した
- API/データソースの追加・削除・変更を行った
- 設定ファイル（settings.py、.env）を変更した
- アーキテクチャに影響する変更を行った
- 機能の廃止・置き換えを行った

### 1. コード品質チェック

```bash
# Ruff でlintチェック
python -m ruff check src/ scripts/ config/ --ignore E402

# 自動修正
python -m ruff check src/ scripts/ config/ --fix --ignore E402
```

### 2. 型チェック

```bash
# エディタの診断を確認
# get_errors ツールで全ファイルのエラーを確認
```

### 3. ドキュメント更新

以下のファイルを更新：
- `.github/README.md` - システム構成図、技術スタック、フロー図
- `.github/copilot-instructions.md` - 技術スタック、接続方式など

更新が必要な箇所：
- 新しいAPI/データソースの追加
- 接続方式の変更（SFTP→FTPなど）
- アーキテクチャの変更

### 4. 変更のコミット

```bash
# 変更を確認
git status
git diff

# コミット（Conventional Commits形式）
git add -A
git commit -m "refactor: プロジェクト全体のチェックとリファクタリング"

# プッシュ
git push origin main
```

### 5. GitHub Actions確認（必要に応じて）

- ワークフローの手動実行でテスト
- エラーがあればログを確認して修正
