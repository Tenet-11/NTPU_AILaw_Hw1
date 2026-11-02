"""Concept management UI components."""
import uuid
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget,
    QListWidgetItem, QTreeWidget, QTreeWidgetItem,
    QAbstractItemView, QLineEdit, QPushButton,
    QLabel, QWidget, QMessageBox
)

class ConceptSelectionDialog(QDialog):
    """彈出視窗：讓使用者從現有概念挑選，或輸入新概念。"""
    def __init__(
        self,
        concepts: dict[str, str],
        default_text: str = "",
        parent=None,
        allow_new: bool = True,
        broader_by_concept: dict[str, str] | None = None,
    ):
        super().__init__(parent)
        self.allow_new = allow_new
        self._updating_tree = False
        self.setWindowTitle("選擇或新增對應概念")
        self.resize(420, 500)
        
        layout = QVBoxLayout(self)
        
        layout.addWidget(QLabel("1. 從概念階層中選擇："))
        self.tree_widget = QTreeWidget()
        self.tree_widget.setHeaderHidden(True)
        self.tree_widget.setSelectionMode(
            QAbstractItemView.SingleSelection
        )
        self._concept_map = {
            name: cid for cid, name in concepts.items()
        }
        self._tree_items: dict[str, QTreeWidgetItem] = {}
        self._build_concept_tree(
            concepts,
            broader_by_concept or {},
        )
        self.tree_widget.expandAll()
        layout.addWidget(self.tree_widget)

        self.input_label = QLabel("2. 或直接輸入新概念：")
        layout.addWidget(self.input_label)
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("輸入新術語概念...")
        # 自動將反白的文字填入輸入框
        self.input_edit.setText(default_text) 
        # 選取框內所有文字，方便使用者如果不滿意可以直接打字覆蓋
        self.input_edit.selectAll()
        layout.addWidget(self.input_edit)

        # 有些流程（例如「要被設定的子概念」）只能選既有概念。
        # 直接隱藏新增欄位，避免使用者輸入後才收到拒絕訊息。
        self.input_label.setVisible(allow_new)
        self.input_edit.setVisible(allow_new)

        # 按鈕區
        btn_layout = QHBoxLayout()
        self.btn_ok = QPushButton("確定 (Enter)")
        self.btn_ok.setStyleSheet("background-color: #2196F3; color: white; font-weight: bold; padding: 6px; border-radius: 4px;")
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setStyleSheet("background-color: #546E7A; color: white; padding: 6px; border-radius: 4px;")
        self.btn_cancel.clicked.connect(self.reject)

        # 將按鈕推到對話框的右下角
        btn_layout.addStretch()
        
        # 將 OK 放在前面 (左邊)，Cancel 放在後面 (右邊)
        btn_layout.addWidget(self.btn_ok)
        btn_layout.addWidget(self.btn_cancel)
        layout.addLayout(btn_layout)

        # 階層清單採單選勾選；點文字或方框都會選取該概念。
        self.tree_widget.itemClicked.connect(
            self._on_tree_item_clicked
        )
        self.tree_widget.itemChanged.connect(
            self._on_tree_item_changed
        )
        self.tree_widget.itemDoubleClicked.connect(
            lambda _item, _column: self.accept()
        )
        self.input_edit.textEdited.connect(
            self._on_input_edited
        )

    def _build_concept_tree(
        self,
        concepts: dict[str, str],
        broader_by_concept: dict[str, str],
    ):
        """依 concept -> broader concept 關係建立可展開的概念樹。"""
        parent_by_child = {
            child_id: broader_id
            for child_id, broader_id in broader_by_concept.items()
            if child_id in concepts
            and broader_id in concepts
            and child_id != broader_id
        }

        # 防止舊資料中的循環關係讓概念完全無法顯示；遇到循環時，
        # 將其中一個節點提升為根節點。
        for concept_id in list(parent_by_child):
            seen = {concept_id}
            current = parent_by_child.get(concept_id)
            while current is not None:
                if current in seen:
                    parent_by_child.pop(concept_id, None)
                    break
                seen.add(current)
                current = parent_by_child.get(current)

        children_by_parent: dict[str, list[str]] = {}
        for child_id, parent_id in parent_by_child.items():
            children_by_parent.setdefault(parent_id, []).append(
                child_id
            )

        def add_item(
            concept_id: str,
            parent_item: QTreeWidgetItem | None,
        ):
            item = QTreeWidgetItem([concepts[concept_id]])
            item.setData(0, Qt.UserRole, concept_id)
            item.setFlags(
                item.flags()
                | Qt.ItemIsUserCheckable
                | Qt.ItemIsSelectable
                | Qt.ItemIsEnabled
            )
            item.setCheckState(0, Qt.Unchecked)

            parent_id = parent_by_child.get(concept_id)
            if parent_id is None:
                item.setToolTip(0, "最上層概念")
            else:
                item.setToolTip(
                    0,
                    f"上位概念：{concepts[parent_id]}",
                )

            if parent_item is None:
                self.tree_widget.addTopLevelItem(item)
            else:
                parent_item.addChild(item)
            self._tree_items[concept_id] = item

            child_ids = children_by_parent.get(concept_id, [])
            for child_id in sorted(
                child_ids,
                key=lambda cid: concepts[cid],
            ):
                add_item(child_id, item)

        root_ids = [
            concept_id
            for concept_id in concepts
            if concept_id not in parent_by_child
        ]
        for concept_id in sorted(
            root_ids,
            key=lambda cid: concepts[cid],
        ):
            add_item(concept_id, None)

    def _select_tree_item(self, item: QTreeWidgetItem):
        self._updating_tree = True
        try:
            for other in self._tree_items.values():
                other.setCheckState(
                    0,
                    Qt.Checked if other is item else Qt.Unchecked,
                )
            self.tree_widget.setCurrentItem(item)
        finally:
            self._updating_tree = False

        if self.allow_new:
            self.input_edit.setText(item.text(0))

    def _on_tree_item_clicked(
        self,
        item: QTreeWidgetItem,
        _column: int,
    ):
        self._select_tree_item(item)

    def _on_tree_item_changed(
        self,
        item: QTreeWidgetItem,
        _column: int,
    ):
        if self._updating_tree:
            return
        if item.checkState(0) == Qt.Checked:
            self._select_tree_item(item)

    def _on_input_edited(self, text: str):
        """輸入新名稱時取消舊勾選，避免畫面同時表示兩種結果。"""
        if not self.allow_new:
            return
        current = self.tree_widget.currentItem()
        if current is None or text.strip() == current.text(0):
            return
        self._updating_tree = True
        try:
            current.setCheckState(0, Qt.Unchecked)
            self.tree_widget.clearSelection()
        finally:
            self._updating_tree = False

    def accept(self):
        if not self.allow_new:
            if self.tree_widget.currentItem() is None:
                QMessageBox.information(
                    self,
                    "請選擇既有概念",
                    "請從上方清單選擇要設定的概念。",
                )
                self.tree_widget.setFocus()
                return

            super().accept()
            return

        text = self.input_edit.text().strip()

        if not text:
            QMessageBox.information(
                self,
                "概念名稱不可空白",
                "請選擇既有概念，或輸入新的概念名稱。",
            )
            self.input_edit.setFocus()
            return

        super().accept()


    def get_result(self) -> tuple[str | None, str | None]:
        """回傳 (已存在的 ID, 新增的名稱)。若輸入框為空則回傳 (None, None)。"""
        if not self.allow_new:
            item = self.tree_widget.currentItem()
            if item is None:
                return None, None
            return item.data(0, Qt.UserRole), None

        text = self.input_edit.text().strip()
        if not text:
            return None, None
        if text in self._concept_map:
            return self._concept_map[text], None
        return None, text


class ConceptSidebar(QWidget):
    """側邊欄：顯示當前文件所有的概念池"""
    concept_clicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        
        title = QLabel("文件概念清單 (Concepts)")
        f = title.font()
        f.setBold(True)
        title.setFont(f)
        
        self.list_widget = QListWidget()
        self.list_widget.itemClicked.connect(
            self._on_item_clicked
        )
        
        layout.addWidget(title)
        layout.addWidget(self.list_widget)

    def refresh(self, doc):
        self.list_widget.clear()
        if not doc or not hasattr(doc, 'concepts'):
            return
        for cid, name in doc.concepts.items():
            item = QListWidgetItem(f"● {name}")
            item.setData(Qt.UserRole, cid)
            self.list_widget.addItem(item)

        # 讓側邊欄的概念清單也依照筆畫/字母自動排序
        self.list_widget.sortItems(Qt.AscendingOrder)

    def _on_item_clicked(self, item: QListWidgetItem):
        concept_id = item.data(Qt.UserRole)

        if concept_id:
            self.concept_clicked.emit(concept_id)
