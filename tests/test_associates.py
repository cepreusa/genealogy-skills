#!/usr/bin/env python3
"""Release 5 — associates (ASSO/RELA) and the scan-manifest integrity check.

Pure standard library (unittest). Run with:

    PYTHONIOENCODING=utf-8 python3 -m unittest discover -s tests -v

Covers:
- Tree.associations_of / association_index (direction, resolution, dedup);
- ASSO links are social/evidentiary, never pedigree edges;
- the report's associates summary (counts, by-relation, non-pedigree);
- the scan manifest: verified / mismatch / missing / external-url states and
  the path-traversal / absolute-path guards.
"""

import hashlib
import importlib.util
import json
import os
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(ROOT, "tests", "fixtures")
READER = os.path.join(ROOT, "skills", "gedcom-reader", "scripts")
REPORT = os.path.join(ROOT, "skills", "gedcom-report", "scripts")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GEDCOM = _load("gedcom", os.path.join(READER, "gedcom.py"))


class AssociationTest(unittest.TestCase):
    def _tree(self):
        return GEDCOM.Tree(os.path.join(ROOT, "examples", "demo.ged"))

    def test_outbound_and_relation(self):
        tree = self._tree()
        a = tree.associations_of(tree.people["@I1@"])
        self.assertEqual(len(a), 1)
        self.assertEqual(a[0]["to_id"], "@I10@")
        self.assertTrue(a[0]["resolved"])
        self.assertIn("Священник", a[0]["relation"])

    def test_index_records_both_directions(self):
        tree = self._tree()
        index, unresolved = tree.association_index()
        self.assertEqual(unresolved, [])
        priest = index["@I10@"]
        dirs = sorted(e["direction"] for e in priest)
        self.assertEqual(dirs, ["inbound", "inbound"])
        # The priest names nobody outbound himself.
        self.assertFalse(any(e["direction"] == "outbound" for e in priest))

    def test_association_is_not_pedigree(self):
        tree = self._tree()
        # @I10@ is an associate but must not be a parent/spouse/child of @I1@.
        d = tree.person_full(tree.people["@I1@"])
        rel_ids = {r["id"] for r in
                   d["parents"] + d["spouses"] + d["children"]}
        self.assertNotIn("@I10@", rel_ids)

    def test_unresolved_pointer(self):
        tree = GEDCOM.Tree(os.path.join(FIXTURES, "scans", "scans.ged"))
        # scans.ged has no ASSO -> empty index, no crash.
        index, unresolved = tree.association_index()
        self.assertEqual(index, {})
        self.assertEqual(unresolved, [])

    def test_dangling_asso_pointer(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "a.ged")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("0 HEAD\n1 CHAR UTF-8\n"
                     "0 @I1@ INDI\n1 NAME A /B/\n"
                     "1 ASSO @I99@\n2 RELA witness\n0 TRLR\n")
        tree = GEDCOM.Tree(p)
        a = tree.associations_of(tree.people["@I1@"])
        self.assertEqual(len(a), 1)
        self.assertFalse(a[0]["resolved"])
        self.assertEqual(a[0]["to_name"], "")
        index, unresolved = tree.association_index()
        self.assertEqual(len(unresolved), 1)
        self.assertEqual(unresolved[0]["to_id"], "@I99@")
        # The dangling target never gains an inbound entry.
        self.assertNotIn("@I99@", index)


class ReportAssociatesTest(unittest.TestCase):
    def setUp(self):
        self.report = _load("report", os.path.join(REPORT, "report.py"))

    def test_summary_counts(self):
        tree = GEDCOM.Tree(os.path.join(ROOT, "examples", "demo.ged"))
        m = self.report.build_metrics(tree, lang="ru")
        a = m["associates"]
        self.assertEqual(a["pairs"], 2)
        self.assertEqual(a["people_with"], 2)
        # The priest has no FAMS/FAMC -> counts as outside the pedigree.
        self.assertEqual(a["non_pedigree"], 1)
        self.assertEqual(a["unresolved"], 0)
        rels = {r["relation"] for r in a["by_relation"]}
        self.assertIn("Крёстный отец", rels)

    def test_share_mode_hides_omitted_associates(self):
        # Everyone in the demo is deceased, so share keeps them; assert the
        # summary is still well-formed (no crash, pairs present).
        import importlib.util as _il
        privacy = _load("privacy", os.path.join(REPORT, "privacy.py"))
        tree = GEDCOM.Tree(os.path.join(ROOT, "examples", "demo.ged"))
        ctx = privacy.PrivacyContext(tree, "share")
        m = self.report.build_metrics(tree, lang="ru", ctx=ctx)
        self.assertIn("associates", m)
        self.assertIsInstance(m["associates"]["pairs"], int)


