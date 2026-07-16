#!/usr/bin/env python3
"""Build a self-contained, interactive HTML family-tree viewer from a GEDCOM file.

Pure Python standard library. Reuses the parser from the sibling
`gedcom-reader` skill (scripts/gedcom.py) — no external dependencies, no
Gramps, no Docker. Cyrillic-safe (UTF-8) and tolerant of MyHeritage exports.

The viewer is a single HTML file that works fully offline: no CDN, no network.
It draws an interactive pedigree/descendant chart on an SVG canvas. Click any
person to re-center the tree on them; pan by dragging, zoom with the wheel or
the +/- buttons, and search by name. Cards are coloured by sex and show the
name plus life years.

Click any person to re-center; click the ``ⓘ`` badge on a card to open a side
panel with their full detail — notes, sources (with clickable links), documents
/scans, residences, occupations and quick links to relatives.

Usage:
    PYTHONIOENCODING=utf-8 python3 tree.py <file.ged> [output.html] \
        [--focus <id|name>] [--private | --share] [--lang ru|en]

If no output path is given, the viewer is written next to the .ged file as
``<name>.tree.html``. If no --focus is given, the most-connected person (the
one with the largest surrounding family) is chosen as the starting point.

Privacy (mutually exclusive):
- ``--private`` — an *identified* family view: names, year-level dates and the
  family graph remain, but sensitive details (exact dates, places, occupations,
  contacts, notes, sources, events, documents, links) of possibly-living people,
  and any marriage date of a family they belong to, are removed. NOT anonymous.
- ``--share`` — a fail-closed historical export: possibly-living and
  unknown-status people are omitted entirely (with every reference to them);
  details are empty; the source filename is not exposed. Generation aborts if a
  payload audit finds any protected data leaked through.

``--lang`` sets the interface language; when omitted it is auto-detected from the
names (Cyrillic -> Russian, otherwise English).
"""

import json
import os
import re
import sys

# Reuse the bundled GEDCOM parser. Prefer the copy shipped alongside this
# script; otherwise fall back to the sibling gedcom-reader skill (when all
# skills are installed side by side under one skills/ directory).
_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _here)
sys.path.insert(1, os.path.join(_here, "..", "..", "gedcom-reader", "scripts"))
import gedcom  # noqa: E402
import privacy  # noqa: E402


