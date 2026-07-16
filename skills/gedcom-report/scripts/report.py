#!/usr/bin/env python3
"""Build a self-contained HTML analytics dashboard from a GEDCOM file.

Pure Python standard library. Reuses the parser from the sibling
`gedcom-reader` skill (scripts/gedcom.py) — no external dependencies, no
Gramps, no Docker. Cyrillic-safe (UTF-8) and tolerant of MyHeritage exports.

Usage:
    PYTHONIOENCODING=utf-8 python3 report.py <file.ged> [output.html] \
        [--private | --share] [--lang ru|en] \
        [--manifest scans.json [--verify-hash]]

If no output path is given, the report is written next to the .ged file as
``<name>.report.html``. Open it by double-clicking; it is fully offline — the
Chart.js library is vendored (scripts/vendor/chart.umd.min.js) and inlined into
the output, so no CDN or network connection is ever needed. Every chart also has
a data table/SVG fallback underneath.

Privacy (mutually exclusive):
- ``--private`` — keeps names/surnames and aggregate counts, but excludes exact
  birthdays (heatmap), places, named lifespans, and family-event/timeline
  entries of possibly-living people. NOT anonymous.
- ``--share`` — omits possibly-living and unknown-status people entirely; all
  statistics are recomputed over the historical subset and the source filename
  is not exposed. Aborts if a payload audit finds protected data leaked through.

``--lang`` sets the interface language; when omitted it is auto-detected from the
names (Cyrillic -> Russian, else English).
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

MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}
DAYS_IN_MONTH = [0, 31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

# --------------------------------------------------------------------------- #
# UI localization
# --------------------------------------------------------------------------- #
# Interface strings for the dashboard (Russian + English). The chosen set — plus
# the generator-side pieces below (month names, QUAY labels, anomaly messages,
# the page title) — is injected into the page as ``metrics.i18n`` and read by the
# template's JS instead of hard-coded text. Language is picked with ``--lang`` or
# auto-detected from the people's names.
#
# QUAY is a submitter-supplied citation assessment in older GEDCOM practice. It
# is NOT a GPS proof status and does not measure source independence or evidence
# quality — so the labels stay neutral ("QUAY 3 — submitter assessment"), not
# "Proven"/"Probable"/…
QUAY_LABELS = {
    "ru": {
        "3": "QUAY 3 — оценка автора",
        "2": "QUAY 2 — оценка автора",
        "1": "QUAY 1 — оценка автора",
        "0": "QUAY 0 — оценка автора",
    },
    "en": {
        "3": "QUAY 3 — submitter assessment",
        "2": "QUAY 2 — submitter assessment",
        "1": "QUAY 1 — submitter assessment",
        "0": "QUAY 0 — submitter assessment",
    },
}

MONTH_NAMES = {
    "ru": ["", "Янв", "Фев", "Мар", "Апр", "Май", "Июн",
           "Июл", "Авг", "Сен", "Окт", "Ноя", "Дек"],
    "en": ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
}

# Anomaly message templates (kept in the generator because the numbers are
# computed here). ``{...}`` placeholders are filled with .format().
ANOMALY = {
    "ru": {
        "death_before_birth": "{name}: год смерти ({dy}) раньше рождения ({by})",
        "marriage_before_birth": "{label}: брак ({marr_y}) раньше рождения ({py})",
        "mother_age": "{wn}: возраст матери {age} при рождении ребёнка ({cy})",
    },
    "en": {
        "death_before_birth": "{name}: death year ({dy}) is before birth ({by})",
        "marriage_before_birth": "{label}: marriage ({marr_y}) is before birth ({py})",
        "mother_age": "{wn}: mother's age {age} at child's birth ({cy})",
    },
}

I18N = {
    "ru": {
        "report_title": "Родословная",
        "show_as_table": "Показать данные таблицей",
        "no_data": "нет данных",
        "decade_suffix_x": "-е",     # "1900-е"
        # overview cards
        "ov_people": "Людей", "ov_families": "Семей",
        "ov_male": "Мужчин", "ov_female": "Женщин",
        "ov_birth_years": "Годы рождения", "ov_generations": "Поколений",
        "ov_avg_age": "Средний возраст", "ov_years_suffix": "лет",
        "ov_children_per_family": "Детей на семью",
        "ov_unique_surnames": "Уникальных фамилий",
        # sex section
        "sec_sex": "Пропорция полов",
        "sec_sex_hint": "мужчины / женщины и по поколениям",
        "sex_ratio": "Соотношение полов",
        "sex_by_gen": "Полы по поколениям",
        "male": "Мужчины", "female": "Женщины", "sex_unknown": "Не указан",
        "col_sex": "Пол", "col_count": "Кол-во", "col_decade": "Декада",
        "col_m": "М", "col_f": "Ж",
        # clouds
        "sec_clouds": "Облака имён", "sec_clouds_hint": "размер = частота",
        "surnames": "Фамилии", "given_names": "Имена",
        # trends
        "sec_trends": "Мода на имена по декадам",
        "sec_trends_hint": "топ-3 имени каждого десятилетия",
        "no_birth_dates": "нет данных о датах рождения",
        "col_decade2": "Десятилетие", "col_popular_names": "Популярные имена",
        # births
        "sec_births": "Рождения по десятилетиям",
        "births": "Рождений",
        # surnames chart
        "sec_top_surnames": "Топ фамилий",
        "col_surname": "Фамилия", "bearers": "Носителей",
        # heatmap
        "sec_birthday_cal": "Календарь дней рождения",
        "sec_birthday_cal_hint": "месяц × день",
        "less": "реже", "more": "чаще",
        # longevity
        "sec_longevity": "Долгожители",
        "sec_longevity_hint": "по продолжительности жизни",
        "no_lifespans": "нет пар дат рождения и смерти",
        "col_hash": "#", "col_name": "Имя", "col_years": "Годы",
        "col_age": "Возраст",
        # families
        "sec_big_families": "Самые большие семьи",
        "sec_big_families_hint": "по числу детей",
        "no_families_children": "нет семей с детьми",
        "col_parents": "Родители", "col_children": "Детей",
        # places
        "sec_top_places": "Топ мест",
        "col_place": "Место", "events": "Событий",
        # timeline
        "sec_timeline": "Лента событий",
        "sec_timeline_hint": "рождения, браки, смерти",
        "tl_all": "Все", "tl_births": "Рождения",
        "tl_marriages": "Браки", "tl_deaths": "Смерти",
        "no_events": "нет событий",
        # quality
        "sec_quality": "Проверка качества данных",
        "sec_quality_hint": "для дальнейшего исследования",
        "q_no_birth": "Без даты рождения", "q_no_death": "Без даты смерти",
        "q_no_parents": "Без родителей", "q_singletons": "Одиночные записи",
        "q_citations": "Ссылок на источники",
        "q_facts_cited": "Фактов с источником",
        "q_coverage": "Покрытие источниками",
        "q_coverage_by_tag": "Покрытие источниками по типам фактов",
        "q_record_level": "На уровне записи",
        "col_fact": "Факт", "col_cited": "С источником", "col_pct": "%",
        "q_possible_anomalies": "Возможных аномалий",
        "q_source_levels": "Оценки цитат в QUAY",
        "q_quay_note": "QUAY — это оценка, записанная автором GEDCOM. "
                       "Это не статус доказанности по GPS и не мера "
                       "независимости источников.",
        "col_level": "Уровень",
        "q_date_anomalies": "Возможные аномалии дат",
        "q_anomalies_help": "Это подсказки для проверки, а не ошибки — "
                            "данные могли быть внесены приблизительно.",
        "q_no_anomalies": "Явных аномалий дат не найдено",
        "privacy_private": "Приватный режим: точные даты рождения, места и "
                           "семейные события возможно живущих людей исключены. "
                           "Имена и фамилии сохранены — отчёт не анонимен.",
        "privacy_share": "Режим публикации: возможно живущие и люди с "
                         "неизвестным статусом исключены; показатели рассчитаны "
                         "по историческому подмножеству.",
        # associates (ASSO/RELA)
        "sec_associates": "Связанные лица",
        "sec_associates_hint": "свидетели, крёстные, информанты",
        "a_pairs": "Связей ASSO",
        "a_people": "Людей со связями",
        "a_non_pedigree": "Вне родословной",
        "a_unresolved": "Битых ссылок",
        "a_by_relation": "По типу связи",
        "a_note": "ASSO/RELA — это социальные и доказательные связи "
                  "(свидетель, крёстный, информант), а не кровное родство.",
        "col_relation": "Связь", "col_count": "Кол-во",
        "a_none": "Связей ASSO не найдено",
        # footer
        "footer": 'Сгенерировано скиллом <b>gedcom-report</b> · полностью '
                  'автономно, без интернета · библиотека Chart.js встроена в '
                  'файл, под каждым графиком есть таблица с теми же данными',
    },
    "en": {
        "report_title": "Family tree",
        "show_as_table": "Show data as a table",
        "no_data": "no data",
        "decade_suffix_x": "s",      # "1900s"
        "ov_people": "People", "ov_families": "Families",
        "ov_male": "Male", "ov_female": "Female",
        "ov_birth_years": "Birth years", "ov_generations": "Generations",
        "ov_avg_age": "Average age", "ov_years_suffix": "yrs",
        "ov_children_per_family": "Children per family",
        "ov_unique_surnames": "Unique surnames",
        "sec_sex": "Sex proportion",
        "sec_sex_hint": "male / female and by generation",
        "sex_ratio": "Sex ratio",
        "sex_by_gen": "Sex by generation",
        "male": "Male", "female": "Female", "sex_unknown": "Unspecified",
        "col_sex": "Sex", "col_count": "Count", "col_decade": "Decade",
        "col_m": "M", "col_f": "F",
        "sec_clouds": "Name clouds", "sec_clouds_hint": "size = frequency",
        "surnames": "Surnames", "given_names": "Given names",
        "sec_trends": "Name trends by decade",
        "sec_trends_hint": "top 3 names of each decade",
        "no_birth_dates": "no birth-date data",
        "col_decade2": "Decade", "col_popular_names": "Popular names",
        "sec_births": "Births by decade",
        "births": "Births",
        "sec_top_surnames": "Top surnames",
        "col_surname": "Surname", "bearers": "Bearers",
        "sec_birthday_cal": "Birthday calendar",
        "sec_birthday_cal_hint": "month × day",
        "less": "less", "more": "more",
        "sec_longevity": "Longest-lived",
        "sec_longevity_hint": "by lifespan",
        "no_lifespans": "no birth+death date pairs",
        "col_hash": "#", "col_name": "Name", "col_years": "Years",
        "col_age": "Age",
        "sec_big_families": "Largest families",
        "sec_big_families_hint": "by number of children",
        "no_families_children": "no families with children",
        "col_parents": "Parents", "col_children": "Children",
        "sec_top_places": "Top places",
        "col_place": "Place", "events": "Events",
        "sec_timeline": "Event timeline",
        "sec_timeline_hint": "births, marriages, deaths",
        "tl_all": "All", "tl_births": "Births",
        "tl_marriages": "Marriages", "tl_deaths": "Deaths",
        "no_events": "no events",
        "sec_quality": "Data quality check",
        "sec_quality_hint": "for further research",
        "q_no_birth": "No birth date", "q_no_death": "No death date",
        "q_no_parents": "No parents", "q_singletons": "Isolated records",
        "q_citations": "Source citations",
        "q_facts_cited": "Facts with a source",
        "q_coverage": "Source coverage",
        "q_coverage_by_tag": "Source coverage by fact type",
        "q_record_level": "Record-level",
        "col_fact": "Fact", "col_cited": "Cited", "col_pct": "%",
        "q_possible_anomalies": "Possible anomalies",
        "q_source_levels": "Citation assessments recorded in QUAY",
        "q_quay_note": "QUAY is an assessment recorded by the GEDCOM's author. "
                       "It is not a GPS proof status and does not measure source "
                       "independence.",
        "col_level": "Level",
        "q_date_anomalies": "Possible date anomalies",
        "q_anomalies_help": "These are hints to check, not errors — the data "
                            "may have been entered approximately.",
        "q_no_anomalies": "No obvious date anomalies found",
        "privacy_private": "Private mode: exact birthdays, places and family "
                           "events of possibly-living people are excluded. Names "
                           "and surnames remain — this report is not anonymous.",
        "privacy_share": "Share mode: possibly-living and unknown-status people "
                         "were omitted; the statistics cover the historical "
                         "subset only.",
        # associates (ASSO/RELA)
        "sec_associates": "Associated people",
        "sec_associates_hint": "witnesses, godparents, informants",
        "a_pairs": "ASSO links",
        "a_people": "People with links",
        "a_non_pedigree": "Outside the pedigree",
        "a_unresolved": "Broken pointers",
        "a_by_relation": "By relation",
        "a_note": "ASSO/RELA are social and evidentiary links (witness, "
                  "godparent, informant), not blood kinship.",
        "col_relation": "Relation", "col_count": "Count",
        "a_none": "No ASSO links found",
        "footer": 'Generated by the <b>gedcom-report</b> skill · fully offline, '
                  'no internet needed · the Chart.js library is embedded in the '
                  'file and every graph has a data table beneath it',
    },
}

_CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")


def detect_lang(tree):
    """Guess the UI language: Russian if any person's name has Cyrillic."""
    for indi in tree.people.values():
        if _CYRILLIC_RE.search(tree.name(indi) or ""):
            return "ru"
    return "en"


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

