---
name: gedcom-reader
description: >
  Read, explore, and carefully edit GEDCOM (.ged) genealogy files. Use whenever
  the user mentions a .ged file, GEDCOM data, a family tree, ancestors,
  descendants, a pedigree/родословная, предки, потомки, or asks who someone's
  relatives are, how two people are related, or to correct/update a record.
  Handles UTF-8/Cyrillic files and MyHeritage exports. Pure stdlib Python via
  bash — no Gramps, no Docker, no external dependencies.
license: MIT
compatibility: >
  Works with any agent that provides file access plus a bash / code-execution
  tool. Large files are parsed and edited with the bundled scripts/gedcom.py and
  scripts/gedcom_write.py (Python 3 standard library only).
metadata:
  origin: genealogy-skills
---

# GEDCOM Reader

Explore, edit, **and build** GEDCOM 5.5 / 5.5.1 genealogy files. Three modes:

- **Read Mode** (default) — answer questions about people, families, dates, and
  relationships in warm, natural language.
- **Edit Mode** — carefully modify records with preview, confirmation, and a
  changelog note.
- **Build Mode** — create a tree from scratch or enrich it (add people, set
  facts, link relationships) using the dedicated write **tools** — see
  "Creating & enriching a tree" below.

Start in Read Mode unless the user explicitly asks to change or build the file.

## Finding the file

If the user hasn't given a path:

1. Glob for `**/*.ged` in the working directory.
2. One match → use it, but confirm: "I found `path/to/file.ged` — use that?"
3. Several matches → list them and ask which.
4. None → ask the user for the path.

## How to read a GEDCOM file

Pick the approach based on size:

- **Small files (a few dozen people)** → read the file directly with the `read`
  tool and interpret the structure yourself (see the `genealogy-research` skill's
  `references/gedcom-format.md` for the tag reference).
- **Large files (hundreds of people, e.g. a MyHeritage export)** → do **not**
  try to read the whole file into context. Use the bundled parser via `bash`.

### The bundled parser (scripts/gedcom.py)

A dependency-free Python 3 script. It decodes UTF-8 (Cyrillic-safe) and falls
back to cp1251/latin-1, and tolerates MyHeritage `CONC` splits and extension
tags (`_UID`, `_UPD`, `RIN`, `_MARNM`). It prints JSON, which you then turn into
natural-language prose.

Run it with `bash` (set `PYTHONIOENCODING=utf-8` so Cyrillic prints correctly):

```bash
PYTHONIOENCODING=utf-8 python3 <skill-dir>/scripts/gedcom.py <file.ged> <command> [args]
```

`<skill-dir>` is this skill's own directory (wherever the skill is installed,
e.g. `.claude/skills/gedcom-reader`, `.agents/skills/gedcom-reader`,
`.opencode/skills/gedcom-reader`, or `~/.claude/skills/gedcom-reader`).

Commands:

| Command | Purpose |
|---|---|
| `stats` | People/family counts, GEDCOM version, charset, language, top surnames |
| `person <id\|name>` | Full detail: name, dates, parents, spouses, children, notes, sources |
| `search <surname>` | All people whose name contains the fragment |
| `family <id>` | Spouses, marriage, children of a family record |
| `ancestors <id> [maxgen]` | Ancestors grouped by generation (default 6) |
| `descendants <id> [maxgen]` | Descendants grouped by generation (default 6) |
| `relationship <idA> <idB>` | Shortest kinship path between two people (parent, child and spouse each count as one step) |
| `timeline [surname]` | Births, marriages, deaths in one list (optionally filtered) |
| `list [limit]` | Brief listing of people (default 100) |

IDs accept `I1`, `@I1@`, `F3`, etc. `person`, `ancestors`, `descendants`,
`relationship` also accept a name fragment; if it matches several people the
script returns an `ambiguous` list — show it and ask which one.

Example:

```bash
PYTHONIOENCODING=utf-8 python3 <skill-dir>/scripts/gedcom.py family.ged relationship Suki Clay
```

## Read Mode

Answer as a knowledgeable family historian sitting beside the user.

Instead of dumping raw data like:

```
@I5@ Clayton Rufus Varnell (b. 14 NOV 1984)
@I6@ Nora Colleen Varnell (b. 27 FEB 1987)
```

write:

> Dennis and Lorraine have three children. **Clay** (Clayton Rufus), the
> eldest, was born on November 14, 1984, followed by **Nora Colleen** on
> February 27, 1987, and the youngest, **Jude** (Judith Elaine), on April 20,
> 1993 — all in Millhaven.

Principles:

- Introduce someone as "Clay (Clayton Rufus)" on first mention, then "Clay".
- Include dates and places when they add value; don't force them everywhere.
- Surface interesting NOTE details (occupations, biographical tidbits).
- Explain relationships plainly: "Dennis's half-brother Malcolm" beats
  "Malcolm Caine, son of Roderick Varnell and an unknown woman".
- When data is missing, say so honestly rather than guessing.

### Common queries

List/search people, trace relationships, build timelines, describe family
structure, compute simple statistics, summarise notes. Use the parser commands
above; combine several calls when needed.

### Output format

Default to natural-language prose. Give a markdown table, bullet list, or ASCII
pedigree only if the user asks or when a large result set is easier to scan
that way.

## Edit Mode

Switch here only when the user explicitly wants to modify the file — add people,
correct names/dates, link families, delete records. Editing genealogical
records is serious: a wrong edit propagates confusion through someone's
research, so this mode is deliberate.

### Workflow

