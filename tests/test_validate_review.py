"""Regression tests for scripts/validate_review.py.

The JSON examples in references/finding-contract.md are the fixtures, so the
contract text and the validator cannot drift apart silently.

Run: python3 -m unittest discover -s tests
"""
from __future__ import annotations

import copy
import importlib.util
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
VALIDATOR = ROOT / "scripts" / "validate_review.py"
CONTRACT = ROOT / "references" / "finding-contract.md"

_spec = importlib.util.spec_from_file_location("validate_review", VALIDATOR)
validate_review = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(validate_review)
validate = validate_review.validate

_blocks = re.findall(r"```json\n(.*?)```", CONTRACT.read_text(encoding="utf-8"), re.S)
BASE = json.loads(_blocks[0])
VERIFY_FRAGMENT = json.loads(_blocks[1])

BAD_TYPES = ([], {}, 123, None)


def base():
    return copy.deepcopy(BASE)


def verify_doc():
    doc = base()
    doc.update(copy.deepcopy(VERIFY_FRAGMENT))
    return doc


def set_path(doc, path, value):
    target = doc
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value


class ContractExamples(unittest.TestCase):
    def test_review_example_is_valid(self):
        self.assertEqual(validate(base()), [])

    def test_verify_example_is_valid(self):
        self.assertEqual(validate(verify_doc()), [])


class Versions(unittest.TestCase):
    def test_legacy_1_1_document_accepted(self):
        doc = base()
        doc["schema_version"] = "1.1"
        del doc["mode"]
        del doc["scope"]["kind"]
        self.assertEqual(validate(doc), [])

    def test_1_1_rejects_1_2_fields(self):
        for key, path in (("mode", None), ("kind", ("scope",))):
            doc = base()
            doc["schema_version"] = "1.1"
            if key == "mode":
                del doc["scope"]["kind"]
            else:
                del doc["mode"]
            with self.subTest(field=key):
                self.assertTrue(validate(doc))

    def test_unknown_version_rejected(self):
        doc = base()
        doc["schema_version"] = "1.3"
        self.assertTrue(validate(doc))

    def test_1_2_requires_mode(self):
        doc = base()
        del doc["mode"]
        self.assertTrue(validate(doc))


class EnumTypes(unittest.TestCase):
    """Non-string enum values must produce diagnostics, never TypeError."""

    PATHS = [
        ("checks", 0, "status"),
        ("quality_assessment", "direction", "status"),
        ("findings", 0, "kind"),
        ("findings", 0, "axis"),
        ("findings", 0, "severity"),
        ("findings", 0, "confidence"),
        ("findings", 0, "verification", "status"),
        ("conclusion", "status"),
        ("mode",),
        ("scope", "kind"),
    ]

    def test_bad_types_rejected(self):
        for path in self.PATHS:
            for bad in BAD_TYPES:
                doc = base()
                set_path(doc, path, bad)
                with self.subTest(path=path, value=bad):
                    self.assertTrue(validate(doc))

    def test_bad_verdict_rejected(self):
        for bad in (*BAD_TYPES, "maybe"):
            doc = verify_doc()
            doc["candidate_verdicts"][1]["verdict"] = bad
            with self.subTest(value=bad):
                self.assertTrue(validate(doc))


class CandidateVerdicts(unittest.TestCase):
    def test_verify_requires_verdicts(self):
        doc = base()
        doc["mode"] = "verify"
        self.assertTrue(validate(doc))

    def test_verdicts_must_be_list(self):
        doc = base()
        doc["mode"] = "verify"
        doc["candidate_verdicts"] = "C1"
        self.assertTrue(validate(doc))

    def test_review_mode_rejects_verdicts(self):
        doc = base()
        doc["candidate_verdicts"] = copy.deepcopy(VERIFY_FRAGMENT["candidate_verdicts"])
        self.assertTrue(validate(doc))

    def test_confirmed_requires_existing_finding(self):
        doc = verify_doc()
        doc["candidate_verdicts"][0]["finding_id"] = "F9"
        self.assertTrue(validate(doc))
        doc = verify_doc()
        del doc["candidate_verdicts"][0]["finding_id"]
        self.assertTrue(validate(doc))

    def test_plausible_and_unverified_require_limitation(self):
        for index in (2, 3):
            doc = verify_doc()
            del doc["candidate_verdicts"][index]["limitation"]
            with self.subTest(verdict=doc["candidate_verdicts"][index]["verdict"]):
                self.assertTrue(validate(doc))

    def test_duplicate_candidate_id_rejected(self):
        doc = verify_doc()
        doc["candidate_verdicts"][1]["candidate_id"] = "C1"
        self.assertTrue(validate(doc))

    def test_unverified_blocks_clean_conclusion(self):
        doc = base()
        doc["mode"] = "verify"
        doc["findings"] = []
        doc["candidate_verdicts"] = [copy.deepcopy(VERIFY_FRAGMENT["candidate_verdicts"][3])]
        doc["conclusion"] = {"status": "no_actionable_findings", "summary": "x"}
        self.assertTrue(validate(doc))
        doc["conclusion"]["status"] = "incomplete"
        self.assertEqual(validate(doc), [])


class ScopeKind(unittest.TestCase):
    def snapshot(self):
        doc = base()
        doc["scope"]["kind"] = "snapshot"
        return doc

    def test_snapshot_without_base(self):
        doc = self.snapshot()
        del doc["scope"]["base"]
        self.assertEqual(validate(doc), [])
        doc["scope"]["base"] = None
        self.assertEqual(validate(doc), [])

    def test_snapshot_rejects_base(self):
        self.assertTrue(validate(self.snapshot()))

    def test_snapshot_requires_target(self):
        doc = self.snapshot()
        del doc["scope"]["base"]
        del doc["scope"]["target"]
        self.assertTrue(validate(doc))

    def test_diff_requires_base(self):
        doc = base()
        del doc["scope"]["base"]
        self.assertTrue(validate(doc))


class Cli(unittest.TestCase):
    def run_cli(self, payload: bytes):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "review.json"
            path.write_bytes(payload)
            return subprocess.run(
                [sys.executable, "-I", str(VALIDATOR), str(path)],
                capture_output=True,
                text=True,
            )

    def test_valid_file(self):
        result = self.run_cli(json.dumps(BASE).encode("utf-8"))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_non_utf8_file_is_input_error(self):
        result = self.run_cli(b'{"x": "\xff\xfe"}')
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
