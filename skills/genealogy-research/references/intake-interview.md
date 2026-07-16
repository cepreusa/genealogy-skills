# Intake Interview — starting a tree from nothing

Many users arrive with **no GEDCOM file at all**, just memories. This reference
is the workflow for turning those memories into a first real tree: a short,
gentle, generation-by-generation interview that builds a `.ged` as you go, using
the write tools from the `gedcom-reader` skill.

The goal of intake is a **skeleton** — the closest 2–3 generations — not a
finished tree. It gives every later research session an anchor to work from.

## When to start it

Offer intake when the user wants a tree / родословную but there is nothing to
read yet. Detect this:

- Glob `**/*.ged` → **no file**, or
- The file exists but `stats` reports **0 people** (an empty tree).

**Always ask first — never start unprompted.** A good opener:

> Дерева пока нет. Давайте соберём основу за несколько минут — начнём с вас, а
> дальше по одному добавим родителей, бабушек и дедушек, братьев и сестёр.
> Готовы? (Если чего-то не знаете — так и скажем, это нормально.)

Begin only after a "yes". If the user would rather import an existing file or
start elsewhere, follow that instead.

## How to run it

- **One small step at a time**, in this order: *the person themselves →
  parents → grandparents → siblings → (optionally) spouse & children*.
- **Ask in plain prose**, in the user's language. A couple of related people per
  turn is fine (e.g. "как звали ваших родителей?"), but don't dump a huge form.
- **"Не знаю" is a valid answer.** Skip the field, record what's known, move on.
  Approximate is valuable: "где-то 1950-е" → `ABT 1955`; "родился, когда деду
  было лет 30" is an indirect clue worth a note.
- **Never re-ask** what you already have. Keep a running mental (and TodoWrite)
  model of who's entered.
- **Keep it light.** This is a conversation with a relative, not an intake form
  at an office. Warmth first, completeness second.
- **Track the plan with TodoWrite:** e.g. `person → parents → grandparents →
  siblings → build tree`. Intake is inherently multi-step.

## What to capture per person

Minimum (ask for these):

- **Name** — given + surname. For married women, ask the **maiden surname**
  (record it as the surname; note the married name).
- **Sex** — usually clear from the name/role; confirm if unsure.
- **Alive or deceased**, and roughly **when born** (a year, or `ABT`/decade).

Optional, only if it flows naturally:

- Birth place, places lived, occupation, death year/place, a memorable detail.

If a name is unknown, it's fine to add a person with only a surname or only a
role (e.g. "бабушка по маме") — the tree tolerates surname-only cards. Fill the
given name later.

## Recording provenance — intake is an *oral-history source*

The interview itself is a source; facts come from memory, not documents. Be
honest about that per assertion (see [gps-methodology.md](gps-methodology.md)):

- On **every** person you add, put a note naming the speaker and date, and — for
  each material claim — whether it is firsthand, family tradition, or uncertain,
  e.g. `Источник: со слов <кто рассказал>, <дата>. Firsthand: год рождения;
  family tradition: место рождения. Статус: provisional.`
- Use `gedcom_add_person`'s `note` on creation, or `gedcom_set add_note` after.
- Do not assign one blanket status to a whole person. Oral information is not
  automatically weak — its value depends on the assertion and the speaker's
  knowledge. Treat details to be confirmed later as `provisional` or
  `hypothesis`, not "proven".

## Turning answers into GEDCOM (tool sequence)

Use the write tools (they allocate ids, keep two-way links, back up, re-parse):

1. **First person / new file.** If no `.ged` exists, `gedcom_init` — ask where
   to save it (offer a sensible default next to the vault, e.g.
   `my-family/tree.ged`) and an optional tree name. Then `gedcom_add_person`
   for the starting person (note the returned `@Ixx@`).
2. **Each additional person** → `gedcom_add_person`, then link **only the
   relationships the user actually asserts**:
   - A child to their parent(s): `gedcom_link relation:"child"` with one or both
     parents — from the explicit statement, not from a shared household.
   - Link two adults as `spouses` **only when the user says** they were married
     or partners. Do not infer marriage merely because two people are named as
     someone's parents.
   - When it matters and isn't clear, ask whether a parent link is biological,
     adoptive, step, foster, or guardian.
   - GEDCOM needs a family record to hold two parents; note that this is
     representational structure — it does **not** itself assert a marriage.
   - Don't infer sex from a name; ask when you need it to encode faithfully.
3. **Unknowns:** omit the date, or pass `ABT <year>`; add a surname-only or
   role-only person when a name is missing.
4. Confirm the growing shape briefly ("добавил маму и обеих бабушек, связал"),
   but don't interrupt for confirmation on every single field — keep momentum.

You can identify people in `gedcom_link`/`gedcom_set` by `@Ixx@` id **or a unique
name fragment**; if a name is ambiguous the tool returns the matches — show them
and ask which.

## Finishing — show it and point forward

When the skeleton is in place (usually the person + parents + grandparents, plus
siblings):

1. Run `stats` to sanity-check counts, then generate the interactive viewer with
   the **gedcom-tree** skill, focused on the starting person:
   ```bash
   PYTHONIOENCODING=utf-8 python3 <gedcom-tree-skill-dir>/scripts/tree.py <file.ged> --focus "<name-or-id>"
   ```
2. Tell the user the path and how to open it (double-click; click a card to
   re-centre).
3. **Offer the next step**, don't just stop:
   - go deeper up a branch (great-grandparents), or
   - start real archival research on the **oldest known person** — hand off to
     the normal research workflow (plan a search, then research in the browser
     via a browser MCP; see [databases-by-region.md](databases-by-region.md)).

Optionally, if a vault is in use, mirror the skeleton into `Chronicles/People/`
notes later (see [vault-templates.md](vault-templates.md)) — but the `.ged` is
the primary artefact from intake.

## Mini example (neutral names)

> **Agent:** Дерева пока нет — давайте соберём основу? Начнём с вас: как вас
> зовут и в каком году вы родились?
> **User:** Иван Петров, 1985, Москва.

→ `gedcom_init` (`tree.ged`), then
`gedcom_add_person given:"Иван" surname:"Петров" sex:"M" birt_date:"1985"
birt_place:"Москва" note:"Источник: со слов Ивана, 2026-07. Firsthand. Статус: provisional."`

> **Agent:** Отлично. А как звали ваших родителей — отца и мать (девичью
> фамилию мамы тоже, если знаете)?
> **User:** Отец — Пётр Петров, примерно 1960. Мама — Мария, в девичестве
> Иванова, кажется 1962-й.

→ add `Пётр Петров` (`M`, `ABT 1960`), add `Мария Иванова` (`F`, `ABT 1962`),
`gedcom_link child` (Иван → Пётр, Мария). Each with an oral-history note. Then
ask before marrying them:

> **Agent:** Пётр и Мария были в браке (или партнёрами), или вы просто знаете,
> что это ваши родители?
> **User:** Да, были женаты.

→ only now `gedcom_link spouses` (Пётр, Мария). If the user didn't confirm a
marriage, leave them linked to Иван as parents without a spouse link.

> **Agent:** Записал родителей и связал с вами. Теперь бабушки и дедушки —
> начнём с папиной стороны: помните, как звали его родителей?

…continue up to the grandparents, then siblings, then build the tree.
