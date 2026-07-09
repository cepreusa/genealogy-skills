#!/usr/bin/env python3
"""Create and enrich GEDCOM files (pure stdlib, no Gramps/Docker).

Companion writer to gedcom.py (the reader). It builds a new tree from scratch or
mutates an existing one — adding people, setting facts/events, and linking
relationships — while keeping the file's structure valid: a proper HEAD/TRLR,
unique XREFs, and, crucially, **two-way** family links (FAMC/FAMS on the person
mirrored by HUSB/WIFE/CHIL on the family).

Design: the file is parsed into the same Node tree the reader uses, mutated in
memory, then serialized back out. Every mutating command writes a timestamped
backup first and re-parses the result as a sanity check. UTF-8, Cyrillic-safe.

Usage:
    # create an empty tree
    python3 gedcom_write.py <file.ged> init [--name "Tree name"]

    # add a person; prints the new @Ixx@ id as JSON
    python3 gedcom_write.py <file.ged> add-person \\
        --given "Иван" --surname "Петров" --sex M \\
        [--birt-date "9 FEB 1960"] [--birt-place "Москва"] \\
        [--deat-date "2007"] [--deat-place "..."] [--occu "..."] \\
        [--note "..."]

    # set / replace a fact or event on an existing person
    python3 gedcom_write.py <file.ged> set <id> \\
        [--sex M] [--birt-date ...] [--birt-place ...] \\
        [--deat-date ...] [--deat-place ...] [--occu ...] \\
        [--name-given ...] [--name-surname ...] [--add-note "..."]

    # link relationships (creates/updates the FAM record, both directions)
    python3 gedcom_write.py <file.ged> link spouses <idA> <idB> \\
        [--marr-date ...] [--marr-place ...]
    python3 gedcom_write.py <file.ged> link child <childId> \\
        --parent <idA> [--parent <idB>]      # attaches child to parents' family

    # remove a link (keeps the people; detaches from the family)
    python3 gedcom_write.py <file.ged> unlink child <childId> --family <Fxx>

IDs may be given with or without @-signs. Set PYTHONIOENCODING=utf-8 so Cyrillic
prints correctly. A backup <file>.bak-YYYYMMDD-HHMMSS.ged is made before writing.
"""

import argparse
import datetime
import json
import os
import shutil
import sys

# Reuse the reader's parser and model.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gedcom  # noqa: E402
from gedcom import Node  # noqa: E402


# --------------------------------------------------------------------------- #
# Serialization
# --------------------------------------------------------------------------- #

def _emit(node, out):
    """Serialize a Node and its children into GEDCOM lines (level from node)."""
    line = str(node.level)
    if node.xref:
        line += " " + node.xref
    line += " " + node.tag
    if node.value != "":
        # Split multi-line values into CONT continuations.
        parts = node.value.split("\n")
        line += " " + parts[0]
        out.append(line)
        for extra in parts[1:]:
            out.append(f"{node.level + 1} CONT {extra}")
    else:
        out.append(line)
    for ch in node.children:
        _emit(ch, out)


def serialize(records):
    out = []
    for rec in records:
        _emit(rec, out)
    return "\n".join(out) + "\n"


def _renumber(node, level):
    node.level = level
    for ch in node.children:
        _renumber(ch, level + 1)


# --------------------------------------------------------------------------- #
# Tree helpers
# --------------------------------------------------------------------------- #

def _today():
    return datetime.date.today().strftime("%d %b %Y").upper()


def _now_stamp():
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


def _next_id(existing, prefix):
    """Return the next free @<prefix><n>@ not present in `existing` (a set)."""
    n = 1
    while True:
        cand = f"@{prefix}{n}@"
        if cand not in existing:
            return cand
        n += 1


def new_head(tree_name=None):
    head = Node(0, "HEAD", None, "")
    sour = Node(1, "SOUR", None, "gedcom-skills")
    sour.children.append(Node(2, "NAME", None, "gedcom-skills reader/writer"))
    head.children.append(sour)
    gedc = Node(1, "GEDC", None, "")
    gedc.children.append(Node(2, "VERS", None, "5.5.1"))
    form = Node(2, "FORM", None, "LINEAGE-LINKED")
    gedc.children.append(form)
    head.children.append(gedc)
    head.children.append(Node(1, "CHAR", None, "UTF-8"))
    dt = Node(1, "DATE", None, _today())
    head.children.append(dt)
    if tree_name:
        head.children.append(Node(1, "FILE", None, tree_name))
    return head


