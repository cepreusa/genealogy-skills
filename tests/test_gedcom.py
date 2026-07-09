#!/usr/bin/env python3
"""Smoke + regression tests for the genealogy-skills engine.

Pure standard library (unittest), no external dependencies. Run with:

    PYTHONIOENCODING=utf-8 python3 -m unittest discover -s tests -v

Covers: the parser, the writer round-trip, and the behaviours called out in
review (ambiguous-name handling, same-sex HUSB/WIFE, partial-family filling,
multi-marriage link-child refusal, slash-form surname fallback), plus a check
that the three bundled copies of gedcom.py stay byte-identical.
"""

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
READER = os.path.join(ROOT, "skills", "gedcom-reader", "scripts")
GEDCOM_PY = os.path.join(READER, "gedcom.py")
WRITE_PY = os.path.join(READER, "gedcom_write.py")

ENV = dict(os.environ, PYTHONIOENCODING="utf-8")


def _load_gedcom_module():
    spec = importlib.util.spec_from_file_location("gedcom", GEDCOM_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_read(gedfile, *args):
    out = subprocess.run(
        [sys.executable, GEDCOM_PY, gedfile, *args],
        capture_output=True, text=True, env=ENV, check=True)
    return json.loads(out.stdout)


def run_write(gedfile, *args):
    out = subprocess.run(
        [sys.executable, WRITE_PY, gedfile, *args],
        capture_output=True, text=True, env=ENV)
    # writer may exit 1 on expected errors; still return parsed JSON + code
    data = json.loads(out.stdout) if out.stdout.strip() else {}
    return data, out.returncode


class BuildAndReadTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.ged = os.path.join(self.dir, "t.ged")

    def _init_family(self):
        run_write(self.ged, "init", "--name", "Test")
        run_write(self.ged, "add-person", "--given", "Иван",
                  "--surname", "Петров", "--sex", "M", "--birt-date", "1960")
        run_write(self.ged, "add-person", "--given", "Мария",
                  "--surname", "Иванова", "--sex", "F", "--birt-date", "1962")
        run_write(self.ged, "link", "spouses", "Иван Петров",
                  "Мария Иванова", "--marr-date", "1983")
        run_write(self.ged, "add-person", "--given", "Пётр",
                  "--surname", "Петров", "--sex", "M", "--birt-date", "1985")
        run_write(self.ged, "link", "child", "Пётр Петров",
                  "--parent", "Иван Петров", "--parent", "Мария Иванова")

    def test_build_and_query_cyrillic(self):
        self._init_family()
        stats = run_read(self.ged, "stats")
        self.assertEqual(stats["people"], 3)
        self.assertEqual(stats["families"], 1)
        self.assertEqual(stats["charset"], "UTF-8")
        desc = run_read(self.ged, "descendants", "Иван Петров")
        names = [d["name"] for d in desc["descendants"]]
        self.assertIn("Пётр Петров", names)
        rel = run_read(self.ged, "relationship", "Иван Петров", "Пётр Петров")
        self.assertNotIn("error", rel)

    def test_ambiguous_name_is_reported(self):
        self._init_family()
        # second Иван Петров → ambiguous
        run_write(self.ged, "add-person", "--given", "Иван",
                  "--surname", "Петров", "--sex", "M", "--birt-date", "1911")
        for cmd in ("ancestors", "descendants"):
            res = run_read(self.ged, cmd, "Иван Петров")
            self.assertIn("ambiguous", res, cmd)
            self.assertEqual(len(res["ambiguous"]), 2)
        rel = run_read(self.ged, "relationship", "Иван Петров", "Мария Иванова")
        self.assertIn("ambiguous", rel)

    def test_same_sex_couple_keeps_order(self):
        run_write(self.ged, "init")
        run_write(self.ged, "add-person", "--given", "Alex", "--sex", "M")
        run_write(self.ged, "add-person", "--given", "Ben", "--sex", "M")
        run_write(self.ged, "link", "spouses", "Alex", "Ben")
        fam = run_read(self.ged, "family", "F1")
        self.assertEqual(fam["husb"]["name"].strip(), "Alex")
        self.assertEqual(fam["wife"]["name"].strip(), "Ben")

    def test_partial_family_is_filled_not_duplicated(self):
        run_write(self.ged, "init")
        run_write(self.ged, "add-person", "--given", "Dad", "--sex", "M")
        run_write(self.ged, "add-person", "--given", "Son", "--sex", "M")
        run_write(self.ged, "link", "child", "Son", "--parent", "Dad")
        self.assertEqual(run_read(self.ged, "stats")["families"], 1)
        run_write(self.ged, "add-person", "--given", "Mom", "--sex", "F")
        run_write(self.ged, "link", "spouses", "Dad", "Mom")
        # should fill the empty WIFE slot, not create a second family
        self.assertEqual(run_read(self.ged, "stats")["families"], 1)
        fam = run_read(self.ged, "family", "F1")
        self.assertEqual(fam["wife"]["name"].strip(), "Mom")
        self.assertEqual(len(fam["children"]), 1)

    def test_link_child_multi_marriage_refused(self):
        run_write(self.ged, "init")
        run_write(self.ged, "add-person", "--given", "P", "--sex", "M")
        run_write(self.ged, "add-person", "--given", "W1", "--sex", "F")
        run_write(self.ged, "add-person", "--given", "W2", "--sex", "F")
        run_write(self.ged, "link", "spouses", "P", "W1")
        run_write(self.ged, "link", "spouses", "P", "W2")
        run_write(self.ged, "add-person", "--given", "Kid")
        data, code = run_write(self.ged, "link", "child", "Kid", "--parent", "P")
        self.assertEqual(code, 1)
        self.assertIn("error", data)
        self.assertGreaterEqual(len(data.get("candidates", [])), 2)


class SurnameFallbackTest(unittest.TestCase):
    def test_slash_form_surname_counted_in_stats(self):
        mod = _load_gedcom_module()
        d = tempfile.mkdtemp()
        ged = os.path.join(d, "s.ged")
        # A record using only the slash NAME form (no GIVN/SURN sub-tags).
        with open(ged, "w", encoding="utf-8") as fh:
            fh.write(
                "0 HEAD\n1 CHAR UTF-8\n1 GEDC\n2 VERS 5.5.1\n"
                "0 @I1@ INDI\n1 NAME John /Smith/\n"
                "0 TRLR\n")
        tree = mod.Tree(ged)
        indi = tree.people["@I1@"]
        self.assertEqual(tree.surname_of(indi), "Smith")
        stats = run_read(ged, "stats")
        self.assertEqual(stats["distinct_surnames"], 1)
        self.assertEqual(stats["top_surnames"][0]["surname"], "Smith")


class ParserCopiesInSyncTest(unittest.TestCase):
    def test_three_copies_identical(self):
        copies = [
            GEDCOM_PY,
            os.path.join(ROOT, "skills", "gedcom-report", "scripts", "gedcom.py"),
            os.path.join(ROOT, "skills", "gedcom-tree", "scripts", "gedcom.py"),
        ]
        digests = {}
        for path in copies:
            with open(path, "rb") as fh:
                digests[path] = hashlib.md5(fh.read()).hexdigest()
        unique = set(digests.values())
        self.assertEqual(
            len(unique), 1,
            "gedcom.py copies diverged; re-sync them:\n" +
            "\n".join(f"  {os.path.relpath(p, ROOT)}: {d}"
                      for p, d in digests.items()))


class DemoFileTest(unittest.TestCase):
    def test_demo_parses(self):
        demo = os.path.join(ROOT, "examples", "demo.ged")
        stats = run_read(demo, "stats")
        self.assertGreater(stats["people"], 0)
        self.assertEqual(stats["charset"], "UTF-8")


if __name__ == "__main__":
    unittest.main(verbosity=2)
