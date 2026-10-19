"""LexiArbiter entry point."""

import logging
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from lexiarbiter import __version__
from lexiarbiter.app import MainWindow
from lexiarbiter.core.config import app_root
from lexiarbiter.core.logger import (
    current_log_dir,
    install_exception_hook,
    log_environment,
    setup_logging,
    used_fallback,
)


def main():
    # 最優先初始化 logging，確保後續任何錯誤都能被記錄
    setup_logging()
    log_environment(__version__)
    log = logging.getLogger(__name__)

    app = QApplication(sys.argv)
    app.setApplicationName("LexiArbiter")
    app.setOrganizationName("LexiArbiter")

    # 視窗 / 工作列 icon；優先用 png（跨平台一致），找不到才退回 ico。
    # 找不到任何 icon 就略過，不影響啟動。
    assets_dir = app_root() / "assets"
    icon_path = None
    for candidate in (assets_dir / "LexiArbiter_icon.png",
                      assets_dir / "LexiArbiter_icon.ico"):
        if candidate.exists():
            icon_path = candidate
            break
    if icon_path is not None:
        app.setWindowIcon(QIcon(str(icon_path)))
    else:
        log.info("未找到 icon 檔，略過 setWindowIcon：%s", assets_dir)

    # log 寫不進預設位置時告知使用者 fallback 路徑，避免發生問題卻不知道 log 在哪。
    if used_fallback() and current_log_dir() is not None:
        QMessageBox.information(
            None, "Log 路徑提示",
            "預設的 log 資料夾無法寫入，已改用以下位置：\n"
            f"{current_log_dir()}\n\n"
            "若程式發生問題，請將此資料夾內的檔案傳給開發者協助 debug。",
        )

    win = MainWindow()
    # 安裝 crash hook，未捕獲例外時先緊急存檔再寫 log
    install_exception_hook(win.emergency_save)
    win.show()

    try:
        sys.exit(app.exec())
    except Exception:
        log.critical("app.exec() 發生未預期例外", exc_info=True)
        raise


if __name__ == "__main__":
    main()
