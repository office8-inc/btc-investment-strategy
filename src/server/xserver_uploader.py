"""XSERVER SFTPアップローダー.

分析結果のJSONとHTMLをXSERVERにアップロードする。
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import paramiko
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import settings

logger = logging.getLogger(__name__)


class XServerUploader:
    """XSERVER SFTPアップローダー.

    分析結果をXSERVERにSFTPアップロードし、
    Webページで予測チャートを表示できるようにする。
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        username: str | None = None,
        private_key_path: str | None = None,
        passphrase: str | None = None,
        remote_dir: str | None = None,
    ) -> None:
        """初期化.

        Args:
            host: SFTPホスト名
            port: SFTPポート番号
            username: SFTPユーザー名
            private_key_path: 秘密鍵ファイルパス
            passphrase: 秘密鍵のパスフレーズ
            remote_dir: リモートディレクトリ
        """
        self._host = host or settings.XSERVER_SFTP_HOST
        self._port = port or settings.XSERVER_SFTP_PORT
        self._username = username or settings.XSERVER_SFTP_USER
        self._private_key_path = private_key_path or settings.XSERVER_PRIVATE_KEY_PATH
        self._passphrase = passphrase or settings.XSERVER_PASSPHRASE
        self._remote_dir = remote_dir or settings.XSERVER_REMOTE_DIR

        self._is_configured = bool(
            self._host
            and self._username
            and self._private_key_path
            and "your_" not in self._host.lower()
        )

        if not self._is_configured:
            logger.warning(
                "XSERVER SFTP not configured. "
                "Upload features will not work."
            )

    def _get_sftp_client(self) -> tuple[paramiko.SSHClient, paramiko.SFTPClient]:
        """SFTP接続を確立.

        Returns:
            (SSHClient, SFTPClient) のタプル
        """
        # 秘密鍵を読み込む
        private_key = paramiko.RSAKey.from_private_key_file(
            self._private_key_path,
            password=self._passphrase if self._passphrase else None,
        )

        # SSH接続
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(
            hostname=self._host,
            port=self._port,
            username=self._username,
            pkey=private_key,
        )

        # SFTP接続
        sftp = ssh.open_sftp()

        return ssh, sftp

    def _ensure_remote_dir(self, sftp: paramiko.SFTPClient, path: str | None = None) -> None:
        """リモートディレクトリが存在することを確認.

        Args:
            sftp: SFTPクライアント
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
                sftp.stat(current_path)
            except FileNotFoundError:
                try:
                    sftp.mkdir(current_path)
                    logger.info(f"Created directory: {current_path}")
                except Exception:
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
            logger.error("XSERVER SFTP not configured")
            return False

        ssh = None
        sftp = None

        try:
            # JSONを文字列に変換
            json_str = json.dumps(data, ensure_ascii=False, indent=2)

            # SFTP接続
            ssh, sftp = self._get_sftp_client()

            # ディレクトリ確認・作成
            self._ensure_remote_dir(sftp)

            # リモートパス
            remote_path = f"{self._remote_dir}/{filename}" if self._remote_dir else filename

            # アップロード
            with sftp.file(remote_path, "w") as f:
                f.write(json_str)

            logger.info(f"Uploaded {filename} to XSERVER via SFTP")
            return True

        except paramiko.SSHException as e:
            logger.error(f"SSH/SFTP error: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to upload JSON: {e}")
            return False
        finally:
            if sftp:
                sftp.close()
            if ssh:
                ssh.close()

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
            logger.error("XSERVER SFTP not configured")
            return False

        local_path = Path(local_path)
        if not local_path.exists():
            logger.error(f"File not found: {local_path}")
            return False

        remote_filename = remote_filename or local_path.name

        ssh = None
        sftp = None

        try:
            # SFTP接続
            ssh, sftp = self._get_sftp_client()

            # ディレクトリ確認・作成
            self._ensure_remote_dir(sftp)

            # リモートパス
            remote_path = f"{self._remote_dir}/{remote_filename}" if self._remote_dir else remote_filename

            # アップロード
            sftp.put(str(local_path), remote_path)

            logger.info(f"Uploaded {remote_filename} to XSERVER via SFTP")
            return True

        except paramiko.SSHException as e:
            logger.error(f"SSH/SFTP error: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to upload file: {e}")
            return False
        finally:
            if sftp:
                sftp.close()
            if ssh:
                ssh.close()

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

        ssh = None
        sftp = None

        try:
            ssh, sftp = self._get_sftp_client()

            # predictions ディレクトリを作成
            predictions_dir = f"{self._remote_dir}/predictions" if self._remote_dir else "predictions"
            self._ensure_remote_dir(sftp, predictions_dir)

            # 日付別JSONをアップロード
            date_json_path = f"{predictions_dir}/{date_str}.json"
            json_str = json.dumps(data, ensure_ascii=False, indent=2)
            with sftp.file(date_json_path, "w") as f:
                f.write(json_str)
            logger.info(f"Uploaded prediction archive: {date_str}.json")

            # index.json を更新（既存の日付リストを読み込み）
            index_path = f"{predictions_dir}/index.json"
            dates = []

            try:
                with sftp.file(index_path, "r") as f:
                    index_data = json.load(f)
                    dates = index_data.get("dates", [])
            except FileNotFoundError:
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
            with sftp.file(index_path, "w") as f:
                f.write(index_str)
            logger.info(f"Updated predictions index.json with {len(dates)} dates")

            return True

        except Exception as e:
            logger.error(f"Failed to upload prediction archive: {e}")
            return False
        finally:
            if sftp:
                sftp.close()
            if ssh:
                ssh.close()

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
