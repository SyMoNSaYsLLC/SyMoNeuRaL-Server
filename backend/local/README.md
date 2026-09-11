# backend/local/

> **Write this paragraph.** What is this surface for, who calls it, and what will bite
> someone changing it? The table below is generated and cannot answer any of those.
> Delete this block when you have.

<!-- generated: do not edit below -->

## Operations — 8

|  | path | what it does |
|---|---|---|
| GET | `/local/coder/file` |  |
| GET | `/local/coder/history` |  |
| GET | `/local/coder/journal` | The audit trail. Gated like every other read -- it names paths. |
| GET | `/local/coder/ls` |  |
| GET | `/local/coder/status` | What the surface is, plus each gate separately. |
| POST | `/local/intake` | Set one assignment's box in INTAKE.md: `[ ]`, `[x]` ready, or `[-]` drop |
| GET | `/local/progress` | Serve run/progress.html from this origin, so the buttons above are same- |
| POST | `/local/tasknote` | Append one `note:` line to a task's indented detail block in PROJECT-TAS |

<!-- end generated -->
