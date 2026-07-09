#!/usr/bin/env python3
"""Build a self-contained HTML analytics dashboard from a GEDCOM file.

Pure Python standard library. Reuses the parser from the sibling
`gedcom-reader` skill (scripts/gedcom.py) — no external dependencies, no
Gramps, no Docker. Cyrillic-safe (UTF-8) and tolerant of MyHeritage exports.

Usage:
    PYTHONIOENCODING=utf-8 python3 report.py <file.ged> [output.html]

If no output path is given, the report is written next to the .ged file as
``<name>.report.html``. Open it by double-clicking; it works offline (Chart.js
graphs need the CDN, but every section has a table/SVG fallback that renders
without a network connection).
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

MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}
MONTH_NAMES_RU = ["", "Янв", "Фев", "Мар", "Апр", "Май", "Июн",
                  "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"]
DAYS_IN_MONTH = [0, 31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

QUAY_LABELS = {
    "3": "Первичный (Proven)",
    "2": "Вторичный (Probable)",
    "1": "Сомнительный (Possible)",
    "0": "Ненадёжный (Unproven)",
}


# --------------------------------------------------------------------------- #
# Date helpers
# --------------------------------------------------------------------------- #

def year_of(date_str):
    """Extract a 4-digit year from a GEDCOM date; None if absent.

    Tolerates ABT/EST/BEF/AFT/CAL prefixes and ranges (picks the first year).
    """
    if not date_str:
        return None
    m = re.search(r"\b(\d{3,4})\b", date_str)
    if not m:
        return None
    y = int(m.group(1))
    if 1 <= y <= 2100:
        return y
    return None


def day_month_of(date_str):
    """Return (day, month) if the date has an explicit ``DD MON YYYY``, else None."""
    if not date_str:
        return None
    m = re.search(r"\b(\d{1,2})\s+([A-Za-z]{3})\b", date_str)
    if not m:
        return None
    day = int(m.group(1))
    mon = MONTHS.get(m.group(2).upper())
    if mon and 1 <= day <= DAYS_IN_MONTH[mon]:
        return (day, mon)
    return None


def decade_of(year):
    return (year // 10) * 10 if year is not None else None


# --------------------------------------------------------------------------- #
# Name helpers
# --------------------------------------------------------------------------- #

def given_surname(tree, indi):
    """Return (given_first_token, surname) for an individual.

    Delegates to the shared parser so stats and the report agree on names.
    """
    return tree.given_surname(indi)


# --------------------------------------------------------------------------- #
# Metric builders
# --------------------------------------------------------------------------- #

def build_metrics(tree):
    people = tree.people
    families = tree.families

    sex_counts = {"M": 0, "F": 0, "U": 0}
    surname_counts = {}
    given_counts = {"M": {}, "F": {}, "U": {}}
    birth_years = []
    birth_decades = {}
    sex_by_decade = {}          # decade -> {"M": n, "F": n}
    name_by_decade = {}         # decade -> {given: count}
    day_month_counts = {}       # (month, day) -> count
    lifespans = []              # {name, birth, death, age}
    anomalies = []
    no_birth = no_death = no_parents = isolated = 0
    quay_counts = {}
    sour_total = 0

    # Precompute parent/child family membership for isolation + parents check.
    for xid, indi in people.items():
        sex = (indi.value_of("SEX") or "U").upper()
        if sex not in sex_counts:
            sex = "U"
        sex_counts[sex] += 1

        first, surn = given_surname(tree, indi)
        if surn:
            surname_counts[surn] = surname_counts.get(surn, 0) + 1
        if first:
            given_counts[sex][first] = given_counts[sex].get(first, 0) + 1

        birth = tree.event(indi, "BIRT")
        death = tree.event(indi, "DEAT")
        by = year_of(birth["date"])
        dy = year_of(death["date"])

        if by is not None:
            birth_years.append(by)
            dec = decade_of(by)
            birth_decades[dec] = birth_decades.get(dec, 0) + 1
            sd = sex_by_decade.setdefault(dec, {"M": 0, "F": 0})
            if sex in sd:
                sd[sex] += 1
            if first:
                nd = name_by_decade.setdefault(dec, {})
                nd[first] = nd.get(first, 0) + 1
            dm = day_month_of(birth["date"])
            if dm:
                day, mon = dm
                key = f"{mon}-{day}"
                day_month_counts[key] = day_month_counts.get(key, 0) + 1

        if not birth["date"]:
            no_birth += 1
        if not death["date"]:
            no_death += 1

        # Lifespan.
        if by is not None and dy is not None:
            age = dy - by
            if 0 <= age <= 120:
                lifespans.append({
                    "name": tree.name(indi), "birth": by,
                    "death": dy, "age": age,
                })
            elif age < 0:
                anomalies.append(
                    f"{tree.name(indi)}: год смерти ({dy}) раньше рождения ({by})")

        # Sources / evidence quality.
        for s in indi.children_by("SOUR"):
            sour_total += 1
            q = s.value_of("QUAY")
            if q:
                quay_counts[q] = quay_counts.get(q, 0) + 1

        # Isolation & missing parents.
        has_famc = bool(indi.children_by("FAMC"))
        has_fams = bool(indi.children_by("FAMS"))
        if not has_famc:
            no_parents += 1
        if not has_famc and not has_fams:
            isolated += 1

    # Family-level metrics: children counts, mother-age anomalies, marriage vs birth.
    family_sizes = []
    total_children = 0
    for fid, fam in families.items():
        kids = fam.children_by("CHIL")
        n_kids = len(kids)
        total_children += n_kids
        husb = fam.value_of("HUSB")
        wife = fam.value_of("WIFE")
        hn = tree.name(people[tree.norm_id(husb)]) if husb and tree.norm_id(husb) in people else "?"
        wn = tree.name(people[tree.norm_id(wife)]) if wife and tree.norm_id(wife) in people else "?"
        if n_kids:
            family_sizes.append({"family": f"{hn} — {wn}", "children": n_kids})

        # Marriage before either spouse's birth.
        marr_y = year_of(tree.event(fam, "MARR")["date"])
        for ref, label in ((husb, hn), (wife, wn)):
            if ref and tree.norm_id(ref) in people:
                p = people[tree.norm_id(ref)]
                py = year_of(tree.event(p, "BIRT")["date"])
                if marr_y and py and marr_y < py:
                    anomalies.append(
                        f"{label}: брак ({marr_y}) раньше рождения ({py})")

        # Mother age at children's births.
        if wife and tree.norm_id(wife) in people:
            mother = people[tree.norm_id(wife)]
            my = year_of(tree.event(mother, "BIRT")["date"])
            if my:
                for ch in kids:
                    cid = tree.norm_id(ch.value)
                    if cid in people:
                        cy = year_of(tree.event(people[cid], "BIRT")["date"])
                        if cy:
                            age = cy - my
                            if age < 13:
                                anomalies.append(
                                    f"{wn}: возраст матери {age} при рождении "
                                    f"ребёнка ({cy})")
                            elif age > 55:
                                anomalies.append(
                                    f"{wn}: возраст матери {age} при рождении "
                                    f"ребёнка ({cy})")

    # Generation depth: BFS from roots (people without parents) downward.
    depth = generation_depth(tree)

    # -- assemble sortable / trimmed views -------------------------------- #
    top_surnames = sorted(surname_counts.items(), key=lambda kv: -kv[1])[:15]

    def top_names(d, n=40):
        return sorted(d.items(), key=lambda kv: -kv[1])[:n]

    cloud_surnames = [{"text": s, "count": c}
                      for s, c in sorted(surname_counts.items(),
                                         key=lambda kv: -kv[1])[:60]]
    all_given = {}
    for grp in ("M", "F", "U"):
        for k, v in given_counts[grp].items():
            all_given[k] = all_given.get(k, 0) + v
    cloud_given = [{"text": g, "count": c}
                   for g, c in sorted(all_given.items(),
                                      key=lambda kv: -kv[1])[:60]]

    decades_sorted = sorted(birth_decades)
    births_series = [{"decade": d, "count": birth_decades[d]}
                     for d in decades_sorted]
    sex_decade_series = [
        {"decade": d,
         "M": sex_by_decade.get(d, {}).get("M", 0),
         "F": sex_by_decade.get(d, {}).get("F", 0)}
        for d in decades_sorted
    ]
    name_trends = [
        {"decade": d,
         "names": [{"name": nm, "count": c}
                   for nm, c in top_names(name_by_decade.get(d, {}), 3)]}
        for d in decades_sorted if name_by_decade.get(d)
    ]

    longevity = sorted(lifespans, key=lambda x: -x["age"])[:15]
    biggest = sorted(family_sizes, key=lambda x: -x["children"])[:15]

    places = build_places(tree)

    timeline = build_timeline(tree)

    avg_life = round(sum(x["age"] for x in lifespans) / len(lifespans), 1) \
        if lifespans else None
    avg_children = round(total_children / len(families), 2) if families else None

    quality = {
        "no_birth": no_birth,
        "no_death": no_death,
        "no_parents": no_parents,
        "isolated": isolated,
        "anomalies": anomalies[:60],
        "anomaly_total": len(anomalies),
        "sources_total": sour_total,
        "quay": [{"level": QUAY_LABELS.get(k, f"QUAY {k}"), "count": v}
                 for k, v in sorted(quay_counts.items(), reverse=True)],
    }

    heatmap = [{"m": int(k.split("-")[0]), "d": int(k.split("-")[1]), "c": v}
               for k, v in day_month_counts.items()]

    overview = {
        "people": len(people),
        "families": len(families),
        "male": sex_counts["M"],
        "female": sex_counts["F"],
        "unknown": sex_counts["U"],
        "year_min": min(birth_years) if birth_years else None,
        "year_max": max(birth_years) if birth_years else None,
        "generations": depth,
        "avg_lifespan": avg_life,
        "avg_children": avg_children,
        "distinct_surnames": len(surname_counts),
    }

    header = tree.header
    meta = {
        "file": os.path.basename(tree.path),
        "gedcom_version": header.value_of("GEDC", "VERS") if header else "",
        "charset": header.value_of("CHAR") if header else "",
        "language": header.value_of("LANG") if header else "",
    }

    return {
        "meta": meta,
        "overview": overview,
        "sex": {"M": sex_counts["M"], "F": sex_counts["F"],
                "U": sex_counts["U"]},
        "sex_by_decade": sex_decade_series,
        "cloud_surnames": cloud_surnames,
        "cloud_given": cloud_given,
        "name_trends": name_trends,
        "births_by_decade": births_series,
        "top_surnames": [{"surname": s, "count": c} for s, c in top_surnames],
        "heatmap": heatmap,
        "longevity": longevity,
        "biggest_families": biggest,
        "places": places,
        "timeline": timeline,
        "quality": quality,
    }


def generation_depth(tree):
    """Longest chain of parent→child links (number of generations)."""
    memo = {}

    def depth(xid, seen):
        if xid in memo:
            return memo[xid]
        if xid in seen:
            return 0  # cycle guard
        seen = seen | {xid}
        best = 0
        for ch in tree.children_of(xid):
            best = max(best, depth(ch, seen))
        memo[xid] = best + 1
        return memo[xid]

    roots = [xid for xid in tree.people
             if not tree.parents_of(xid)]
    if not roots:
        roots = list(tree.people)
    return max((depth(r, set()) for r in roots), default=0)


def _norm_place(place):
    p = place.strip().rstrip(",").strip()
    return p


def build_places(tree):
    counts = {}
    for indi in tree.people.values():
        for tag in ("BIRT", "DEAT", "RESI", "BURI"):
            pl = tree.event(indi, tag)["place"]
            if pl:
                key = _norm_place(pl)
                if key:
                    counts[key] = counts.get(key, 0) + 1
    for fam in tree.families.values():
        pl = tree.event(fam, "MARR")["place"]
        if pl:
            key = _norm_place(pl)
            if key:
                counts[key] = counts.get(key, 0) + 1
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:15]
    return [{"place": p, "count": c} for p, c in top]


def build_timeline(tree):
    events = []
    for indi in tree.people.values():
        name = tree.name(indi)
        for tag, label in (("BIRT", "birth"), ("DEAT", "death")):
            ev = tree.event(indi, tag)
            y = year_of(ev["date"])
            if y is not None:
                events.append({"year": y, "type": label, "who": name,
                               "place": ev["place"]})
    for fam in tree.families.values():
        ev = tree.event(fam, "MARR")
        y = year_of(ev["date"])
        if y is None:
            continue
        h = fam.value_of("HUSB")
        w = fam.value_of("WIFE")
        hn = tree.name(tree.people[tree.norm_id(h)]) \
            if h and tree.norm_id(h) in tree.people else "?"
        wn = tree.name(tree.people[tree.norm_id(w)]) \
            if w and tree.norm_id(w) in tree.people else "?"
        events.append({"year": y, "type": "marriage",
                       "who": f"{hn} & {wn}", "place": ev["place"]})
    events.sort(key=lambda e: e["year"])
    return events


# --------------------------------------------------------------------------- #
# Render
# --------------------------------------------------------------------------- #

def render(metrics, template_path):
    with open(template_path, "r", encoding="utf-8") as fh:
        html = fh.read()
    data_json = json.dumps(metrics, ensure_ascii=False)
    # Guard against an accidental </script> inside data breaking the tag.
    data_json = data_json.replace("</", "<\\/")
    # The template ships a valid default (``/*__DATA__*/null``) so it parses on
    # its own; here we swap the whole marker for the real data.
    html = html.replace("/*__DATA__*/null", data_json)
    html = html.replace("<!--__TITLE__-->",
                        f"Родословная — {metrics['meta']['file']}")
    return html


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    path = argv[1]
    if not os.path.exists(path):
        print(f"file not found: {path}", file=sys.stderr)
        return 1
    if len(argv) > 2:
        out = argv[2]
    else:
        base = os.path.splitext(path)[0]
        out = base + ".report.html"

    tree = gedcom.Tree(path)
    metrics = build_metrics(tree)
    template = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "template.html")
    html = render(metrics, template)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(html)

    ov = metrics["overview"]
    print(json.dumps({
        "output": out,
        "people": ov["people"],
        "families": ov["families"],
        "male": ov["male"],
        "female": ov["female"],
        "years": [ov["year_min"], ov["year_max"]],
        "generations": ov["generations"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