def load_or_die(path):
    try:
        tree = gedcom.Tree(path)
    except FileNotFoundError:
        print(json.dumps({"error": f"file not found: {path}"},
                         ensure_ascii=False))
        sys.exit(1)
    return tree


def existing_xrefs(tree):
    s = set(tree.people.keys()) | set(tree.families.keys())
    for rec in tree.records:
        if rec.xref:
            s.add(rec.xref)
    return s


def find_one(tree, query):
    """Resolve an id or unique name fragment to a single xref, or exit."""
    hits = tree.find(query)
    if not hits:
        print(json.dumps({"error": f"no person matching '{query}'"},
                         ensure_ascii=False))
        sys.exit(1)
    if len(hits) > 1:
        print(json.dumps({
            "error": f"'{query}' is ambiguous",
            "matches": [{"id": h, "name": tree.name(tree.people[h])}
                        for h in hits],
        }, ensure_ascii=False))
        sys.exit(1)
    return hits[0]


def write_out(tree, path, note):
    """Backup, serialize, write, and re-parse as a sanity check."""
    if os.path.exists(path):
        backup = f"{os.path.splitext(path)[0]}.bak-{_now_stamp()}.ged"
        shutil.copy2(path, backup)
    else:
        backup = None
    text = serialize(tree.records)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    # Sanity check: re-parse.
    verify = gedcom.Tree(path)
    result = {
        "ok": True,
        "action": note,
        "file": path,
        "people": len(verify.people),
        "families": len(verify.families),
    }
    if backup:
        result["backup"] = os.path.basename(backup)
    return result


# --------------------------------------------------------------------------- #
# Record mutation helpers
# --------------------------------------------------------------------------- #

def set_event(indi, tag, date=None, place=None):
    """Create or update an event node (BIRT/DEAT/...) with DATE/PLAC."""
    ev = indi.child(tag)
    if ev is None:
        ev = Node(1, tag, None, "")
        indi.children.append(ev)
    if date is not None:
        d = ev.child("DATE")
        if d is None:
            ev.children.append(Node(2, "DATE", None, date))
        else:
            d.value = date
    if place is not None:
        p = ev.child("PLAC")
        if p is None:
            ev.children.append(Node(2, "PLAC", None, place))
        else:
            p.value = place
    return ev


def set_simple(indi, tag, value):
    """Set a simple 1-level tag value (SEX, OCCU), creating if needed."""
    node = indi.child(tag)
    if node is None:
        indi.children.append(Node(1, tag, None, value))
    else:
        node.value = value


def set_name(indi, given=None, surname=None):
    n = indi.child("NAME")
    if n is None:
        n = Node(1, "NAME", None, "")
        indi.children.insert(0, n)
    g = given if given is not None else n.value_of("GIVN")
    s = surname if surname is not None else n.value_of("SURN")
    n.value = f"{g} /{s}/".strip()
    gn = n.child("GIVN")
    if given is not None:
        if gn is None:
            n.children.append(Node(2, "GIVN", None, given))
        else:
            gn.value = given
    sn = n.child("SURN")
    if surname is not None:
        if sn is None:
            n.children.append(Node(2, "SURN", None, surname))
        else:
            sn.value = surname


def add_note(indi, text):
    indi.children.append(Node(1, "NOTE", None, text))


def add_changelog(indi, text):
    add_note(indi, f"[CHANGELOG] {datetime.date.today().isoformat()}: {text}")


def _fam_spouses(tree, fam):
    """Return the (husb, wife) xrefs of a family (either may be None)."""
    h = fam.value_of("HUSB")
    w = fam.value_of("WIFE")
    return (tree.norm_id(h) if h else None,
            tree.norm_id(w) if w else None)


def find_couple_family(tree, aid, bid):
    """Return the FAM xref where aid & bid are the two spouses, if any."""
    for fid, fam in tree.families.items():
        husb, wife = _fam_spouses(tree, fam)
        if {aid, bid} == {husb, wife}:
            return fid
    return None


