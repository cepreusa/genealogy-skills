#!/usr/bin/env python3
"""Lightweight GEDCOM reader (pure stdlib, no Gramps/Docker).

Parses a GEDCOM 5.5/5.5.1 file and answers structural queries. Output is JSON
so the calling agent can turn it into natural language.

Encoding: tries UTF-8 first, falls back to latin-1. Cyrillic-safe.
Handles common MyHeritage extension tags (_UID, _UPD, RIN, _MARNM) gracefully.

Usage:
    python3 gedcom.py <file.ged> stats
    python3 gedcom.py <file.ged> person <id|name-fragment>
    python3 gedcom.py <file.ged> search <surname-fragment>
    python3 gedcom.py <file.ged> family <id>
    python3 gedcom.py <file.ged> ancestors <id> [maxgen]
    python3 gedcom.py <file.ged> descendants <id> [maxgen]
    python3 gedcom.py <file.ged> relationship <idA> <idB>
    python3 gedcom.py <file.ged> timeline [surname-fragment]
    python3 gedcom.py <file.ged> list [limit]
    python3 gedcom.py <file.ged> audit

IDs may be given with or without @-signs (e.g. I1, @I1@, F3).

``audit`` runs a structural check (dangling/one-sided links, duplicate XREFs,
cycles, source/object pointers, conservative date anomalies) and prints a JSON
report with a stable ``code`` per finding. It exits 0 even when findings exist;
``ok`` is false only when there are errors.
"""

import json
import re
import sys


# --------------------------------------------------------------------------- #
# Link extraction
# --------------------------------------------------------------------------- #

_URL_RE = re.compile(r"https?://[^\s<>\"')]+")
# Vault-relative scan/document paths mentioned in note text, e.g.
# "Скан: materials/skany/Ivan_award.png".
_SCAN_RE = re.compile(
    r"(?:materials/)?skany/[^\s<>\"']+\.(?:png|jpe?g|pdf|tif?f|gif)",
    re.IGNORECASE,
)


def extract_links(notes):
    """Harvest external URLs and document/scan paths from a list of note texts.

    Returns {"urls": [...], "scans": [...]} with de-duplicated, order-preserved
    entries. Used to turn plain-text references inside NOTE into clickable links
    in the tree viewer, without altering the note text itself.
    """
    urls, scans = [], []
    for note in notes or []:
        for m in _URL_RE.findall(note or ""):
            u = m.rstrip(".,;)")
            if u not in urls:
                urls.append(u)
        for m in _SCAN_RE.findall(note or ""):
            if m not in scans:
                scans.append(m)
    return {"urls": urls, "scans": scans}


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #

def _detect_charset(raw):
    """Read the GEDCOM `1 CHAR` header value from the raw bytes."""
    head = raw[:4096].decode("latin-1", errors="replace")
    for line in head.splitlines():
        s = line.strip()
        if s.startswith("1 CHAR "):
            return s[len("1 CHAR "):].strip().upper()
    return ""


def read_lines(path):
    """Read a GEDCOM file, tolerating UTF-8, latin-1, or cp1251, stripping a BOM.

    Decodes the whole buffer at once (never per line): some exporters split
    long values with CONC in the middle of a multi-byte character, so a naive
    per-line decode would corrupt the text. When the declared charset is UTF-8
    we prefer UTF-8 with error replacement over silently falling back to a
    single-byte codec that would mangle every non-ASCII character.
    """
    with open(path, "rb") as fh:
        raw = fh.read()
    if raw.startswith(b"\xef\xbb\xbf"):
        raw = raw[3:]

    declared = _detect_charset(raw)

    # When the file declares UTF-8, trust it and decode with error replacement.
    # Some exporters (e.g. MyHeritage) split long values with CONC in the
    # middle of a multi-byte character, which makes strict UTF-8 decoding fail
    # on a handful of bytes. Replacing those is far better than falling back to
    # a single-byte codec, which would mangle every Cyrillic/accented name.
    if declared in ("UTF-8", "UTF8", "UNICODE") or not declared:
        try:
            return raw.decode("utf-8").splitlines()
        except UnicodeDecodeError:
            return raw.decode("utf-8", errors="replace").splitlines()

    # Otherwise honour common single-byte / ANSEL declarations.
    if declared in ("CP1251", "WINDOWS-1251", "ANSI"):
        order = ("cp1251", "utf-8", "latin-1")
    elif declared == "ANSEL":
        order = ("cp1251", "latin-1", "utf-8")
    else:
        order = ("utf-8", "cp1251", "latin-1")

    for enc in order:
        try:
            return raw.decode(enc).splitlines()
        except UnicodeDecodeError:
            continue
    return raw.decode(order[0], errors="replace").splitlines()


class Node:
    """A single GEDCOM line with its children."""

    __slots__ = ("level", "tag", "xref", "value", "children")

    def __init__(self, level, tag, xref, value):
        self.level = level
        self.tag = tag
        self.xref = xref
        self.value = value
        self.children = []

    def child(self, tag):
        for c in self.children:
            if c.tag == tag:
                return c
        return None

    def children_by(self, tag):
        return [c for c in self.children if c.tag == tag]

    def value_of(self, *path):
        """Follow a tag path (e.g. value_of('BIRT', 'DATE')) and return value."""
        node = self
        for tag in path:
            node = node.child(tag)
            if node is None:
                return ""
        return node.value


def parse(path):
    """Parse GEDCOM into a list of top-level (level 0) Nodes."""
    lines = read_lines(path)
    records = []
    stack = []  # (level, node)
    for line in lines:
        line = line.rstrip("\r\n")
        if not line.strip():
            continue
        parts = line.split(" ", 1)
        try:
            level = int(parts[0])
        except ValueError:
            # Continuation of a malformed line; attach to previous value.
            if stack:
                stack[-1][1].value += " " + line.strip()
            continue
        rest = parts[1] if len(parts) > 1 else ""

        xref = None
        if rest.startswith("@"):
            end = rest.find("@", 1)
            if end != -1:
                xref = rest[: end + 1]
                rest = rest[end + 1:].strip()
        toks = rest.split(" ", 1)
        tag = toks[0]
        value = toks[1] if len(toks) > 1 else ""

        node = Node(level, tag, xref, value)

        # CONC/CONT continue the parent value.
        if tag in ("CONC", "CONT") and stack:
            parent = stack[-1][1]
            sep = "" if tag == "CONC" else "\n"
            parent.value += sep + value
            continue

        while stack and stack[-1][0] >= level:
            stack.pop()
        if stack:
            stack[-1][1].children.append(node)
        else:
            records.append(node)
        stack.append((level, node))

    return records


