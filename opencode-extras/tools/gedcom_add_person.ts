import { tool } from "@opencode-ai/plugin"
import { runWrite, resolveGedPath } from "./_gedcom.ts"

export default tool({
  description:
    "Add a new person (INDI) to a GEDCOM tree. Allocates a free @Ixx@ id and " +
    "writes name, sex, birth/death and optional occupation/note. A timestamped " +
    "backup is made and the file is re-parsed as a sanity check. Returns JSON " +
    "with the new person's id. To connect this person to parents/spouse/" +
    "children, call gedcom_link afterwards. Cyrillic and other scripts are " +
    "fully supported. Dates use GEDCOM form, e.g. '9 FEB 1960', 'ABT 1890', '1962'.",
  args: {
    file: tool.schema.string().describe("Path to the .ged file"),
    given: tool.schema
      .string()
      .optional()
      .describe("Given name(s), e.g. 'Иван' or 'John Robert'"),
    surname: tool.schema.string().optional().describe("Surname / family name"),
    sex: tool.schema
      .string()
      .optional()
      .describe("Sex: 'M', 'F' or 'U' (unknown)"),
    birt_date: tool.schema
      .string()
      .optional()
      .describe("Birth date in GEDCOM form, e.g. '9 FEB 1960'"),
    birt_place: tool.schema.string().optional().describe("Birth place"),
    deat_date: tool.schema
      .string()
      .optional()
      .describe("Death date in GEDCOM form"),
    deat_place: tool.schema.string().optional().describe("Death place"),
    occu: tool.schema.string().optional().describe("Occupation"),
    note: tool.schema.string().optional().describe("Free-text note"),
  },
  async execute(args, context) {
    const file = await resolveGedPath(args.file, context.worktree)
    const scriptArgs = [file, "add-person"]
    if (args.given) scriptArgs.push("--given", args.given)
    if (args.surname) scriptArgs.push("--surname", args.surname)
    if (args.sex) scriptArgs.push("--sex", args.sex)
    if (args.birt_date) scriptArgs.push("--birt-date", args.birt_date)
    if (args.birt_place) scriptArgs.push("--birt-place", args.birt_place)
    if (args.deat_date) scriptArgs.push("--deat-date", args.deat_date)
    if (args.deat_place) scriptArgs.push("--deat-place", args.deat_place)
    if (args.occu) scriptArgs.push("--occu", args.occu)
    if (args.note) scriptArgs.push("--note", args.note)
    return runWrite("gedcom_add_person", scriptArgs)
  },
})
