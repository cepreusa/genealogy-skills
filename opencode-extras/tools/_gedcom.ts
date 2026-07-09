// Shared helper for the gedcom_* write tools.
//
// This file intentionally exports NO `export default tool(...)`, so the opencode
// plugin loader does not register it as a callable tool. It is a plain module
// imported by the sibling gedcom_*.ts tool wrappers.
//
// The write tools shell out to the dependency-free Python engine
// (.opencode/skills/gedcom-reader/scripts/gedcom_write.py) via Bun. Two things
// worth noting:
//
//   1. PYTHONIOENCODING=utf-8 is forced so Cyrillic / non-ASCII prints correctly
//      (the engine writes JSON with ensure_ascii=False).
//   2. Under opencode's stdio server, Bun occasionally hands the child python3 a
//      closed stdin fd, aborting the interpreter before any user code runs
//      ("init_sys_streams" / "Bad file descriptor"). This is a transient Bun
//      spawn race, not a Python bug. We redirect stdin from /dev/null and retry
//      a couple of times only on that crash signature; real errors are surfaced.

import path from "path"

// The skill scripts live under the project's .opencode. Derive the project root
// from this file's location: .opencode/tools/_gedcom.ts -> up two = project root.
export const PROJECT_ROOT = path.resolve(import.meta.dir, "..", "..")

export const WRITE_SCRIPT = path.join(
  PROJECT_ROOT,
  ".opencode/skills/gedcom-reader/scripts/gedcom_write.py",
)
export const READ_SCRIPT = path.join(
  PROJECT_ROOT,
  ".opencode/skills/gedcom-reader/scripts/gedcom.py",
)

export interface PyResult {
  exitCode: number
  stdout: string
  stderr: string
}

const TRANSIENT_CRASH_PATTERNS = [
  "init_sys_streams",
  "Bad file descriptor",
  "core initialized",
  "can't initialize sys standard streams",
]

function isTransientStdioCrash(exitCode: number, stderr: string): boolean {
  if (exitCode === 0) return false
  return TRANSIENT_CRASH_PATTERNS.some((p) => stderr.includes(p))
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

/**
 * Run a project python3 script with PYTHONIOENCODING=utf-8, from PROJECT_ROOT,
 * capturing stdout/stderr. Retries only on the transient interpreter-init crash.
 *
 * @param script       absolute path to the .py script
 * @param scriptArgs   positional/flag arguments passed verbatim to the script
 * @param maxAttempts  total attempts including the first (default 3)
 */
export async function runPython(
  script: string,
  scriptArgs: string[],
  maxAttempts = 3,
): Promise<PyResult> {
  let last: PyResult = { exitCode: -1, stdout: "", stderr: "" }

  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    // Spawn python3 directly (no `bash -c`): Bun.spawn passes argv verbatim, so
    // Cyrillic/spaces in arguments are never re-tokenized by a shell. stdin is
    // set to "ignore" (a valid /dev/null fd) so python never inherits a closed
    // descriptor — the root of the transient interpreter-init crash.
    const proc = Bun.spawnSync(["python3", script, ...scriptArgs], {
      cwd: PROJECT_ROOT,
      stdin: "ignore",
      env: { ...process.env, PYTHONIOENCODING: "utf-8" },
    })

    last = {
      exitCode: proc.exitCode ?? -1,
      stdout: proc.stdout.toString().trim(),
      stderr: proc.stderr.toString().trim(),
    }

    if (!isTransientStdioCrash(last.exitCode, last.stderr)) {
      return last
    }
    if (attempt < maxAttempts) {
      await sleep(200 * attempt)
    }
  }
  return last
}

/**
 * Resolve a .ged path argument: absolute is used as-is; relative is tried
 * against the project root first, then the session worktree.
 */
export async function resolveGedPath(
  filePath: string,
  worktree: string,
): Promise<string> {
  if (filePath.startsWith("/")) return filePath
  const fromRoot = path.join(PROJECT_ROOT, filePath)
  if (await Bun.file(fromRoot).exists()) return fromRoot
  const fromWorktree = path.join(worktree, filePath)
  if (await Bun.file(fromWorktree).exists()) return fromWorktree
  // Default to project-root join (used by `init`, where the file doesn't exist yet).
  return fromRoot
}

/** Format a failed PyResult into a readable tool error string. */
export function formatFailure(toolName: string, r: PyResult): string {
  return [
    `${toolName} failed (exit ${r.exitCode}).`,
    r.stdout && `stdout:\n${r.stdout}`,
    r.stderr && `stderr:\n${r.stderr}`,
  ]
    .filter(Boolean)
    .join("\n\n")
}

/** Run the write engine and return stdout (JSON) or a formatted failure. */
export async function runWrite(
  toolName: string,
  scriptArgs: string[],
): Promise<string> {
  const r = await runPython(WRITE_SCRIPT, scriptArgs)
  if (r.exitCode !== 0) return formatFailure(toolName, r)
  return r.stdout || r.stderr
}