NOISE_TAGS = {"_UID", "_UPD", "RIN", "_RTLSAVE", "_PROJECT_GUID",
              "_EXPORTED_FROM_SITE_ID"}


# --------------------------------------------------------------------------- #
# Model
# --------------------------------------------------------------------------- #

class Tree:
    def __init__(self, path):
        self.path = path
        self.records = parse(path)
        self.people = {}   # xref -> Node (INDI)
        self.families = {}  # xref -> Node (FAM)
        self.sources = {}  # xref -> Node (SOUR record)
        self.objects = {}  # xref -> Node (OBJE multimedia record)
        self.header = None
        for rec in self.records:
            if rec.tag == "INDI" and rec.xref:
                self.people[rec.xref] = rec
            elif rec.tag == "FAM" and rec.xref:
                self.families[rec.xref] = rec
            elif rec.tag == "SOUR" and rec.xref:
                self.sources[rec.xref] = rec
            elif rec.tag == "OBJE" and rec.xref:
                self.objects[rec.xref] = rec
            elif rec.tag == "HEAD":
                self.header = rec

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def norm_id(raw):
        raw = raw.strip()
        if not raw.startswith("@"):
            raw = "@" + raw
        if not raw.endswith("@"):
            raw = raw + "@"
        return raw.upper()

    def name(self, indi):
        n = indi.child("NAME")
        if n is None:
            return "?"
        given = n.value_of("GIVN")
        surn = n.value_of("SURN")
        if given or surn:
            return f"{given} {surn}".strip()
        # Fall back to the /Surname/ slash form.
        return n.value.replace("/", "").strip() or "?"

    def given_surname(self, indi):
        """Return (first_given_token, surname) for an individual.

        Prefers the GIVN/SURN sub-tags; falls back to parsing the slash form
        of the NAME value (``Given /Surname/``) so files without GIVN/SURN
        (common in older exports) still yield a surname.
        """
        n = indi.child("NAME")
        given = surn = ""
        if n is not None:
            given = n.value_of("GIVN")
            surn = n.value_of("SURN")
            if not (given or surn):
                raw = n.value or ""
                if "/" in raw:
                    before, _, after = raw.partition("/")
                    given = before.strip()
                    surn = after.replace("/", "").strip()
                else:
                    given = raw.strip()
        first = given.split()[0] if given else ""
        return first, surn.strip()

    def surname_of(self, indi):
        return self.given_surname(indi)[1]

    def nick(self, indi):
        n = indi.child("NAME")
        return n.value_of("NICK") if n else ""

    def event(self, indi, tag):
        ev = indi.child(tag)
        if ev is None:
            return {"date": "", "place": ""}
        return {"date": ev.value_of("DATE"), "place": ev.value_of("PLAC")}

    def person_brief(self, indi):
        birth = self.event(indi, "BIRT")
        death = self.event(indi, "DEAT")
        return {
            "id": indi.xref,
            "name": self.name(indi),
            "nick": self.nick(indi),
            "sex": indi.value_of("SEX"),
            "birth": birth,
            "death": death,
            "occupation": indi.value_of("OCCU"),
        }

    def source_ref(self, sour):
        """Resolve one SOUR child of a record into a structured dict.

        Handles both inline sources (``1 SOUR <text>`` with ``2 PAGE``/``2 DATA
        /TEXT``) and pointers to a top-level SOUR record (``1 SOUR @Sxx@`` whose
        record carries ``AUTH``/``TITL``/``TEXT``). Always-present keys (empty
        string / None when absent): title, author, page, text, url, source_id,
        quay. ``source_id`` is the ``@Sxx@`` pointer for a linked source, or
        ``None`` for an inline source.
        """
        page = sour.value_of("PAGE")
        text = sour.value_of("DATA", "TEXT") or sour.value_of("TEXT")
        quay = sour.value_of("QUAY")
        title = author = ""
        source_id = None
        # A pointer like "1 SOUR @S500003@" carries its value as the ref.
        ref = (sour.value or "").strip()
        rec = None
        if ref.startswith("@"):
            source_id = self.norm_id(ref)
            rec = self.sources.get(source_id)
        if rec is not None:
            author = rec.value_of("AUTH")
            title = rec.value_of("TITL")
            if not text:
                text = rec.value_of("TEXT")
        elif ref and not ref.startswith("@"):
            title = ref  # inline free-text source description
        url = ""
        for cand in (page, ref, text, title):
            m = re.search(r"https?://\S+", cand or "")
            if m:
                url = m.group(0)
                break
        return {"title": title, "author": author, "page": page,
                "text": text, "url": url, "source_id": source_id,
                "quay": quay}

    def _obje_files(self, obje):
        """Yield {path, form, title} for each FILE inside an OBJE node."""
        out = []
        # An OBJE may hold several FILE entries, or a single FILE with FORM/TITL
        # either under the FILE or under the OBJE itself (both forms exist).
        files = obje.children_by("FILE")
        if not files and (obje.value or "").strip():
            files = [obje]  # tolerate "1 OBJE <path>" shorthand
        for f in files:
            path = (f.value or "").strip()
            if not path:
                continue
            form = f.value_of("FORM") or obje.value_of("FORM")
            title = f.value_of("TITL") or obje.value_of("TITL")
            out.append({"path": path, "form": form, "title": title})
        return out

    def _documents_of(self, indi):
        """Collect attached documents (OBJE/FILE) for an individual.

        Handles inline ``1 OBJE`` blocks and pointers to a top-level ``@Oxx@``
        OBJE record. Returns a list of {path, form, title}, de-duplicated by path.
        """
        docs, seen = [], set()
        for obje in indi.children_by("OBJE"):
            ref = (obje.value or "").strip()
            node = obje
            if ref.startswith("@"):
                node = self.objects.get(self.norm_id(ref)) or obje
            for d in self._obje_files(node):
                if d["path"] not in seen:
                    seen.add(d["path"])
                    docs.append(d)
        return docs

    def person_full(self, indi):
        data = self.person_brief(indi)
        # Death cause, if recorded.
        deat = indi.child("DEAT")
        data["death"]["cause"] = deat.value_of("CAUS") if deat else ""
        # All occupations (there can be several), with place.
        data["occupations"] = [
            {"title": (o.value or "").strip(), "place": o.value_of("PLAC")}
            for o in indi.children_by("OCCU") if (o.value or "").strip()
        ]
        # Residences (RESI): date + place/address + contacts (contacts are
        # flagged sensitive so the tree viewer can hide them with --private).
        data["residences"] = []
        for r in indi.children_by("RESI"):
            addr = r.child("ADDR")
            place = r.value_of("PLAC")
            if addr is not None:
                bits = [addr.value_of("ADR1"), addr.value_of("CITY"),
                        addr.value_of("STAE"), addr.value_of("CTRY")]
                addr_str = ", ".join(b for b in bits if b) or (addr.value or "")
            else:
                addr_str = ""
            data["residences"].append({
                "date": r.value_of("DATE"),
                "place": place,
                "address": addr_str,
                "phone": r.value_of("PHON"),
                "email": r.value_of("EMAIL"),
            })
        # Events carrying an external URL (e.g. archive database links).
        data["events"] = []
        for ev in indi.children_by("EVEN"):
            val = (ev.value or "").strip()
            m = re.search(r"https?://\S+", val)
            data["events"].append({
                "type": ev.value_of("TYPE"),
                "text": val,
                "url": m.group(0) if m else "",
            })
        # Notes, plus links (URLs and scan paths) harvested from note text.
        notes = [c.value for c in indi.children_by("NOTE") if c.value]
        data["notes"] = notes
        data["links"] = extract_links(notes)
        # Attached multimedia objects (OBJE/FILE): scans, PDFs, or a linked
        # dossier note (e.g. an Obsidian `.md` file). Both inline OBJE blocks and
        # pointers to top-level `@Oxx@` OBJE records are handled.
        data["documents"] = self._documents_of(indi)
        # Structured sources (resolved).
        data["sources"] = [self.source_ref(c)
                           for c in indi.children_by("SOUR")]
        # Families where this person is a spouse / child.
        spouse_fams = [c.value for c in indi.children_by("FAMS")]
        child_fams = [c.value for c in indi.children_by("FAMC")]
        data["parents"] = []
        for fid in child_fams:
            fam = self.families.get(self.norm_id(fid)) if fid else None
            if fam:
                for role in ("HUSB", "WIFE"):
                    ref = fam.value_of(role)
                    if ref:
                        p = self.people.get(self.norm_id(ref))
                        if p:
                            data["parents"].append(
                                {"id": p.xref, "name": self.name(p),
                                 "role": role})
        data["spouses"] = []
        data["children"] = []
        for fid in spouse_fams:
            fam = self.families.get(self.norm_id(fid)) if fid else None
            if not fam:
                continue
            for role in ("HUSB", "WIFE"):
                ref = fam.value_of(role)
                if ref and self.norm_id(ref) != indi.xref:
                    p = self.people.get(self.norm_id(ref))
                    if p:
                        data["spouses"].append(
                            {"id": p.xref, "name": self.name(p)})
            for ch in fam.children_by("CHIL"):
                p = self.people.get(self.norm_id(ch.value))
                if p:
                    data["children"].append(
                        {"id": p.xref, "name": self.name(p)})
        return data

    # Genealogical fact/event tags whose citations count toward source coverage.
    INDI_FACT_TAGS = (
        "NAME", "SEX", "BIRT", "CHR", "BAPM", "DEAT", "BURI", "CREM", "ADOP",
        "OCCU", "RESI", "CENS", "EDUC", "EMIG", "IMMI", "NATU", "RELI",
        "TITL", "EVEN", "FACT",
    )
    FAM_FACT_TAGS = (
        "MARR", "DIV", "ANUL", "ENGA", "MARB", "MARC", "MARL", "MARS",
        "EVEN", "FACT",
    )

    def facts_of(self, record, owner_type, owner_id):
        """Enumerate a record's genealogical facts with their fact-level sources.

        Returns a list of fact dicts; each has a deterministic ``id`` and a
        ``citations`` list (fact-level SOUR children resolved via source_ref).
        Record-level SOUR children of the record itself are NOT folded into
        every fact — the caller gets those separately so a person-level citation
        never falsely "covers" every fact.
        """
        tags = (self.INDI_FACT_TAGS if owner_type == "INDI"
                else self.FAM_FACT_TAGS)
        facts = []
        counters = {}
        for node in record.children:
            if node.tag not in tags:
                continue
            counters[node.tag] = counters.get(node.tag, 0) + 1
            ordinal = counters[node.tag]
            citations = [self.source_ref(s) for s in node.children_by("SOUR")]
            facts.append({
                "id": f"{owner_type}:{owner_id}:{node.tag}:{ordinal}",
                "tag": node.tag,
                "type": node.value_of("TYPE"),
                "value": (node.value or "").strip(),
                "date": node.value_of("DATE"),
                "place": node.value_of("PLAC"),
                "citations": citations,
                "cited": bool(citations),
            })
        return facts

    def record_sources(self, record):
        """Record-level SOUR citations attached directly to a record (not a fact)."""
        return [self.source_ref(s) for s in record.children_by("SOUR")]

    def find(self, query):
        """Return list of INDI xrefs matching an id or name fragment."""
        q = query.strip()
        nid = self.norm_id(q)
        if nid in self.people:
            return [nid]
        ql = q.lower()
        hits = []
        for xid, indi in self.people.items():
            if ql in self.name(indi).lower() or ql in self.nick(indi).lower():
                hits.append(xid)
        return hits

    def parents_of(self, xid):
        indi = self.people.get(xid)
        if not indi:
            return []
        out = []
        for fc in indi.children_by("FAMC"):
            fam = self.families.get(self.norm_id(fc.value))
            if not fam:
                continue
            for role in ("HUSB", "WIFE"):
                ref = fam.value_of(role)
                if ref:
                    pid = self.norm_id(ref)
                    if pid in self.people:
                        out.append(pid)
        return out

    def children_of(self, xid):
        indi = self.people.get(xid)
        if not indi:
            return []
        out = []
        for fs in indi.children_by("FAMS"):
            fam = self.families.get(self.norm_id(fs.value))
            if not fam:
                continue
            for ch in fam.children_by("CHIL"):
                cid = self.norm_id(ch.value)
                if cid in self.people:
                    out.append(cid)
        return out

    def ancestors(self, xid, maxgen=6):
        # BFS so that, when the same person is reachable by several paths
        # (pedigree collapse), they get their MINIMAL generation number.
        result = {}
        frontier = [xid]
        gen = 1
        while frontier and gen <= maxgen:
            nxt = []
            for pid in frontier:
                for par in self.parents_of(pid):
                    if par not in result and par != xid:
                        result[par] = gen
                        nxt.append(par)
            frontier = nxt
            gen += 1
        return result

    def descendants(self, xid, maxgen=6):
        result = {}
        frontier = [xid]
        gen = 1
        while frontier and gen <= maxgen:
            nxt = []
            for pid in frontier:
                for ch in self.children_of(pid):
                    if ch not in result and ch != xid:
                        result[ch] = gen
                        nxt.append(ch)
            frontier = nxt
            gen += 1
        return result

    def audit(self):
        """Return a deterministic, JSON-serializable structural audit."""
        return audit_tree(self)


