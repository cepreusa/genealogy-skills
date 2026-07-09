import { tool } from "@opencode-ai/plugin"
import { runWrite, resolveGedPath } from "./_gedcom.ts"

export default tool({
  description:
    "Set or update facts on an existing person in a GEDCOM tree: name, sex, " +
    "birth/death date & place, occupation, or append a note. Only the fields " +
    "you pass are changed; a [CHANGELOG] note recording the edit is added " +
    "automatically. A backup is made and the file re-parsed. The person is " +
    "identified by @Ixx@ id or a unique name fragment (ambiguous names are " +
    "rejected with the list of matches). For correcting a person's own records; " +
    "use gedcom_link to change relationships.",
  args: {
    file: tool.schema.string().describe("Path to the .ged file"),
    id: tool.schema
      .string()
      .describe("Person @Ixx@ id or a unique name fragment"),
    name_given: tool.schema
      .string()
      .optional()
      .describe("Replace given name(s)"),
    name_surname: tool.schema.string().optional().describe("Replace surname"),
    sex: tool.schema.string().optional().describe("Set sex: 'M', 'F' or 'U'"),
    birt_date: tool.schema.string().optional().describe("Set birth date"),
    birt_place: tool.schema.string().optional().describe("Set birth place"),
    deat_date: tool.schema.string().optional().describe("Set death date"),
    deat_place: tool.schema.string().optional().describe("Set death place"),
    occu: tool.schema.string().optional().describe("Set occupation"),
    add_note: tool.schema
      .string()
      .optional()
      .describe("Append a free-text note"),
  },
  async execute(args, context) {
    const file = await resolveGedPath(args.file, context.worktree)
    const scriptArgs = [file, "set", args.id]
    if (args.name_given) scriptArgs.push("--name-given", args.name_given)
    if (args.name_surname) scriptArgs.push("--name-surname", args.name_surname)
    if (args.sex) scriptArgs.push("--sex", args.sex)
    if (args.birt_date) scriptArgs.push("--birt-date", args.birt_date)
    if (args.birt_place) scriptArgs.push("--birt-place", args.birt_place)
    if (args.deat_date) scriptArgs.push("--deat-date", args.deat_date)
    if (args.deat_place) scriptArgs.push("--deat-place", args.deat_place)
    if (args.occu) scriptArgs.push("--occu", args.occu)
    if (args.add_note) scriptArgs.push("--add-note", args.add_note)
    return runWrite("gedcom_set", scriptArgs)
  },
})