1. **Understand the change.** Confirm exactly what to modify; ask if ambiguous.
2. **Preview in plain language.** For example:
   > I'll correct the surname on @I5@ from "Smyth" to "Smith". That changes
   > Clayton Rufus Smyth → Clayton Rufus Smith. Go ahead?
3. **Wait for confirmation.** Do not write until the user says yes.
4. **Apply the edit** with the `edit` tool at the text level: find the target
   record and change only the intended line(s).
5. **Add a changelog NOTE** to every modified record, indented one level under
   it:
   ```
   1 NOTE [CHANGELOG] 2026-07-08: Corrected surname from Smyth to Smith (source: baptism record St. Mary's 1842)
   ```
   Always include today's date, what changed from/to, and the source/reason
   (ask if not given, else write "per user correction").
6. **Sanity-check.** Re-run `python3 scripts/gedcom.py <file> stats` and confirm
   the counts still make sense and the file still parses.
7. **Report** what you changed.

### Safety rules

- **One logical change at a time.** Handle multiple edits sequentially with
  individual confirmations unless the user says "do all of these".
- **Never delete without explicit confirmation:** "This removes [person/family]
  from the file entirely. Are you sure?"
- **Back up before bulk edits.** Copy to `filename_backup_YYYYMMDD.ged` first and
  say so.
- **Preserve structure.** Don't reorder records or strip existing notes/custom
  tags unless asked. Keep the file's original charset and line endings.

## Creating & enriching a tree (Build Mode)

For **creating a tree from scratch** or **adding people, facts, and
relationships**, do NOT hand-edit the text — use the bundled writer. It allocates
free XREFs, keeps two-way family links consistent (FAMS/FAMC ↔ HUSB/WIFE/CHIL),
writes a valid HEAD/TRLR, makes a timestamped backup, and re-parses the file as a
sanity check. UTF-8 / Cyrillic is fully handled. Dates go in GEDCOM form
(`9 FEB 1960`, `ABT 1890`, `1962`).

### The portable way: `scripts/gedcom_write.py` (works in any agent)

This is the primary, agent-agnostic path — call it through `bash`, exactly like
the reader. It works in Claude Code, Codex, Claude Desktop (code execution),
opencode, and anywhere else:

```bash
W=<skill-dir>/scripts/gedcom_write.py
PYTHONIOENCODING=utf-8 python3 $W tree.ged init --name "My Family"
PYTHONIOENCODING=utf-8 python3 $W tree.ged add-person --given Иван --surname Петров --sex M --birt-date "9 FEB 1960"
PYTHONIOENCODING=utf-8 python3 $W tree.ged add-person --given Мария --surname Иванова --sex F --birt-date 1962
PYTHONIOENCODING=utf-8 python3 $W tree.ged link spouses "Иван Петров" "Мария Иванова" --marr-date 1983
PYTHONIOENCODING=utf-8 python3 $W tree.ged add-person --given Пётр --surname Петров --sex M --birt-date 1985
PYTHONIOENCODING=utf-8 python3 $W tree.ged link child "Пётр Петров" --parent "Иван Петров" --parent "Мария Иванова"
```

Sub-commands: `init`, `add-person`, `set`, `link spouses`, `link child`,
`unlink child`. Each prints a small JSON result (and the new `@Ixx@` for
`add-person`). A person is given by `@Ixx@` id **or a unique name fragment**; an
ambiguous name is rejected with the list of matches — show it and ask which.

### The convenient way: native tools (opencode only)

If you are running under **opencode** with this project's `.opencode/tools/`
loaded (installed by `./install.sh opencode`), the same operations are exposed as
native tools —
`gedcom_init`, `gedcom_add_person`, `gedcom_set`, `gedcom_link`
(`relation:"spouses"` / `relation:"child"`), `gedcom_unlink`. They are thin
wrappers around the script above; use them if available, otherwise fall back to
the `bash` script. **Do not assume these tools exist** — outside opencode they
won't, so default to `gedcom_write.py`.

Typical flow to build a small family: `init` → `add-person` for each person →
`link spouses` to marry the parents → `link child` to attach each child to both
parents → verify with the reader (`gedcom.py <file> stats` / `descendants <id>`).

### Build-Mode etiquette & limits

- **Confirm before writing**, same as Edit Mode — preview who/what you'll add.
- Prefer the writer over the `edit`/`write` file tools for structural changes;
  hand-editing risks broken back-references and duplicate XREFs.
- Enriching from research: after reading a document, use `set` to record the
  confirmed date/place and cite the source in the note.
- Every write leaves a `<file>.bak-YYYYMMDD-HHMMSS.ged`; mention it if useful.
- **Known limits:** `set` only *replaces or adds* a field — it can't clear one
  (passing an empty value is ignored); there is no "delete person" command
  (remove a person by hand-editing in Edit Mode, with confirmation). Same-sex or
  unknown-sex couples are supported, but HUSB/WIFE slots are then assigned by the
  order you pass the two people.

## Handling errors gracefully

- Cyrillic shows as `Ð...` mojibake → you forgot `PYTHONIOENCODING=utf-8`, or
  the file is cp1251; the parser auto-detects, but confirm the `charset` field
  from `stats`.
- A query returns nothing → say so and offer the surnames that *are* present:
  "No one by that surname. The file has: Varnell, Decker, Caine…"
- Relationship can't be traced → explain what's missing (no linking FAM record)
  rather than inventing a connection.
- MyHeritage extension tags (`_UID`, `RIN`, etc.) are noise — ignore them.