# --------------------------------------------------------------------------- #
# Audit
# --------------------------------------------------------------------------- #
#
# A read-only structural check over the parsed model. It operates on the Tree /
# Node interface (never on raw lines), so it is honest about what a tolerant,
# lossy parser can diagnose: CONC/CONT are already merged and source line
# numbers are gone, so this is a MODEL-level audit, not a full GEDCOM grammar
# validator. Findings carry a stable ``code`` and structured ``details``; the
# English ``message`` is a convenience — consumers branch on ``code``.
#
# ``ok`` is true iff there are zero errors; warnings never make ok false. The
# audit command still exits 0 when findings exist (a completed audit succeeded);
# a non-zero exit is reserved for being unable to run.

AUDIT_SCHEMA_VERSION = 1

_XREF_RE = re.compile(r"^@[^@\s]+@$")
_SEVERITY_RANK = {"error": 0, "warning": 1, "info": 2}


def _valid_xref(value):
    return bool(value) and bool(_XREF_RE.match(value.strip()))


def _pointer(value):
    """Return the raw pointer text if a value looks like a single @xref@."""
    v = (value or "").strip()
    return v if _valid_xref(v) else ""


def _year_bounds(value):
    """Conservative (min_year, max_year) for a GEDCOM date, or (None, None).

    Only returns bounds when they can be read unambiguously. Handles plain
    years, common qualifiers (ABT/EST/CAL/BEF/AFT) and ranges (BET..AND,
    FROM..TO) by taking the outer years. Calendar-qualified or otherwise
    unparseable dates yield (None, None) so no false chronology finding fires.
    """
    if not value:
        return (None, None)
    v = value.strip().upper()
    if v.startswith("@#"):  # explicit non-Gregorian calendar — don't guess
        return (None, None)
    years = [int(y) for y in re.findall(r"\b(\d{3,4})\b", v)]
    if not years:
        return (None, None)
    return (min(years), max(years))


