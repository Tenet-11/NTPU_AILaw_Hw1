"""The annotation editor widget.

We keep the *original* text in `Document.text` (with raw ``\\r\\n`` line
endings, exactly as it appears in the source JSON), because that is what gets
serialised into ``.lexa`` / ``.txt`` output and what the user's MTL pipeline
preprocesses later.

For *display*, ``\\r\\n`` is normalised to ``\\n`` so Qt renders nicely. We
maintain two-way maps between the two coordinate systems so annotation offsets
always refer to the original (storage) text.
"""

from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger(__name__)

from PySide6.QtCore import QEvent, Qt, QPoint, Signal
from PySide6.QtGui import (
    QAction, QColor, QGuiApplication, QKeySequence, QShortcut, QTextCharFormat,
    QTextCursor, QFont, QPalette,
)
from PySide6.QtWidgets import QMenu, QTextEdit, QToolTip

from ..core.config import AnnotationMode, UserPreferences, default_ui_font
from ..core.models import Annotation, Document


# 術語模式下依文件概念循環使用。相同 concept_id 會維持同色，前 12 個
# 概念則各有不同顏色；只影響畫面，不影響 .lexa 的標籤資料。
_CONCEPT_COLORS = [
    "#FFE082",  # amber
    "#80CBC4",  # teal
    "#90CAF9",  # blue
    "#CE93D8",  # purple
    "#FFAB91",  # deep orange
    "#A5D6A7",  # green
    "#F48FB1",  # pink
    "#BCAAA4",  # brown
    "#9FA8DA",  # indigo
    "#E6EE9C",  # lime
    "#80DEEA",  # cyan
    "#FFCC80",  # orange
]


class _OffsetMap:
    """Bidirectional map between storage offsets (with \\r\\n) and display
    offsets (with \\n)."""

    def __init__(self, raw: str):
        # Walk through `raw` and build a mapping.
        self.storage_to_display: list[int] = [0] * (len(raw) + 1)
        self.display_to_storage: list[int] = []
        d = 0
        i = 0
        while i < len(raw):
            self.storage_to_display[i] = d
            ch = raw[i]
            if ch == "\r" and i + 1 < len(raw) and raw[i + 1] == "\n":
                # Skip the \r entirely in display.
                self.storage_to_display[i + 1] = d  # \n still maps to current d
                self.display_to_storage.append(i + 1)  # display position d -> storage \n
                d += 1
                i += 2
            else:
                self.display_to_storage.append(i)
                d += 1
                i += 1
        self.storage_to_display[len(raw)] = d
        self.display_to_storage.append(len(raw))

    def to_display(self, storage_offset: int) -> int:
        if storage_offset <= 0:
            return 0
        if storage_offset >= len(self.storage_to_display):
            return self.storage_to_display[-1]
        return self.storage_to_display[storage_offset]

    def to_storage(self, display_offset: int) -> int:
        if display_offset <= 0:
            return 0
        if display_offset >= len(self.display_to_storage):
            return self.display_to_storage[-1]
        return self.display_to_storage[display_offset]


def _hex_to_qcolor(value: Optional[str], alpha: int = 110) -> Optional[QColor]:
    if not value:
        return None
    c = QColor(value)
    if not c.isValid():
        return None
    c.setAlpha(alpha)
    return c


def _is_dark_palette(widget) -> bool:
    """判斷 widget 目前是否處於深色背景主題。

    優先讀 Qt 6.5+ 的 ``styleHints().colorScheme()``；舊版或回報 Unknown 時
    退回以 ``QPalette.Base`` 亮度判斷（< 128 視為深色）。
    """
    try:
        scheme = QGuiApplication.styleHints().colorScheme()
        if scheme == Qt.ColorScheme.Dark:
            return True
        if scheme == Qt.ColorScheme.Light:
            return False
    except (AttributeError, RuntimeError):
        pass
    return widget.palette().color(QPalette.Base).lightness() < 128