# --------------------------------------------------------------------------- #
# UI localization
# --------------------------------------------------------------------------- #
# The viewer's interface strings live here (Russian + English). The chosen set
# is injected into the page as `DATA.i18n`, and the template's JS reads keys from
# it instead of hard-coding text. `title`/`born`/`died` etc. carry no dynamic
# parts; the JS does any interpolation around them.
I18N = {
    "ru": {
        "title": "Древо",                 # window/header title prefix: "Древо — file"
        "people": "чел.",                 # "N чел. · M семей"
        "families": "семей",
        "search_ph": "Поиск по имени…",
        "zoom_in": "Приблизить",
        "zoom_out": "Отдалить",
        "fit": "Показать всё",
        "close": "Закрыть (Esc)",
        "ancestors": "Предки",
        "descendants": "Потомки",
        "focus": "в фокусе",
        "male": "муж.",
        "female": "жен.",
        "unknown": "?",
        "empty": "Нет данных для отображения.",
        "born_prefix": "р. ",             # "р. 1960"
        "died_prefix": "ум. ",            # "ум. 1974"
        "hint_center": "клик — в центр",
        "hint_center_info": "клик — в центр · ⓘ — подробнее",
        "sec_facts": "Факты",
        "fact_birth": "Рождение",
        "fact_death": "Смерть",
        "sec_occupations": "Занятия",
        "sec_residence": "Проживание",
        "sec_notes": "Заметки",
        "sec_sources": "Источники",
        "sec_documents": "Документы и ссылки",
        "sec_parents": "Родители",
        "sec_spouses": "Супруг(а)",
        "sec_children": "Дети",
        "changelog": "История изменений",  # "История изменений (N)"
        "recenter": "↺ В центр дерева",
        "role_father": "отец",
        "role_mother": "мать",
        "status_negative": "негативный результат",
        "status_version": "версия",
        "no_results": "Никого не найдено",
        "quay_note": "QUAY — оценка автора GEDCOM, а не статус "
                     "доказанности по GPS.",
        "privacy_private": "Приватный режим: удалены чувствительные данные "
                           "возможно живущих людей. Имена, годы и родственные "
                           "связи сохранены — файл не анонимен.",
        "privacy_share": "Режим публикации: возможно живущие и люди с "
                         "неизвестным статусом исключены из экспорта; заметки, "
                         "источники, документы и исходные идентификаторы не "
                         "включены.",
    },
    "en": {
        "title": "Tree",
        "people": "people",
        "families": "families",
        "search_ph": "Search by name…",
        "zoom_in": "Zoom in",
        "zoom_out": "Zoom out",
        "fit": "Fit to view",
        "close": "Close (Esc)",
        "ancestors": "Ancestors",
        "descendants": "Descendants",
        "focus": "focused",
        "male": "male",
        "female": "female",
        "unknown": "?",
        "empty": "No data to display.",
        "born_prefix": "b. ",
        "died_prefix": "d. ",
        "hint_center": "click — center",
        "hint_center_info": "click — center · ⓘ — details",
        "sec_facts": "Facts",
        "fact_birth": "Birth",
        "fact_death": "Death",
        "sec_occupations": "Occupations",
        "sec_residence": "Residence",
        "sec_notes": "Notes",
        "sec_sources": "Sources",
        "sec_documents": "Documents & links",
        "sec_parents": "Parents",
        "sec_spouses": "Spouse",
        "sec_children": "Children",
        "changelog": "Change log",
        "recenter": "↺ Center the tree",
        "role_father": "father",
        "role_mother": "mother",
        "status_negative": "negative result",
        "status_version": "hypothesis",
        "no_results": "No one found",
        "quay_note": "QUAY is the GEDCOM author's assessment, not a GPS "
                     "proof status.",
        "privacy_private": "Private mode: sensitive details of possibly-living "
                           "people were removed. Names, years and family "
                           "relationships remain — this file is not anonymous.",
        "privacy_share": "Share mode: possibly-living and unknown-status people "
                         "were omitted from the export; notes, sources, "
                         "documents and original identifiers are not included.",
    },
}

_CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")


def detect_lang(tree, people):
    """Guess the UI language from the tree's person names.

    If any name contains Cyrillic letters, use Russian; otherwise English.
    Used when no explicit --lang is given, so Cyrillic trees stay Russian and
    Latin-only trees come out in English.
    """
    for p in people.values():
        if _CYRILLIC_RE.search(p.get("name") or ""):
            return "ru"
    return "en"


def strings_for(lang):
    return I18N.get(lang, I18N["ru"])


def year_of(date_str):
    """Extract a 4-digit year from a GEDCOM date; None if absent."""
    if not date_str:
        return None
    m = re.search(r"\b(\d{3,4})\b", date_str)
    if not m:
        return None
    y = int(m.group(1))
    return y if 1 <= y <= 2100 else None