def _make_issue(severity, code, message, record=None, record_type=None,
                path=None, value=None, related=None, details=None):
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "record": record,
        "record_type": record_type,
        "path": path,
        "value": value,
        "related": related or [],
        "details": details or {},
    }


def _walk(node, prefix, out):
    """Yield (path, node) for every descendant, path like INDI.BIRT.SOUR."""
    for child in node.children:
        p = prefix + "." + child.tag
        out.append((p, child))
        _walk(child, p, out)


def _audit_structure(tree, issues):
    recs = tree.records
    heads = [r for r in recs if r.tag == "HEAD"]
    trlrs = [r for r in recs if r.tag == "TRLR"]
    if not heads:
        issues.append(_make_issue("error", "format.head_missing",
                                   "file has no HEAD record"))
    elif len(heads) > 1:
        issues.append(_make_issue("error", "format.head_duplicate",
                                  f"file has {len(heads)} HEAD records",
                                  details={"count": len(heads)}))
    elif recs and recs[0].tag != "HEAD":
        issues.append(_make_issue("warning", "format.head_not_first",
                                  "HEAD is not the first record"))
    if not trlrs:
        issues.append(_make_issue("error", "format.trailer_missing",
                                   "file has no TRLR record"))
    elif len(trlrs) > 1:
        issues.append(_make_issue("error", "format.trailer_duplicate",
                                  f"file has {len(trlrs)} TRLR records",
                                  details={"count": len(trlrs)}))
    elif recs and recs[-1].tag != "TRLR":
        issues.append(_make_issue("warning", "format.trailer_not_last",
                                  "TRLR is not the last record"))
    # Node levels: each child should be exactly parent.level + 1.
    for rec in recs:
        nodes = []
        _walk(rec, rec.tag, nodes)
        for path, node in nodes:
            parent_level = node.level - 1
            # find nearest ancestor via path depth is expensive; instead flag
            # any node whose level is not a sensible step. We reconstruct the
            # expected level from the number of path segments below the record.
            depth = path.count(".")
            if node.level != depth:
                issues.append(_make_issue(
                    "error", "format.level_jump",
                    f"{rec.xref or rec.tag}: '{node.tag}' has level "
                    f"{node.level}, expected {depth}",
                    record=rec.xref, record_type=rec.tag, path=path,
                    details={"level": node.level, "expected": depth}))
            if not node.tag:
                issues.append(_make_issue(
                    "warning", "format.empty_tag",
                    f"{rec.xref or rec.tag}: empty tag on a line",
                    record=rec.xref, record_type=rec.tag, path=path))


