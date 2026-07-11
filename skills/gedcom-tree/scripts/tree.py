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
        [--focus <id|name>] [--private] [--lang ru|en]

If no output path is given, the viewer is written next to the .ged file as
``<name>.tree.html``. If no --focus is given, the most-connected person (the
one with the largest surrounding family) is chosen as the starting point.
``--private`` strips contact details (phone/email/street address) of people with
no recorded death date, so the exported HTML doesn't leak info about the living.
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


def build_graph(tree):
    """Compact JSON graph: people + families with spouse/child links.

    people: {id: {id, name, sex, birth, death, occ, place, fams:[], famc:[]}}
    families: {id: {id, husb, wife, chil:[], marr}}
    """
    people = {}
    for xid, indi in tree.people.items():
        birth = tree.event(indi, "BIRT")
        death = tree.event(indi, "DEAT")
        sex = (indi.value_of("SEX") or "").upper()
        if sex not in ("M", "F"):
            sex = "U"
        people[xid] = {
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
                     if c.value],
            "famc": [tree.norm_id(c.value) for c in indi.children_by("FAMC")
                     if c.value],
        }

    families = {}
    for fid, fam in tree.families.items():
        husb = fam.value_of("HUSB")
        wife = fam.value_of("WIFE")
        families[fid] = {
            "id": fid,
            "husb": tree.norm_id(husb) if husb else None,
            "wife": tree.norm_id(wife) if wife else None,
            "chil": [tree.norm_id(c.value) for c in fam.children_by("CHIL")
                     if c.value],
            "marr": year_of(tree.event(fam, "MARR")["date"]),
        }

    return people, families


def build_details(tree, private=False):
    """Rich per-person detail for the info panel: notes, sources, residences,
    events, links (URLs + scan paths), attached documents (OBJE/FILE), occupations.

    With ``private=True``, contact details (phone/email/street address) of people
    with no recorded death date (treated as possibly living) are stripped, so the
    exported HTML doesn't leak personal contact info about the living.
    """
    details = {}
    for xid, indi in tree.people.items():
        d = tree.person_full(indi)
        maybe_living = not (d.get("death") or {}).get("date")
        residences = []
        for r in d.get("residences", []):
            r = dict(r)
            if private and maybe_living:
                r["phone"] = ""
                r["email"] = ""
                r["address"] = ""  # keep coarse place, drop street/contacts
            residences.append(r)
        details[xid] = {
            "notes": d.get("notes", []),
            "sources": d.get("sources", []),
            "events": d.get("events", []),
            "occupations": d.get("occupations", []),
            "residences": residences,
            "links": d.get("links", {"urls": [], "scans": []}),
            "documents": d.get("documents", []),
            "birth": d.get("birth", {}),
            "death": d.get("death", {}),
            "parents": d.get("parents", []),
            "spouses": d.get("spouses", []),
            "children": d.get("children", []),
        }
    return details


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
    """Resolve a --focus argument (id or name fragment) to a person id."""
    if not query:
        return None, None
    hits = tree.find(query)
    if not hits:
        return None, f"no person matching '{query}'"
    if len(hits) > 1:
        names = ", ".join(f"{h} {tree.name(tree.people[h])}" for h in hits[:8])
        return None, f"ambiguous '{query}' — matches: {names}"
    return hits[0], None


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
    private = False
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
            private = True
        elif a == "--lang":
            i += 1
            lang = args[i] if i < len(args) else None
        elif a.startswith("--lang="):
            lang = a.split("=", 1)[1]
        else:
            positional.append(a)
        i += 1

    if lang is not None and lang not in I18N:
        print(json.dumps({"error": f"unknown --lang '{lang}' (use ru|en)"},
                         ensure_ascii=False), file=sys.stderr)
        return 1

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
    people, families = build_graph(tree)
    details = build_details(tree, private=private)

    focus, err = resolve_focus(tree, people, focus_query)
    if err:
        print(json.dumps({"error": err}, ensure_ascii=False), file=sys.stderr)
        return 1
    if not focus:
        focus = most_connected(tree, people, families)

    if not people:
        print(json.dumps({"error": "no individuals in file"},
                         ensure_ascii=False), file=sys.stderr)
        return 1

    if lang is None:
        lang = detect_lang(tree, people)
    strings = strings_for(lang)

    header = tree.header
    payload = {
        "meta": {
            "file": os.path.basename(tree.path),
            "charset": header.value_of("CHAR") if header else "",
        },
        "people": people,
        "families": families,
        "details": details,
        "focus": focus,
        "private": private,
        "lang": lang,
        "i18n": strings,
        "counts": {"people": len(people), "families": len(families)},
    }

    template = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "template.html")
    title = f"{strings['title']} — {payload['meta']['file']}"
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
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