class AnnotationEditor(QTextEdit):
    """Read-only-ish text view that renders annotations as background highlights.

    Selection is editable in the sense that the user can click and drag to
    select text spans, and we expose those spans for the host window to apply
    annotations to. The text content itself cannot be modified.
    """

    annotation_clicked = Signal(str)  # annotation id
    selection_changed = Signal(int, int)  # storage start, storage end
    # 滑鼠左鍵拖選結束、且選取範圍非空時 emit；參數為放開滑鼠的 global 座標，
    # 讓 host window 可以在原地附近彈出快速標註選單。
    selection_finished = Signal(QPoint)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setUndoRedoEnabled(False)
        # Allow text selection but keep cursor visible.
        self.setTextInteractionFlags(
            Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard
        )
        self.setMouseTracking(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        self.selectionChanged.connect(self._on_selection_changed)

        self._doc: Optional[Document] = None
        self._mode: Optional[AnnotationMode] = None
        self._prefs: Optional[UserPreferences] = None
        self._omap: Optional[_OffsetMap] = None
        self._active_annotation_id: Optional[str] = None
        self._context_menu_builder = None
        # 追蹤是不是「正在拖左鍵」；右鍵 / 中鍵 / 鍵盤選取都不應觸發 popup。
        self._left_drag_active: bool = False

        # 系統深 / 淺色主題切換時自動重繪。Qt 6.5+ 才有此 signal，
        # 舊版直接 fallback 到「重啟程式才生效」。
        try:
            QGuiApplication.styleHints().colorSchemeChanged.connect(
                lambda _scheme: self.refresh_highlights()
            )
        except (AttributeError, RuntimeError):
            pass

    # ------------------------------------------------------------------ setup

    def attach(self, doc: Document, mode: AnnotationMode, prefs: UserPreferences):
        self._doc = doc
        self._mode = mode
        self._prefs = prefs
        self._active_annotation_id = None

        font = QFont(prefs.ui.get("font_family", default_ui_font()),
                     prefs.ui.get("font_size", 14))
        self.setFont(font)

        # Normalise \r\n -> \n for display.
        display_text = doc.text.replace("\r\n", "\n")
        self._omap = _OffsetMap(doc.text)
        self.setPlainText(display_text)

        # Block-format with line spacing.
        self._apply_line_spacing(prefs.ui.get("line_spacing", 1.4))
        self.refresh_highlights()

    def _apply_line_spacing(self, factor: float):
        if not self._doc:
            return
        cursor = QTextCursor(self.document())
        cursor.select(QTextCursor.Document)
        block_fmt = cursor.blockFormat()
        block_fmt.setLineHeight(int(factor * 100), 1)  # ProportionalHeight
        cursor.setBlockFormat(block_fmt)

    def set_active_annotation(
        self,
        ann_id: Optional[str],
    ):
        self._active_annotation_id = ann_id
        self.refresh_highlights()

    def set_context_menu_builder(self, fn):
        """`fn(menu, ann_id_or_None, sel_start, sel_end)` populates the menu."""
        self._context_menu_builder = fn

    # ----------------------------------------------------------- selection

    def storage_selection(self) -> tuple[int, int]:
        if self._omap is None:
            return (0, 0)
        cur = self.textCursor()
        d_start = cur.selectionStart()
        d_end = cur.selectionEnd()
        return (self._omap.to_storage(d_start), self._omap.to_storage(d_end))

    def has_selection(self) -> bool:
        s, e = self.storage_selection()
        return e > s

    def _on_selection_changed(self):
        s, e = self.storage_selection()
        self.selection_changed.emit(s, e)

    # --------------------------------------------------- mouse drag detection

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._left_drag_active = True
        super().mousePressEvent(ev)

    # 使用者點擊已標註文字時，Editor 發出 annotation_clicked
    def mouseReleaseEvent(self, ev):
        super().mouseReleaseEvent(ev)

        if ev.button() == Qt.LeftButton and self._left_drag_active:
            self._left_drag_active = False

        # 有拖選文字：顯示快速標註選單。
            if self.has_selection():
                self.selection_finished.emit(
                    ev.globalPosition().toPoint()
                )
                return

        # 沒有選取文字：檢查是否點到既有標註。
            if self._doc is None or self._omap is None:
                return

            cursor = self.cursorForPosition(
                ev.position().toPoint()
            )
            display_pos = cursor.position()
            storage_pos = self._omap.to_storage(display_pos)

            annotations = self._doc.annotations_at(storage_pos)

            if annotations:
                self.annotation_clicked.emit(
                    annotations[-1].id
                )

    # ------------------------------------------------------ highlight render
    # 滑鼠停在解釋範圍時，顯示該解釋所屬的概念。
    def viewportEvent(self, event):
        if (
            event.type() == QEvent.ToolTip
            and self._doc is not None
            and self._omap is not None
        ):
            cursor = self.cursorForPosition(
                event.pos()
            )
            storage_pos = self._omap.to_storage(
                cursor.position()
            )

            tooltip_blocks: list[str] = []

            # 先檢查滑鼠是否位於某筆術語的解釋範圍。
            for ann in self._doc.annotations:
                start = ann.explanation_start
                end = ann.explanation_end

                if start is None or end is None:
                    continue

                if not (start <= storage_pos < end):
                    continue

                term_text = self._doc.text[
                    ann.start:ann.end
                ]

                if ann.concept_id is not None:
                    concept_name = (
                        self._doc.concepts.get(
                            ann.concept_id,
                            ann.concept_id,
                        )
                    )
                else:
                    concept_name = "尚未指定概念"

                if ann.broader_concept_id is not None:
                    broader_name = (
                        self._doc.concepts.get(
                            ann.broader_concept_id,
                            ann.broader_concept_id,
                        )
                    )
                else:
                    broader_name = "尚未設定"

                if ann.id == self._active_annotation_id:
                    selected_text = "目前選取：是"
                else:
                    selected_text = "目前選取：否"

                block = (
                    f"對應術語：{term_text}\n"
                    f"文件概念：{concept_name}\n"
                    f"上位概念：{broader_name}\n"
                    f"{selected_text}"
                )

                if block not in tooltip_blocks:
                    tooltip_blocks.append(block)

            # 如果不是解釋範圍，再檢查是否停在黃色術語上。
            if not tooltip_blocks:
                annotations = self._doc.annotations_at(
                    storage_pos
                )

                for ann in annotations:
                    term_text = self._doc.text[
                        ann.start:ann.end
                    ]

                    if ann.concept_id is not None:
                        concept_name = (
                            self._doc.concepts.get(
                                ann.concept_id,
                                ann.concept_id,
                            )
                        )
                    else:
                        concept_name = "尚未指定概念"


                    if ann.broader_concept_id is not None:
                        broader_name = (
                            self._doc.concepts.get(
                                ann.broader_concept_id,
                                ann.broader_concept_id,
                            )
                        )
                    else:
                        broader_name = "尚未設定"

                    if (
                        ann.explanation_start is not None
                        and ann.explanation_end is not None
                    ):
                        explanation_text = self._doc.text[
                            ann.explanation_start:
                            ann.explanation_end
                        ]

                        explanation_text = (
                            explanation_text
                            .replace("\r", " ")
                            .replace("\n", " ")
                            .strip()
                        )

                        if len(explanation_text) > 50:
                            explanation_text = (
                                explanation_text[:47] + "…"
                            )
                    else:
                        explanation_text = "尚未標記"

                    block = (
                        f"術語：{term_text}\n"
                        f"文件概念：{concept_name}\n"
                        f"上位概念：{broader_name}\n"
                        f"解釋：{explanation_text}"
                    )

                    if block not in tooltip_blocks:
                        tooltip_blocks.append(block)

            if tooltip_blocks:
                QToolTip.showText(
                    event.globalPos(),
                    "\n\n".join(tooltip_blocks),
                    self,
                )
                return True

        return super().viewportEvent(event)
    
    def refresh_highlights(self):
        if self._doc is None or self._mode is None or self._omap is None:
            return
        try:
            selections = []

            # 先繪製解釋範圍，再繪製術語。
            # 這樣當解釋與術語重疊時，術語的黃色仍會顯示在上層。
            explanation_ranges: set[tuple[int, int]] = set()
            dark = _is_dark_palette(self)

            for ann in self._doc.annotations:
                start = ann.explanation_start
                end = ann.explanation_end

                # 沒有解釋座標或範圍不合法時，不進行繪製。
                if start is None or end is None:
                    continue
                if not (0 <= start < end <= len(self._doc.text)):
                    continue

                # 相同概念的多個術語可能共用同一段解釋，
                # 所以使用 set 避免同一範圍被重複畫很多次。
                explanation_range = (start, end)
                if explanation_range in explanation_ranges:
                    continue
                explanation_ranges.add(explanation_range)

                explanation_selection = QTextEdit.ExtraSelection()
                explanation_cursor = self.textCursor()

                display_start = self._omap.to_display(start)
                display_end = self._omap.to_display(end)

                explanation_cursor.setPosition(display_start)
                explanation_cursor.setPosition(
                    display_end,
                    QTextCursor.KeepAnchor,
                )
                explanation_selection.cursor = explanation_cursor

                explanation_format = QTextCharFormat()
                is_active = (
                    ann.id == self._active_annotation_id
                )
                if is_active:
                    # 目前選中術語的解釋：使用較深的藍色。
                    explanation_color = QColor("#0288D1")
                    explanation_color.setAlpha(
                        220 if dark else 170
                    )
                else:
                    # 其他術語的解釋：維持較淡的藍色。
                    explanation_color = QColor("#64B5F6")
                    explanation_color.setAlpha(
                        160 if dark else 90
                    )

                explanation_format.setBackground(
                    explanation_color
                )

                concept_name = (
                    self._doc.concepts.get(
                        ann.concept_id,
                        ann.concept_id,
                    )
                    if ann.concept_id is not None
                    else "尚未指定概念"
                )

                term_text = self._doc.text[
                    ann.start:ann.end
                ]

                explanation_format.setToolTip(
                    f"對應術語：{term_text}\n"
                    f"文件概念：{concept_name}"
                )

                if dark:
                    explanation_format.setForeground(
                        QColor("#102027")
                    )

                explanation_selection.format = explanation_format
                selections.append(explanation_selection)

            for ann in self._doc.annotations:
                sel = QTextEdit.ExtraSelection()
                cursor = self.textCursor()
                d_start = self._omap.to_display(ann.start)
                d_end = self._omap.to_display(ann.end)
                cursor.setPosition(d_start)
                cursor.setPosition(d_end, QTextCursor.KeepAnchor)
                sel.cursor = cursor

                fmt = QTextCharFormat()
                self._apply_format_for_labels(fmt, ann)
                if ann.id == self._active_annotation_id:
                    fmt.setFontWeight(QFont.Bold)
                sel.format = fmt
                selections.append(sel)
            self.setExtraSelections(selections)
        except Exception:
            # 高亮渲染失敗時清空顯示，避免整個 UI 崩潰
            log.error("refresh_highlights 發生例外，已清空高亮", exc_info=True)
            self.setExtraSelections([])

    def _apply_format_for_labels(self, fmt: QTextCharFormat, ann: Annotation):
        """First group with a non-null color drives the background.
        Other group labels are reflected via underline style.

        渲染參數依當下 palette（深 / 淺）自動切換：深色模式提高背景 alpha 並
        強制反白標註內文字色，底線色則固定取近黑或近白以保證對比。
        """
        if self._mode is None:
            return
        dark = _is_dark_palette(self)
        bg_alpha = 180 if dark else 130
        fallback_alpha = 90 if dark else 50
        # 底線色一律取與編輯器背景對比最強的近黑 / 近白，不再從主背景色 darker/lighter 派生
        underline_default = QColor("#ECEFF1") if dark else QColor("#1B1B1B")

        bg_color: Optional[QColor] = None
        underline_style = QTextCharFormat.NoUnderline
        underline_color: Optional[QColor] = None
        tooltip_parts: list[str] = []

        for g in self._mode.groups:
            lid = ann.labels.get(g.id)
            if not lid:
                continue
            lb = g.label(lid)
            if lb is None:
                continue
            tooltip_parts.append(f"{g.name}：{lb.name}")
            color = _hex_to_qcolor(lb.color, alpha=bg_alpha)
            if color is not None and bg_color is None:
                bg_color = color
            elif color is None:
                # 輔助群組：依該群組內 label 索引選底線樣式。
                # WaveUnderline / DashDotLine 兩者視覺差異大，在中文字下都不會被誤認為實線。
                idx = g.labels.index(lb)
                styles = [
                    QTextCharFormat.WaveUnderline,    # 第一人稱：波浪線（視覺重量大，主關注點）
                    QTextCharFormat.DashDotLine,      # 非第一人稱：dash-dot（次要層次）
                    QTextCharFormat.SingleUnderline,  # 預留第三類
                    QTextCharFormat.DotLine,          # 預留第四類
                ]
                underline_style = styles[idx % len(styles)]
                underline_color = underline_default

        if (
            self._mode.id == "term_definition"
            and self._doc is not None
            and ann.concept_id is not None
            and ann.concept_id in self._doc.concepts
        ):
            concept_ids = list(self._doc.concepts)
            concept_index = concept_ids.index(ann.concept_id)
            concept_hex = _CONCEPT_COLORS[
                concept_index % len(_CONCEPT_COLORS)
            ]
            bg_color = _hex_to_qcolor(
                concept_hex,
                alpha=bg_alpha,
            )

        if bg_color is None:
            # 無主背景色時：淡黃後備，深色模式提高 alpha 讓 span 仍可辨識。
            bg_color = _hex_to_qcolor("#FFF59D", alpha=fallback_alpha)

        fmt.setBackground(bg_color)
        # 深色模式下標註背景變得不透明度高，強制深色文字色保證閱讀對比。
        if dark and bg_color is not None:
            fmt.setForeground(QColor("#1B1B1B"))
        if underline_style != QTextCharFormat.NoUnderline:
            fmt.setUnderlineStyle(underline_style)
            if underline_color is not None:
                fmt.setUnderlineColor(underline_color)
        if tooltip_parts:
            fmt.setToolTip("　|　".join(tooltip_parts))

    # ----------------------------------------------------------- context menu

    def _on_context_menu(self, pos: QPoint):
        if self._context_menu_builder is None:
            return
        menu = QMenu(self)
        cursor = self.cursorForPosition(pos)
        d_pos = cursor.position()
        if self._omap is None:
            return
        storage_pos = self._omap.to_storage(d_pos)
        sel_start, sel_end = self.storage_selection()
        ann_id = None
        if self._doc is not None:
            anns_at = self._doc.annotations_at(storage_pos)
            if anns_at:
                ann_id = anns_at[-1].id
        self._context_menu_builder(menu, ann_id, sel_start, sel_end)
        if not menu.isEmpty():
            menu.exec(self.mapToGlobal(pos))

    def annotation_at_cursor(self) -> Optional[str]:
        if self._doc is None or self._omap is None:
            return None
        cur = self.textCursor()
        storage_pos = self._omap.to_storage(cur.position())
        anns_at = self._doc.annotations_at(storage_pos)
        return anns_at[-1].id if anns_at else None

    def jump_to_annotation(self, ann_id: str):
        if self._doc is None or self._omap is None:
            return
        ann = self._doc.find_annotation(ann_id)
        if ann is None:
            return
        cur = self.textCursor()
        cur.setPosition(self._omap.to_display(ann.start))
        cur.setPosition(self._omap.to_display(ann.end), QTextCursor.KeepAnchor)
        self.setTextCursor(cur)
        self.ensureCursorVisible()