def _audit_xrefs(tree, issues, dup_ids):
    seen = {}
    for rec in tree.records:
        if rec.tag in ("HEAD", "TRLR"):
            continue
        if rec.xref is None:
            if rec.tag in ("INDI", "FAM"):
                issues.append(_make_issue(
                    "error", "xref.missing",
                    f"a {rec.tag} record has no XREF id",
                    record_type=rec.tag))
            continue
        if not _valid_xref(rec.xref):
            issues.append(_make_issue(
                "error", "xref.malformed",
                f"malformed XREF id {rec.xref!r}",
                record=rec.xref, record_type=rec.tag, value=rec.xref))
        if rec.xref in seen:
            dup_ids.add(rec.xref)
        seen.setdefault(rec.xref, []).append(rec.tag)
    for xid, tags in sorted(seen.items()):
        if len(tags) > 1:
            issues.append(_make_issue(
                "error", "xref.duplicate",
                f"XREF {xid} is defined {len(tags)} times",
                record=xid, value=xid,
                details={"count": len(tags), "types": tags}))


def _audit_links(tree, issues, dup_ids):
    people, families = tree.people, tree.families

    def note_dangling(rec, path, ref, code):
        issues.append(_make_issue(
            "error", code,
            f"{rec.xref}: {path} points to missing record {ref}",
            record=rec.xref, record_type=rec.tag, path=path,
            value=ref, related=[ref]))

    for xid, indi in people.items():
        if xid in dup_ids:
            continue
        for fs in indi.children_by("FAMS"):
            ref = _pointer(fs.value)
            if not ref:
                continue
            fid = tree.norm_id(ref)
            if fid not in families:
                note_dangling(indi, "INDI.FAMS", fs.value, "link.fams_dangling")
            elif fid not in dup_ids:
                fam = families[fid]
                spouses = {tree.norm_id(_pointer(r.value))
                           for role in ("HUSB", "WIFE")
                           for r in fam.children_by(role) if _pointer(r.value)}
                if xid not in spouses:
                    issues.append(_make_issue(
                        "error", "link.fams_missing_reverse",
                        f"{xid}: FAMS {fid} but not listed as HUSB/WIFE there",
                        record=xid, record_type="INDI", path="INDI.FAMS",
                        value=fs.value, related=[fid]))
        for fc in indi.children_by("FAMC"):
            ref = _pointer(fc.value)
            if not ref:
                continue
            fid = tree.norm_id(ref)
            if fid not in families:
                note_dangling(indi, "INDI.FAMC", fc.value, "link.famc_dangling")
            elif fid not in dup_ids:
                fam = families[fid]
                kids = {tree.norm_id(_pointer(c.value))
                        for c in fam.children_by("CHIL") if _pointer(c.value)}
                if xid not in kids:
                    issues.append(_make_issue(
                        "error", "link.famc_missing_reverse",
                        f"{xid}: FAMC {fid} but not listed as CHIL there",
                        record=xid, record_type="INDI", path="INDI.FAMC",
                        value=fc.value, related=[fid]))

    for fid, fam in families.items():
        if fid in dup_ids:
            continue
        spouses = []
        for role in ("HUSB", "WIFE"):
            refs = fam.children_by(role)
            if len(refs) > 1:
                issues.append(_make_issue(
                    "warning", "link." + role.lower() + "_duplicate",
                    f"{fid}: {len(refs)} {role} entries",
                    record=fid, record_type="FAM",
                    details={"count": len(refs)}))
            for r in refs:
                ref = _pointer(r.value)
                if not ref:
                    continue
                iid = tree.norm_id(ref)
                spouses.append(iid)
                if iid not in people:
                    note_dangling(fam, "FAM." + role, r.value,
                                  "link." + role.lower() + "_dangling")
                elif iid not in dup_ids:
                    indi = people[iid]
                    fams = {tree.norm_id(_pointer(f.value))
                            for f in indi.children_by("FAMS") if _pointer(f.value)}
                    if fid not in fams:
                        issues.append(_make_issue(
                            "error", "link.spouse_missing_reverse",
                            f"{fid}: {role} {iid} but that person has no FAMS "
                            f"back to {fid}",
                            record=fid, record_type="FAM", path="FAM." + role,
                            value=r.value, related=[iid]))
        child_ids = []
        for c in fam.children_by("CHIL"):
            ref = _pointer(c.value)
            if not ref:
                continue
            cid = tree.norm_id(ref)
            child_ids.append(cid)
            if cid not in people:
                note_dangling(fam, "FAM.CHIL", c.value, "link.child_dangling")
            elif cid not in dup_ids:
                indi = people[cid]
                famc = {tree.norm_id(_pointer(f.value))
                        for f in indi.children_by("FAMC") if _pointer(f.value)}
                if fid not in famc:
                    issues.append(_make_issue(
                        "error", "link.child_missing_reverse",
                        f"{fid}: CHIL {cid} but that person has no FAMC back "
                        f"to {fid}",
                        record=fid, record_type="FAM", path="FAM.CHIL",
                        value=c.value, related=[cid]))
        if len(set(child_ids)) != len(child_ids):
            issues.append(_make_issue(
                "warning", "link.child_duplicate",
                f"{fid}: the same child is listed more than once",
                record=fid, record_type="FAM"))
        # Family shape.
        uniq_spouses = [s for s in spouses if s in people]
        if len(uniq_spouses) == 2 and uniq_spouses[0] == uniq_spouses[1]:
            issues.append(_make_issue(
                "error", "family.same_spouses",
                f"{fid}: the same person is both spouses",
                record=fid, record_type="FAM", related=[uniq_spouses[0]]))
        both = set(uniq_spouses) & set(child_ids)
        for p in sorted(both):
            issues.append(_make_issue(
                "error", "family.child_is_spouse",
                f"{fid}: {p} is both a spouse and a child",
                record=fid, record_type="FAM", related=[p]))
        if not uniq_spouses and not child_ids:
            issues.append(_make_issue(
                "warning", "family.empty",
                f"{fid}: family has no spouses and no children",
                record=fid, record_type="FAM"))


