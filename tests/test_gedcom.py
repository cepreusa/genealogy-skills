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


class OfflineReportTest(unittest.TestCase):
    """The generated report must be fully self-contained (no CDN / no network)."""

    def _load_report(self):
        path = os.path.join(ROOT, "skills", "gedcom-report", "scripts",
                            "report.py")
        spec = importlib.util.spec_from_file_location("repmod_offline", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def _html(self):
        repmod = self._load_report()
        import gedcom  # importable via report.py's sys.path insert
        tree = gedcom.Tree(os.path.join(ROOT, "examples", "demo.ged"))
        metrics = repmod.build_metrics(tree, lang="ru")
        template = os.path.join(ROOT, "skills", "gedcom-report", "scripts",
                                "template.html")
        return repmod.render(metrics, template)

    def test_vendored_chartjs_present(self):
        path = os.path.join(ROOT, "skills", "gedcom-report", "scripts",
                            "vendor", "chart.umd.min.js")
        self.assertTrue(os.path.exists(path), "vendored Chart.js is missing")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("window.Chart=", src)
        self.assertNotIn("sourceMappingURL", src)

    def test_no_external_resources(self):
        html = self._html()
        # No script/link should reference the network.
        self.assertNotIn("cdn.jsdelivr", html)
        self.assertNotIn('<script src=', html)
        self.assertNotIn('<link rel="stylesheet" href="http', html)
        self.assertNotIn("chart.js@4", html.split("<script>")[0])

    def test_chartjs_inlined_and_markers_filled(self):
        html = self._html()
        self.assertIn("window.Chart=", html)          # library inlined
        self.assertNotIn("/*__CHARTJS__*/", html)     # marker consumed
        self.assertNotIn("/*__DATA__*/null", html)    # data injected
        self.assertNotIn("<!--__TITLE__-->", html)    # title injected

    def test_marker_strings_in_data_stay_inert(self):
        # GEDCOM data containing the template markers or script-breaking
        # sequences must not expand the library twice or close the script tag.
        repmod = self._load_report()
        template = os.path.join(ROOT, "skills", "gedcom-report", "scripts",
                                "template.html")
        evil = "/*__CHARTJS__*/ </script> <!--__TITLE__--> <SCRIPT>"
        metrics = {"meta": {"file": evil}, "i18n": repmod.I18N["ru"]}
        html = repmod.render(metrics, template)
        # Library inlined exactly once, not into the data.
        self.assertEqual(html.count("window.Chart="), 1)
        data_line = next(l for l in html.splitlines()
                         if l.startswith("const DATA"))
        low = data_line.lower()
        self.assertNotIn("</script", low)
        self.assertNotIn("<script", low)
        self.assertNotIn("<!--", data_line)
        # The marker text survives as inert JSON, not as an expansion.
        self.assertIn("/*__CHARTJS__*/", data_line)

    def test_missing_vendor_degrades_gracefully(self):
        # _load_chartjs returns '' when the file is absent; render still works.
        repmod = self._load_report()
        import gedcom
        tree = gedcom.Tree(os.path.join(ROOT, "examples", "demo.ged"))
        metrics = repmod.build_metrics(tree, lang="ru")
        template = os.path.join(ROOT, "skills", "gedcom-report", "scripts",
                                "template.html")
        orig = repmod._load_chartjs
        try:
            repmod._load_chartjs = lambda: ""
            html = repmod.render(metrics, template)
        finally:
            repmod._load_chartjs = orig
        # Marker consumed, no library inlined, page still parses.
        self.assertNotIn("/*__CHARTJS__*/", html)
        self.assertNotIn("window.Chart=", html)
        # The canvas fallback tables are always present in the template.
        self.assertIn('class="fallback"', html)


FIXTURES = os.path.join(ROOT, "tests", "fixtures")


class AuditTest(unittest.TestCase):
    """Structural audit: schema, determinism, and exact finding codes."""

    def _audit(self, fixture):
        return run_read(os.path.join(FIXTURES, fixture + ".ged"), "audit")

    def _codes(self, report):
        return sorted({i["code"] for i in report["issues"]})

    def test_schema_and_clean_fixture(self):
        r = self._audit("audit-clean")
        self.assertEqual(r["schema_version"], 2)
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


def _temp_ged(body):
    """Write a minimal GEDCOM (HEAD/TRLR added) to a temp file, return path."""
    d = tempfile.mkdtemp()
    p = os.path.join(d, "t.ged")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write("0 HEAD\n1 CHAR UTF-8\n" + body + "0 TRLR\n")
    return p


class AuditEdgeCaseTest(unittest.TestCase):
    """Regressions from review: date bounds, calendars, case, deep chains."""

    def _codes(self, path):
        return sorted({i["code"] for i in run_read(path, "audit")["issues"]})

    def test_overlapping_death_range_not_flagged(self):
        # DEAT may extend past BIRT (1899..1950 vs 1900) — no false positive.
        p = _temp_ged("0 @I1@ INDI\n1 NAME A /B/\n1 BIRT\n2 DATE 1900\n"
                      "1 DEAT\n2 DATE BET 1899 AND 1950\n")
        self.assertNotIn("date.death_before_birth", self._codes(p))

    def test_unambiguous_death_before_birth_flagged(self):
        p = _temp_ged("0 @I1@ INDI\n1 NAME A /B/\n1 BIRT\n2 DATE 1900\n"
                      "1 DEAT\n2 DATE BET 1800 AND 1890\n")
        self.assertIn("date.death_before_birth", self._codes(p))

    def test_calendar_escape_after_qualifier_not_flagged(self):
        # "ABT @#DHEBREW@ 5660" is legal GEDCOM; 5660 is not a Gregorian year.
        p = _temp_ged("0 @I1@ INDI\n1 NAME A /B/\n"
                      "1 BIRT\n2 DATE ABT @#DHEBREW@ 5660\n"
                      "1 DEAT\n2 DATE 1910\n")
        self.assertNotIn("date.death_before_birth", self._codes(p))

    def test_lowercase_xrefs_no_false_danglings(self):
        # @i1@ and @I1@ spellings are the same record for the index — the audit
        # must not report dangling/empty-family cascades.
        p = _temp_ged("0 @i1@ INDI\n1 NAME A /B/\n1 SEX M\n1 FAMS @f1@\n"
                      "0 @F1@ FAM\n1 HUSB @I1@\n")
        codes = self._codes(p)
        for bad in ("link.fams_dangling", "link.husb_dangling",
                    "link.fams_missing_reverse", "link.spouse_missing_reverse",
                    "family.empty"):
            self.assertNotIn(bad, codes)

    def test_deep_parent_chain_no_recursion_error(self):
        # A 1500-generation chain must not blow the recursion limit.
        n = 1500
        lines = []
        for i in range(1, n + 1):
            lines.append(f"0 @I{i}@ INDI\n1 NAME P{i} /X/\n")
            if i < n:                       # child in F{i} (parent is I{i+1})
                lines.append(f"1 FAMC @F{i}@\n")
            if i > 1:                       # parent in F{i-1}
                lines.append(f"1 FAMS @F{i - 1}@\n")
        for i in range(1, n):
            lines.append(f"0 @F{i}@ FAM\n1 HUSB @I{i + 1}@\n1 CHIL @I{i}@\n")
        p = _temp_ged("".join(lines))
        r = run_read(p, "audit")   # check=True would raise on a crash
        self.assertNotIn("pedigree.cycle",
                         {i["code"] for i in r["issues"]})

    def test_self_parent_reported_once_not_as_cycle(self):
        p = _temp_ged("0 @I1@ INDI\n1 NAME A /B/\n1 FAMC @F1@\n1 FAMS @F1@\n"
                      "0 @F1@ FAM\n1 HUSB @I1@\n1 CHIL @I1@\n")
        r = run_read(p, "audit")
        codes = [i["code"] for i in r["issues"]]
        self.assertIn("pedigree.self_parent", codes)
        self.assertNotIn("pedigree.cycle", codes)

    def test_empty_link_value_warns_not_a_pointer(self):
        p = _temp_ged("0 @I1@ INDI\n1 NAME A /B/\n1 FAMS\n"
                      "0 @F1@ FAM\n1 HUSB I1\n1 WIFE @I1@\n")
        r = run_read(p, "audit")
        nap = [i for i in r["issues"] if i["code"] == "link.not_a_pointer"]
        self.assertEqual(len(nap), 2)   # empty FAMS + non-pointer HUSB
        self.assertTrue(all(i["severity"] == "warning" for i in nap))


class ProvenanceTest(unittest.TestCase):
    """Fact-level source provenance and coverage metrics."""

    def _tree(self):
        mod = _load_gedcom_module()
        return mod.Tree(os.path.join(FIXTURES, "provenance.ged"))

    def test_fact_level_citation_attaches_to_fact(self):
        tree = self._tree()
        facts = {f["tag"]: f for f in tree.facts_of(tree.people["@I1@"],
                                                     "INDI", "@I1@")}
        self.assertTrue(facts["BIRT"]["cited"])
        self.assertFalse(facts["OCCU"]["cited"])
        self.assertEqual(facts["BIRT"]["citations"][0]["quay"], "3")
        self.assertEqual(facts["BIRT"]["citations"][0]["source_id"], "@S1@")

    def test_record_level_source_is_separate(self):
        tree = self._tree()
        # @I1@ has a record-level `1 SOUR @S1@` that must not mark every fact cited.
        rec = tree.record_sources(tree.people["@I1@"])
        self.assertEqual(len(rec), 1)
        facts = {f["tag"]: f for f in tree.facts_of(tree.people["@I1@"],
                                                    "INDI", "@I1@")}
        self.assertFalse(facts["OCCU"]["cited"])

    def test_family_marriage_source_counted(self):
        tree = self._tree()
        facts = {f["tag"]: f for f in tree.facts_of(tree.families["@F1@"],
                                                    "FAM", "@F1@")}
        self.assertTrue(facts["MARR"]["cited"])
        self.assertEqual(facts["MARR"]["citations"][0]["quay"], "2")

    def test_fact_ids_are_deterministic(self):
        tree = self._tree()
        a = [f["id"] for f in tree.facts_of(tree.people["@I1@"], "INDI", "@I1@")]
        b = [f["id"] for f in tree.facts_of(tree.people["@I1@"], "INDI", "@I1@")]
        self.assertEqual(a, b)
        self.assertIn("INDI:@I1@:BIRT:1", a)

    def test_audit_coverage_metrics(self):
        r = run_read(os.path.join(FIXTURES, "provenance.ged"), "audit")
        m = r["metrics"]
        self.assertGreater(m["facts_total"], 0)
        self.assertEqual(m["facts_cited"], 2)   # I1 BIRT + F1 MARR
        self.assertIsNotNone(m["coverage_pct"])
        self.assertEqual(m["record_level_citations"], 1)
        # QUAY from fact citations: one 3 and one 2.
        self.assertEqual(m["source_quality"]["3"], 1)
        self.assertEqual(m["source_quality"]["2"], 1)
        by = {t["tag"]: t for t in m["coverage_by_tag"]}
        self.assertEqual(by["BIRT"]["cited"], 1)
        self.assertEqual(by["BIRT"]["eligible"], 2)


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