def _included(ctx, xid):
    return ctx.include_person(xid) if ctx else True


def _protected(ctx, xid):
    return ctx.is_protected(xid) if ctx else False


def build_metrics(tree, lang="ru", audit_result=None, ctx=None):
    mode = ctx.mode if ctx else "none"
    # In share mode only non-protected people/families are visible to the report.
    people = {x: i for x, i in tree.people.items() if _included(ctx, x)}
    families = {}
    for fid, fam in tree.families.items():
        members = []
        for role in ("HUSB", "WIFE"):
            ref = fam.value_of(role)
            if ref:
                members.append(tree.norm_id(ref))
        for c in fam.children_by("CHIL"):
            if c.value:
                members.append(tree.norm_id(c.value))
        if mode == "share":
            remaining = [m for m in members if _included(ctx, m)]
            if not remaining:
                if ctx:
                    ctx.omitted_families += 1
                continue
        families[fid] = fam
    anomaly_msg = ANOMALY.get(lang, ANOMALY["ru"])
    quay_labels = QUAY_LABELS.get(lang, QUAY_LABELS["ru"])
    # Structural completeness/quality counts come from the shared parser audit so
    # the report and the `gedcom.py audit` command never diverge.
    audit_result = audit_result or tree.audit()
    am = audit_result["metrics"]

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

    for xid, indi in people.items():
        # In private mode a protected (possibly-living) person still counts in
        # aggregates (sex, names, decade) but their exact birthday, place, named
        # lifespan/anomaly are suppressed.
        hide = (mode == "private" and _protected(ctx, xid))
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
            if not hide:
                dm = day_month_of(birth["date"])
                if dm:
                    day, mon = dm
                    key = f"{mon}-{day}"
                    day_month_counts[key] = day_month_counts.get(key, 0) + 1
            else:
                ctx.record("dates")

        # Lifespan (never applies to a protected person; guard anyway).
        if by is not None and dy is not None and not hide:
            age = dy - by
            if 0 <= age <= 120:
                lifespans.append({
                    "name": tree.name(indi), "birth": by,
                    "death": dy, "age": age,
                })
            elif age < 0:
                anomalies.append(anomaly_msg["death_before_birth"].format(
                    name=tree.name(indi), dy=dy, by=by))

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
                    anomalies.append(anomaly_msg["marriage_before_birth"].format(
                        label=label, marr_y=marr_y, py=py))

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
                            if age < 13 or age > 55:
                                anomalies.append(anomaly_msg["mother_age"].format(
                                    wn=wn, age=age, cy=cy))

    # Generation depth: BFS from roots (people without parents) downward.
    depth = generation_depth(tree, ctx)

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

    places = build_places(tree, ctx)

    associates = build_associates(tree, ctx)

    timeline = build_timeline(tree, ctx)

    avg_life = round(sum(x["age"] for x in lifespans) / len(lifespans), 1) \
        if lifespans else None
    avg_children = round(total_children / len(families), 2) if families else None

    quay_counts = am["source_quality"]
    quality = {
        "no_birth": am["people_without_birth"],
        "no_death": am["people_without_death"],
        "no_parents": am["people_without_parent_family"],
        "isolated": am["isolated_people"],
        "anomalies": anomalies[:60],
        "anomaly_total": len(anomalies),
        "quay": [{"level": quay_labels.get(k, f"QUAY {k}"), "count": quay_counts[k]}
                 for k in ("3", "2", "1", "0") if quay_counts.get(k)],
        "audit_errors": audit_result["summary"]["errors"],
        "audit_warnings": audit_result["summary"]["warnings"],
        # Fact-level source provenance (record-level vs fact-level distinction).
        "facts_total": am["facts_total"],
        "facts_cited": am["facts_cited"],
        "coverage_pct": am["coverage_pct"],
        "fact_citations": am["fact_citations"],
        "record_level_citations": am["record_level_citations"],
        "citations_total": am["fact_citations"] + am["record_level_citations"],
        "coverage_by_tag": am["coverage_by_tag"][:12],
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
    # Share mode does not expose the source filename.
    meta = {
        "file": "shared-tree" if mode == "share"
                else os.path.basename(tree.path),
        "gedcom_version": header.value_of("GEDC", "VERS") if header else "",
        "charset": header.value_of("CHAR") if header else "",
        "language": header.value_of("LANG") if header else "",
    }

    metrics = {
        "meta": meta,
        "lang": lang,
        "i18n": I18N.get(lang, I18N["ru"]),
        "months": MONTH_NAMES.get(lang, MONTH_NAMES["ru"]),
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
        "associates": associates,
        "timeline": timeline,
        "quality": quality,
    }
    if mode != "none":
        metrics["privacy"] = {"mode": mode}
    return metrics


def generation_depth(tree, ctx=None):
    """Longest chain of parent→child links (number of generations).

    In share mode, omitted people are not counted (the depth reflects the
    exported subset).
    """
    def inc(xid):
        return _included(ctx, xid) if ctx and ctx.mode == "share" else True

    memo = {}

    def depth(xid, seen):
        if xid in memo:
            return memo[xid]
        if xid in seen:
            return 0  # cycle guard
        seen = seen | {xid}
        best = 0
        for ch in tree.children_of(xid):
            if inc(ch):
                best = max(best, depth(ch, seen))
        memo[xid] = best + 1
        return memo[xid]

    roots = [xid for xid in tree.people
             if inc(xid) and not tree.parents_of(xid)]
    if not roots:
        roots = [x for x in tree.people if inc(x)]
    return max((depth(r, set()) for r in roots), default=0)


def _norm_place(place):
    p = place.strip().rstrip(",").strip()
    return p


def build_places(tree, ctx=None):
    def shown(xid):
        # Skip omitted people (share) and protected people's places (private).
        if not _included(ctx, xid):
            return False
        if ctx and ctx.mode == "private" and _protected(ctx, xid):
            return False
        return True

    counts = {}
    for xid, indi in tree.people.items():
        if not shown(xid):
            continue
        for tag in ("BIRT", "DEAT", "RESI", "BURI"):
            pl = tree.event(indi, tag)["place"]
            if pl:
                key = _norm_place(pl)
                if key:
                    counts[key] = counts.get(key, 0) + 1
    for fam in tree.families.values():
        h = fam.value_of("HUSB")
        w = fam.value_of("WIFE")
        members = [tree.norm_id(r) for r in (h, w) if r]
        if any(not shown(m) for m in members):
            continue
        pl = tree.event(fam, "MARR")["place"]
        if pl:
            key = _norm_place(pl)
            if key:
                counts[key] = counts.get(key, 0) + 1
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:15]
    return [{"place": p, "count": c} for p, c in top]


