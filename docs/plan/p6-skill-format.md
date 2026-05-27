# P6 — Forge SKILL.md Output Format

**Target:** v0.4.5
**Source:** [design doc supplement, section 2](../design/v0-4-2-design.md#skillmd-格式锻造产物的目标规格)

## Current State

`ToolForge` and `export_as_skill` produce single Python function files. No metadata, usage instructions, or dependency declarations. The 12 forged tools in `tools/forged/` have inconsistent structures.

## Target Format

Adopt Mini-Agent's SKILL.md convention as the forge output specification:

```
skill-name/
├── SKILL.md              # YAML frontmatter + markdown body
├── scripts/              # executable code
├── references/           # reference materials
└── assets/               # output templates
```

### SKILL.md structure

```markdown
---
name: skill-name
description: One-line summary
version: 1.0.0
created: 2026-05-26
dependencies: []
parameters:
  param_name:
    type: string
    description: What this parameter does
---

# {Skill Name}

## Description
...

## Usage
...

## Examples
...
```

## Implementation

### Modified: `tain_agent/tools/forge.py` or `export_as_skill`

- `export_as_skill(tool_name)` now produces a `skill-name/` directory
- Auto-generates SKILL.md from tool metadata (name, description, parameters, docstring)
- Pulls docstring sections into SKILL.md body
- Copies tool source to `scripts/`
- Creates empty `references/` and `assets/` directories

### Modified: `tain_agent/tools/skill_loader.py` (new or extend existing loader)

- Parse SKILL.md frontmatter
- Progressive disclosure: Level 1 metadata for tool listing, Level 2 full content for invocation

## Verification

- `export_as_skill("existing_tool")` produces valid SKILL.md directory
- SKILL.md passes frontmatter parsing
- Agent can load and execute skill from SKILL.md directory
- Existing forged tools can be migrated to SKILL.md format
