"""XSERVER FTPアップローダー.

分析結果のJSONとHTMLをXSERVERにアップロードする。
"""

import ftplib
import json
import logging
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import settings

logger = logging.getLogger(__name__)


class XServerUploader:
    """XSERVER FTPアップローダー.

    分析結果をXSERVERにFTPアップロードし、
    Webページで予測チャートを表示できるようにする。
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        username: str | None = None,
        password: str | None = None,
        remote_dir: str | None = None,
    ) -> None:
        """初期化.

        Args:
            host: FTPホスト名
            port: FTPポート番号
            username: FTPユーザー名
            password: FTPパスワード
            remote_dir: リモートディレクトリ
        """
        self._host = host or settings.XSERVER_FTP_HOST
        self._port = port or settings.XSERVER_FTP_PORT
        self._username = username or settings.XSERVER_FTP_USER
        self._password = password or settings.XSERVER_FTP_PASSWORD
        self._remote_dir = remote_dir or settings.XSERVER_REMOTE_DIR

        self._is_configured = bool(
            self._host
            and self._username
            and self._password
            and "your_" not in self._host.lower()
        )

        if not self._is_configured:
            logger.warning(
                "XSERVER FTP not configured. "
                "Upload features will not work."
            )

    def _get_ftp_client(self) -> ftplib.FTP:
        """FTP接続を確立.

        Returns:
            FTPクライアント
        """
        ftp = ftplib.FTP()
        ftp.connect(self._host, self._port)
        ftp.login(self._username, self._password)
        ftp.encoding = "utf-8"
        return ftp

    def _ensure_remote_dir(self, ftp: ftplib.FTP, path: str | None = None) -> None:
        """リモートディレクトリが存在することを確認.

        Args:
            ftp: FTPクライアント
            path: ディレクトリパス（未指定時はself._remote_dir）
        """
        target_dir = path or self._remote_dir
        if not target_dir:
            return

        # ディレクトリを階層的に作成
        parts = target_dir.split("/")
        current_path = ""

        for part in parts:
            if not part:
                continue
            current_path = f"{current_path}/{part}"
            try:
                ftp.cwd(current_path)
            except ftplib.error_perm:
                try:
                    ftp.mkd(current_path)
                    logger.info(f"Created directory: {current_path}")
                except ftplib.error_perm:
                    pass  # ディレクトリが既に存在する場合

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def upload_json(
        self,
        data: dict[str, Any],
        filename: str = "prediction.json",
    ) -> bool:
        """JSONデータをアップロード.

        Args:
            data: アップロードするデータ
            filename: ファイル名

        Returns:
            成功した場合True
        """
        if not self._is_configured:
            logger.error("XSERVER FTP not configured")
            return False

        ftp = None

        try:
            # JSONを文字列に変換
            json_str = json.dumps(data, ensure_ascii=False, indent=2)
            json_bytes = json_str.encode("utf-8")

            # FTP接続
            ftp = self._get_ftp_client()

            # ディレクトリ確認・作成
            self._ensure_remote_dir(ftp)

            # リモートパス
            remote_path = f"{self._remote_dir}/{filename}" if self._remote_dir else filename

            # サブディレクトリがある場合は作成
            if "/" in filename:
                subdir = filename.rsplit("/", 1)[0]
                full_subdir = f"{self._remote_dir}/{subdir}" if self._remote_dir else subdir
                self._ensure_remote_dir(ftp, full_subdir)

            # アップロード
            ftp.storbinary(f"STOR {remote_path}", BytesIO(json_bytes))

            logger.info(f"Uploaded {filename} to XSERVER via FTP")
            return True

        except ftplib.all_errors as e:
            logger.error(f"FTP error: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to upload JSON: {e}")
            return False
        finally:
            if ftp:
                ftp.quit()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def upload_file(
        self,
        local_path: str | Path,
        remote_filename: str | None = None,
    ) -> bool:
        """ローカルファイルをアップロード.

        Args:
            local_path: ローカルファイルパス
            remote_filename: リモートファイル名（未指定時はローカルと同じ）

        Returns:
            成功した場合True
        """
        if not self._is_configured:
            logger.error("XSERVER FTP not configured")
            return False

        local_path = Path(local_path)
        if not local_path.exists():
            logger.error(f"File not found: {local_path}")
            return False

        remote_filename = remote_filename or local_path.name

        ftp = None

        try:
            # FTP接続
            ftp = self._get_ftp_client()

            # ディレクトリ確認・作成
            self._ensure_remote_dir(ftp)

            # リモートパス
            remote_path = f"{self._remote_dir}/{remote_filename}" if self._remote_dir else remote_filename

            # サブディレクトリがある場合は作成
            if "/" in remote_filename:
                subdir = remote_filename.rsplit("/", 1)[0]
                full_subdir = f"{self._remote_dir}/{subdir}" if self._remote_dir else subdir
                self._ensure_remote_dir(ftp, full_subdir)

            # アップロード
            with open(local_path, "rb") as f:
                ftp.storbinary(f"STOR {remote_path}", f)

            logger.info(f"Uploaded {remote_filename} to XSERVER via FTP")
            return True

        except ftplib.all_errors as e:
            logger.error(f"FTP error: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to upload file: {e}")
            return False
        finally:
            if ftp:
                ftp.quit()

    def upload_prediction_page(
        self,
        patterns: list[Any],
        current_price: float,
        analysis_summary: str,
    ) -> str | None:
        """予測結果ページをアップロード.

        JSONデータと表示用HTMLをアップロードする。
        日付別アーカイブも保存し、過去予測を参照可能にする。

        Args:
            patterns: 予測パターンリスト
            current_price: 現在価格
            analysis_summary: 分析サマリー

        Returns:
            成功した場合は公開URL、失敗した場合はNone
        """
        # PredictionPatternオブジェクトを辞書に変換
        pattern_dicts = []
        for p in patterns:
            if hasattr(p, "to_dict"):
                pattern_dicts.append(p.to_dict())
            elif hasattr(p, "__dict__"):
                pattern_dicts.append({
                    "rank": getattr(p, "rank", 0),
                    "probability": getattr(p, "probability", 0),
                    "direction": getattr(p, "direction", ""),
                    "target_price": getattr(p, "target_price", 0),
                    "timeframe": getattr(p, "timeframe", ""),
                    "pattern_name": getattr(p, "pattern_name", ""),
                    "reasoning": getattr(p, "reasoning", ""),
                    "key_levels": getattr(p, "key_levels", {}),
                })
            else:
                pattern_dicts.append(p)

        # 現在の日付
        today = datetime.now().strftime("%Y-%m-%d")

        # JSONデータを作成
        data = {
            "date": today,
            "timestamp": datetime.now().isoformat(),
            "current_price": current_price,
            "summary": analysis_summary,
            "patterns": pattern_dicts,
        }

        # 最新JSONをアップロード
        json_success = self.upload_json(data, "prediction.json")

        # 日付別アーカイブをアップロード
        archive_success = self._upload_prediction_archive(data, today)

        # HTMLをアップロード（初回のみ、または更新時）
        html_path = Path(__file__).parent.parent.parent / "web" / "index.html"
        if html_path.exists():
            html_success = self.upload_file(html_path, "index.html")
        else:
            logger.warning(f"HTML template not found: {html_path}")
            html_success = True  # HTMLがなくてもJSONアップロードは成功

        if json_success and html_success and archive_success:
            return self.get_public_url()
        return None

    def _upload_prediction_archive(
        self,
        data: dict[str, Any],
        date_str: str,
    ) -> bool:
        """日付別予測アーカイブをアップロード.

        predictions/{YYYY-MM-DD}.json に保存し、
        predictions/index.json に日付リストを更新する。

        Args:
            data: 予測データ
            date_str: 日付文字列 (YYYY-MM-DD)

        Returns:
            成功した場合True
        """
        if not self._is_configured:
            logger.warning("XSERVER not configured, skipping archive upload")
            return True  # 設定がない場合はスキップ（エラーではない）

        ftp = None

        try:
            ftp = self._get_ftp_client()

            # predictions ディレクトリを作成
            predictions_dir = f"{self._remote_dir}/predictions" if self._remote_dir else "predictions"
            self._ensure_remote_dir(ftp, predictions_dir)

            # 日付別JSONをアップロード
            date_json_path = f"{predictions_dir}/{date_str}.json"
            json_str = json.dumps(data, ensure_ascii=False, indent=2)
            json_bytes = json_str.encode("utf-8")
            ftp.storbinary(f"STOR {date_json_path}", BytesIO(json_bytes))
            logger.info(f"Uploaded prediction archive: {date_str}.json")

            # index.json を更新（既存の日付リストを読み込み）
            index_path = f"{predictions_dir}/index.json"
            dates = []

            try:
                # 既存のindex.jsonを読み込み
                buffer = BytesIO()
                ftp.retrbinary(f"RETR {index_path}", buffer.write)
                buffer.seek(0)
                index_data = json.loads(buffer.read().decode("utf-8"))
                dates = index_data.get("dates", [])
            except ftplib.error_perm:
                logger.info("Creating new predictions index.json")

            # 今日の日付を追加（重複回避）
            if date_str not in dates:
                dates.append(date_str)
                dates.sort(reverse=True)  # 新しい順

            # index.jsonをアップロード
            index_data = {
                "updated_at": datetime.now().isoformat(),
                "dates": dates,
            }
            index_str = json.dumps(index_data, ensure_ascii=False, indent=2)
            index_bytes = index_str.encode("utf-8")
            ftp.storbinary(f"STOR {index_path}", BytesIO(index_bytes))
            logger.info(f"Updated predictions index.json with {len(dates)} dates")

            return True

        except Exception as e:
            logger.error(f"Failed to upload prediction archive: {e}")
            return False
        finally:
            if ftp:
                ftp.quit()

    def get_public_url(self, filename: str = "index.html") -> str:
        """公開URLを取得.

        Args:
            filename: ファイル名

        Returns:
            公開URL
        """
        base_url = settings.XSERVER_PUBLIC_URL
        if not base_url:
            return ""
        if filename == "index.html":
            return base_url.rstrip("/")
        return f"{base_url.rstrip('/')}/{filename}"