def find_partial_family(tree, aid, bid):
    """Find a FAM that already has one of the pair as a spouse with the other
    slot free — so we can fill it instead of creating a duplicate family.

    Returns (fid, empty_role) or (None, None). empty_role is "HUSB"/"WIFE".
    """
    for fid, fam in tree.families.items():
        husb, wife = _fam_spouses(tree, fam)
        if husb in (aid, bid) and wife is None:
            return fid, "WIFE"
        if wife in (aid, bid) and husb is None:
            return fid, "HUSB"
    return None, None


def _assign_husb_wife(tree, aid, bid):
    """Pick (husb_xref, wife_xref) for a new couple by SEX when known, else by
    the order the two people were given. Handles same-sex / unknown cleanly:
    the first person keeps HUSB unless sex dictates otherwise."""
    asex = (tree.people[aid].value_of("SEX") or "").upper()
    bsex = (tree.people[bid].value_of("SEX") or "").upper()
    # If exactly one is clearly female, put her in WIFE; likewise for male.
    if asex == "F" and bsex != "F":
        return bid, aid
    if bsex == "F" and asex != "F":
        return aid, bid
    if asex == "M" and bsex != "M":
        return aid, bid
    if bsex == "M" and asex != "M":
        return bid, aid
    # Same-sex or unknown: keep argument order.
    return aid, bid


def person_fams(indi, tag):
    return [c.value for c in indi.children_by(tag)]


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #

def cmd_init(args):
    path = args.file
    if os.path.exists(path) and not args.force:
        print(json.dumps({"error": f"{path} already exists; use --force"},
                         ensure_ascii=False))
        return 1
    # Build a minimal tree object without parsing.
    tree = gedcom.Tree.__new__(gedcom.Tree)
    tree.path = path
    tree.people = {}
    tree.families = {}
    tree.header = new_head(args.name)
    tree.records = [tree.header, Node(0, "TRLR", None, "")]
    # Write directly (no backup for a brand-new file).
    text = serialize(tree.records)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    verify = gedcom.Tree(path)
    print(json.dumps({"ok": True, "action": "init", "file": path,
                      "people": len(verify.people),
                      "families": len(verify.families)},
                     ensure_ascii=False))
    return 0


def _insert_record(tree, node):
    """Insert a level-0 record before TRLR (or at end)."""
    for i, rec in enumerate(tree.records):
        if rec.tag == "TRLR":
            tree.records.insert(i, node)
            return
    tree.records.append(node)


def cmd_add_person(args):
    tree = load_or_die(args.file)
    xid = _next_id(existing_xrefs(tree), "I")
    indi = Node(0, "INDI", xid, "")
    set_name(indi, given=args.given or "", surname=args.surname or "")
    if args.sex:
        set_simple(indi, "SEX", args.sex.upper())
    if args.birt_date or args.birt_place:
        set_event(indi, "BIRT", args.birt_date, args.birt_place)
    if args.deat_date or args.deat_place:
        set_event(indi, "DEAT", args.deat_date, args.deat_place)
    if args.occu:
        set_simple(indi, "OCCU", args.occu)
    if args.note:
        add_note(indi, args.note)
    _renumber(indi, 0)
    _insert_record(tree, indi)
    tree.people[xid] = indi
    res = write_out(tree, args.file, f"add-person {xid}")
    res["id"] = xid
    res["name"] = tree.name(indi)
    print(json.dumps(res, ensure_ascii=False))
    return 0


def cmd_set(args):
    tree = load_or_die(args.file)
    xid = find_one(tree, args.id)
    indi = tree.people[xid]
    changes = []
    if args.name_given is not None or args.name_surname is not None:
        set_name(indi, args.name_given, args.name_surname)
        changes.append("name")
    if args.sex:
        set_simple(indi, "SEX", args.sex.upper())
        changes.append("sex")
    if args.birt_date or args.birt_place:
        set_event(indi, "BIRT", args.birt_date, args.birt_place)
        changes.append("birth")
    if args.deat_date or args.deat_place:
        set_event(indi, "DEAT", args.deat_date, args.deat_place)
        changes.append("death")
    if args.occu:
        set_simple(indi, "OCCU", args.occu)
        changes.append("occupation")
    if args.add_note:
        add_note(indi, args.add_note)
        changes.append("note")
    if not changes:
        print(json.dumps({"error": "nothing to set"}, ensure_ascii=False))
        return 1
    add_changelog(indi, "set " + ", ".join(changes))
    _renumber(indi, 0)
    res = write_out(tree, args.file, f"set {xid}: {', '.join(changes)}")
    res["id"] = xid
    res["name"] = tree.name(indi)
    print(json.dumps(res, ensure_ascii=False))
    return 0


