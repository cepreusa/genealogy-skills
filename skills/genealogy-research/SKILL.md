---
name: genealogy-research
description: >
  Genealogy research assistant using the GPS (Genealogical Proof Standard)
  methodology. Use when analyzing historical documents (scans, photos, database
  screenshots), building or updating a family tree, managing an Obsidian vault
  of genealogical data, planning research strategy, reading handwritten records
  in any language/script, working with GEDCOM files, or identifying the next
  research steps. Triggers on ancestors, family history, parish records, vital
  records, census data, предки, метрики, родословная.
license: MIT
compatibility: >
  Works with any agent that provides file access, web fetch, and a bash /
  code-execution tool. Uses the bundled GEDCOM scripts (Python 3 standard
  library only).
metadata:
  origin: genealogy-skills
---

# Genealogy Research

## Role

Act as a genealogy research partner. The human provides documents (photos,
scans, database screenshots). Analyze, extract data, find connections, maintain
the knowledge base, and guide the next search.

For reading, exploring, or editing GEDCOM (`.ged`) files, use the companion
**gedcom-reader** skill (it has a dependency-free parser for large/Cyrillic
files). For the GEDCOM tag structure and how to map records into the Obsidian
vault, see [references/gedcom-format.md](references/gedcom-format.md).

## Methodology: GPS (Genealogical Proof Standard)

Genealogy has a formal, scientific standard of proof. The full reference —
the five pillars of the GPS, the Source/Information/Evidence model, FAN-cluster
research, negative evidence, and conflict resolution — is in
[references/gps-methodology.md](references/gps-methodology.md). **Read it and
apply it.** The essentials:

### Evidence Levels

Tag every non-trivial fact:
- **Proven** — meets the GPS: original + primary + direct evidence, conflicts resolved
- **Probable** — indirect evidence, matching time/place, one good source
- **Possible** — a hypothesis to test
- **Unproven** — insufficient data

### Source / Information / Evidence

