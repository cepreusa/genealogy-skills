#!/usr/bin/env bash
#
# install.sh — install the genealogy-skills into an agent's skills directory,
#              or rebuild the upload-ready ZIPs for Claude Desktop / claude.ai.
#
# Usage:
#   ./install.sh [target] [project-dir]
#
# Named targets are PROJECT-LOCAL: skills go into a dotfolder inside your project
# (the current directory by default, or the project-dir you pass as the 2nd arg),
# never into a global config. Run this from your project's root.
#
# target is one of:
#   claude     -> <project>/.claude/skills     (Claude Code, project-local)
#   codex      -> <project>/.agents/skills     (OpenAI Codex CLI — scans .agents/skills)
#   opencode   -> <project>/.opencode/skills   (opencode, project-local) — also
#                 installs the genealogist agent, native gedcom_* write tools, and
#                 an opencode.json wired for the Playwright browser MCP
#   agents     -> <project>/.agents/skills     (cross-agent, project-local)
#   zip        -> ./download-skills/<skill>.zip (rebuild the upload-ready ZIPs)
#   <path>     -> that exact directory (absolute or relative to CWD)
#
# With no target, installs to <project>/.claude/skills.
#
#   ./install.sh                 # -> ./.claude/skills
#   ./install.sh opencode        # -> ./.opencode/skills
#   ./install.sh claude ~/proj   # -> ~/proj/.claude/skills
#   ./install.sh ~/.claude/skills   # global (all projects) — pass a path
#
# The 2nd "project-dir" argument applies to the NAMED targets only; when you pass
# an explicit <path> it is used verbatim.
#
# Most users don't need the "zip" target: ready-made ZIPs are already committed
# in download-skills/ for uploading to Claude Desktop / claude.ai. Use "zip" only
# to rebuild them after changing a skill.
#
# The four skills are copied (not symlinked) so they work on every platform.
# Re-running overwrites the installed copies.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
SRC="$ROOT/skills"

SKILLS=(gedcom-reader gedcom-report gedcom-tree genealogy-research)

# --- zip target: rebuild the upload-ready ZIPs in download-skills/ ------------
# Archives are byte-reproducible (fixed mtime + -X) AND idempotent (a ZIP is only
# rewritten when its extracted content actually changed), so re-running never
# produces noisy "modified binary" diffs.
if [ "${1:-}" = "zip" ]; then
  command -v zip >/dev/null 2>&1 || {
    echo "error: 'zip' is not installed. Install it (e.g. 'apt install zip')." >&2
    exit 1
  }
  DEST="$ROOT/download-skills"
  mkdir -p "$DEST"
  STAMP="200001010000"   # fixed mtime for reproducible archives (YYYYMMDDhhmm)
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  echo "Rebuilding upload-ready ZIPs in download-skills/"
  for skill in "${SKILLS[@]}"; do
    # Stage a clean copy with normalized timestamps.
    stage="$TMP/stage"
    rm -rf "$stage"; mkdir -p "$stage"
    cp -R "$SRC/$skill" "$stage/$skill"
    find "$stage/$skill" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
    find "$stage/$skill" -name '*.pyc' -delete 2>/dev/null || true
    # Normalize mtimes (dirs and files) so the archive bytes are stable.
    find "$stage" -exec touch -t "$STAMP" {} +
    # Build into a temp zip; only replace the committed one if content changed.
    new="$TMP/$skill.zip"
    ( cd "$stage" && zip -qrX "$new" "$skill" )
    cur="$DEST/$skill.zip"
    if [ -f "$cur" ] && cmp -s "$new" "$cur"; then
      echo "  = download-skills/$skill.zip (unchanged)"
    else
      mv "$new" "$cur"
      echo "  + download-skills/$skill.zip"
    fi
  done
  echo
  echo "Commit any changed ZIPs. Users upload them in Claude Desktop / claude.ai:"
  echo "  Customize -> Skills -> \"+\" -> Upload a skill (enable Code execution first)."
  exit 0
fi

TARGET="${1:-claude}"

# Project directory for named targets: 2nd arg if given, else the current dir.
PROJECT="${2:-$(pwd)}"
if [ -n "${2:-}" ] && [ ! -d "$PROJECT" ]; then
  echo "error: project dir '$PROJECT' does not exist." >&2
  exit 1
fi

case "$TARGET" in
  claude)             DEST="$PROJECT/.claude/skills" ;;
  codex|agents)       DEST="$PROJECT/.agents/skills" ;;  # Codex scans .agents/skills
  opencode)           DEST="$PROJECT/.opencode/skills" ;;
  *)                  DEST="$TARGET" ;;                   # explicit path, verbatim
esac