def _audit_references(tree, issues):
    """SOUR/OBJE pointer integrity and QUAY validity across all records."""
    for rec in tree.records:
        if rec.tag in ("HEAD", "TRLR"):
            continue
        nodes = [(rec.tag, rec)]
        walked = []
        _walk(rec, rec.tag, walked)
        nodes.extend(walked)
        for path, node in nodes:
            if node.tag == "SOUR":
                ref = _pointer(node.value)
                if ref and tree.norm_id(ref) not in tree.sources:
                    issues.append(_make_issue(
                        "error", "source.pointer_dangling",
                        f"{rec.xref}: SOUR points to missing {node.value}",
                        record=rec.xref, record_type=rec.tag, path=path,
                        value=node.value, related=[node.value]))
                quay = node.value_of("QUAY")
                if quay and quay.strip() not in ("0", "1", "2", "3"):
                    issues.append(_make_issue(
                        "warning", "source.quay_invalid",
                        f"{rec.xref}: QUAY {quay!r} is not 0-3",
                        record=rec.xref, record_type=rec.tag,
                        path=path + ".QUAY", value=quay))
            elif node.tag == "OBJE":
                ref = _pointer(node.value)
                if ref and tree.norm_id(ref) not in tree.objects:
                    issues.append(_make_issue(
                        "error", "object.pointer_dangling",
                        f"{rec.xref}: OBJE points to missing {node.value}",
                        record=rec.xref, record_type=rec.tag, path=path,
                        value=node.value, related=[node.value]))


def _audit_individuals(tree, issues):
    for xid, indi in tree.people.items():
        names = indi.children_by("NAME")
        if not names:
            issues.append(_make_issue(
                "warning", "individual.name_missing",
                f"{xid}: no NAME record", record=xid, record_type="INDI"))
        elif all(not (n.value.strip() or n.value_of("GIVN") or n.value_of("SURN"))
                 for n in names):
            issues.append(_make_issue(
                "warning", "individual.name_empty",
                f"{xid}: NAME is empty", record=xid, record_type="INDI"))
        sexes = indi.children_by("SEX")
        if len(sexes) > 1:
            issues.append(_make_issue(
                "warning", "individual.sex_duplicate",
                f"{xid}: {len(sexes)} SEX records",
                record=xid, record_type="INDI"))
        for s in sexes:
            v = (s.value or "").strip().upper()
            if v and v not in ("M", "F", "U"):
                issues.append(_make_issue(
                    "warning", "individual.sex_invalid",
                    f"{xid}: SEX {s.value!r} is not M/F/U",
                    record=xid, record_type="INDI", value=s.value))


def _audit_dates(tree, issues):
    def yr(node, tag):
        lo, hi = _year_bounds(node.value_of(tag, "DATE"))
        return lo, hi

    for xid, indi in tree.people.items():
        blo, bhi = yr(indi, "BIRT")
        dlo, dhi = yr(indi, "DEAT")
        if bhi is not None and dlo is not None and dlo < blo:
            issues.append(_make_issue(
                "warning", "date.death_before_birth",
                f"{xid}: death year {dlo} is before birth year {blo}",
                record=xid, record_type="INDI",
                details={"birth_year": blo, "death_year": dlo}))

    for fid, fam in tree.families.items():
        mlo, mhi = _year_bounds(fam.value_of("MARR", "DATE"))
        if mlo is None:
            continue
        for role in ("HUSB", "WIFE"):
            ref = _pointer(fam.value_of(role))
            if not ref:
                continue
            iid = tree.norm_id(ref)
            indi = tree.people.get(iid)
            if not indi:
                continue
            blo, bhi = _year_bounds(indi.value_of("BIRT", "DATE"))
            dlo, dhi = _year_bounds(indi.value_of("DEAT", "DATE"))
            if blo is not None and mhi is not None and mhi < blo:
                issues.append(_make_issue(
                    "warning", "date.marriage_before_birth",
                    f"{fid}: marriage {mhi} before {iid}'s birth {blo}",
                    record=fid, record_type="FAM", related=[iid],
                    details={"marriage_year": mhi, "birth_year": blo}))
            if dhi is not None and mlo is not None and mlo > dhi:
                issues.append(_make_issue(
                    "warning", "date.marriage_after_death",
                    f"{fid}: marriage {mlo} after {iid}'s death {dhi}",
                    record=fid, record_type="FAM", related=[iid],
                    details={"marriage_year": mlo, "death_year": dhi}))


def _audit_cycles(tree, issues):
    """Detect ancestry cycles (a person among their own ancestors).

    Pedigree collapse (the same ancestor reached by two paths) is NOT a cycle
    and is not flagged; only a back-edge in the parent relation is.
    """
    WHITE, GREY, BLACK = 0, 1, 2
    color = {}
    reported = set()

    def visit(pid, stack):
        color[pid] = GREY
        stack.append(pid)
        for par in tree.parents_of(pid):
            if color.get(par, WHITE) == GREY:
                key = tuple(sorted((pid, par)))
                if key not in reported:
                    reported.add(key)
                    issues.append(_make_issue(
                        "error", "pedigree.cycle",
                        f"ancestry cycle involving {par} and {pid}",
                        record=par, record_type="INDI", related=[pid],
                        details={"between": list(key)}))
            elif color.get(par, WHITE) == WHITE:
                visit(par, stack)
        stack.pop()
        color[pid] = BLACK

    for xid in tree.people:
        if color.get(xid, WHITE) == WHITE:
            visit(xid, [])
    for xid, indi in tree.people.items():
        parents = tree.parents_of(xid)
        if xid in parents:
            issues.append(_make_issue(
                "error", "pedigree.self_parent",
                f"{xid} is their own parent",
                record=xid, record_type="INDI"))


