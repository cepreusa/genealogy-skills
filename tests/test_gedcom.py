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


class PersonDetailTest(unittest.TestCase):
    """Rich person_full extraction used by the tree viewer's detail panel."""

    def test_extract_links_from_notes(self):
        mod = _load_gedcom_module()
        notes = [
            "See https://archive.org/rec/1 and Скан: materials/skany/doc.png",
            "Another http://obd-memorial.ru/ ref; skany/award.jpg too",
        ]
        links = mod.extract_links(notes)
        self.assertIn("https://archive.org/rec/1", links["urls"])
        self.assertIn("http://obd-memorial.ru/", links["urls"])
        self.assertIn("materials/skany/doc.png", links["scans"])
        self.assertIn("skany/award.jpg", links["scans"])

    def test_person_full_rich_fields_on_demo(self):
        mod = _load_gedcom_module()
        demo = os.path.join(ROOT, "examples", "demo.ged")
        tree = mod.Tree(demo)
        ivan = tree.people["@I1@"]
        d = tree.person_full(ivan)
        # occupation with place
        self.assertTrue(any(o["place"] for o in d["occupations"]))
        # death cause
        self.assertTrue(d["death"]["cause"])
        # residence recorded
        self.assertTrue(d["residences"])
        # scan link harvested from a note
        self.assertTrue(any("skany/" in s for s in d["links"]["scans"]))
        # a @Sxx@ source resolved to author + title
        resolved = [s for s in d["sources"] if s["author"] and s["title"]]
        self.assertTrue(resolved, "expected a resolved @S1@ source record")
        # event carrying a URL
        self.assertTrue(any(e["url"] for e in d["events"]))

    def test_documents_from_obje_file(self):
        mod = _load_gedcom_module()
        demo = os.path.join(ROOT, "examples", "demo.ged")
        tree = mod.Tree(demo)
        d = tree.person_full(tree.people["@I1@"])
        docs = d["documents"]
        paths = [x["path"] for x in docs]
        # the Obsidian .md dossier attached via OBJE/FILE must be present
        self.assertTrue(any(p.endswith(".md") for p in paths),
                        "expected a .md dossier document from OBJE/FILE")
        md = next(x for x in docs if x["path"].endswith(".md"))
        self.assertTrue(md["title"], "document should carry its TITL")
        # de-duplicated by path
        self.assertEqual(len(paths), len(set(paths)))

    def test_source_pointer_resolution(self):
        mod = _load_gedcom_module()
        demo = os.path.join(ROOT, "examples", "demo.ged")
        tree = mod.Tree(demo)
        d = tree.person_full(tree.people["@I1@"])
        s0 = next(s for s in d["sources"] if s["author"])
        self.assertIn("архив", s0["author"].lower())
        self.assertTrue(s0["url"].startswith("http"))


