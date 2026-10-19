"""Right-hand file list panel.

Files in the working folder are split across three tabs by extension:

* ``原始檔 .json`` — judicial open-data input.
* ``標註檔 .lexa`` — annotation progress files.
* ``模型檔 .txt`` — model-ready exports.

Tab labels include a count, e.g. ``原始檔 .json (12)``. Within a tab:

* ``●`` (filled) marks the row whose path equals the currently-open document,
  with a trailing ``*`` while the in-memory document has unsaved changes.
* In the ``.json`` tab, files whose stem also has a sibling ``.lexa`` get a
  ``◐ `` prefix — the only cross-extension cue carried over from the previous
  badge-based layout, so users can see at a glance which raw files already
  have annotation progress.
* When the open document is a ``.lexa``, its sibling ``.json`` row (matched
  by ``Path.stem``) is also bolded in the .json tab.

``.txt`` rows can be opened by double-click or Enter — they go through
:func:`lexiarbiter.core.io.parse_legacy_txt`, which re-parses the model
export format back into a ``Document``. The same ``●`` / ``*`` active-doc
treatment applies across all three tabs.

When ``set_directory(dir, current_path)`` is called with a non-None
``current_path``, the panel automatically switches to the tab matching that
file's extension.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QLabel, QListWidget, QListWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)


_EXTS = (".json", ".lexa", ".txt")
_TAB_ORDER: tuple[str, ...] = ("raw", ".lexa", ".txt")
_TAB_LABELS: dict[str, str] = {
    "raw": "原始檔",
    ".lexa": "標註檔 .lexa",
    ".txt": "模型檔 .txt",
}


class FilePanel(QWidget):
    file_open_requested = Signal(str)  # absolute path

    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.title = QLabel("資料夾檔案")
        font = self.title.font()
        font.setPointSize(font.pointSize() + 1)
        font.setBold(True)
        self.title.setFont(font)

        self.tabs = QTabWidget()
        self._lists: dict[str, QListWidget] = {}
        for ext in _TAB_ORDER:
            lst = QListWidget()
            # itemActivated 已涵蓋雙擊與 Enter；不要再連 itemDoubleClicked，
            # 否則開檔後 refresh() 清空清單時，第二次派送會收到 None item。
            lst.itemActivated.connect(self._on_item_activated)
            self.tabs.addTab(lst, _TAB_LABELS[ext])
            self._lists[ext] = lst

        layout.addWidget(self.title)
        layout.addWidget(self.tabs, 1)

        self._dir: Optional[Path] = None
        self._current_path: Optional[Path] = None
        self._current_dirty: bool = False

    # ----------------------------------------------------------- public api

    def set_directory(self, directory: Optional[Path], current_path: Optional[Path]):
        self._dir = Path(directory) if directory else None
        self._current_path = Path(current_path) if current_path else None
        # 切檔後 dirty 由 MainWindow._update_window_title() 在後續同步補正。
        self._current_dirty = False
        self.refresh()
        if self._current_path is not None:
            self._switch_to_tab_for(self._current_path)

    def set_dirty(self, dirty: bool):
        """更新「目前列」未存檔標記，不觸發目錄重讀。"""
        if dirty == self._current_dirty:
            return
        self._current_dirty = dirty
        if self._current_path is None:
            return
        try:
            current_resolved = self._current_path.resolve()
        except OSError:
            return
        for lst in self._lists.values():
            for i in range(lst.count()):
                item = lst.item(i)
                if item is None:
                    continue
                path_str = item.data(Qt.UserRole)
                if not path_str:
                    continue
                try:
                    if Path(path_str).resolve() != current_resolved:
                        continue
                except OSError:
                    continue
                text = item.text()
                if dirty:
                    if not text.endswith("*"):
                        item.setText(text + "*")
                else:
                    if text.endswith("*"):
                        item.setText(text[:-1])
                break  # at most one row per list can match

    def refresh(self):
        for lst in self._lists.values():
            lst.clear()
        if not self._dir or not self._dir.exists():
            for ext in _TAB_ORDER:
                idx = _TAB_ORDER.index(ext)
                self.tabs.setTabText(idx, f"{_TAB_LABELS[ext]} (0)")
            return

        try:
            entries = sorted(self._dir.iterdir())
        except OSError:
            log.warning("無法讀取目錄：%s", self._dir, exc_info=True)
            for ext in _TAB_ORDER:
                idx = _TAB_ORDER.index(ext)
                self.tabs.setTabText(idx, f"{_TAB_LABELS[ext]} (0)")
            return

        by_ext: dict[str, list[Path]] = {ext: [] for ext in _TAB_ORDER}
        for entry in entries:
            if not entry.is_file():
                continue
            ext = entry.suffix.lower()
            # 隱藏 autosave 產物（含舊版 *.autosave.lexa 與新版
            # *.autosave.<timestamp>.lexa）。它們是 crash backup 用，
            # 不應該讓使用者誤點而把 doc.file_path 指到 autosave 檔。
            if ext == ".lexa" and ".autosave." in entry.name:
                continue

            # 將 .json 與 .docx 都分派給 "raw" tab
            tab_key = None
            if ext in (".json", ".docx"):
                tab_key = "raw"
            elif ext == ".lexa":
                tab_key = ".lexa"
            elif ext == ".txt":
                tab_key = ".txt"

            if tab_key in by_ext:
                by_ext[tab_key].append(entry)

        lexa_stems = {p.stem for p in by_ext[".lexa"]}

        # Stem of the currently-open .lexa, used to also bold its sibling
        # .json row so the user can see "this raw file is what I'm working on".
        current_lexa_stem: Optional[str] = None
        if (self._current_path is not None
                and self._current_path.suffix.lower() == ".lexa"):
            current_lexa_stem = self._current_path.stem

        try:
            current_resolved = (self._current_path.resolve()
                                if self._current_path is not None else None)
        except OSError:
            current_resolved = None

        for ext in _TAB_ORDER:
            lst = self._lists[ext]
            files = by_ext[ext]
            for entry in files:
                try:
                    is_current = (current_resolved is not None
                                  and entry.resolve() == current_resolved)
                except OSError:
                    is_current = False

                prefix = ""
                tooltip_lines = [entry.name]
                # 將原本判斷 ".json" 改為判斷 "raw"
                if ext == "raw" and entry.stem in lexa_stems:
                    prefix = "◐ "
                    tooltip_lines.append("• 已有對應 .lexa 標註進度")
                if is_current:
                    prefix = "● " + prefix.lstrip()
                    if not prefix.endswith(" "):
                        prefix += " "

                dirty_mark = "*" if (is_current and self._current_dirty) else ""
                item = QListWidgetItem(f"{prefix}{entry.name}{dirty_mark}")
                item.setData(Qt.UserRole, str(entry))

                # Bold the sibling .json row of the currently-open .lexa,
                # even though that .json itself isn't the active document.
                bold = is_current or (
                    ext == "raw"
                    and current_lexa_stem is not None
                    and entry.stem == current_lexa_stem
                )
                if bold:
                    f = item.font()
                    f.setBold(True)
                    item.setFont(f)

                item.setToolTip("\n".join(tooltip_lines))
                lst.addItem(item)

            idx = _TAB_ORDER.index(ext)
            self.tabs.setTabText(idx, f"{_TAB_LABELS[ext]} ({len(files)})")

    def select_path(self, path: Optional[Path]):
        self._current_path = Path(path) if path else None
        self.refresh()
        if self._current_path is not None:
            self._switch_to_tab_for(self._current_path)

    def select_relative(self, delta: int):
        active = self.tabs.currentWidget()
        if not isinstance(active, QListWidget) or active.count() == 0:
            return
        cur = active.currentRow()
        if cur < 0:
            cur = 0
        new = max(0, min(active.count() - 1, cur + delta))
        active.setCurrentRow(new)
        item = active.item(new)
        if item is not None:
            self.file_open_requested.emit(item.data(Qt.UserRole))

    # ------------------------------------------------------------ handlers

    def _on_item_activated(self, item: Optional[QListWidgetItem]):
        # item 可能是 None：同一次雙擊在開檔後 refresh() 把原 item 銷毀，
        # 之後 Qt 仍可能派送陳舊訊號。
        if item is None:
            return
        path = item.data(Qt.UserRole)
        if path:
            self.file_open_requested.emit(path)

    # ------------------------------------------------------------ internals

    def _switch_to_tab_for(self, path: Path) -> None:
        ext = path.suffix.lower()
        if ext in (".json", ".docx"):
            tab_key = "raw"
        elif ext == ".lexa":
            tab_key = ".lexa"
        elif ext == ".txt":
            tab_key = ".txt"
        else:
            return
        if tab_key in _TAB_ORDER:
            self.tabs.setCurrentIndex(_TAB_ORDER.index(tab_key))