def _audit_metrics(tree):
    people = tree.people
    no_birth = no_death = no_parent = isolated = 0
    quay = {"0": 0, "1": 0, "2": 0, "3": 0}
    citations = 0                    # record-level INDI citations (legacy count)
    fact_citations = 0               # fact-level citations
    facts_total = facts_cited = 0
    record_level = 0                 # record-level citations (INDI + FAM)
    by_tag = {}                      # tag -> [eligible, cited]

    def tally(record, owner_type, owner_id):
        nonlocal facts_total, facts_cited, fact_citations, record_level
        for fact in tree.facts_of(record, owner_type, owner_id):
            facts_total += 1
            slot = by_tag.setdefault(fact["tag"], [0, 0])
            slot[0] += 1
            if fact["cited"]:
                facts_cited += 1
                slot[1] += 1
            for c in fact["citations"]:
                fact_citations += 1
                q = (c.get("quay") or "").strip()
                if q in quay:
                    quay[q] += 1
        for c in tree.record_sources(record):
            record_level += 1
            q = (c.get("quay") or "").strip()
            if q in quay:
                quay[q] += 1

    for xid, indi in people.items():
        if not indi.value_of("BIRT", "DATE"):
            no_birth += 1
        if not indi.value_of("DEAT", "DATE"):
            no_death += 1
        has_parent = bool(indi.children_by("FAMC"))
        has_family = has_parent or bool(indi.children_by("FAMS"))
        if not has_parent:
            no_parent += 1
        if not has_family:
            isolated += 1
        citations += len(indi.children_by("SOUR"))
        tally(indi, "INDI", xid)
    for fid, fam in tree.families.items():
        tally(fam, "FAM", fid)

    coverage_pct = (round(100.0 * facts_cited / facts_total, 1)
                    if facts_total else None)
    coverage_by_tag = [
        {"tag": tag, "eligible": e, "cited": c,
         "pct": round(100.0 * c / e, 1) if e else None}
        for tag, (e, c) in sorted(by_tag.items(), key=lambda kv: -kv[1][0])
    ]
    return {
        "people_without_birth": no_birth,
        "people_without_death": no_death,
        "people_without_parent_family": no_parent,
        "isolated_people": isolated,
        "source_citations": citations,
        "source_quality": quay,
        # Fact-level provenance.
        "facts_total": facts_total,
        "facts_cited": facts_cited,
        "coverage_pct": coverage_pct,
        "fact_citations": fact_citations,
        "record_level_citations": record_level,
        "coverage_by_tag": coverage_by_tag,
    }


def audit_tree(tree):
    """Run all structural checks and return a deterministic report dict."""
    issues = []
    dup_ids = set()
    _audit_structure(tree, issues)
    _audit_xrefs(tree, issues, dup_ids)
    _audit_links(tree, issues, dup_ids)
    _audit_references(tree, issues)
    _audit_individuals(tree, issues)
    _audit_dates(tree, issues)
    _audit_cycles(tree, issues)

    issues.sort(key=lambda i: (
        _SEVERITY_RANK.get(i["severity"], 9), i["code"],
        i["record"] or "", i["path"] or "", i["value"] or "",
        ",".join(i["related"])))

    errors = sum(1 for i in issues if i["severity"] == "error")
    warnings = sum(1 for i in issues if i["severity"] == "warning")
    info = sum(1 for i in issues if i["severity"] == "info")
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "file": tree.path,
        "ok": errors == 0,
        "summary": {
            "records": len(tree.records),
            "people": len(tree.people),
            "families": len(tree.families),
            "errors": errors,
            "warnings": warnings,
            "info": info,
            "total": len(issues),
        },
        "metrics": _audit_metrics(tree),
        "issues": issues,
    }


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #

def cmd_stats(tree, args):
    surnames = {}
    births = []
    for indi in tree.people.values():
        surn = tree.surname_of(indi)
        if surn:
            surnames[surn] = surnames.get(surn, 0) + 1
        d = tree.event(indi, "BIRT")["date"]
        if d:
            births.append(d)
    top = sorted(surnames.items(), key=lambda kv: -kv[1])[:15]
    lang = tree.header.value_of("LANG") if tree.header else ""
    char = tree.header.value_of("CHAR") if tree.header else ""
    vers = tree.header.value_of("GEDC", "VERS") if tree.header else ""
    return {
        "file": tree.path,
        "people": len(tree.people),
        "families": len(tree.families),
        "gedcom_version": vers,
        "charset": char,
        "language": lang,
        "distinct_surnames": len(surnames),
        "top_surnames": [{"surname": s, "count": c} for s, c in top],
    }


def cmd_person(tree, args):
    if not args:
        return {"error": "person requires an id or name fragment"}
    xid = _resolve_one(tree, args[0])
    if isinstance(xid, dict):
        return xid
    return tree.person_full(tree.people[xid])


def cmd_search(tree, args):
    if not args:
        return {"error": "search requires a surname fragment"}
    q = args[0].lower()
    out = []
    for indi in tree.people.values():
        if q in tree.name(indi).lower():
            out.append(tree.person_brief(indi))
    return {"query": args[0], "count": len(out), "results": out}


def cmd_family(tree, args):
    if not args:
        return {"error": "family requires a family id"}
    fam = tree.families.get(tree.norm_id(args[0]))
    if not fam:
        return {"error": f"no family {args[0]}"}
    out = {"id": fam.xref, "marriage": tree.event(fam, "MARR")}
    for role in ("HUSB", "WIFE"):
        ref = fam.value_of(role)
        if ref:
            p = tree.people.get(tree.norm_id(ref))
            out[role.lower()] = {"id": p.xref, "name": tree.name(p)} if p else None
    out["children"] = []
    for ch in fam.children_by("CHIL"):
        p = tree.people.get(tree.norm_id(ch.value))
        if p:
            out["children"].append({"id": p.xref, "name": tree.name(p)})
    out["notes"] = [c.value for c in fam.children_by("NOTE") if c.value]
    return out


