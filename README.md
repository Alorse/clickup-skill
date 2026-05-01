# ClickUp Skill

ClickUp API wrapper for Claude Code and standalone CLI use.

## First-Time Setup

Set these environment variables in your shell (e.g. `~/.zshrc` or `~/.bashrc`):

```bash
export CLICKUP_API_KEY="pk_YOUR_TOKEN_HERE"
export CLICKUP_TEAM_ID="529"   # optional; defaults to 529 (Ventura)
```

Then reload your shell:

```bash
source ~/.zshrc
```

### Finding your ClickUp Team ID

Run the skill and ask for workspaces, or call directly:

```bash
python3 ~/.claude/skills/clickup/scripts/clickup.py workspace spaces
```

## Usage

See [SKILL.md](SKILL.md) for the full command reference.

Quick examples:

```bash
# Tasks
python3 ~/.claude/skills/clickup/scripts/clickup.py task get 86c9k6jxf
python3 ~/.claude/skills/clickup/scripts/clickup.py task list 901522906120

# Time tracking (uses CLICKUP_TEAM_ID)
python3 ~/.claude/skills/clickup/scripts/clickup.py time status
python3 ~/.claude/skills/clickup/scripts/clickup.py time start 86c9k6jxf

# Override team per command
python3 ~/.claude/skills/clickup/scripts/clickup.py time status --team 12345
python3 ~/.claude/skills/clickup/scripts/clickup.py hierarchy --team 12345
```
