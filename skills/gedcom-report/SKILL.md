---
name: gedcom-report
description: >
  Build a self-contained HTML analytics dashboard from a GEDCOM (.ged) family
  tree. Use whenever the user asks for a report, analytics, dashboard,
  statistics, or a visualization of their tree — отчёт, аналитика, дашборд,
  статистика, визуализация, облако имён, красивый отчёт по дереву. Produces one
  offline-friendly HTML file with charts, name clouds, a birthday heatmap, a
  timeline and a data-quality check. Handles UTF-8/Cyrillic and MyHeritage
  exports. Pure stdlib Python via bash — no Gramps, no Docker, no dependencies.
license: MIT
compatibility: >
  Works with any agent that provides a bash / code-execution tool. Generates HTML
  with the bundled scripts/report.py (Python 3 standard library only); it bundles
  its own copy of the parser, so it also runs standalone.
metadata:
  origin: genealogy-skills
---

# GEDCOM Report

Turn a GEDCOM file into a single, self-contained **HTML dashboard**. This is a
separate mode from reading/editing: load it when the user asks for a *report*,
*analytics*, *dashboard*, *statistics*, or a *visualization* of their tree
(«сделай отчёт», «аналитику», «дашборд», «облако имён», «красивый отчёт по
дереву»). For plain questions about people or relationships, use `gedcom-reader`
instead.

## Finding the file

If the user hasn't given a path, glob for `**/*.ged`; one match → confirm and
use it, several → ask which, none → ask for the path. (Same rule as
`gedcom-reader`.)

## Generating the report

Run the bundled generator with `bash` (set `PYTHONIOENCODING=utf-8` so Cyrillic
is handled correctly):

```bash
PYTHONIOENCODING=utf-8 python3 <skill-dir>/scripts/report.py <file.ged> [output.html] [--private | --share] [--lang ru|en] [--manifest scans.json [--verify-hash]]
```

`<skill-dir>` is this skill's own directory wherever it is installed (e.g.
`.opencode/skills/gedcom-report`, `~/.claude/skills/gedcom-report`).

- If you omit `output.html`, the report is written next to the `.ged` file as
  `<name>.report.html`.
- **Privacy (mutually exclusive), for sharing the dashboard:**
  - `--private` keeps names/surnames and aggregate counts but excludes exact
    birthdays (heatmap), places, named lifespans, and family-event/timeline
    entries of **possibly-living** people. A banner states it is **not anonymous**.
  - `--share` omits possibly-living and unknown-status people entirely; every
    statistic is recomputed over the historical subset and the source filename is
    hidden. Generation **aborts** if a payload audit finds protected data leaked.
    Use this to publish the dashboard publicly.
- `--lang ru|en` sets the interface language; when omitted it is **auto-detected**
  from the names (any Cyrillic → Russian, otherwise English). Only the dashboard's
  own labels are translated — the data itself is shown as-is.
- `--manifest scans.json` (optional, ignored in `--share`) verifies every local
  document/scan referenced in the tree against a sidecar JSON manifest and adds a
  small integrity summary (verified / missing / size-mismatch / unmanifested).
  Add `--verify-hash` to also check SHA-256. The manifest lists `{path, size,
  sha256}` relative to a `base`; absolute paths and parent-directory escapes are
  rejected, and external `http(s)` URLs are reported as external, not missing.
- The script prints a small JSON summary (people, families, M/F, year range,
  generations) — use it to tell the user what was built.
- It ships its own copy of the parser (`scripts/gedcom.py`) and also falls back
  to the `gedcom-reader` skill's copy when installed side by side, so it works
  standalone.

After generating, tell the user the path and that they can open it by
double-clicking, e.g.:

> Готово — отчёт сохранён рядом с файлом: `…/tree.report.html`. Откройте его
> двойным щелчком в браузере. 445 человек, 156 семей, рождения 1840–2019,
> 7 поколений.

## What the dashboard contains

Thirteen sections, in this order:

1. **Обзор** — people, families, M/F, year span, generations, average lifespan,
   average children per family, distinct surnames.
2. **Пропорция полов** — donut M/F plus a stacked bar of M/F by birth decade.
3. **Облака имён** — separate frequency clouds for surnames and given names.
4. **Мода на имена по декадам** — the top given names of each decade.
5. **Рождения по десятилетиям** — birth histogram.
6. **Топ фамилий** — most common surnames.
7. **Календарь дней рождения** — a month × day heatmap.
8. **Долгожители** — longest lifespans (from paired birth/death years).
9. **Самые большие семьи** — families with the most children.
10. **Топ мест** — most frequent places across events.
11. **Связанные лица** — an ASSO/RELA summary: how many association links exist,
    how many people have them, how many associates fall **outside the pedigree**
    (no family of their own), broken pointers, and a by-relation breakdown. These
    are social/evidentiary links (witnesses, godparents, informants), **not**
    blood kinship, and are reported separately for exactly that reason.
12. **Лента событий** — a filterable timeline of births, marriages, deaths.
13. **Проверка качества данных** — missing dates/parents, isolated records and
    the structural completeness counts come from the shared parser **audit**
    (`gedcom.py … audit`), so the report and the reader agree. **Source coverage**
    is reported honestly at the fact level: the number of citations, how many
    genealogical facts have a source (cited / total), an overall coverage
    percentage, and a *coverage by fact type* table. A record-level `1 SOUR` on a
    person is counted separately and does **not** imply every fact is sourced.
    Date anomalies are flagged as *possible*, not errors, in the spirit of the
    GPS; the `QUAY` summary shows the citation assessments recorded in the file —
    explicitly **not** a GPS proof status.

## Offline behaviour

The HTML is self-contained. Bar/donut/stacked charts use **Chart.js from a CDN**;
each of them has a fallback data table underneath. The name clouds, heatmap and
timeline are rendered with plain SVG/CSS/DOM and need **no** network. So even
without internet the report stays fully informative — only the four Chart.js
graphs go blank, and their tables cover the same numbers.

## Notes

- Universal: works on any `.ged`, not just one tree. Latin and Cyrillic both fine.
- MyHeritage extension tags (`_UID`, `RIN`, …) and `CONC`-split UTF-8 are handled
  by the shared parser.
- Regenerate after editing the tree to refresh the dashboard.
- If Cyrillic looks like `Ð…` mojibake, you forgot `PYTHONIOENCODING=utf-8`.
