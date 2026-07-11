---
name: gedcom-tree
description: >
  Build a self-contained, interactive HTML family-tree viewer from a GEDCOM
  (.ged) file. Use whenever the user wants to *see* or *browse* the tree —
  дерево, древо, посмотреть дерево, интерактивное дерево, схема родословной,
  визуальное дерево, как в MyHeritage. Produces one offline HTML file that
  centres on a person, shows ancestors above and descendants below, and lets
  you click any card to re-centre, pan, zoom and search by name. Each card has
  an ⓘ badge that opens a side panel with the person's full detail — notes,
  sources with clickable links, documents/scans, residences and occupations.
  Handles UTF-8/Cyrillic and MyHeritage exports. Pure stdlib Python via bash — no
  Gramps, no Docker, no dependencies, no CDN.
license: MIT
compatibility: >
  Works with any agent that provides a bash / code-execution tool. Generates HTML
  with the bundled scripts/tree.py (Python 3 standard library only); it bundles
  its own copy of the parser, so it also runs standalone.
metadata:
  origin: genealogy-skills
---

# GEDCOM Tree Viewer

Turn a GEDCOM file into a single, self-contained **interactive tree viewer** —
the "покажи дерево" mode. Load it when the user wants to *look at* or *navigate*
the tree («покажи дерево», «древо», «интерактивное дерево», «схема
родословной», «как в MyHeritage»).

Pick the right skill:

- **`gedcom-tree`** — a visual, clickable chart of who-descends-from-whom.
- **`gedcom-report`** — analytics dashboard (charts, name clouds, statistics).
- **`gedcom-reader`** — answer questions in words, or read/edit/build the file.

## Finding the file

If the user hasn't given a path, glob for `**/*.ged`; one match → confirm and
use it, several → ask which, none → ask for the path. (Same rule as the other
GEDCOM skills.)

## Generating the viewer

Run the bundled generator with `bash` (set `PYTHONIOENCODING=utf-8` so Cyrillic
is handled correctly):

```bash
PYTHONIOENCODING=utf-8 python3 <skill-dir>/scripts/tree.py <file.ged> [output.html] [--focus <id|name>] [--private]
```

`<skill-dir>` is this skill's own directory wherever it is installed (e.g.
`.opencode/skills/gedcom-tree`, `~/.claude/skills/gedcom-tree`).

- Omit `output.html` → written next to the `.ged` file as `<name>.tree.html`.
- `--focus` sets the starting person by `@Ixx@` id **or a unique name fragment**.
  An ambiguous name is rejected with the list of matches — show it and ask.
- With no `--focus`, the viewer opens on the **most-connected** person (the one
  with the largest surrounding family), which is usually a sensible centre.
- `--private` strips contact details (phone, email, street address) of people
  with **no recorded death date** (treated as possibly living), so the exported
  HTML doesn't leak personal contact info. Use it when sharing the file.
- The script prints a small JSON summary (output path, people, families, the
  chosen focus id/name) — use it to tell the user what was built.
- It ships its own copy of the parser (`scripts/gedcom.py`) and also falls back
  to the `gedcom-reader` skill's copy when installed side by side, so it works
  standalone.

After generating, tell the user the path and that they can open it by
double-clicking, e.g.:

> Готово — интерактивное дерево сохранено рядом с файлом: `…/tree.tree.html`.
> Откройте его двойным щелчком. Кликните по любому человеку, чтобы поставить
> его в центр; значок ⓘ на карточке открывает панель с подробностями (заметки,
> источники, ссылки на документы). Тяните мышью, чтобы двигать, колесо —
> масштаб, сверху — поиск по имени.

## What the viewer does

- **Focus person in the centre** (highlighted gold), **ancestors fan out above**
  (up to N generations) and **descendants below** (up to M generations), with
  spouses drawn beside each person and couples joined to their children.
- **Click any card → that person becomes the new centre.** This is how you walk
  the whole tree, however large — only a neighbourhood is drawn at a time, so it
  stays fast and readable even for hundreds of people.
- **Pan** by dragging the background, **zoom** with the wheel or the +/−/fit
  buttons.
- **Search** by name (top-right); clicking a result re-centres on that person.
- **Generation depth** is adjustable live with the «Предки» / «Потомки»
  selectors (0–6 each).
- **Cards** are coloured by sex (blue = male, pink = female, grey = unknown) and
  show the name and life years; hover shows a tooltip with birth place and
  occupation when present.
- **Detail panel:** each card with extra data shows a small **ⓘ badge**; clicking
  it opens a side panel with the person's full record — facts (birth/death with
  cause), occupations, residences, **notes** (with PROVEN/PROBABLE/… status
  chips, and a foldaway changelog), **sources** (author/title + clickable
  archive links), **documents & scans** (note-embedded `materials/skany/*.png`
  paths and URLs become links), and clickable **relatives** to jump around. The
  panel is keyboard-friendly (Esc closes). Clicking the card itself still
  re-centres, as before.

## Offline behaviour

The HTML is **fully self-contained and offline** — no CDN, no external scripts,
no fonts to fetch. The whole chart is drawn with inline SVG/DOM and a small
vanilla-JS script embedded in the file. It opens with a double-click and works
with no internet at all.

## Notes

- Universal: works on any `.ged`, not just one tree. Latin and Cyrillic both fine.
- People with an empty given name show just their surname — that's a gap in the
  source data, not a viewer bug. Fix it with `gedcom-reader` if desired.
- MyHeritage extension tags (`_UID`, `RIN`, …) and `CONC`-split UTF-8 are handled
  by the shared parser.
- Regenerate after editing the tree to refresh the view.
- If Cyrillic looks like `Ð…` mojibake, you forgot `PYTHONIOENCODING=utf-8`.
- Loops or unusual multi-family links are handled defensively (each person is
  drawn once per branch), so the layout won't run away on messy data.