class ScanManifestTest(unittest.TestCase):
    def setUp(self):
        self.mdir = os.path.join(FIXTURES, "scans")
        self.manifest = GEDCOM.load_scan_manifest(
            os.path.join(self.mdir, "manifest.json"))

    def test_verified(self):
        r = GEDCOM.verify_scan(self.manifest, "img/present.png", do_hash=True)
        self.assertEqual(r["state"], "verified")

    def test_size_mismatch(self):
        r = GEDCOM.verify_scan(self.manifest, "img/mismatch.png")
        self.assertEqual(r["state"], "mismatch")

    def test_missing(self):
        r = GEDCOM.verify_scan(self.manifest, "skany/missing.png")
        self.assertEqual(r["state"], "missing")

    def test_external_url_flagged(self):
        r = GEDCOM.verify_scan(self.manifest, "https://example.org/x.png")
        self.assertEqual(r["state"], "external-url")

    def test_unmanifested(self):
        r = GEDCOM.verify_scan(self.manifest, "img/unknown.png")
        self.assertEqual(r["state"], "unmanifested")

    def test_path_traversal_rejected(self):
        self.assertIsNone(
            GEDCOM._safe_join(self.manifest["root"], self.manifest["base"],
                              "../../etc/passwd"))

    def test_absolute_path_rejected(self):
        self.assertIsNone(
            GEDCOM._safe_join(self.manifest["root"], self.manifest["base"],
                              "/etc/passwd"))

    def test_all_document_paths(self):
        tree = GEDCOM.Tree(os.path.join(self.mdir, "scans.ged"))
        paths = tree.all_document_paths()
        self.assertIn("img/present.png", paths)       # from OBJE/FILE
        self.assertIn("skany/missing.png", paths)     # from the NOTE text
        self.assertNotIn("https://example.org/external.png", paths)

    def test_hash_unchecked_without_flag(self):
        # Without --verify-hash a hashed entry is reported "unchecked".
        r = GEDCOM.verify_scan(self.manifest, "img/present.png", do_hash=False)
        self.assertEqual(r["state"], "unchecked")

    def test_report_scan_check(self):
        report = _load("report", os.path.join(REPORT, "report.py"))
        tree = GEDCOM.Tree(os.path.join(self.mdir, "scans.ged"))
        sc = report.build_scan_check(
            tree, os.path.join(self.mdir, "manifest.json"), do_hash=True)
        self.assertEqual(sc["states"].get("verified"), 1)
        self.assertEqual(sc["states"].get("mismatch"), 1)
        # missing.png is referenced in the NOTE and listed in the manifest.
        self.assertEqual(sc["states"].get("missing"), 1)

    def test_report_scan_check_hides_paths_when_asked(self):
        report = _load("report", os.path.join(REPORT, "report.py"))
        tree = GEDCOM.Tree(os.path.join(self.mdir, "scans.ged"))
        sc = report.build_scan_check(
            tree, os.path.join(self.mdir, "manifest.json"), do_hash=True,
            include_paths=False)
        self.assertFalse(sc["paths_included"])
        self.assertTrue(all(p["path"] == "" for p in sc["problems"]))
        self.assertTrue(all(p["state"] for p in sc["problems"]))


class ManifestHardeningTest(unittest.TestCase):
    """The manifest itself must not be able to escape its own directory."""

    def _write_manifest(self, d, data):
        p = os.path.join(d, "manifest.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        return p

    def test_absolute_base_rejected(self):
        d = tempfile.mkdtemp()
        p = self._write_manifest(d, {"base": "/", "files": []})
        with self.assertRaises(ValueError):
            GEDCOM.load_scan_manifest(p)

    def test_escaping_base_rejected(self):
        d = tempfile.mkdtemp()
        p = self._write_manifest(d, {"base": "../..", "files": []})
        with self.assertRaises(ValueError):
            GEDCOM.load_scan_manifest(p)

    def test_backslash_and_drive_paths_rejected(self):
        d = tempfile.mkdtemp()
        p = self._write_manifest(d, {"base": ".", "files": []})
        m = GEDCOM.load_scan_manifest(p)
        self.assertIsNone(GEDCOM._safe_join(m["root"], m["base"],
                                            "..\\..\\etc\\passwd"))
        self.assertIsNone(GEDCOM._safe_join(m["root"], m["base"],
                                            "C:\\Windows\\evil.png"))

    def test_hash_mismatch_detected(self):
        d = tempfile.mkdtemp()
        scan = os.path.join(d, "s.png")
        with open(scan, "wb") as fh:
            fh.write(b"actual-bytes")
        p = self._write_manifest(d, {
            "base": ".",
            "files": [{"path": "s.png", "size": len(b"actual-bytes"),
                       "sha256": hashlib.sha256(b"other-bytes").hexdigest()}],
        })
        m = GEDCOM.load_scan_manifest(p)
        r = GEDCOM.verify_scan(m, "s.png", do_hash=True)
        self.assertEqual(r["state"], "mismatch")

    def test_unsupported_algorithm_never_verifies(self):
        d = tempfile.mkdtemp()
        scan = os.path.join(d, "s.png")
        with open(scan, "wb") as fh:
            fh.write(b"bytes")
        p = self._write_manifest(d, {
            "base": ".", "algorithm": "md5",
            "files": [{"path": "s.png", "size": 5, "sha256": "aa" * 32}],
        })
        m = GEDCOM.load_scan_manifest(p)
        r = GEDCOM.verify_scan(m, "s.png", do_hash=True)
        self.assertEqual(r["state"], "unsupported-algorithm")

    def test_fam_and_sour_documents_collected(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "f.ged")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write("0 HEAD\n1 CHAR UTF-8\n"
                     "0 @I1@ INDI\n1 NAME A /B/\n1 FAMS @F1@\n"
                     "0 @F1@ FAM\n1 HUSB @I1@\n"
                     "1 OBJE\n2 FILE scans/marriage.png\n"
                     "0 @S1@ SOUR\n1 TITL Register\n"
                     "1 OBJE\n2 FILE scans/register.pdf\n"
                     "0 TRLR\n")
        tree = GEDCOM.Tree(p)
        paths = tree.all_document_paths()
        self.assertIn("scans/marriage.png", paths)
        self.assertIn("scans/register.pdf", paths)


if __name__ == "__main__":
    unittest.main()