def _resolve_one(tree, query):
    """Resolve a query to a single xref, or return an (ambiguous|error) dict.

    Returns a string xref on a unique match, otherwise a dict describing the
    problem (so callers can surface it instead of silently picking hits[0]).
    """
    hits = tree.find(query)
    if not hits:
        return {"error": f"no person matching '{query}'"}
    if len(hits) > 1:
        return {"ambiguous": [tree.person_brief(tree.people[h]) for h in hits],
                "query": query}
    return hits[0]


def _gen_list(tree, mapping):
    out = []
    for xid, gen in sorted(mapping.items(), key=lambda kv: kv[1]):
        p = tree.people[xid]
        b = tree.person_brief(p)
        b["generation"] = gen
        out.append(b)
    return out


def cmd_ancestors(tree, args):
    if not args:
        return {"error": "ancestors requires a person id"}
    xid = _resolve_one(tree, args[0])
    if isinstance(xid, dict):
        return xid
    maxgen = int(args[1]) if len(args) > 1 else 6
    return {"center": tree.person_brief(tree.people[xid]),
            "ancestors": _gen_list(tree, tree.ancestors(xid, maxgen))}


def cmd_descendants(tree, args):
    if not args:
        return {"error": "descendants requires a person id"}
    xid = _resolve_one(tree, args[0])
    if isinstance(xid, dict):
        return xid
    maxgen = int(args[1]) if len(args) > 1 else 6
    return {"center": tree.person_brief(tree.people[xid]),
            "descendants": _gen_list(tree, tree.descendants(xid, maxgen))}


def cmd_relationship(tree, args):
    if len(args) < 2:
        return {"error": "relationship requires two ids"}
    aid = _resolve_one(tree, args[0])
    if isinstance(aid, dict):
        return aid
    bid = _resolve_one(tree, args[1])
    if isinstance(bid, dict):
        return bid

    # BFS over parent/child/spouse edges, tracking the path.
    from collections import deque

    def neighbours(pid):
        edges = []
        for p in tree.parents_of(pid):
            edges.append((p, "parent"))
        for c in tree.children_of(pid):
            edges.append((c, "child"))
        indi = tree.people.get(pid)
        if indi:
            for fs in indi.children_by("FAMS"):
                fam = tree.families.get(tree.norm_id(fs.value))
                if fam:
                    for role in ("HUSB", "WIFE"):
                        ref = fam.value_of(role)
                        if ref and tree.norm_id(ref) != pid:
                            sp = tree.norm_id(ref)
                            if sp in tree.people:
                                edges.append((sp, "spouse"))
        return edges

    q = deque([aid])
    prev = {aid: None}
    while q:
        cur = q.popleft()
        if cur == bid:
            break
        for nxt, rel in neighbours(cur):
            if nxt not in prev:
                prev[nxt] = (cur, rel)
                q.append(nxt)

    if bid not in prev:
        return {"a": tree.person_brief(tree.people[aid]),
                "b": tree.person_brief(tree.people[bid]),
                "connected": False,
                "message": "no path found in the file"}

    path = []
    node = bid
    while node and node != aid:
        parent, rel = prev[node]
        path.append({"from": tree.name(tree.people[parent]),
                     "to": tree.name(tree.people[node]),
                     "relation": rel})
        node = parent
    path.reverse()
    return {"a": tree.person_brief(tree.people[aid]),
            "b": tree.person_brief(tree.people[bid]),
            "connected": True,
            "steps": len(path),
            "path": path}


def cmd_timeline(tree, args):
    q = args[0].lower() if args else None
    events = []
    for indi in tree.people.values():
        name = tree.name(indi)
        if q and q not in name.lower():
            continue
        for tag, label in (("BIRT", "birth"), ("DEAT", "death")):
            ev = tree.event(indi, tag)
            if ev["date"]:
                events.append({"who": name, "event": label,
                               "date": ev["date"], "place": ev["place"]})
    for fam in tree.families.values():
        m = tree.event(fam, "MARR")
        if not m["date"]:
            continue
        h = fam.value_of("HUSB")
        w = fam.value_of("WIFE")
        hn = tree.name(tree.people[tree.norm_id(h)]) if h and tree.norm_id(h) in tree.people else "?"
        wn = tree.name(tree.people[tree.norm_id(w)]) if w and tree.norm_id(w) in tree.people else "?"
        if q and q not in hn.lower() and q not in wn.lower():
            continue
        events.append({"who": f"{hn} & {wn}", "event": "marriage",
                       "date": m["date"], "place": m["place"]})
    return {"count": len(events), "events": events}


def cmd_list(tree, args):
    limit = int(args[0]) if args else 100
    out = [tree.person_brief(indi) for indi in list(tree.people.values())[:limit]]
    return {"total": len(tree.people), "shown": len(out), "people": out}


def cmd_audit(tree, args):
    return tree.audit()


COMMANDS = {
    "stats": cmd_stats,
    "person": cmd_person,
    "search": cmd_search,
    "family": cmd_family,
    "ancestors": cmd_ancestors,
    "descendants": cmd_descendants,
    "relationship": cmd_relationship,
    "timeline": cmd_timeline,
    "list": cmd_list,
    "audit": cmd_audit,
}


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    path, command = argv[1], argv[2]
    args = argv[3:]
    fn = COMMANDS.get(command)
    if fn is None:
        print(json.dumps({"error": f"unknown command '{command}'",
                          "commands": sorted(COMMANDS)}, ensure_ascii=False))
        return 2
    try:
        tree = Tree(path)
    except FileNotFoundError:
        print(json.dumps({"error": f"file not found: {path}"},
                         ensure_ascii=False))
        return 1
    result = fn(tree, args)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
