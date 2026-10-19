"""集中式 logging 設定。

使用方式：
    在 main.py 最開頭呼叫 setup_logging()，之後各模組直接用
    logging.getLogger(__name__) 取得 logger 即可。
"""

from __future__ import annotations

import logging
import platform
import sys
import tempfile
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from .config import app_root

_LOG_MAX_BYTES = 512 * 1024   # 單檔上限 512 KB（只需保留近期操作供 debug 用）
_LOG_BACKUP_COUNT = 2         # 最多保留 2 個輪替檔（共約 1.5 MB）

# setup_logging() 解析後實際使用的 log 目錄；
# 其他模組（緊急存檔、Help 選單）需要這個資訊才能找到 log。
_LOG_DIR: Optional[Path] = None
_USED_FALLBACK: bool = False


def current_log_dir() -> Optional[Path]:
    """目前實際寫入 log 的資料夾；若 logging 完全初始化失敗回傳 None。"""
    return _LOG_DIR


def used_fallback() -> bool:
    """主要位置寫不進去、改用系統暫存目錄時為 True，方便 UI 端跳一次提示。"""
    return _USED_FALLBACK


def _build_handler(log_dir: Path) -> Optional[RotatingFileHandler]:
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            log_dir / "lexiarbiter.log",
            maxBytes=_LOG_MAX_BYTES,
            backupCount=_LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
    except OSError:
        return None
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s:%(lineno)d - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(fmt)
    # 檔案 handler 只寫 INFO 以上（INFO 記錄使用者操作脈絡，WARNING/ERROR 記錄問題）
    handler.setLevel(logging.INFO)
    return handler


def setup_logging() -> None:
    """初始化檔案 logging，應用程式啟動時呼叫一次。

    優先寫入 <app_root>/logs/lexiarbiter.log。若該位置不可寫
    （唯讀媒體、權限不足等），fallback 到 <tempdir>/LexiArbiter/logs/，
    這樣即便 .exe 放在 Program Files 之類的位置也能保有 log。
    若兩個位置都失敗則靜默放棄。
    """
    global _LOG_DIR, _USED_FALLBACK

    primary = app_root() / "logs"
    handler = _build_handler(primary)
    if handler is None:
        fallback = Path(tempfile.gettempdir()) / "LexiArbiter" / "logs"
        handler = _build_handler(fallback)
        if handler is None:
            return
        _LOG_DIR = fallback
        _USED_FALLBACK = True
    else:
        _LOG_DIR = primary

    root = logging.getLogger("lexiarbiter")
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)


def log_environment(version: str) -> None:
    """啟動時記錄關鍵環境資訊，方便事後從 log 判斷使用者實際跑的版本/平台。"""
    log = logging.getLogger("lexiarbiter.boot")
    log.info("LexiArbiter 啟動 version=%s", version)
    log.info("Python=%s platform=%s", sys.version.split()[0], platform.platform())
    log.info("frozen=%s executable=%s", getattr(sys, "frozen", False), sys.executable)
    log.info("app_root=%s", app_root())
    log.info("log_dir=%s fallback=%s", _LOG_DIR, _USED_FALLBACK)


def install_exception_hook(emergency_save_fn=None) -> None:
    """安裝 sys.excepthook，捕捉未處理的例外並寫入 log。

    emergency_save_fn: 可選的 callable()，在 crash 前嘗試緊急存檔。
    """
    log = logging.getLogger("lexiarbiter.crash")
    _orig = sys.excepthook

    def _hook(exc_type, exc_value, exc_tb):
        log.critical("未捕獲的例外（程式崩潰）", exc_info=(exc_type, exc_value, exc_tb))
        if emergency_save_fn is not None:
            try:
                emergency_save_fn()
            except Exception:
                log.error("緊急存檔失敗", exc_info=True)

        # 寫一份純文字提示讓非技術使用者知道要把 log 傳給開發者。
        if _LOG_DIR is not None:
            try:
                marker = _LOG_DIR / "last_crash.txt"
                marker.write_text(
                    "LexiArbiter 發生未預期錯誤。\n"
                    f"時間：{datetime.now().isoformat(timespec='seconds')}\n"
                    f"錯誤類型：{exc_type.__name__}\n"
                    f"錯誤訊息：{exc_value}\n\n"
                    "請將整個 log 資料夾（特別是 lexiarbiter.log）傳給開發者協助 debug。\n",
                    encoding="utf-8",
                )
            except Exception:
                log.error("寫入 last_crash.txt 失敗", exc_info=True)

        # process 即將終止，先沖刷 buffer，避免最後幾行 critical 訊息漏寫到磁碟。
        for h in logging.getLogger("lexiarbiter").handlers:
            try:
                h.flush()
            except Exception:
                pass

        _orig(exc_type, exc_value, exc_tb)

    sys.excepthook = _hook
