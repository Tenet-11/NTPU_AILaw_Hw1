"""Concept management UI components."""
import uuid
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QLineEdit, QPushButton, 
    QLabel, QWidget, QMessageBox
)

class ConceptSelectionDialog(QDialog):
    """彈出視窗：讓使用者從現有概念挑選，或輸入新概念。"""
    def __init__(self, concepts: dict[str, str], default_text: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("選擇或新增對應概念")
        self.resize(350, 450)
        
        layout = QVBoxLayout(self)
        
        layout.addWidget(QLabel("1. 從現有概念選擇："))
        self.list_widget = QListWidget()
        # 依最近加入(或字母)排序顯示
        self._concept_map = {}
        for cid, name in concepts.items():
            self.list_widget.addItem(name)
            self._concept_map[name] = cid
        layout.addWidget(self.list_widget)
        # 將清單依照筆畫/字母順序排序
        self.list_widget.sortItems(Qt.AscendingOrder)

        layout.addWidget(QLabel("2. 或直接輸入新概念："))
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("輸入新術語概念...")
        # 自動將反白的文字填入輸入框
        self.input_edit.setText(default_text) 
        # 選取框內所有文字，方便使用者如果不滿意可以直接打字覆蓋
        self.input_edit.selectAll()
        layout.addWidget(self.input_edit)

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

        # 點擊清單時自動填入輸入框
        self.list_widget.itemClicked.connect(lambda item: self.input_edit.setText(item.text()))
        self.list_widget.itemDoubleClicked.connect(self.accept)

    def get_result(self) -> tuple[str | None, str | None]:
        """回傳 (已存在的 ID, 新增的名稱)。若輸入框為空則回傳 (None, None)。"""
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
        
        layout.addWidget(title)
        layout.addWidget(self.list_widget)

    def refresh(self, doc):
        self.list_widget.clear()
        if not doc or not hasattr(doc, 'concepts'):
            return
        for cid, name in doc.concepts.items():
            self.list_widget.addItem(f"● {name}")

        # 讓側邊欄的概念清單也依照筆畫/字母自動排序
        self.list_widget.sortItems(Qt.AscendingOrder)