def build_graph(tree, ctx=None):
    """Compact JSON graph: people + families with spouse/child links.

    people: {id: {id, name, sex, birth, death, occ, place, fams:[], famc:[]}}
    families: {id: {id, husb, wife, chil:[], marr}}

    With a privacy ``ctx``:
    - share mode omits protected people entirely and drops references to them;
    - private mode keeps everyone but redacts protected people's exact dates,
      place, occupation, and any marriage date of a family they belong to.
    """
    mode = ctx.mode if ctx else "none"

    def included(xid):
        return ctx.include_person(xid) if ctx else True

    people = {}
    for xid, indi in tree.people.items():
        if not included(xid):
            continue
        birth = tree.event(indi, "BIRT")
        death = tree.event(indi, "DEAT")
        sex = (indi.value_of("SEX") or "").upper()
        if sex not in ("M", "F"):
            sex = "U"
        protected = ctx.is_protected(xid) if ctx else False
        entry = {
            "id": xid,
            "name": tree.name(indi),
            "sex": sex,
            "birth": year_of(birth["date"]),
            "death": year_of(death["date"]),
            "bdate": birth["date"] or "",
            "ddate": death["date"] or "",
            "place": (birth["place"] or "").strip(),
            "occ": (indi.value_of("OCCU") or "").strip(),
            "fams": [tree.norm_id(c.value) for c in indi.children_by("FAMS")
                     if c.value and included(tree.norm_id(c.value)) is not False],
            "famc": [tree.norm_id(c.value) for c in indi.children_by("FAMC")
                     if c.value],
        }
        if protected and mode == "private":
            # Keep name, sex, year-level dates and topology; drop the rest.
            entry["bdate"] = str(entry["birth"]) if entry["birth"] else ""
            entry["ddate"] = ""
            entry["death"] = None
            entry["place"] = ""
            entry["occ"] = ""
            ctx.record("dates"); ctx.record("places")
        people[xid] = entry

    families = {}
    for fid, fam in tree.families.items():
        husb = fam.value_of("HUSB")
        wife = fam.value_of("WIFE")
        husb_id = tree.norm_id(husb) if husb else None
        wife_id = tree.norm_id(wife) if wife else None
        chil = [tree.norm_id(c.value) for c in fam.children_by("CHIL")
                if c.value]
        members = [m for m in ([husb_id, wife_id] + chil) if m]
        if ctx:
            # Drop references to omitted people.
            if not included(husb_id):
                husb_id = None
            if not included(wife_id):
                wife_id = None
            chil = [c for c in chil if included(c)]
            remaining = [m for m in ([husb_id, wife_id] + chil) if m]
            if mode == "share" and len(remaining) < 1:
                ctx.omitted_families += 1
                continue
        marr = year_of(tree.event(fam, "MARR")["date"])
        if ctx and mode in ("private", "share"):
            # If any original member was protected, drop the marriage date.
            if any(ctx.is_protected(m) for m in members):
                if marr is not None:
                    ctx.record("family_events")
                marr = None
        families[fid] = {
            "id": fid,
            "husb": husb_id,
            "wife": wife_id,
            "chil": chil,
            "marr": marr,
        }

    return people, families


def _relatives_visible(rels, ctx):
    """Drop relatives that are omitted people (share mode)."""
    if not ctx:
        return rels
    return [r for r in rels if ctx.include_person(r.get("id"))]


