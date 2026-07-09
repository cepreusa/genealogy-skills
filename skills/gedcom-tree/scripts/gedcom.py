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

IDs may be given with or without @-signs (e.g. I1, @I1@, F3).
"""

import json
import sys


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
        self.header = None
        for rec in self.records:
            if rec.tag == "INDI" and rec.xref:
                self.people[rec.xref] = rec
            elif rec.tag == "FAM" and rec.xref:
                self.families[rec.xref] = rec
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

    def person_full(self, indi):
        data = self.person_brief(indi)
        notes = [c.value for c in indi.children_by("NOTE") if c.value]
        data["notes"] = notes
        data["sources"] = [c.value_of("PAGE") or (c.value or c.xref or "")
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