def build_associates(tree, ctx=None):
    """Summarise ASSO/RELA associations (witnesses, godparents, informants).

    Associations are social/evidentiary links, not pedigree edges, so they are
    reported separately. Counts pairs, breaks them down by relation label, notes
    unresolved pointers, and reports how many associate targets are non-pedigree
    persons (no FAMS/FAMC of their own). Any association touching an omitted or
    protected person is dropped so the summary never leaks a hidden individual.
    """
    def shown(xid):
        if not _included(ctx, xid):
            return False
        if ctx and ctx.mode == "private" and _protected(ctx, xid):
            return False
        return True

    index, unresolved = tree.association_index()
    pairs = 0
    by_relation = {}
    non_pedigree = set()
    people_with = set()
    for xid, entries in index.items():
        if not shown(xid):
            continue
        for e in entries:
            if e["direction"] != "outbound":
                continue
            oid = e["other_id"]
            if not shown(oid):
                continue
            pairs += 1
            people_with.add(xid)
            rel = (e["relation"] or "").strip() or "—"
            by_relation[rel] = by_relation.get(rel, 0) + 1
            other = tree.people.get(oid)
            if other is not None and not (
                other.children_by("FAMS") or other.children_by("FAMC")):
                non_pedigree.add(oid)

    unresolved_shown = [u for u in unresolved if shown(u["from_id"])]
    top = sorted(by_relation.items(), key=lambda kv: -kv[1])[:12]
    return {
        "pairs": pairs,
        "people_with": len(people_with),
        "non_pedigree": len(non_pedigree),
        "unresolved": len(unresolved_shown),
        "by_relation": [{"relation": r, "count": c} for r, c in top],
    }


