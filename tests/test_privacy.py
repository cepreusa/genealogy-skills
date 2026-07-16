#!/usr/bin/env python3
"""Privacy tests for the tree viewer and report dashboard.

Pure stdlib. Builds a synthetic GEDCOM with canary strings in every channel and
checks the living-person classifier, the --private redaction, the --share
omission, the fail-closed payload audit, and that the two privacy.py copies stay
byte-identical.

    PYTHONIOENCODING=utf-8 python3 -m unittest discover -s tests -v
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
TREE_DIR = os.path.join(ROOT, "skills", "gedcom-tree", "scripts")
REPORT_DIR = os.path.join(ROOT, "skills", "gedcom-report", "scripts")
TREE_PY = os.path.join(TREE_DIR, "tree.py")
REPORT_PY = os.path.join(REPORT_DIR, "report.py")
ENV = dict(os.environ, PYTHONIOENCODING="utf-8")

# Canary strings — none of these may appear in a --share export.
LIVING_NAME = "Zoe Livingston"
LIVING_ID = "@I9@"
CANARY_PHONE = "555-0100"
CANARY_EMAIL = "zoe@example.com"
CANARY_STREET = "42 Secret Lane"
CANARY_PLACE = "Hidden City"
CANARY_NOTE = "PRIVATE-NOTE-CANARY"
CANARY_SCAN = "materials/skany/zoe_secret.png"

GED = f"""0 HEAD
1 CHAR UTF-8
1 GEDC
2 VERS 5.5.1
0 @I1@ INDI
1 NAME Great /Elder/
1 SEX M
1 BIRT
2 DATE 1850
1 DEAT
2 DATE 1910
1 FAMS @F1@
1 ASSO @I9@
2 RELA witness
0 @I2@ INDI
1 NAME Old /Elder/
1 SEX F
1 BIRT
2 DATE 1855
1 DEAT
2 DATE 1915
1 FAMS @F1@
0 @I3@ INDI
1 NAME Mid /Elder/
1 SEX M
1 BIRT
2 DATE 1885
1 BURI
2 DATE 1950
1 FAMC @F1@
1 FAMS @F2@
0 @I9@ INDI
1 NAME {LIVING_NAME.replace(' Livingston', '')} /Livingston/
1 SEX F
1 BIRT
2 DATE 12 MAR 1990
2 PLAC {CANARY_PLACE}
1 OCCU Engineer
1 RESI
2 PLAC {CANARY_PLACE}
2 PHON {CANARY_PHONE}
2 EMAIL {CANARY_EMAIL}
2 ADDR
3 ADR1 {CANARY_STREET}
1 NOTE {CANARY_NOTE} scan {CANARY_SCAN}
1 FAMC @F2@
0 @F1@ FAM
1 HUSB @I1@
1 WIFE @I2@
1 CHIL @I3@
1 MARR
2 DATE 1882
0 @F2@ FAM
1 HUSB @I3@
1 CHIL @I9@
1 MARR
2 DATE 1988
0 TRLR
"""


def _load(modname, path, extradir):
    sys.path.insert(0, extradir)
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def write_ged():
    d = tempfile.mkdtemp()
    p = os.path.join(d, "t.ged")
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(GED)
    return p


class ClassifyTest(unittest.TestCase):
    def setUp(self):
        self.privacy = _load("privacy_t", os.path.join(TREE_DIR, "privacy.py"),
                             TREE_DIR)
        import gedcom
        self.gedcom = gedcom
        self.ged = write_ged()

    def _cls(self, as_of=2026):
        tree = self.gedcom.Tree(self.ged)
        return {k: v["class"]
                for k, v in self.privacy.classify_people(tree, as_of).items()}

    def test_deceased_and_living(self):
        c = self._cls()
        self.assertEqual(c["@I1@"], self.privacy.DECEASED)      # DEAT date
        self.assertEqual(c["@I3@"], self.privacy.DECEASED)      # BURI
        self.assertEqual(c["@I9@"], self.privacy.LIKELY_LIVING)  # born 1990

    def test_old_birth_presumed_deceased(self):
        priv = self.privacy
        # A person born long before as_of with no death evidence.
        ged2 = GED.replace("2 DATE 12 MAR 1990", "2 DATE 1700")
        d = tempfile.mkdtemp(); p = os.path.join(d, "o.ged")
        open(p, "w", encoding="utf-8").write(ged2)
        t2 = self.gedcom.Tree(p)
        c = {k: v["class"] for k, v in priv.classify_people(t2, 2026).items()}
        self.assertEqual(c["@I9@"], priv.PRESUMED_DECEASED)

    def test_as_of_year_boundary(self):
        # Born exactly at the 110-year cutoff -> still likely living.
        c = self._cls(as_of=1990 + 110)
        self.assertEqual(c["@I9@"], self.privacy.LIKELY_LIVING)
        c2 = self._cls(as_of=1990 + 111)
        self.assertEqual(c2["@I9@"], self.privacy.PRESUMED_DECEASED)

    def _cls_with(self, replace_from, replace_to, as_of=2026):
        ged2 = GED.replace(replace_from, replace_to)
        d = tempfile.mkdtemp(); p = os.path.join(d, "r.ged")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(ged2)
        t = self.gedcom.Tree(p)
        return {k: v["class"]
                for k, v in self.privacy.classify_people(t, as_of).items()}

    def test_range_birth_uses_latest_year(self):
        # BET 1900 AND 1980: the person may have been born in 1980 — must be
        # treated as possibly living, not classified off the earliest year.
        c = self._cls_with("2 DATE 12 MAR 1990", "2 DATE BET 1900 AND 1980")
        self.assertEqual(c["@I9@"], self.privacy.LIKELY_LIVING)
        # A range that is old on both ends stays presumed deceased.
        c2 = self._cls_with("2 DATE 12 MAR 1990", "2 DATE BET 1700 AND 1800")
        self.assertEqual(c2["@I9@"], self.privacy.PRESUMED_DECEASED)

    def test_bare_deat_placeholder_is_not_death_evidence(self):
        # A bare "1 DEAT" with no value/date is a placeholder, not evidence:
        # with a recent birth the person must stay protected.
        ged2 = GED.replace("1 OCCU Engineer", "1 OCCU Engineer\n1 DEAT")
        d = tempfile.mkdtemp(); p = os.path.join(d, "b.ged")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(ged2)
        t = self.gedcom.Tree(p)
        c = {k: v["class"]
             for k, v in self.privacy.classify_people(t, 2026).items()}
        self.assertEqual(c["@I9@"], self.privacy.LIKELY_LIVING)
        # But "1 DEAT Y" (an asserted death) is evidence.
        ged3 = GED.replace("1 OCCU Engineer", "1 OCCU Engineer\n1 DEAT Y")
        p3 = os.path.join(d, "y.ged")
        with open(p3, "w", encoding="utf-8") as fh:
            fh.write(ged3)
        t3 = self.gedcom.Tree(p3)
        c3 = {k: v["class"]
              for k, v in self.privacy.classify_people(t3, 2026).items()}
        self.assertEqual(c3["@I9@"], self.privacy.DECEASED)


class TreePrivacyPayloadTest(unittest.TestCase):
    def setUp(self):
        self.tree_mod = _load("tree_mod", TREE_PY, TREE_DIR)
        self.privacy = _load("privacy_t2", os.path.join(TREE_DIR, "privacy.py"),
                             TREE_DIR)
        import gedcom
        self.gedcom = gedcom
        self.ged = write_ged()

    def _payload(self, mode):
        tree = self.gedcom.Tree(self.ged)
        ctx = self.privacy.PrivacyContext(tree, mode)
        people, families = self.tree_mod.build_graph(tree, ctx)
        details = self.tree_mod.build_details(tree, ctx=ctx)
        return {"people": people, "families": families, "details": details}, ctx

    def _blob(self, payload):
        return json.dumps(payload, ensure_ascii=False)

    def test_share_omits_living_and_all_canaries(self):
        payload, ctx = self._payload("share")
        self.assertNotIn(LIVING_ID, payload["people"])
        blob = self._blob(payload)
        for canary in (LIVING_NAME.split()[0], "Livingston", CANARY_PHONE,
                       CANARY_EMAIL, CANARY_STREET, CANARY_PLACE, CANARY_NOTE,
                       CANARY_SCAN, LIVING_ID):
            self.assertNotIn(canary, blob, f"share leaked {canary!r}")
        # Details are empty in share mode.
        self.assertEqual(payload["details"], {})

    def test_share_drops_references_to_omitted(self):
        payload, _ = self._payload("share")
        for fam in payload["families"].values():
            self.assertNotIn(LIVING_ID, fam["chil"])
            self.assertNotEqual(fam["husb"], LIVING_ID)
            self.assertNotEqual(fam["wife"], LIVING_ID)

    def test_private_keeps_living_but_redacts_sensitive(self):
        payload, _ = self._payload("private")
        # The living person is still present (identified view).
        self.assertIn(LIVING_ID, payload["people"])
        p = payload["people"][LIVING_ID]
        self.assertEqual(p["place"], "")
        self.assertEqual(p["occ"], "")
        det = payload["details"][LIVING_ID]
        self.assertEqual(det["residences"], [])
        self.assertEqual(det["notes"], [])
        self.assertEqual(det["documents"], [])
        blob = json.dumps({"people": {LIVING_ID: p}, "det": det},
                          ensure_ascii=False)
        for canary in (CANARY_PHONE, CANARY_EMAIL, CANARY_STREET, CANARY_PLACE,
                       CANARY_NOTE, CANARY_SCAN):
            self.assertNotIn(canary, blob)

    def test_private_marriage_date_dropped_for_protected_family(self):
        payload, _ = self._payload("private")
        # @F2@ contains the living person -> its marriage year is dropped.
        self.assertIsNone(payload["families"]["@F2@"]["marr"])
        # @F1@ is all-deceased -> keeps its marriage year.
        self.assertIsNotNone(payload["families"]["@F1@"]["marr"])

    def test_private_drops_associations_to_protected(self):
        # @I1@ (deceased) names @I9@ (living) as a witness. In private mode the
        # association is a fact about a living person — dropped both ways.
        payload, _ = self._payload("private")
        self.assertEqual(payload["details"]["@I1@"]["associates"], [])
        self.assertEqual(payload["details"][LIVING_ID]["associates"], [])
        payload_none, _ = self._payload("none")
        self.assertEqual(len(payload_none["details"]["@I1@"]["associates"]), 1)

    def test_share_has_no_dangling_family_refs(self):
        payload, _ = self._payload("share")
        fids = set(payload["families"])
        for p in payload["people"].values():
            for fid in p["fams"] + p["famc"]:
                self.assertIn(fid, fids)

    def test_private_scrubs_urls_inside_citation_text(self):
        # A URL inside a note/citation string (not just the url field) must be
        # scrubbed in private mode.
        ged2 = GED.replace(
            "1 NAME Great /Elder/",
            "1 NAME Great /Elder/\n1 NOTE see https://secret.example/x.png")
        d = tempfile.mkdtemp(); p = os.path.join(d, "u.ged")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(ged2)
        tree = self.gedcom.Tree(p)
        ctx = self.privacy.PrivacyContext(tree, "private")
        details = self.tree_mod.build_details(tree, ctx=ctx)
        blob = json.dumps(details, ensure_ascii=False)
        self.assertNotIn("secret.example", blob)


class ReportSharePrivacyTest(unittest.TestCase):
    """Report --share: family aggregates must cover the historical subset only."""

    def setUp(self):
        self.report = _load("report_mod", REPORT_PY, REPORT_DIR)
        self.privacy = _load("privacy_r", os.path.join(REPORT_DIR, "privacy.py"),
                             REPORT_DIR)
        import gedcom
        self.gedcom = gedcom
        self.ged = write_ged()

    def _ctx(self, tree, mode):
        return self.privacy.PrivacyContext(tree, mode)

    def test_share_timeline_hides_spouseless_family_marriage(self):
        # A family whose only disclosed member set contains a protected child
        # must not leak its marriage year — even with no recorded spouses.
        ged2 = GED.replace("0 TRLR", "0 @F3@ FAM\n1 CHIL @I9@\n1 MARR\n"
                                     "2 DATE 2015\n2 PLAC Hidden City\n0 TRLR")
        d = tempfile.mkdtemp(); p = os.path.join(d, "s.ged")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(ged2)
        tree = self.gedcom.Tree(p)
        ctx = self._ctx(tree, "share")
        timeline = self.report.build_timeline(tree, ctx)
        years = {e["year"] for e in timeline if e["type"] == "marriage"}
        self.assertNotIn(2015, years)
        # @F2@ has a protected child too -> its 1988 marriage is hidden as well.
        self.assertNotIn(1988, years)
        # The all-deceased @F1@ marriage stays.
        self.assertIn(1882, years)

    def test_share_children_counts_exclude_omitted(self):
        tree = self.gedcom.Tree(self.ged)
        ctx = self._ctx(tree, "share")
        m = self.report.build_metrics(tree, lang="en", ctx=ctx)
        # @F2@'s only child is the living person -> no family with children
        # besides @F1@ (1 child), and totals must not count the omitted child.
        fams = {f["family"]: f["children"] for f in m["biggest_families"]}
        self.assertTrue(all(c == 1 for c in fams.values()), fams)
        self.assertEqual(m["overview"]["avg_children"], 0.5)  # 1 child / 2 fams


class PayloadAuditTest(unittest.TestCase):
    def setUp(self):
        self.privacy = _load("privacy_t3", os.path.join(TREE_DIR, "privacy.py"),
                             TREE_DIR)
        import gedcom
        self.gedcom = gedcom
        self.ged = write_ged()

    def test_audit_flags_a_deliberately_bad_payload(self):
        tree = self.gedcom.Tree(self.ged)
        ctx = self.privacy.PrivacyContext(tree, "share")
        bad = {"people": {LIVING_ID: {"name": LIVING_NAME,
                                      "phone": CANARY_PHONE,
                                      "url": "https://x.example",
                                      "path": "/abs/secret.png"}}}
        pa = self.privacy.audit_payload(
            bad, ctx, protected_names={LIVING_NAME}, protected_ids={LIVING_ID})
        self.assertGreater(pa["protected_ids"], 0)
        self.assertGreater(pa["protected_names"], 0)
        self.assertGreater(pa["contacts"], 0)
        self.assertGreater(pa["external_urls"], 0)
        self.assertGreater(pa["absolute_paths"], 0)
        self.assertGreater(self.privacy.share_leak_total(pa), 0)


class CliPrivacyTest(unittest.TestCase):
    def setUp(self):
        self.ged = write_ged()
        self.out = os.path.join(os.path.dirname(self.ged), "o.html")

    def _run(self, script, *args):
        r = subprocess.run([sys.executable, script, self.ged, self.out, *args],
                           capture_output=True, text=True, env=ENV)
        # Success prints JSON to stdout; errors print JSON to stderr.
        raw = r.stdout.strip() or r.stderr.strip()
        data = json.loads(raw) if raw.startswith("{") else {}
        return data, r.returncode

    def test_tree_modes(self):
        d, rc = self._run(TREE_PY, "--share")
        self.assertEqual(rc, 0)
        self.assertEqual(d["privacy_mode"], "share")
        self.assertEqual(d["omitted_people"], 1)
        html = open(self.out, encoding="utf-8").read()
        for canary in (CANARY_PHONE, CANARY_NOTE, CANARY_SCAN, LIVING_ID):
            self.assertNotIn(canary, html)

    def test_report_share(self):
        d, rc = self._run(REPORT_PY, "--share")
        self.assertEqual(rc, 0)
        self.assertEqual(d["privacy_mode"], "share")
        html = open(self.out, encoding="utf-8").read()
        for canary in (CANARY_PLACE, LIVING_ID):
            self.assertNotIn(canary, html)

    def test_report_private(self):
        d, rc = self._run(REPORT_PY, "--private")
        self.assertEqual(rc, 0)
        self.assertEqual(d["privacy_mode"], "private")
        html = open(self.out, encoding="utf-8").read()
        # Places/contacts of the possibly-living person stay out even though
        # names remain (identified view).
        for canary in (CANARY_PLACE, CANARY_PHONE, CANARY_EMAIL, CANARY_NOTE):
            self.assertNotIn(canary, html)

    def test_mutually_exclusive_and_unknown(self):
        _, rc = self._run(TREE_PY, "--private", "--share")
        self.assertEqual(rc, 2)
        _, rc2 = self._run(REPORT_PY, "--bogus")
        self.assertEqual(rc2, 2)

    def test_share_focus_on_protected_person_fails(self):
        d, rc = self._run(TREE_PY, "--share", "--focus", "Livingston")
        self.assertEqual(rc, 1)
        self.assertIn("omitted", d.get("error", ""))


class PrivacyCopiesInSyncTest(unittest.TestCase):
    def test_two_copies_identical(self):
        a = os.path.join(TREE_DIR, "privacy.py")
        b = os.path.join(REPORT_DIR, "privacy.py")
        da = hashlib.md5(open(a, "rb").read()).hexdigest()
        db = hashlib.md5(open(b, "rb").read()).hexdigest()
        self.assertEqual(da, db, "privacy.py copies diverged; re-sync them")


if __name__ == "__main__":
    unittest.main()
