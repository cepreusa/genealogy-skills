# Obsidian Vault Templates for Genealogy Research

A proven, low-friction structure for a genealogy knowledge base. It grew out of
real research sessions and pairs naturally with the GPS method
([gps-methodology.md](gps-methodology.md)).

## Vault structure

```
<vault>/                       # e.g. my-family/
├── PROCESS.md                 # research tracker: done / pending / findings / dead ends
├── materials/skany/           # archive scans (saved here by the browser, not the project root)
└── Chronicles/                # the Obsidian knowledge base
    ├── People/                # one file per person
    ├── Places/                # one file per settlement/parish (history, jurisdiction, archive)
    ├── Research/              # one file per family LINE + one per SEARCH PLAN
    ├── Documents/             # (optional) per-document transcriptions
    └── Events/                # (optional) migrations, wars, resettlements
```

`People` + `Places` + `Research` are the working core — start with these and add
`Documents`/`Events` as material grows. Everything links with Obsidian
`[[wiki-links]]`, so the vault becomes a navigable graph.

### Conventions (apply everywhere)

- **Link generously:** every person, place and source note cross-links with
  `[[...]]`. This is what makes the graph useful.
- **Tag evidence** on every non-trivial claim: `Proven / Probable / Possible /
  Unproven` (see the GPS reference). Never state a fact without its basis.