# Guard against the classic mistake: running the installer inside this repo's own
# checkout, which would drop skills where no real project can see them.
case "$TARGET" in
  claude|codex|opencode|agents)
    if [ "$PROJECT" = "$ROOT" ]; then
      echo "warning: installing into the genealogy-skills checkout itself ($ROOT)." >&2
      echo "         That's almost certainly not what you want — the skills are" >&2
      echo "         already in ./skills/. Run this from YOUR project's root, e.g." >&2
      echo "           ./install.sh $TARGET /path/to/your/project" >&2
      echo "         or install globally with a path, e.g. ./install.sh ~/.claude/skills" >&2
      printf '         Continue anyway? [y/N] ' >&2
      read -r reply || reply=""
      case "$reply" in
        [yY]|[yY][eE][sS]) ;;
        *) echo "Aborted." >&2; exit 1 ;;
      esac
    fi
    ;;
esac

echo "Installing genealogy-skills"
echo "  from: $SRC"
echo "  to:   $DEST"

mkdir -p "$DEST"
for skill in "${SKILLS[@]}"; do
  rm -rf "${DEST:?}/$skill"
  cp -R "$SRC/$skill" "$DEST/$skill"
  # drop any stray caches
  find "$DEST/$skill" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
  echo "  + $skill"
done

# --- opencode extras: agent, native write tools, and opencode.json -----------
# For the opencode target we also drop in the "genealogist" agent and the native
# gedcom_* write tools (thin wrappers over gedcom_write.py), and make sure an
# opencode.json exists that registers the skills path AND the Playwright browser
# MCP used for archive research. An existing opencode.json is never overwritten.
if [ "$TARGET" = "opencode" ]; then
  EXTRAS="$ROOT/opencode-extras"
  OC="$PROJECT/.opencode"

  if [ -d "$EXTRAS" ]; then
    echo
    echo "opencode extras:"

    # Agent definition. The tools are ours (overwrite freely), but the agent file
    # is a customization point — if the user already has one, don't clobber it.
    if [ -d "$EXTRAS/agents" ]; then
      mkdir -p "$OC/agents"
      for a in "$EXTRAS/agents/"*.md; do
        name="$(basename "$a")"
        if [ -f "$OC/agents/$name" ] && ! cmp -s "$a" "$OC/agents/$name"; then
          echo "  ! .opencode/agents/$name exists and differs — left untouched."
          echo "    (compare with opencode-extras/agents/$name to merge changes.)"
        else
          cp "$a" "$OC/agents/$name"
          echo "  + .opencode/agents/$name  (genealogist agent)"
        fi
      done
    fi

    # Native write tools (gedcom_init / add_person / set / link / unlink + helper).
    # These are ours and safe to refresh; a failing cp must abort (set -e), not
    # be silently swallowed and then reported as success.
    if [ -d "$EXTRAS/tools" ]; then
      mkdir -p "$OC/tools"
      cp "$EXTRAS/tools/"*.ts "$OC/tools/"
      echo "  + .opencode/tools/   (native gedcom_* write tools)"
    fi

    # Plugin dependency manifest (+ lockfile) so `@opencode-ai/plugin` resolves.
    # Never overwrite an existing package.json — the project may pin other plugin
    # deps. Print what to add instead.
    if [ -f "$OC/package.json" ]; then
      echo "  = .opencode/package.json exists — left untouched. Ensure it has:"
      echo '      "dependencies": { "@opencode-ai/plugin": "..." }'
      echo "    (see opencode-extras/package.json for the pinned version.)"
    else
      cp "$EXTRAS/package.json" "$OC/package.json"
      [ -f "$EXTRAS/package-lock.json" ] && cp "$EXTRAS/package-lock.json" "$OC/package-lock.json"
      echo "  + .opencode/package.json  (@opencode-ai/plugin, pinned via lockfile)"
    fi

    # opencode.json — create from template if missing; otherwise leave it and
    # tell the user what to add (skills path + Playwright MCP).
    if [ -f "$OC/opencode.json" ]; then
      echo "  = .opencode/opencode.json already exists — left untouched."
      echo "    Make sure it contains (see opencode-extras/opencode.json):"
      echo '      "skills":     { "paths": [".opencode/skills"] }'
      echo '      "mcp": { "playwright": { "type": "local",'
      echo '               "command": ["npx","@playwright/mcp@latest"], "enabled": true } }'
    elif [ -f "$EXTRAS/opencode.json" ]; then
      cp "$EXTRAS/opencode.json" "$OC/opencode.json"
      echo "  + .opencode/opencode.json  (skills path + Playwright browser MCP)"
    fi

    echo
    echo "The Playwright MCP lets the agent open online archives in a browser."
    echo "It runs via 'npx @playwright/mcp@latest' on first use (needs Node/npx)."
  fi
fi

# If the user installed the skills into an .opencode/skills path *explicitly*
# (not via the named "opencode" target), the extras above were skipped. Point
# them at the named target so they also get the agent, tools and config.
if [ "$TARGET" != "opencode" ]; then
  case "$DEST" in
    *.opencode/skills|*.opencode/skills/)
      echo
      echo "note: looks like an opencode skills dir. To also install the"
      echo "      genealogist agent, native write tools and a Playwright-wired"
      echo "      opencode.json, run:  ./install.sh opencode [project-dir]"
      ;;
  esac
fi

echo
echo "Done. Restart your agent so it picks up the new skills."
