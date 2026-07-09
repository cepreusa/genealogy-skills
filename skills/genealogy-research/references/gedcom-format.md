# GEDCOM Format — Compact Reference

A practical reference for reading GEDCOM files and mapping their records into an
Obsidian genealogy vault. For hands-on reading/editing use the **gedcom-reader**
skill and its `scripts/gedcom.py` parser.

## Table of Contents
- [What GEDCOM Is](#what-gedcom-is)
- [Line Structure](#line-structure)
- [Record Types](#record-types)
- [Key Tags](#key-tags)
- [Cross-references (XREF)](#cross-references-xref)
- [Dates and Places](#dates-and-places)
- [Encoding](#encoding)
- [MyHeritage and Other Exporter Quirks](#myheritage-and-other-exporter-quirks)
- [Mapping GEDCOM to the Obsidian Vault](#mapping-gedcom-to-the-obsidian-vault)
- [Import / Export Notes](#import--export-notes)

---

## What GEDCOM Is

GEDCOM (GEnealogical Data COMmunication) is the de-facto interchange format for
family trees. Versions **5.5** and **5.5.1** are by far the most common; 7.0
exists but is rarely exported. It is a plain-text, line-oriented format — you
can read and edit it with any text editor.

---

## Line Structure

Every line is: `LEVEL [@XREF@] TAG [value]`

```
0 @I1@ INDI
1 NAME Иван /Петров/
2 GIVN Иван
2 SURN Петров
1 SEX M
1 BIRT
2 DATE 9 FEB 1960
2 PLAC Владимиро-Александровское, Россия
```

- **LEVEL** — nesting depth. `0` starts a top-level record; higher numbers are
  sub-fields of the nearest lower-level line above them.
- **@XREF@** — an optional identifier, only on level-0 records (`@I1@`, `@F3@`).
- **TAG** — a 3–5 letter code (`NAME`, `BIRT`, `DATE`). Tags starting with `_`
  are vendor extensions (non-standard).
- **value** — the rest of the line.
- **CONC / CONT** — continuation of a long value: `CONC` appends with no space,
  `CONT` appends a line break. Some exporters split multi-byte characters across
  a `CONC` boundary — decode the whole file at once, never line by line.

---

## Record Types

| Level-0 tag | Meaning |
|---|---|
| `HEAD` | File header: version, charset, language, source program |
| `INDI` | An individual person |
| `FAM` | A family (a couple and/or their children) |
| `SOUR` | A source (document, database, book) |
| `SUBM` | The submitter of the file |
| `NOTE` | A shared note (also appears inline under records) |
| `OBJE` | A multimedia object (photo, scan) |
| `REPO` | A repository (archive holding a source) |
| `TRLR` | Trailer — the last line of the file |

---

## Key Tags

**Inside `INDI`:**

| Tag | Meaning |
|---|---|
| `NAME` | Full name; surname wrapped in slashes: `Given /Surname/` |
| `GIVN` / `SURN` | Given name / surname (sub-tags of `NAME`) |
| `NICK` | Nickname |
| `SEX` | `M` / `F` / `U` |
| `BIRT` / `DEAT` | Birth / death events (contain `DATE`, `PLAC`) |
| `CHR` / `BURI` | Christening / burial |
| `OCCU` | Occupation |
| `RESI` | Residence |
| `NOTE` | Free-text note |
| `SOUR` | Link/citation to a source (may carry `PAGE`, `QUAY`) |
| `FAMC` | The family where this person is a **child** |
| `FAMS` | A family where this person is a **spouse** |
| `ADOP` | Adoption event (with its own `FAMC`) |

**Inside `FAM`:**

| Tag | Meaning |
|---|---|
| `HUSB` / `WIFE` | Spouse references (`@I..@`) |
| `CHIL` | A child reference (`@I..@`), repeated per child |
| `MARR` | Marriage event (`DATE`, `PLAC`) |
| `DIV` | Divorce event |

**Source quality (`SOUR` → `QUAY`)** maps neatly to GPS evidence levels:
`3` = primary/original, `2` = secondary, `1` = questionable, `0` = unreliable.

---

## Cross-references (XREF)

Relationships are expressed by pointers, not nesting:

```
0 @I1@ INDI
1 FAMS @F1@          ← I1 is a spouse in family F1
1 FAMC @F2@          ← I1 is a child in family F2

0 @F1@ FAM
1 HUSB @I1@
1 WIFE @I2@
1 CHIL @I3@          ← child links back via FAMC @F1@
```

To reconstruct a tree: follow `FAMC`/`FAMS` on people and `HUSB`/`WIFE`/`CHIL`
on families. The `gedcom-reader` parser does exactly this for `ancestors`,
`descendants`, and `relationship`.

---

## Dates and Places

- **Dates**: `DD MON YYYY` (`9 FEB 1960`), or partial (`1957`, `FEB 1960`).
  Qualifiers: `ABT` (about), `EST` (estimated), `CAL` (calculated), `BEF`,
  `AFT`, `BET x AND y`. Preserve them — they encode uncertainty.
- **Calendars**: default Gregorian. Russian Empire church records are often
  Julian (`@#DJULIAN@`); see `common-pitfalls.md`.
- **Places**: `PLAC` uses comma-separated hierarchy, usually smallest → largest:
  `Village, District, Region, Country`.

---

## Encoding

- The `1 CHAR` header declares the charset: `UTF-8`, `ANSEL`, `ASCII`, or a
  code page. Modern exports (MyHeritage, Gramps, Geni) use **UTF-8**.
- A UTF-8 BOM (`EF BB BF`) may precede the first line — strip it.
- Older files may be `ANSEL` (a genealogy-specific encoding) or Windows-1251
  for Cyrillic. When Cyrillic looks like `Ð...` mojibake, the file was decoded
  with the wrong codec.
- The `gedcom-reader` parser auto-detects and prefers UTF-8, falling back to
  cp1251/latin-1.

---

## MyHeritage and Other Exporter Quirks

MyHeritage exports (like `MyHeritage_GEDCOM_*.ged`) add non-standard tags —
treat these as **noise** when reading:

| Tag | What it is |
|---|---|
| `_UID` | Internal unique ID |
| `_UPD` | Last-updated timestamp |
| `RIN` | Record ID number |
| `_MARNM` | Married name (occasionally useful) |
| `_RTLSAVE`, `_PROJECT_GUID`, `_EXPORTED_FROM_SITE_ID` | Site metadata |

They also split long `NOTE`/`ADDR` values across `CONC` lines, sometimes mid
UTF-8 character. Decode the full byte buffer, then split into lines.

---

## Mapping GEDCOM to the Obsidian Vault

Turn records into vault files (templates in
[vault-templates.md](vault-templates.md)):

| GEDCOM | Obsidian |
|---|---|
| `INDI` | `Chronicles/People/<Name>.md` — one file per person |
| `NAME` / `GIVN` / `SURN` / `NICK` | `title`, `aliases` in frontmatter |
| `BIRT` / `DEAT` `DATE`/`PLAC` | `birth_year`/`birth_place`, `death_year`/`death_place` |
| `FAMC` → `HUSB`/`WIFE` | `father`, `mother` wikilinks |
| `FAMS` → spouse | `spouse` wikilink |
| `PLAC` | `Chronicles/Places/<Place>.md` with coordinates |
| `SOUR` + `QUAY` | Source citation + evidence level (Proven/Probable/…) |
| `NOTE` | Notes section / Research file |

Mapping back (vault → GEDCOM): each People file becomes an `INDI`; each
parent/spouse link becomes a `FAM` with the right `HUSB`/`WIFE`/`CHIL`/`FAMC`/
`FAMS` pointers.

---

## Import / Export Notes

- **Reading**: use `gedcom-reader`'s parser for anything beyond a few dozen
  people; read the raw file directly only for small trees.
- **Editing**: edit at the text level, preserving the original charset, line
  endings, and record order. Add a `1 NOTE [CHANGELOG] <date>: …` to every
  changed record.
- **Round-tripping**: GEDCOM loses vendor-specific extension data across tools.
  Keep the original export file untouched as the source of truth; treat the
  vault as the working knowledge base.
- **Validation**: a well-formed file starts with `0 HEAD` and ends with
  `0 TRLR`; every `@XREF@` referenced should have a matching definition.