def build_scan_check(tree, manifest_path, do_hash=False):
    """Verify every referenced local scan/document against a sidecar manifest.

    Returns a summary of how many referenced paths are verified / missing /
    mismatched / unmanifested, plus a short list of problems. Uses the shared
    parser helpers so the tree and report agree on the result.
    """
    manifest = gedcom.load_scan_manifest(manifest_path)
    states = {}
    problems = []
    for path in tree.all_document_paths():
        r = gedcom.verify_scan(manifest, path, do_hash=do_hash)
        states[r["state"]] = states.get(r["state"], 0) + 1
        if r["state"] in ("missing", "mismatch", "invalid-path"):
            problems.append(r)
    return {
        "manifest": os.path.basename(manifest_path),
        "hash_checked": bool(do_hash),
        "referenced": sum(states.values()),
        "states": states,
        "problems": problems[:50],
    }


def build_timeline(tree, ctx=None):
    def shown(xid):
        if not _included(ctx, xid):
            return False
        if ctx and ctx.mode == "private" and _protected(ctx, xid):
            return False
        return True

    events = []
    for xid, indi in tree.people.items():
        if not shown(xid):
            continue
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
        hid = tree.norm_id(h) if h else None
        wid = tree.norm_id(w) if w else None
        # A marriage with any protected/omitted partner is suppressed.
        if (hid and not shown(hid)) or (wid and not shown(wid)):
            continue
        hn = tree.name(tree.people[hid]) if hid in tree.people else "?"
        wn = tree.name(tree.people[wid]) if wid in tree.people else "?"
        events.append({"year": y, "type": "marriage",
                       "who": f"{hn} & {wn}", "place": ev["place"]})
    events.sort(key=lambda e: e["year"])
    return events


