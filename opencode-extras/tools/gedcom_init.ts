import { tool } from "@opencode-ai/plugin"
import { runWrite, resolveGedPath } from "./_gedcom.ts"

export default tool({
  description:
    "Create a new, empty GEDCOM (.ged) family tree with a valid HEAD/TRLR, " +
    "UTF-8 encoding and GEDCOM 5.5.1. Use when starting a tree from scratch. " +
    "Returns JSON confirming the file was created. To populate it, follow up " +
    "with gedcom_add_person and gedcom_link.",
  args: {
    file: tool.schema
      .string()
      .describe("Path to the .ged file to create (relative or absolute)"),
    name: tool.schema
      .string()
      .optional()
      .describe("Optional tree/file name stored in the header"),
    force: tool.schema
      .boolean()
      .optional()
      .describe("Overwrite if the file already exists (default false)"),
  },
  async execute(args, context) {
    const file = await resolveGedPath(args.file, context.worktree)
    const scriptArgs = [file, "init"]
    if (args.name) scriptArgs.push("--name", args.name)
    if (args.force) scriptArgs.push("--force")
    return runWrite("gedcom_init", scriptArgs)
  },
})
