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

    def _ensure_remote_dir(self, sftp: paramiko.SFTPClient) -> None:
        """リモートディレクトリが存在することを確認.

        Args:
            sftp: SFTPクライアント
        """
        if not self._remote_dir:
            return

        # ディレクトリを階層的に作成
        parts = self._remote_dir.split("/")
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

        # JSONデータを作成
        data = {
            "timestamp": datetime.now().isoformat(),
            "current_price": current_price,
            "summary": analysis_summary,
            "patterns": pattern_dicts,
        }

        # JSONをアップロード
        json_success = self.upload_json(data, "prediction.json")

        # HTMLをアップロード（初回のみ、または更新時）
        html_path = Path(__file__).parent.parent.parent / "web" / "index.html"
        if html_path.exists():
            html_success = self.upload_file(html_path, "index.html")
        else:
            logger.warning(f"HTML template not found: {html_path}")
            html_success = True  # HTMLがなくてもJSONアップロードは成功

        if json_success and html_success:
            return self.get_public_url()
        return None

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