# --------------------------------------------------------------------------- #
# Render
# --------------------------------------------------------------------------- #

def _load_chartjs():
    """Return the vendored Chart.js UMD source (or '' if it is missing).

    The library is shipped inside the skill so the generated report is fully
    offline — no CDN. If the file is absent the report still works: the charts
    degrade to the data tables that sit under every canvas.
    """
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "vendor", "chart.umd.min.js")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


def render(metrics, template_path):
    with open(template_path, "r", encoding="utf-8") as fh:
        html = fh.read()
    data_json = json.dumps(metrics, ensure_ascii=False)
    # Guard against an accidental </script> inside data breaking the tag.
    data_json = data_json.replace("</", "<\\/")
    # The template ships a valid default (``/*__DATA__*/null``) so it parses on
    # its own; here we swap the whole marker for the real data.
    html = html.replace("/*__DATA__*/null", data_json)
    # Inline the vendored Chart.js so the file needs no network at all. Escape
    # any "</script" so a literal sequence in the library can't close the tag.
    chartjs = _load_chartjs().replace("</script", "<\\/script")
    html = html.replace("/*__CHARTJS__*/", chartjs)
    strings = metrics.get("i18n", I18N["ru"])
    title = f"{strings['report_title']} — {metrics['meta']['file']}"
    html = html.replace("<!--__TITLE__-->", title)
    return html


