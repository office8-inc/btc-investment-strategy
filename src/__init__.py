"""ビットコイン投資戦略自動化 - メインパッケージ.

AIを使用したビットコインのテクニカル・ファンダメンタル分析を行い、
予測チャートをWebページに表示するシステム。
"""

from src.data.ohlcv import OHLCVData

__all__ = ["OHLCVData"]