- **Cite the source** inline: archive + fond/opis/delo (or act #) + page + URL +
  access date. An index citation and a scan citation are not the same.
- **Record negative results** — a documented "not found" is a finding, kept in
  PROCESS.md → Dead Ends.
- **Status markers** (optional, scannable) in prose/PROCESS.md:
  🆕 new lead · 🎯 target found · ✅ confirmed · ❌ ruled out · ❓ open question ·
  🗺 place/jurisdiction issue · 🧭 direction/decision.

## Person File Template

Create one file per person in `Chronicles/People/`:

```yaml
---
title: Firstname Lastname
aliases:
  - Alternate Spelling
  - Name in Other Language
  - Maiden Name (for women)
tags:
  - person
  - generation/3
birth_year: 1879
birth_place: "[[Place Name]]"
death_year: 1945
death_place: "[[Place Name]]"
father: "[[Father Name]]"
mother: "[[Mother Name (Maiden Name)]]"
spouse: "[[Spouse Name]]"
evidence_level: proven
---

# Firstname Lastname

## Biographical Data
| Field | Value | Source | Evidence |
|-------|-------|--------|----------|
| Birth | 1879-03-15, Korzeniówka | Geneteka, Dołubowo, act #28, 1879 | Proven |
| Baptism | 1879-03-17 | same source | Proven |
| Marriage | 1902-11-26 | SzukajWArchiwach, Boćki, act #39, 1902 | Proven |
| Death | ~1945 | family oral history | Unproven |

## Parents
- Father: [[Father Name]]
- Mother: [[Mother Name (Maiden Name)]]

## Spouse(s)
1. [[Spouse Name]] — married [date], [place] (source)

## Children
1. [[Child 1]] (born [year])
2. [[Child 2]] (born [year])

## Notes
- [Any relevant observations, discrepancies, research leads]

## Sources
1. [Full source citation]
2. [Full source citation]
```

## Place File Template

Create in `Chronicles/Places/`:

```yaml
---
title: Place Name
aliases:
  - Historical Name
  - Name in Other Language
tags:
  - place
  - parish
coordinates: [52.4567, 22.8901]
modern_country: Poland
historical_region: Podlasie
---

# Place Name

## Location
- Modern: [modern administrative location]
- Historical: [historical jurisdiction by period]
- Parish: [[Parish Name]]
- Coordinates: [lat, lon]

## Families Connected
- [[Family 1]]
- [[Family 2]]

## Notes
- [Church history, administrative changes, etc.]
```

## Document File Template

Create in `Chronicles/Documents/`:

```yaml
---
title: Document Description
tags:
  - document
  - birth-record
document_type: birth_record
date: 1879-03-15
parish: Dołubowo
archive: "Archiwum Państwowe w Białymstoku"
source_url: "https://..."
scan_file: "materials/skany/filename.jpg"
---

# Document Description

## Summary
| Field | Value |
|-------|-------|
| Type | Birth/Marriage/Death Record |
| Date | 1879-03-15 |
| Parish | Dołubowo |
| Act Number | 28 |
| Archive | AP Białystok |

## Transcription
[Full or partial transcription of the document]

## Translation
[Translation if in foreign language]

## People Mentioned
- [[Person 1]] — role (newborn, parent, witness, etc.)
- [[Person 2]] — role

## Notes
- [Observations about handwriting, damage, unusual entries]
```

## Research Line Template

One file per family line in `Chronicles/Research/` — the analytical narrative
that ties a branch together (structure, findings, open questions, next steps).
This is where indirect-evidence proof arguments are built.

```yaml
---
title: The <Surname> Line — <short descriptor>
tags:
  - research
  - line
surnames: [Surname, SpellingVariant]
regions: ["[[Origin Place]]", "[[Later Place]]"]
status: active
---

# The <Surname> Line — <short descriptor>

## Structure (from the tree)
<Who descends from whom; what the GEDCOM already gives (and what it lacks).>

## Established (with evidence)
- ✅ **<Claim>** — <basis>. Source: <archive/fond/opis/delo/URL>. Tag: Proven.
- **<Claim>** — <indirect basis, matching time/place>. Tag: Probable.

## Ruled out / negative
- ❌ <Hypothesis> — checked <where/params>, not supported.

## Open questions → next steps
- [ ] <Specific question> → <which source/archive, what to look for>.

## Correlation notes
<Conflicts between sources and how they were (or weren't) resolved.>
```

## Search Plan Template

One file per active investigation in `Chronicles/Research/` — the concrete plan
for answering a specific question (per GPS: plan before searching).

```yaml
---
title: Search Plan — <the question>
tags:
  - research
  - search-plan
question: "<the precise question, e.g. maiden name of X / birth years of Y>"
status: open
---

# Search Plan — <the question>

## Anchor (what we already know)
<The years/places/relatives to start from. If none — first task is to find one.>

## Candidate sources (priority order)
1. **<Source/archive>** — why it could answer this; exact collection
   (fond/opis/delo or parish/years); how to access (incl. navigator mode if gated).
2. **<Source>** — ...

## Steps
- [ ] <Concrete step: site, query/parameters, what a hit looks like>
- [ ] <Concrete step>

## Log (fill as you go)
| Date | Searched (where / params) | Result | Tag |
|------|---------------------------|--------|-----|
| | | | |
```

## PROCESS.md Template

Maintain this file at the vault root (long-term memory; the per-session
TodoWrite list is the short-term plan):

```markdown
# Research Process: [Family Name]

## Current Hypothesis
[Main working hypothesis, updated as findings accumulate]

## Completed Actions
### [Date]: [Topic]
- [x] Action — result (source)
- [x] Action — 0 records found (NEGATIVE RESULT — eliminates possibility X)

### [Date]: [Topic]
- [x] Action — result

## Pending Tasks
### Priority 1: [description]
- [ ] Specific action (database, parameters)
- [ ] Specific action

### Priority 2: [description]
- [ ] Specific action
- [ ] Specific action

## Key Findings
| Finding | Evidence Level | Source | Date Found |
|---------|---------------|--------|------------|
| X is son of Y | Proven | Birth record, act #N | 2026-03-22 |
| A married B | Probable | Index only, no scan | 2026-03-22 |

## Unresolved Questions
1. [Question] — what would resolve it, where to look
2. [Question] — what would resolve it, where to look

## Dead Ends
| Question | Searched | Result | Date |
|----------|----------|--------|------|
| Birth of X | Geneteka (parish Y, 1840-1860) | 0 results | 2026-03-22 |
```

## Resources Note Template (optional)

An optional `Chronicles/Research/Resources.md` (or vault-root `RESOURCES.md`)
gathering the services, archives, parishes, and logins relevant to *this* tree.
General database listings live in
[databases-by-region.md](databases-by-region.md); this note is the project-
specific shortlist.

```markdown
# Research Resources

## Online Databases
| Service | URL | What it Contains | Access | Notes |
|---------|-----|-----------------|--------|-------|
| Geneteka | geneteka.genealodzy.pl | Parish record indexes | Free | Use 15km checkbox |
| FamilySearch | familysearch.org | Microfilms, records | Free | Login: [username] |

## Archives (for personal contact)
| Archive | Holdings | Contact | Notes |
|---------|----------|---------|-------|
| [Name] | [What they keep] | [Address/email/phone] | [Status of inquiry] |

## Key Parishes
| Parish | Denomination | Records Available | Online? |
|--------|-------------|-------------------|---------|
| [Name] | Catholic | Births 1808-1870, Marriages 1808-1850 | Geneteka (indexed), Skanoteka (scans) |

## Forums and Communities
| Resource | URL | Description |
|----------|-----|------------|
| [Forum name] | [URL] | [What it's useful for] |

## Tools
| Tool | URL | Purpose |
|------|-----|---------|
| GEDmatch | gedmatch.com | DNA cross-matching |
| Hebcal | hebcal.com | Hebrew calendar conversion |

## Contacts
| Person | Role | Contact | Notes |
|--------|------|---------|-------|
| [Name] | Local researcher | [email] | [Status] |
```

## File Naming Conventions

- **People:** Use the primary name form: `Firstname Lastname.md` or native script: `Имя Фамилия.md`
- **Places:** Use modern name: `Dziadkowice.md`, with historical names as aliases
- **Documents:** Descriptive: `Birth Record - Jan Kowalski 1879.md` or by archive reference: `Act 28 Dołubowo 1879.md`
- **Keep consistent** within a project — pick one convention and stick with it
