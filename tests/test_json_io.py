import json
import unittest
from unittest.mock import mock_open, patch

from lexiarbiter.core.io import load_judicial_json, load_lexa


class JudicialJsonTests(unittest.TestCase):
    def test_br_variants_become_real_newlines(self):
        payload = {
            "JFULL": "甲<br>乙<BR/>丙<br />丁<br  /  >戊",
            "JID": "sample-id",
        }

        with patch(
            "builtins.open",
            mock_open(read_data=json.dumps(payload, ensure_ascii=False)),
        ):
            doc = load_judicial_json("sample.json")

        self.assertEqual(doc.text, "甲\n乙\n丙\n丁\n戊")
        self.assertEqual(doc.source_meta, {"JID": "sample-id"})
        self.assertNotIn("<br", doc.text.lower())

    def test_list_shaped_json_is_normalized(self):
        payload = [{"jfull": "第一行<br />第二行"}]

        with patch(
            "builtins.open",
            mock_open(read_data=json.dumps(payload, ensure_ascii=False)),
        ):
            doc = load_judicial_json("list-sample.json")

        self.assertEqual(doc.text, "第一行\n第二行")

    def test_existing_lexa_text_is_not_rewritten(self):
        payload = {
            "format": "lexa",
            "version": 1,
            "schema": "term_definition",
            "source": {"filename": "old.json", "meta": {}},
            "concepts": {},
            "text": "既有<br />文字",
            "annotations": [],
        }

        with patch(
            "builtins.open",
            mock_open(read_data=json.dumps(payload, ensure_ascii=False)),
        ):
            doc = load_lexa("existing.lexa")

        self.assertEqual(doc.text, "既有<br />文字")


if __name__ == "__main__":
    unittest.main()
