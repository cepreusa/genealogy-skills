# AGENTS.md — genealogy-skills

Guidance for any AI coding agent (Claude Code, OpenAI Codex, opencode, and
others that read `AGENTS.md`) working in this repository or with these skills
installed.

## What this project is

A set of **agent-agnostic genealogy skills** built on the
[Agent Skills](https://agentskills.io) open standard. They let an agent read,
build, analyse and visualise **GEDCOM (`.ged`)** family trees. All logic is
**pure Python 3 standard library** invoked through `bash` — no Gramps, no
Docker, no external dependencies, no network.

## The skills (`skills/`)

| Skill | Use it when the user wants to… |
|---|---|
| `gedcom-reader` | read a `.ged`, answer who-is-who / relationships, or **build/edit** a tree (add people, set facts, link relations) |
| `gedcom-report` | an analytics dashboard (stats, charts, name cloud, timeline, data-quality) as one offline HTML file |
| `gedcom-tree` | an interactive, browsable HTML family-tree viewer centred on a person |
| `genealogy-research` | plan systematic research with the Genealogical Proof Standard (GPS), keep an Obsidian vault, or **start a tree from nothing** via a short intake interview |

Each skill's `SKILL.md` carries the detailed workflow. Load the skill that fits
the task and defer to it.

## Running the scripts

Always set `PYTHONIOENCODING=utf-8` so Cyrillic and other non-Latin scripts
print correctly. `<skill-dir>` is wherever the skill is installed — commonly a
project-local dotfolder (e.g. `.claude/skills/gedcom-reader`,
`.agents/skills/gedcom-reader`, `.opencode/skills/gedcom-reader`) or a personal
one (`~/.claude/skills/gedcom-reader`).

```bash
# Read / query
PYTHONIOENCODING=utf-8 python3 <skill-dir>/scripts/gedcom.py tree.ged stats
PYTHONIOENCODING=utf-8 python3 <skill-dir>/scripts/gedcom.py tree.ged descendants "Иван Петров"

# Build / edit (see gedcom-reader "Build Mode")
PYTHONIOENCODING=utf-8 python3 <skill-dir>/scripts/gedcom_write.py tree.ged add-person --given Иван --surname Петров --sex M --birt-date 1960
PYTHONIOENCODING=utf-8 python3 <skill-dir>/scripts/gedcom_write.py tree.ged link spouses "Иван Петров" "Мария Иванова"

# Report / tree (write one self-contained HTML file)
PYTHONIOENCODING=utf-8 python3 <skill-dir>/scripts/report.py tree.ged
PYTHONIOENCODING=utf-8 python3 <skill-dir>/scripts/tree.py tree.ged --focus "Иван Петров"
```

Try it against the bundled `examples/demo.ged` (a small fictional family).

## Working principles

- **Human answers, not raw data.** Never dump `@XREF@` ids or GEDCOM lines at the
  user; translate to natural language.
- **Writes are deliberate.** Every write tool makes a timestamped `.bak-*` backup
  and re-parses the file. Preview the change and confirm before editing an
  existing tree.
- **Be honest about uncertainty.** Record memory-based claims with the speaker
  and date and their per-assertion certainty (firsthand vs family tradition),
  status `provisional`/`hypothesis` — don't treat them as documented facts or
  infer unstated relationships. Follow the GPS.
- **Privacy first.** `.ged` files hold personal data about living people. This
  repo's `.gitignore` deliberately ignores all `*.ged` except `examples/demo.ged`
  — never commit a user's real family data.

## opencode users

A ready-made opencode agent, config and native write-tool plugins live in
`opencode-extras/`; `./install.sh opencode` deploys them (and an `opencode.json`
wired for the Playwright browser MCP). Other agents use the skills directly (see
`README.md` for per-agent install).