def _ensure_person_fam_link(indi, tag, fid):
    """Ensure INDI has a FAMS/FAMC pointer to fid (no duplicates)."""
    for c in indi.children_by(tag):
        if gedcom.Tree.norm_id(c.value) == fid:
            return
    indi.children.append(Node(1, tag, None, fid))


def cmd_link_spouses(args):
    tree = load_or_die(args.file)
    aid = find_one(tree, args.a)
    bid = find_one(tree, args.b)
    if aid == bid:
        print(json.dumps({"error": "cannot marry a person to themselves"},
                         ensure_ascii=False))
        return 1
    a = tree.people[aid]
    b = tree.people[bid]
    fid = find_couple_family(tree, aid, bid)
    if fid is not None:
        fam = tree.families[fid]
    else:
        # Reuse a family that already has one of the pair with the other slot
        # empty, rather than creating a duplicate.
        pfid, empty_role = find_partial_family(tree, aid, bid)
        if pfid is not None:
            fid = pfid
            fam = tree.families[fid]
            husb, wife = _fam_spouses(tree, fam)
            missing = aid if aid not in (husb, wife) else bid
            fam.children.append(Node(1, empty_role, None, missing))
        else:
            fid = _next_id(existing_xrefs(tree), "F")
            fam = Node(0, "FAM", fid, "")
            husb, wife = _assign_husb_wife(tree, aid, bid)
            fam.children.append(Node(1, "HUSB", None, husb))
            fam.children.append(Node(1, "WIFE", None, wife))
            _insert_record(tree, fam)
            tree.families[fid] = fam
    if args.marr_date or args.marr_place:
        set_event(fam, "MARR", args.marr_date, args.marr_place)
    _ensure_person_fam_link(a, "FAMS", fid)
    _ensure_person_fam_link(b, "FAMS", fid)
    _renumber(fam, 0)
    _renumber(a, 0)
    _renumber(b, 0)
    res = write_out(tree, args.file, f"link spouses {aid}+{bid} -> {fid}")
    res["family"] = fid
    print(json.dumps(res, ensure_ascii=False))
    return 0


def cmd_link_child(args):
    tree = load_or_die(args.file)
    cid = find_one(tree, args.child)
    parents = [find_one(tree, p) for p in args.parent]
    if not parents:
        print(json.dumps({"error": "need at least one --parent"},
                         ensure_ascii=False))
        return 1
    # Find or create a family for the parents.
    fid = None
    if len(parents) == 2:
        fid = find_couple_family(tree, parents[0], parents[1])
    if fid is None:
        # Look for existing families where all given parents are spouses.
        candidates = []
        for pfid, fam in tree.families.items():
            husb, wife = _fam_spouses(tree, fam)
            spouses = {husb, wife}
            if all(p in spouses for p in parents):
                candidates.append(pfid)
        if len(candidates) > 1:
            # A single parent with several marriages — refuse to guess.
            fams = []
            for c in candidates:
                h, w = _fam_spouses(tree, tree.families[c])
                fams.append({"family": c,
                             "husb": h, "wife": w})
            print(json.dumps(
                {"error": "parent belongs to several families; specify both "
                          "parents or the target family",
                 "candidates": fams}, ensure_ascii=False))
            return 1
        if candidates:
            fid = candidates[0]
    if fid is None:
        fid = _next_id(existing_xrefs(tree), "F")
        fam = Node(0, "FAM", fid, "")
        # Assign parents to HUSB/WIFE by sex.
        husb = wife = None
        for pid in parents:
            sex = (tree.people[pid].value_of("SEX") or "").upper()
            if sex == "M" and husb is None:
                husb = pid
            elif sex == "F" and wife is None:
                wife = pid
        # Fill remaining slots by order.
        for pid in parents:
            if pid not in (husb, wife):
                if husb is None:
                    husb = pid
                elif wife is None:
                    wife = pid
        if husb:
            fam.children.append(Node(1, "HUSB", None, husb))
        if wife:
            fam.children.append(Node(1, "WIFE", None, wife))
        _insert_record(tree, fam)
        tree.families[fid] = fam
    else:
        fam = tree.families[fid]
    # Add CHIL on the family (no duplicates) and FAMC on the child.
    if not any(tree.norm_id(c.value) == cid for c in fam.children_by("CHIL")):
        fam.children.append(Node(1, "CHIL", None, cid))
    _ensure_person_fam_link(tree.people[cid], "FAMC", fid)
    # Ensure parents have FAMS.
    for pid in parents:
        _ensure_person_fam_link(tree.people[pid], "FAMS", fid)
        _renumber(tree.people[pid], 0)
    _renumber(fam, 0)
    _renumber(tree.people[cid], 0)
    res = write_out(tree, args.file, f"link child {cid} -> {fid}")
    res["family"] = fid
    print(json.dumps(res, ensure_ascii=False))
    return 0


