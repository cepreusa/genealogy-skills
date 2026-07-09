import { tool } from "@opencode-ai/plugin"
import { runWrite, resolveGedPath } from "./_gedcom.ts"

export default tool({
  description:
    "Detach a child from a family in a GEDCOM tree (removes the CHIL pointer on " +
    "the family and the matching FAMC on the child). The people themselves are " +
    "kept — only the parent-child link is removed. Use to fix a mis-linked " +
    "child. A backup is made and the file re-parsed. Identify the child by " +
    "@Ixx@ id or unique name; the family by its @Fxx@ id.",
  args: {
    file: tool.schema.string().describe("Path to the .ged file"),
    child: tool.schema
      .string()
      .describe("The child (@Ixx@ id or unique name fragment)"),
    family: tool.schema.string().describe("The family @Fxx@ id to detach from"),
  },
  async execute(args, context) {
    const file = await resolveGedPath(args.file, context.worktree)
    const scriptArgs = [file, "unlink", "child", args.child, "--family", args.family]
    return runWrite("gedcom_unlink", scriptArgs)
  },
})
