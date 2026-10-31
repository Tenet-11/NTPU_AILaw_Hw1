import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QTextCharFormat
from PySide6.QtWidgets import QApplication

from lexiarbiter.app import MainWindow
from lexiarbiter.core.config import UserPreferences, list_annotation_modes
from lexiarbiter.core.models import Annotation, Document
from lexiarbiter.widgets.editor import AnnotationEditor


class _FakeConceptDialog:
    results = []

    def __init__(self, *args, **kwargs):
        pass

    def setWindowTitle(self, _title):
        pass

    def exec(self):
        return True

    def get_result(self):
        return self.results.pop(0)


class TermFeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.mode = next(
            mode
            for mode in list_annotation_modes()
            if mode.id == "term_definition"
        )

    def test_new_broader_concept_is_accepted(self):
        window = MainWindow()
        annotation = Annotation(
            start=0,
            end=4,
            labels={"entity": "term"},
            concept_id="C_child",
        )
        window.doc = Document(
            text="損害賠償",
            annotations=[annotation],
            concepts={"C_child": "損害賠償"},
        )
        window.mode = self.mode

        _FakeConceptDialog.results = [
            ("C_child", None),
            (None, "債務不履行責任"),
        ]

        with patch(
            "lexiarbiter.app.ConceptSelectionDialog",
            _FakeConceptDialog,
        ):
            window.set_broader_concept()

        broader_id = annotation.broader_concept_id
        self.assertIsNotNone(broader_id)
        self.assertEqual(
            window.doc.concepts[broader_id],
            "債務不履行責任",
        )
        window.doc.dirty = False
        window.close()

    def test_long_term_replaces_nested_short_terms_at_all_matches(self):
        text = "損害賠償請求權與損害賠償。另有損害賠償請求權。"
        short_term = "損害賠償"
        long_term = "損害賠償請求權"

        short_starts = []
        search_from = 0
        while True:
            start = text.find(short_term, search_from)
            if start == -1:
                break
            short_starts.append(start)
            search_from = start + len(short_term)

        short_annotations = [
            Annotation(
                start=start,
                end=start + len(short_term),
                labels={"entity": "term"},
                concept_id="C_short",
            )
            for start in short_starts
        ]
        doc = Document(
            text=text,
            annotations=short_annotations,
            concepts={
                "C_short": short_term,
                "C_long": long_term,
            },
        )

        source_start = text.find(long_term)
        source_short = next(
            ann for ann in doc.annotations if ann.start == source_start
        )
        doc.remove_annotation(source_short.id)
        source = Annotation(
            start=source_start,
            end=source_start + len(long_term),
            labels={"entity": "term"},
            concept_id="C_long",
        )
        doc.add_annotation(source)

        window = MainWindow()
        window.doc = doc
        window.mode = self.mode

        added, replaced, skipped = window._auto_annotate_same_terms(
            source,
            "entity",
            "term",
        )

        self.assertEqual((added, replaced, skipped), (1, 1, 0))
        long_annotations = [
            ann for ann in doc.annotations if ann.concept_id == "C_long"
        ]
        short_annotations = [
            ann for ann in doc.annotations if ann.concept_id == "C_short"
        ]
        self.assertEqual(len(long_annotations), 2)
        self.assertEqual(len(short_annotations), 1)
        self.assertEqual(
            text[short_annotations[0].start:short_annotations[0].end],
            short_term,
        )
        window.doc.dirty = False
        window.close()

    def test_different_concepts_receive_different_colors(self):
        doc = Document(
            text="甲乙丙",
            concepts={"C_a": "甲", "C_b": "乙"},
        )
        editor = AnnotationEditor()
        editor.attach(doc, self.mode, UserPreferences.load())

        first = Annotation(
            start=0,
            end=1,
            labels={"entity": "term"},
            concept_id="C_a",
        )
        same_concept = Annotation(
            start=1,
            end=2,
            labels={"entity": "term"},
            concept_id="C_a",
        )
        second = Annotation(
            start=2,
            end=3,
            labels={"entity": "term"},
            concept_id="C_b",
        )

        formats = []
        for annotation in (first, same_concept, second):
            fmt = QTextCharFormat()
            editor._apply_format_for_labels(fmt, annotation)
            formats.append(fmt.background().color().name())

        self.assertEqual(formats[0], formats[1])
        self.assertNotEqual(formats[0], formats[2])


if __name__ == "__main__":
    unittest.main()
