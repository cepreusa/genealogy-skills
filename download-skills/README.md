# download-skills — ready-to-upload skill ZIPs

These four `.zip` files are the skills, packaged for **uploading to Claude
Desktop or claude.ai** (each archive is one skill folder with its `SKILL.md` at
the top level — the layout the Skills uploader expects).

## How to use

1. Download the ZIP(s) you want (open the file → **Download raw file**).
2. In Claude: **Settings → Capabilities → Code execution** (turn it on).
3. **Customize → Skills → “+” → Upload a skill** — upload each ZIP.

`gedcom-reader` is the core (read + build/edit). Add `gedcom-report`,
`gedcom-tree`, and `genealogy-research` for dashboards, the interactive viewer,
and research guidance.

## Don't edit these by hand

They are build artifacts of the skills in [`../skills/`](../skills/). To update
them after changing a skill, run from the repo root:

```bash
./install.sh zip
```

then commit the refreshed ZIPs. (CI checks that these archives match the source
skills, so out-of-date ZIPs will fail the build.)