def build_details(tree, private=False, ctx=None):
    """Rich per-person detail for the info panel: notes, sources, residences,
    events, links (URLs + scan paths), attached documents (OBJE/FILE), occupations.

    Privacy:
    - share mode returns an empty details map (the info panel is disabled);
    - private mode empties protected people's detail entirely, and for everyone
      strips contact fields, document/scan paths and URLs so the shared-family
      HTML doesn't leak machine paths or contacts;
    - the legacy ``private=True`` argument is still accepted and builds a private
      context when none is supplied.
    """
    if ctx is None and private:
        ctx = _LegacyPrivate(tree)
    mode = ctx.mode if ctx else "none"
    if mode == "share":
        return {}

    details = {}
    for xid, indi in tree.people.items():
        if ctx and not ctx.include_person(xid):
            continue
        protected = ctx.is_protected(xid) if ctx else False
        if protected and mode == "private":
            # Keep only relatives (names/topology already disclosed in graph).
            d = tree.person_full(indi)
            details[xid] = {
                "notes": [], "sources": [], "events": [], "occupations": [],
                "residences": [], "links": {"urls": [], "scans": []},
                "documents": [], "birth": {}, "death": {},
                "parents": _relatives_visible(d.get("parents", []), ctx),
                "spouses": _relatives_visible(d.get("spouses", []), ctx),
                "children": _relatives_visible(d.get("children", []), ctx),
            }
            ctx.record("notes"); ctx.record("dates")
            continue

        d = tree.person_full(indi)
        residences = []
        for r in d.get("residences", []):
            r = dict(r)
            if mode == "private":
                for k in ("phone", "email", "address"):
                    if r.get(k):
                        ctx.record("contacts")
                    r[k] = ""
            residences.append(r)
        sources = d.get("sources", [])
        links = d.get("links", {"urls": [], "scans": []})
        events = d.get("events", [])
        documents = d.get("documents", [])
        # Fact-level provenance: each fact with the sources attached to it, plus
        # the record-level sources kept separate (a person-level SOUR does not
        # implicitly support every fact).
        facts = tree.facts_of(indi, "INDI", xid)
        record_srcs = tree.record_sources(indi)
        if mode == "private":
            # Strip machine paths and URLs even for the deceased.
            sources = [dict(s, url="") for s in sources]
            record_srcs = [dict(s, url="") for s in record_srcs]
            facts = [dict(f, citations=[dict(c, url="") for c in f["citations"]])
                     for f in facts]
            events = [dict(e, url="") for e in events]
            links = {"urls": [], "scans": []}
            documents = []
        details[xid] = {
            "notes": d.get("notes", []),
            "sources": sources,
            "facts": facts,
            "record_sources": record_srcs,
            "events": events,
            "occupations": d.get("occupations", []),
            "residences": residences,
            "links": links,
            "documents": documents,
            "birth": d.get("birth", {}),
            "death": d.get("death", {}),
            "parents": _relatives_visible(d.get("parents", []), ctx),
            "spouses": _relatives_visible(d.get("spouses", []), ctx),
            "children": _relatives_visible(d.get("children", []), ctx),
        }
    return details


class _LegacyPrivate:
    """Adapter so build_details(private=True) still works without a context."""
    def __init__(self, tree):
        self._ctx = privacy.PrivacyContext(tree, "private")
        self.mode = "private"
    def include_person(self, xid):
        return True
    def is_protected(self, xid):
        return self._ctx.is_protected(xid)
    def record(self, category, n=1):
        self._ctx.record(category, n)


def most_connected(tree, people, families):
    """Pick a good default focus: person with the most immediate relatives."""
    best_id, best_score = None, -1
    for xid, p in people.items():
        score = 0
        for fid in p["famc"]:
            fam = families.get(fid)
            if fam:
                score += 1  # has parents
                score += sum(1 for c in fam["chil"] if c != xid)  # siblings
        for fid in p["fams"]:
            fam = families.get(fid)
            if fam:
                score += len(fam["chil"])  # children
                if fam["husb"] and fam["husb"] != xid:
                    score += 1
                if fam["wife"] and fam["wife"] != xid:
                    score += 1
        if score > best_score:
            best_id, best_score = xid, score
    return best_id or (next(iter(people)) if people else None)


def resolve_focus(tree, people, query):
    """Resolve a --focus argument (id or name fragment) to a person id.

    In share mode ``people`` already excludes protected people, so a focus that
    resolves to an omitted person is rejected with a clear message rather than
    silently choosing someone else.
    """
    if not query:
        return None, None
    hits = tree.find(query)
    if not hits:
        return None, f"no person matching '{query}'"
    if len(hits) > 1:
        names = ", ".join(f"{h} {tree.name(tree.people[h])}" for h in hits[:8])
        return None, f"ambiguous '{query}' — matches: {names}"
    xid = hits[0]
    if xid not in people:
        return None, (f"'{query}' resolves to a person omitted by privacy rules; "
                      f"choose a person included in the export")
    return xid, None


def render(payload, template_path, title):
    with open(template_path, "r", encoding="utf-8") as fh:
        html = fh.read()
    data_json = json.dumps(payload, ensure_ascii=False)
    data_json = data_json.replace("</", "<\\/")  # never break </script>
    html = html.replace("/*__DATA__*/null", data_json)
    html = html.replace("<!--__TITLE__-->", title)
    return html


