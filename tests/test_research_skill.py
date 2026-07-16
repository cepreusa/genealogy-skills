#!/usr/bin/env python3
"""Documentation-contract + behavioral-fixture checks for genealogy-research.

Pure standard library (unittest); no model calls. These tests guard the
methodology hardening: they verify the skill's docs still link their references,
carry the required headings/fields, avoid known-bad legacy wording, and that the
behavioral fixtures are well formed and cover the required categories.

    PYTHONIOENCODING=utf-8 python3 -m unittest discover -s tests -v
"""

import json
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESEARCH = os.path.join(ROOT, "skills", "genealogy-research")
REFS = os.path.join(RESEARCH, "references")
FIXTURES = os.path.join(ROOT, "tests", "fixtures", "research-behavior")
REPORT_PY = os.path.join(ROOT, "skills", "gedcom-report", "scripts", "report.py")


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class ReferenceLinkTest(unittest.TestCase):
    """Every reference the SKILL.md links to must exist on disk."""

    def test_skill_links_resolve(self):
        skill = read(os.path.join(RESEARCH, "SKILL.md"))
        for rel in re.findall(r"\(references/([A-Za-z0-9._-]+)\)", skill):
            self.assertTrue(
                os.path.exists(os.path.join(REFS, rel)),
                f"SKILL.md links missing reference: {rel}")

    def test_new_protocol_is_linked(self):
        skill = read(os.path.join(RESEARCH, "SKILL.md"))
        self.assertIn("research-run-protocol.md", skill)
        self.assertTrue(os.path.exists(
            os.path.join(REFS, "research-run-protocol.md")))


class RequiredHeadingsTest(unittest.TestCase):
    """The methodology core must cover the hardened concepts."""

    def test_gps_methodology_headings(self):
        text = read(os.path.join(REFS, "gps-methodology.md")).lower()
        for needle in [
            "atomic assertion",
            "negative search result",
            "provenance and independence",
            "relationships and identity",
            "conclusion status",
        ]:
            self.assertIn(needle, text, f"gps-methodology.md missing: {needle}")

    def test_protocol_headings(self):
        text = read(os.path.join(REFS, "research-run-protocol.md")).lower()
        for needle in [
            "pre-run contract",
            "untrusted source content",
            "document intake",
            "review and write gate",
        ]:
            self.assertIn(needle, text,
                          f"research-run-protocol.md missing: {needle}")

    def test_vault_templates_have_new_artifacts(self):
        text = read(os.path.join(REFS, "vault-templates.md")).lower()
        for needle in [
            "document manifest template",
            "assertion ledger template",
            "review card template",
            "bounded run contract template",
        ]:
            self.assertIn(needle, text, f"vault-templates.md missing: {needle}")


class LegacyWordingTest(unittest.TestCase):
    """Reject specific corrected-away formulations in active guidance."""

    # (file, banned substring, case-insensitive)
    BANNED = [
        ("gps-methodology.md", "best-quality evidence = **original"),
        ("gps-methodology.md", "the scientific method of genealogy"),
        ("common-pitfalls.md", 'minimum for "proven"'),
        ("common-pitfalls.md", "negative evidence narrows down where the family"),
        ("gedcom-format.md", "maps neatly to gps evidence levels"),
        ("intake-interview.md", "add the couple, marry them"),
        ("intake-interview.md", "parents to each other: `gedcom_link"),
    ]

    def test_no_banned_wording(self):
        for fname, banned in self.BANNED:
            text = read(os.path.join(REFS, fname)).lower()
            self.assertNotIn(
                banned.lower(), text,
                f"{fname} still contains corrected-away wording: {banned!r}")


class QuayLabelTest(unittest.TestCase):
    """QUAY must not be presented as a GPS proof status."""

    def test_report_quay_labels_are_neutral(self):
        text = read(REPORT_PY)
        # The QUAY_LABELS block must not glue Proven/Probable/… onto QUAY levels.
        for bad in ["Primary (Proven)", "Secondary (Probable)",
                    "Questionable (Possible)", "Unreliable (Unproven)"]:
            self.assertNotIn(bad, text,
                             f"report.py QUAY labels still say {bad!r}")
        self.assertIn("submitter assessment", text)


class BehaviorFixtureTest(unittest.TestCase):
    """The behavioral fixtures must be well formed and cover the categories."""

    REQUIRED_CATEGORIES = {
        "proof-calibration",
        "negative-evidence",
        "source-independence",
        "relationship-inference",
        "untrusted-content",
        "bounded-run",
        "review-gate",
        "oral-history",
    }

    def _load_all(self):
        fixtures = []
        for name in sorted(os.listdir(FIXTURES)):
            if name.endswith(".json"):
                with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
                    fixtures.append((name, json.load(fh)))
        return fixtures

    def test_fixtures_are_valid_and_unique(self):
        fixtures = self._load_all()
        self.assertGreaterEqual(len(fixtures), 8)
        seen = set()
        for name, fx in fixtures:
            for key in ("id", "category", "user_request",
                        "expected_behaviors", "forbidden_behaviors"):
                self.assertIn(key, fx, f"{name} missing key {key}")
            self.assertTrue(fx["expected_behaviors"],
                            f"{name} has no expected_behaviors")
            self.assertTrue(fx["forbidden_behaviors"],
                            f"{name} has no forbidden_behaviors")
            self.assertNotIn(fx["id"], seen, f"duplicate fixture id {fx['id']}")
            seen.add(fx["id"])

    def test_required_categories_present(self):
        cats = {fx["category"] for _, fx in self._load_all()}
        missing = self.REQUIRED_CATEGORIES - cats
        self.assertFalse(missing, f"missing fixture categories: {missing}")


if __name__ == "__main__":
    unittest.main()