def cmd_unlink_child(args):
    tree = load_or_die(args.file)
    cid = find_one(tree, args.child)
    fid = gedcom.Tree.norm_id(args.family)
    fam = tree.families.get(fid)
    if not fam:
        print(json.dumps({"error": f"no family {args.family}"},
                         ensure_ascii=False))
        return 1
    fam.children = [c for c in fam.children
                    if not (c.tag == "CHIL" and tree.norm_id(c.value) == cid)]
    child = tree.people[cid]
    child.children = [c for c in child.children
                      if not (c.tag == "FAMC" and tree.norm_id(c.value) == fid)]
    _renumber(fam, 0)
    _renumber(child, 0)
    res = write_out(tree, args.file, f"unlink child {cid} from {fid}")
    print(json.dumps(res, ensure_ascii=False))
    return 0


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def build_parser():
    p = argparse.ArgumentParser(description="Create/enrich GEDCOM files (stdlib).")
    p.add_argument("file")
    sub = p.add_subparsers(dest="command", required=True)

    pi = sub.add_parser("init", help="create an empty tree")
    pi.add_argument("--name", default=None)
    pi.add_argument("--force", action="store_true")
    pi.set_defaults(func=cmd_init)

    pa = sub.add_parser("add-person", help="add a new INDI")
    pa.add_argument("--given", default="")
    pa.add_argument("--surname", default="")
    pa.add_argument("--sex", default=None)
    pa.add_argument("--birt-date", dest="birt_date", default=None)
    pa.add_argument("--birt-place", dest="birt_place", default=None)
    pa.add_argument("--deat-date", dest="deat_date", default=None)
    pa.add_argument("--deat-place", dest="deat_place", default=None)
    pa.add_argument("--occu", default=None)
    pa.add_argument("--note", default=None)
    pa.set_defaults(func=cmd_add_person)

    ps = sub.add_parser("set", help="set facts/events on a person")
    ps.add_argument("id")
    ps.add_argument("--name-given", dest="name_given", default=None)
    ps.add_argument("--name-surname", dest="name_surname", default=None)
    ps.add_argument("--sex", default=None)
    ps.add_argument("--birt-date", dest="birt_date", default=None)
    ps.add_argument("--birt-place", dest="birt_place", default=None)
    ps.add_argument("--deat-date", dest="deat_date", default=None)
    ps.add_argument("--deat-place", dest="deat_place", default=None)
    ps.add_argument("--occu", default=None)
    ps.add_argument("--add-note", dest="add_note", default=None)
    ps.set_defaults(func=cmd_set)

    pl = sub.add_parser("link", help="link relationships")
    lsub = pl.add_subparsers(dest="link_kind", required=True)
    ls = lsub.add_parser("spouses")
    ls.add_argument("a")
    ls.add_argument("b")
    ls.add_argument("--marr-date", dest="marr_date", default=None)
    ls.add_argument("--marr-place", dest="marr_place", default=None)
    ls.set_defaults(func=cmd_link_spouses)
    lc = lsub.add_parser("child")
    lc.add_argument("child")
    lc.add_argument("--parent", action="append", default=[])
    lc.set_defaults(func=cmd_link_child)

    pu = sub.add_parser("unlink", help="remove a relationship link")
    usub = pu.add_subparsers(dest="unlink_kind", required=True)
    uc = usub.add_parser("child")
    uc.add_argument("child")
    uc.add_argument("--family", required=True)
    uc.set_defaults(func=cmd_unlink_child)

    return p


def main(argv):
    parser = build_parser()
    args = parser.parse_args(argv[1:])
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