def main(argv):
    args = argv[1:]
    if not args:
        print(__doc__)
        return 2

    focus_query = None
    mode = "none"
    lang = None            # None -> auto-detect from the data
    positional = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--focus":
            i += 1
            focus_query = args[i] if i < len(args) else None
        elif a.startswith("--focus="):
            focus_query = a.split("=", 1)[1]
        elif a == "--private":
            mode = "private"
        elif a == "--share":
            mode = "share"
        elif a == "--lang":
            i += 1
            lang = args[i] if i < len(args) else None
        elif a.startswith("--lang="):
            lang = a.split("=", 1)[1]
        elif a.startswith("--"):
            print(json.dumps({"error": f"unknown option '{a}'"},
                             ensure_ascii=False), file=sys.stderr)
            return 2
        else:
            positional.append(a)
        i += 1

    if "--private" in args and "--share" in args:
        print(json.dumps({"error": "--private and --share are mutually exclusive"},
                         ensure_ascii=False), file=sys.stderr)
        return 2
    if lang is not None and lang not in I18N:
        print(json.dumps({"error": f"unknown --lang '{lang}' (use ru|en)"},
                         ensure_ascii=False), file=sys.stderr)
        return 2

    if not positional:
        print(__doc__)
        return 2

    path = positional[0]
    if not os.path.exists(path):
        print(json.dumps({"error": f"file not found: {path}"},
                         ensure_ascii=False), file=sys.stderr)
        return 1
    if len(positional) > 1:
        out = positional[1]
    else:
        out = os.path.splitext(path)[0] + ".tree.html"

    tree = gedcom.Tree(path)
    ctx = privacy.PrivacyContext(tree, mode)
    if mode == "share":
        ctx.omitted_people = sum(1 for x in tree.people
                                 if not ctx.include_person(x))

    people, families = build_graph(tree, ctx)
    details = build_details(tree, ctx=ctx)

    focus, err = resolve_focus(tree, people, focus_query)
    if err:
        print(json.dumps({"error": err}, ensure_ascii=False), file=sys.stderr)
        return 1
    if not focus:
        focus = most_connected(tree, people, families)

    if not people:
        msg = ("all records were omitted by share privacy rules"
               if mode == "share" else "no individuals in file")
        print(json.dumps({"error": msg}, ensure_ascii=False), file=sys.stderr)
        return 1

    if lang is None:
        lang = detect_lang(tree, people)
    strings = strings_for(lang)

    header = tree.header
    # In share mode the source filename is not exposed.
    meta_file = "shared-tree" if mode == "share" else os.path.basename(tree.path)
    payload = {
        "meta": {
            "file": meta_file,
            "charset": header.value_of("CHAR") if header else "",
        },
        "people": people,
        "families": families,
        "details": details,
        "focus": focus,
        "private": mode == "private",
        "lang": lang,
        "i18n": strings,
        "counts": {"people": len(people), "families": len(families)},
    }

    # Fail-closed payload audit before writing HTML.
    protected_names, protected_ids = set(), set()
    if mode != "none":
        for xid, a in ctx.assessments.items():
            if a["class"] in privacy._PROTECTED:
                protected_ids.add(xid)
                protected_names.add(tree.name(tree.people[xid]))
    pa = privacy.audit_payload(payload, ctx, protected_names, protected_ids)
    payload["privacy"] = ctx.summary(pa)

    if mode == "share":
        leak = privacy.share_leak_total(pa)
        if leak:
            print(json.dumps({
                "error": "privacy audit failed — share export aborted",
                "privacy_mode": "share",
                "payload_audit": pa,
            }, ensure_ascii=False), file=sys.stderr)
            return 1

    template = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "template.html")
    title = f"{strings['title']} — {meta_file}"
    html = render(payload, template, title)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)

    print(json.dumps({
        "output": out,
        "people": len(people),
        "families": len(families),
        "focus": focus,
        "focus_name": people[focus]["name"],
        "lang": lang,
        "privacy_mode": mode,
        "omitted_people": ctx.omitted_people,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