class TreePrivateFlagTest(unittest.TestCase):
    """tree.py --private strips contacts of people with no death date."""

    def _load_tree_module(self):
        path = os.path.join(ROOT, "skills", "gedcom-tree", "scripts", "tree.py")
        spec = importlib.util.spec_from_file_location("treemod", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def _write(self, text):
        d = tempfile.mkdtemp()
        ged = os.path.join(d, "p.ged")
        with open(ged, "w", encoding="utf-8") as fh:
            fh.write(text)
        return ged

    def test_private_hides_living_contacts(self):
        treemod = self._load_tree_module()
        import gedcom  # already importable via tree.py's sys.path insert
        # A living person (no DEAT) with a phone; and a deceased one with a phone.
        ged = self._write(
            "0 HEAD\n1 CHAR UTF-8\n1 GEDC\n2 VERS 5.5.1\n"
            "0 @I1@ INDI\n1 NAME Liv /Ing/\n1 SEX F\n"
            "1 RESI\n2 PLAC Town\n2 PHON 12345\n2 EMAIL a@b.co\n"
            "0 @I2@ INDI\n1 NAME Dead /Gone/\n1 SEX M\n1 DEAT\n2 DATE 1990\n"
            "1 RESI\n2 PLAC City\n2 PHON 99999\n"
            "0 TRLR\n")
        tree = gedcom.Tree(ged)
        pub = treemod.build_details(tree, private=False)
        prv = treemod.build_details(tree, private=True)
        # public keeps the living person's phone
        self.assertEqual(pub["@I1@"]["residences"][0]["phone"], "12345")
        # private empties a possibly-living person's detail entirely (stronger
        # than blanking single fields): no residences, notes, sources survive.
        self.assertEqual(prv["@I1@"]["residences"], [])
        self.assertEqual(prv["@I1@"]["notes"], [])
        # a deceased person keeps their residence, but contacts are still blanked.
        self.assertEqual(prv["@I2@"]["residences"][0]["place"], "City")
        self.assertEqual(prv["@I2@"]["residences"][0]["phone"], "")


class LocalizationTest(unittest.TestCase):
    """UI language: --lang override plus auto-detection from the names."""

    def _load(self, skill, script, modname):
        path = os.path.join(ROOT, "skills", skill, "scripts", script)
        spec = importlib.util.spec_from_file_location(modname, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_tree_and_report_have_ru_en_dicts(self):
        for skill, script, modname in (
            ("gedcom-tree", "tree.py", "treemod_i18n"),
            ("gedcom-report", "report.py", "repmod_i18n"),
        ):
            mod = self._load(skill, script, modname)
            self.assertIn("ru", mod.I18N)
            self.assertIn("en", mod.I18N)
            # both languages define exactly the same set of keys
            self.assertEqual(set(mod.I18N["ru"]), set(mod.I18N["en"]),
                             f"{skill}: ru/en string keys differ")

    def test_tree_autodetect_language(self):
        treemod = self._load("gedcom-tree", "tree.py", "treemod_lang")
        cyr = {"a": {"name": "Иван Петров"}}
        lat = {"a": {"name": "John Smith"}}
        self.assertEqual(treemod.detect_lang(None, cyr), "ru")
        self.assertEqual(treemod.detect_lang(None, lat), "en")

    def test_report_autodetect_language(self):
        repmod = self._load("gedcom-report", "report.py", "repmod_lang")
        import gedcom  # importable via report.py's sys.path insert
        en_demo = os.path.join(ROOT, "examples", "demo.en.ged")
        ru_demo = os.path.join(ROOT, "examples", "demo.ged")
        self.assertEqual(repmod.detect_lang(gedcom.Tree(en_demo)), "en")
        self.assertEqual(repmod.detect_lang(gedcom.Tree(ru_demo)), "ru")

    def test_report_metrics_carry_selected_language(self):
        repmod = self._load("gedcom-report", "report.py", "repmod_metrics")
        import gedcom  # importable via report.py's sys.path insert
        m_en = repmod.build_metrics(gedcom.Tree(
            os.path.join(ROOT, "examples", "demo.en.ged")), lang="en")
        self.assertEqual(m_en["lang"], "en")
        self.assertEqual(m_en["i18n"]["report_title"], "Family tree")
        # month names localized
        self.assertIn("Jan", m_en["months"])

    def test_english_demo_parses(self):
        demo = os.path.join(ROOT, "examples", "demo.en.ged")
        stats = run_read(demo, "stats")
        self.assertGreater(stats["people"], 0)
        self.assertEqual(stats["charset"], "UTF-8")


FIXTURES = os.path.join(ROOT, "tests", "fixtures")


class AuditTest(unittest.TestCase):
    """Structural audit: schema, determinism, and exact finding codes."""

    def _audit(self, fixture):
        return run_read(os.path.join(FIXTURES, fixture + ".ged"), "audit")

    def _codes(self, report):
        return sorted({i["code"] for i in report["issues"]})

    def test_schema_and_clean_fixture(self):
        r = self._audit("audit-clean")
        self.assertEqual(r["schema_version"], 1)
        for key in ("ok", "summary", "metrics", "issues", "file"):
            self.assertIn(key, r)
        self.assertTrue(r["ok"])
        self.assertEqual(r["summary"]["errors"], 0)
        self.assertEqual(r["issues"], [])

    def test_ok_equals_zero_errors(self):
        r = self._audit("audit-dates")     # warnings only
        self.assertTrue(r["ok"])
        self.assertGreater(r["summary"]["warnings"], 0)
        r2 = self._audit("audit-broken-links")
        self.assertFalse(r2["ok"])
        self.assertGreater(r2["summary"]["errors"], 0)

    def test_cli_matches_api(self):
        mod = _load_gedcom_module()
        tree = mod.Tree(os.path.join(FIXTURES, "audit-broken-links.ged"))
        api = tree.audit()
        cli = self._audit("audit-broken-links")
        # CLI result is the same report (file path is absolute in both).
        self.assertEqual(api["summary"], cli["summary"])
        self.assertEqual([i["code"] for i in api["issues"]],
                         [i["code"] for i in cli["issues"]])

    def test_audit_cli_exits_zero_with_findings(self):
        # run_read uses check=True, so a non-zero exit would raise.
        r = self._audit("audit-broken-links")
        self.assertFalse(r["ok"])  # findings present, but command succeeded

    def test_broken_links_codes(self):
        codes = self._codes(self._audit("audit-broken-links"))
        for expected in ("link.fams_dangling", "link.child_dangling",
                         "link.child_missing_reverse", "link.child_duplicate",
                         "family.child_is_spouse"):
            self.assertIn(expected, codes)

    def test_duplicate_xref_detected_despite_dict_overwrite(self):
        r = self._audit("audit-duplicate-xrefs")
        self.assertIn("xref.duplicate", self._codes(r))
        dup = [i for i in r["issues"] if i["code"] == "xref.duplicate"][0]
        self.assertEqual(dup["details"]["count"], 2)

    def test_cycle_terminates_and_reports_once(self):
        r = self._audit("audit-cycle")
        cyc = [i for i in r["issues"] if i["code"] == "pedigree.cycle"]
        self.assertEqual(len(cyc), 1)

    def test_dates_flags_unambiguous_only(self):
        codes = self._codes(self._audit("audit-dates"))
        self.assertIn("date.death_before_birth", codes)
        self.assertIn("date.marriage_before_birth", codes)
        # The ABT/BET person (@I2@) must NOT produce a false chronology finding.
        r = self._audit("audit-dates")
        i2 = [i for i in r["issues"] if i["record"] == "@I2@"]
        self.assertEqual(i2, [])

    def test_references_pointer_and_quay(self):
        codes = self._codes(self._audit("audit-references"))
        self.assertIn("source.pointer_dangling", codes)
        self.assertIn("object.pointer_dangling", codes)
        self.assertIn("source.quay_invalid", codes)
        # Inline SOUR text must not be treated as a dangling pointer.
        r = self._audit("audit-references")
        self.assertNotIn("Some inline source text",
                         [i.get("value") for i in r["issues"]])

    def test_clean_has_no_false_positives(self):
        # audit-clean has a same-role family and approximate dates — no findings.
        self.assertEqual(self._audit("audit-clean")["summary"]["total"], 0)

    def test_deterministic_ordering(self):
        a = self._audit("audit-broken-links")["issues"]
        b = self._audit("audit-broken-links")["issues"]
        self.assertEqual([i["code"] for i in a], [i["code"] for i in b])

    def test_demo_audits_clean(self):
        r = run_read(os.path.join(ROOT, "examples", "demo.ged"), "audit")
        self.assertTrue(r["ok"], r["issues"])


class WriterAuditTest(unittest.TestCase):
    """Writer operations report an audit summary and stay structurally clean."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.ged = os.path.join(self.dir, "t.ged")

    def test_write_output_carries_audit_summary(self):
        init, _ = run_write(self.ged, "init", "--name", "T")
        self.assertIn("audit", init)
        self.assertTrue(init["audit"]["ok"])
        res, _ = run_write(self.ged, "add-person", "--given", "Ann",
                           "--surname", "Lee", "--sex", "F")
        self.assertIn("audit", res)
        self.assertEqual(res["audit"]["errors"], 0)

    def test_linked_family_is_clean(self):
        run_write(self.ged, "init", "--name", "T")
        run_write(self.ged, "add-person", "--given", "A", "--surname", "X",
                  "--sex", "M")
        run_write(self.ged, "add-person", "--given", "B", "--surname", "Y",
                  "--sex", "F")
        run_write(self.ged, "link", "spouses", "A X", "B Y")
        run_write(self.ged, "add-person", "--given", "C", "--surname", "X",
                  "--sex", "M")
        res, _ = run_write(self.ged, "link", "child", "C X",
                           "--parent", "A X", "--parent", "B Y")
        self.assertEqual(res["audit"]["errors"], 0)
        # Independent audit confirms two-way link integrity.
        report = run_read(self.ged, "audit")
        self.assertTrue(report["ok"], report["issues"])


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
