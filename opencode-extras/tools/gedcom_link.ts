import { tool } from "@opencode-ai/plugin"
import { runWrite, resolveGedPath } from "./_gedcom.ts"

export default tool({
  description:
    "Link relationships in a GEDCOM tree, keeping both directions consistent. " +
    "relation='spouses': marry two people (creates/updates their FAM record; " +
    "pass person_a and person_b, optionally marriage date/place). " +
    "relation='child': attach a child to their parents (pass child and one or " +
    "two parents; finds or creates the parents' family and sets FAMC/CHIL). " +
    "HUSB/WIFE roles are assigned by each person's sex. People are given by " +
    "@Ixx@ id or a unique name fragment. A backup is made and the file re-parsed.",
  args: {
    file: tool.schema.string().describe("Path to the .ged file"),
    relation: tool.schema
      .string()
      .describe("'spouses' or 'child'"),
    person_a: tool.schema
      .string()
      .optional()
      .describe("For 'spouses': first spouse (@Ixx@ or unique name)"),
    person_b: tool.schema
      .string()
      .optional()
      .describe("For 'spouses': second spouse (@Ixx@ or unique name)"),
    child: tool.schema
      .string()
      .optional()
      .describe("For 'child': the child (@Ixx@ or unique name)"),
    parent_a: tool.schema
      .string()
      .optional()
      .describe("For 'child': first parent (@Ixx@ or unique name)"),
    parent_b: tool.schema
      .string()
      .optional()
      .describe("For 'child': optional second parent"),
    marr_date: tool.schema
      .string()
      .optional()
      .describe("For 'spouses': marriage date (GEDCOM form)"),
    marr_place: tool.schema
      .string()
      .optional()
      .describe("For 'spouses': marriage place"),
  },
  async execute(args, context) {
    const file = await resolveGedPath(args.file, context.worktree)

    if (args.relation === "spouses") {
      if (!args.person_a || !args.person_b) {
        return "Error: relation='spouses' requires person_a and person_b"
      }
      const scriptArgs = [file, "link", "spouses", args.person_a, args.person_b]
      if (args.marr_date) scriptArgs.push("--marr-date", args.marr_date)
      if (args.marr_place) scriptArgs.push("--marr-place", args.marr_place)
      return runWrite("gedcom_link", scriptArgs)
    }

    if (args.relation === "child") {
      if (!args.child || !args.parent_a) {
        return "Error: relation='child' requires child and at least parent_a"
      }
      const scriptArgs = [file, "link", "child", args.child, "--parent", args.parent_a]
      if (args.parent_b) scriptArgs.push("--parent", args.parent_b)
      return runWrite("gedcom_link", scriptArgs)
    }

    return `Error: unknown relation '${args.relation}' (use 'spouses' or 'child')`
  },
})
