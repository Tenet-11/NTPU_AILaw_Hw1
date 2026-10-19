"""Configuration loading: annotation modes and user preferences."""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Locate config directory
# ---------------------------------------------------------------------------

def app_root() -> Path:
    """Project root.

    When running from source, this is the parent of the `lexiarbiter` package.
    When running from a PyInstaller bundle (one-file or one-folder), use the
    directory of the executable so users can edit configs next to it.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


def configs_dir() -> Path:
    return app_root() / "configs"


def annotation_modes_dir() -> Path:
    return configs_dir() / "annotation_modes"


def user_preferences_path() -> Path:
    return configs_dir() / "user_preferences.json"


def default_ui_font() -> str:
    """依執行平台回傳預設 UI 字型名稱。各平台挑系統內建、能正確顯示繁中的字型，
    避免使用者初次啟動時看到方框/缺字。"""
    if sys.platform == "darwin":
        return "PingFang TC"
    if sys.platform.startswith("win"):
        return "Microsoft JhengHei UI"
    return "Noto Sans CJK TC"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class LabelDef:
    id: str
    name: str
    tag: str
    color: Optional[str]
    shortcut: Optional[str]
    group_id: str = ""

    @property
    def qualified_id(self) -> str:
        return f"{self.group_id}.{self.id}"


@dataclass
class GroupDef:
    id: str
    name: str
    role: str
    description: str
    labels: list[LabelDef]

    def label(self, label_id: str) -> Optional[LabelDef]:
        for lb in self.labels:
            if lb.id == label_id:
                return lb
        return None

    def label_by_tag(self, tag: str) -> Optional[LabelDef]:
        for lb in self.labels:
            if lb.tag == tag:
                return lb
        return None


@dataclass
class ExportConfig:
    format: str = "p_tag"
    tag_order: list[str] = field(default_factory=list)
    tag_separator: str = ","
    wrapper_open: str = "<P>"
    wrapper_close: str = "</P>"
    field_separator: str = "|"
    include_unannotated: bool = False
    require_all_groups: bool = False


@dataclass
class AnnotationMode:
    id: str
    name: str
    description: str
    groups: list[GroupDef]
    export: ExportConfig
    file_path: Optional[Path] = None

    def group(self, group_id: str) -> Optional[GroupDef]:
        for g in self.groups:
            if g.id == group_id:
                return g
        return None

    def label(self, group_id: str, label_id: str) -> Optional[LabelDef]:
        g = self.group(group_id)
        return g.label(label_id) if g else None

    def all_labels(self) -> list[LabelDef]:
        return [lb for g in self.groups for lb in g.labels]

    def find_label_by_tag(self, tag: str) -> Optional[LabelDef]:
        for g in self.groups:
            lb = g.label_by_tag(tag)
            if lb is not None:
                return lb
        return None


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_annotation_mode(path: Path | str) -> AnnotationMode:
    path = Path(path)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    groups: list[GroupDef] = []
    for g in data.get("groups", []):
        labels = [
            LabelDef(
                id=lb["id"],
                name=lb["name"],
                tag=lb.get("tag", lb["name"]),
                color=lb.get("color"),
                shortcut=lb.get("shortcut"),
                group_id=g["id"],
            )
            for lb in g.get("labels", [])
        ]
        groups.append(GroupDef(
            id=g["id"],
            name=g["name"],
            role=g.get("role", ""),
            description=g.get("description", ""),
            labels=labels,
        ))

    exp = data.get("export", {}) or {}
    export = ExportConfig(
        format=exp.get("format", "p_tag"),
        tag_order=list(exp.get("tag_order", [g.id for g in groups])),
        tag_separator=exp.get("tag_separator", ","),
        wrapper_open=exp.get("wrapper_open", "<P>"),
        wrapper_close=exp.get("wrapper_close", "</P>"),
        field_separator=exp.get("field_separator", "|"),
        include_unannotated=bool(exp.get("include_unannotated", False)),
        require_all_groups=bool(exp.get("require_all_groups", False)),
    )

    return AnnotationMode(
        id=data["id"],
        name=data.get("name", data["id"]),
        description=data.get("description", ""),
        groups=groups,
        export=export,
        file_path=path,
    )


def list_annotation_modes() -> list[AnnotationMode]:
    out: list[AnnotationMode] = []
    d = annotation_modes_dir()
    if not d.exists():
        return out
    for p in sorted(d.glob("*.json")):
        try:
            out.append(load_annotation_mode(p))
        except Exception:
            # 略過損壞的設定檔，但記錄 warning 方便除錯
            log.warning("略過無法載入的標註模式設定檔：%s", p, exc_info=True)
            continue
    return out


# ---------------------------------------------------------------------------
# User preferences
# ---------------------------------------------------------------------------

DEFAULT_PREFERENCES: dict = {
    "active_annotation_mode": "legal_mtl",
    "ui": {
        "font_family": default_ui_font(),
        "font_size": 14,
        "line_spacing": 1.5,
        "theme": "light",
        "show_paragraph_breaks": True,
    },
    "shortcut_overrides": {
        "_app": {
            "open": "Ctrl+O",
            "save": "Ctrl+S",
            "export_txt": "Ctrl+E",
            "remove_annotation": "Ctrl+D",
            "next_file": "Alt+Down",
            "prev_file": "Alt+Up",
        },
    },
    "behavior": {
        "confirm_unsaved_on_switch": True,
        "warn_partial_groups_on_export": True,
        "auto_popup_on_selection": True,
        "show_concept_popup": True,  # 新增：標註時是否跳出概念選擇視窗
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


class UserPreferences:
    def __init__(self, data: dict, file_path: Optional[Path] = None):
        self.data = data
        self.file_path = file_path

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "UserPreferences":
        path = path or user_preferences_path()
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    user = json.load(f)
                merged = _deep_merge(DEFAULT_PREFERENCES, user)
                return cls(merged, path)
            except Exception:
                # 讀取失敗時退回預設值，並記錄 warning
                log.warning("讀取使用者偏好設定失敗，使用預設值：%s", path, exc_info=True)
        return cls(dict(DEFAULT_PREFERENCES), path)

    def save(self) -> None:
        if self.file_path is None:
            self.file_path = user_preferences_path()
        os.makedirs(self.file_path.parent, exist_ok=True)
        # Skip private "_comment" keys when saving back.
        with open(self.file_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    # convenience
    @property
    def active_mode_id(self) -> str:
        return self.data.get("active_annotation_mode", "legal_mtl")

    @active_mode_id.setter
    def active_mode_id(self, value: str) -> None:
        self.data["active_annotation_mode"] = value

    @property
    def ui(self) -> dict:
        return self.data.get("ui", {})

    @property
    def behavior(self) -> dict:
        return self.data.get("behavior", {})

    def label_shortcut(self, group_id: str, label_id: str, default: Optional[str]) -> Optional[str]:
        ov = self.data.get("shortcut_overrides", {})
        return ov.get(f"{group_id}.{label_id}", default)

    def app_shortcut(self, name: str, default: str) -> str:
        ov = self.data.get("shortcut_overrides", {}).get("_app", {})
        return ov.get(name, default)