Judge each finding on three independent axes (don't collapse into one word):
- **Source:** Original (register scan) > Derivative (index/transcription/database)
- **Information:** Primary (firsthand, at the time) > Secondary (later/hearsay)
- **Evidence:** Direct / Indirect / Negative

Best quality = original source · primary information · direct evidence. Indexes
contain errors — verify against scans when available.

### Planning Before Searching

Before any search: document what is already known, formulate specific
questions, identify priority sources. Start from an existing anchor (a year,
place, or parent) — if none exists, finding an anchor is the first task. Never
perform unsolicited searches without a plan.

**If there's no tree at all**, the first task isn't a search — it's a short
intake interview to capture the closest generations from the user's memory and
build a starting `.ged`. See [references/intake-interview.md](references/intake-interview.md).

### Negative Results

"Not found" is valuable data. If surname X has zero records in parish Y, that's
evidence, not a dead end. Always document what was searched, where, with what
parameters, and what was NOT found — and whether the record *should* have been
there or the index simply doesn't cover those years.

## Project Structure

```
<vault>/                 # e.g. my-family/
├── materials/           # Source documents (photos, scans, PDFs)
│   └── skany/          # Archive scans saved by the browser (never the project root)
├── Chronicles/          # Obsidian vault — knowledge base
│   ├── People/         # One file per person (YAML frontmatter)
│   ├── Places/         # Locations with coordinates, history, parishes/archives
│   ├── Documents/      # Document descriptions and transcriptions
│   ├── Events/         # Key events (migrations, wars, etc.)
│   └── Research/       # Research notes, line analyses, and search plans
└── PROCESS.md          # Research tracker (what's done, what's next)
```

`People`, `Places`, and `Research` are the working core (one file per person /
place / family line); add `Documents` and `Events` as material accumulates.
`PROCESS.md` is the long-term research tracker — pair it with a per-session
TodoWrite plan for the active work.

For Obsidian file templates (person, place, research line, search plan) and the
PROCESS.md format, see [references/vault-templates.md](references/vault-templates.md).

## Workflow Cycle

```
0. No tree yet? Run the intake interview first (intake-interview.md) → skeleton .ged
   ↓
1. Frame the question; check what the tree/vault already knows (the anchor)
   ↓
2. Plan sources (which archive/site, what parameters) — see databases-by-region.md
   ↓
3. Research in the browser (a browser MCP) — or the user provides a scan/screenshot
   ↓
4. Analyze: read the document (incl. handwriting), extract data, identify people
   ↓
5. Correlate & tag (Proven/Probable/Possible/Unproven); resolve conflicts
   ↓
6. Update the vault (People, Places, Research) + save scans to materials/skany/
   ↓
7. Log in PROCESS.md (including negative results); pick the next question
```

### Researching in the browser (a browser MCP)

Online archives are where most records live, so **driving a web browser is a
primary research tool**, used proactively when a task needs a document, scan, or
record online. This works through a **browser-automation MCP** — the tools that
let you `navigate`, `snapshot` and `screenshot` a page. [Playwright
MCP](https://github.com/microsoft/playwright-mcp) is the recommended one, but any
equivalent works.

**First, check whether you actually have such a tool.** Look at the tools
available to you for browser actions (names usually contain `browser_navigate`,
`browser_snapshot`, `browser_take_screenshot`, or similar — e.g. a Playwright
MCP).

- **If a browser MCP is available** — use it. Pattern: `navigate` → `snapshot`
  (read structure) → open the record → screenshot the scan area → transcribe
  (handwriting included).
- **If no browser tool is available** — don't silently give up and don't
  hallucinate records. Tell the user you can research archives directly if they
  connect a browser MCP, and give the one-line setup for Playwright MCP:
  - opencode: already wired by `install.sh opencode`.
  - Claude Desktop / Code: `claude mcp add playwright -- npx @playwright/mcp@latest`
  - other agents: register `npx @playwright/mcp@latest` as a local MCP server.
  Until then, fall back gracefully: ask the user to open the page and **paste a
  screenshot or the page text**, and read that.

- **Save scans into the vault**, not the project root:
  `<vault>/materials/skany/<meaningful_name>.png`.
- **Navigator mode:** government archives often block bots (self-signed
  certificates, e-ID login). When you cannot open/authenticate a site yourself,
  ask the user to open it *in the browser your MCP controls* (or paste the list /
  a screenshot); then navigate and read it. Never invent a record you did not see.

### Practical Tips

- **Screenshots > descriptions**: read tables and registers directly from images.
- **Download scans**: if an archive allows bulk download, get the whole volume
  and browse locally.
- **Log everything in PROCESS.md**: what was searched, where, parameters,
  found / not found.
- **Check neighboring parishes**: families often registered elsewhere (church
  closures, moves). Check a ~15 km radius, and mind that a village's parish may
  differ from the one expected.
- **Index ≠ content**: many archive search engines index only file *titles*
  (fond/opis/delo), not names inside registers — a "not found" there may mean
  the pages must be read by eye.

## Capabilities

**Can do well:**
- Read handwritten documents (19th-20th century) in Latin, Polish, Russian,
  German, French, English, and other European languages
- Analyze tables from genealogical databases (from screenshots)
- Build connections between scattered records (name/date/place matching)
- Identify indexing gaps and suggest alternative sources
- Maintain Obsidian knowledge base with cross-references
- Calculate birth dates from ages in documents
- Handle naming systems: patronymics, maiden names, declension, Russification,
  Latinization
- Work with GEDCOM format (see the gedcom-reader skill and
  [references/gedcom-format.md](references/gedcom-format.md))
- Generate maps with migration routes (Leaflet.js)

**Requires human:**
- Authenticating to gated archives (national e-ID / paid subscriptions) — then
  work in *navigator mode* (user opens the site in the agent's browser)
- Registering on sites, paying subscriptions
- Visiting archives in person, making phone calls, ordering copies

## Common Pitfalls

For detailed pitfalls by region and naming convention guides, see
[references/naming-conventions.md](references/naming-conventions.md) and
[references/common-pitfalls.md](references/common-pitfalls.md).

### Key Warnings

1. **Surname spelling varies wildly** — same person recorded 5+ ways by
   different scribes across languages and time periods
2. **Indexing gaps** — online databases don't cover all years. The year you
   need is often in the gap. Solution: find original scans or microfilms
3. **Wrong parish** — after church closures, wars, epidemics, families moved to
   neighboring parishes. If not found where expected, search 15 km radius
4. **Damaged scans** — 19th-century books often damaged by mold, water, fire.
   Multiple experts may read the same word differently. Trust indexers who
   worked with originals over AI scan analysis
5. **Calendar differences** — Julian vs. Gregorian calendar (Russia used Julian
   until 1918; add 12-13 days). Jewish records may use Hebrew calendar

## Databases by Region

For comprehensive database listings by country, see
[references/databases-by-region.md](references/databases-by-region.md).

### Quick Reference — Universal

| Service | What it contains |
|---------|-----------------|
| **FamilySearch** (familysearch.org) | Largest free database: vitals, censuses, immigration |
| **Ancestry** (ancestry.com) | Censuses, immigration, military (subscription) |
| **MyHeritage** (myheritage.com) | Records, DNA tests (subscription) |
| **Geneanet** (geneanet.org) | European genealogy (free/subscription) |
| **FindAGrave** (findagrave.com) | Cemetery records worldwide |
| **BillionGraves** (billiongraves.com) | GPS-tagged headstone photos |

## Publishing Results

When enough material accumulates:
1. **Quartz** (quartz.jzhao.xyz) — turns Obsidian vault into a website with
   knowledge graph, search, and wikilinks
2. **Cloudflare Pages** / **GitHub Pages** / **Netlify** — free hosting
3. Password protection via `functions/_middleware.js` (Basic Auth) or similar