def main(argv):
    args = argv[1:]
    lang = None            # None -> auto-detect from the data
    mode = "none"
    manifest_path = None
    do_hash = False
    positional = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--lang":
            i += 1
            lang = args[i] if i < len(args) else None
        elif a.startswith("--lang="):
            lang = a.split("=", 1)[1]
        elif a == "--private":
            mode = "private"
        elif a == "--share":
            mode = "share"
        elif a == "--manifest":
            i += 1
            manifest_path = args[i] if i < len(args) else None
        elif a.startswith("--manifest="):
            manifest_path = a.split("=", 1)[1]
        elif a == "--verify-hash":
            do_hash = True
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
    if not positional:
        print(__doc__)
        return 2
    if lang is not None and lang not in I18N:
        print(f"unknown --lang '{lang}' (use ru|en)", file=sys.stderr)
        return 2

    path = positional[0]
    if not os.path.exists(path):
        print(f"file not found: {path}", file=sys.stderr)
        return 1
    if len(positional) > 1:
        out = positional[1]
    else:
        base = os.path.splitext(path)[0]
        out = base + ".report.html"

    tree = gedcom.Tree(path)
    if lang is None:
        lang = detect_lang(tree)
    ctx = privacy.PrivacyContext(tree, mode)
    if mode == "share":
        ctx.omitted_people = sum(1 for x in tree.people
                                 if not ctx.include_person(x))
    metrics = build_metrics(tree, lang=lang, ctx=ctx)

    # Optional scan-manifest integrity check. Only in identified/full views —
    # never in share mode (a shared file must not expose machine paths).
    if manifest_path and mode != "share":
        if not os.path.exists(manifest_path):
            print(f"manifest not found: {manifest_path}", file=sys.stderr)
            return 1
        metrics["scan_check"] = build_scan_check(tree, manifest_path, do_hash)

    # Fail-closed payload audit (share aborts on any protected leak).
    if mode != "none":
        protected_names, protected_ids = set(), set()
        for xid, a in ctx.assessments.items():
            if a["class"] in privacy._PROTECTED:
                protected_ids.add(xid)
                protected_names.add(tree.name(tree.people[xid]))
        pa = privacy.audit_payload(metrics, ctx, protected_names, protected_ids)
        metrics["privacy"] = ctx.summary(pa)
        if mode == "share" and privacy.share_leak_total(pa):
            print(json.dumps({
                "error": "privacy audit failed — share export aborted",
                "privacy_mode": "share",
                "payload_audit": pa,
            }, ensure_ascii=False), file=sys.stderr)
            return 1

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
        "lang": lang,
        "privacy_mode": mode,
        "omitted_people": ctx.omitted_people,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
