# ClickUp Skill

ClickUp API wrapper as a CLI skill for AI agents and standalone use. Replaces the ClickUp MCP
with a fraction of the token cost.

## Why This Instead of the ClickUp MCP?

The ClickUp MCP registers **~50 tools** (~17k tokens) in every agent session, consuming a huge
chunk of the initial context window whether you need ClickUp or not. That means less room for
your actual prompts, files, and instructions.

This skill defers to a lightweight Python CLI that consumes only **~70 tokens** (the skill
descriptor), loaded on demand when you actually invoke ClickUp operations.

| Aspect | MCP | Skill (this) |
|--------|-----|-------------|
| Token cost per session | ~17k (fixed, always loaded) | ~70 (on demand) |
| Context savings | — | **~17k tokens freed** |
| Monthly savings (500 sessions) | — | **~8.5M tokens** |
| Dependency | Node.js + MCP server | Python 3 + stdlib only |
| Startup latency | MCP handshake on init | Zero (lazy) |

> **Bottom line**: Each MCP tool burns ~300 tokens just for its description. Registering 50 of
> them devours ~17k tokens from your usable context before you've said a word. This skill gives
> you the same ClickUp API access at **0.4% of the token cost**, preserving context for what
> matters — your instructions and data.

## Coverage Status

The CLI wraps the [ClickUp REST API v2](https://clickup.com/api). Here's what's implemented vs.
the original MCP:

| Category | MCP Tools | CLI Commands |
|----------|-----------|-------------|
| **Tasks** | `create`, `get`, `update`, `delete`, `filter`, `move` | `task get/create/update/delete/list/search/move` |
| **Comments** | `create`, `get`, `get_threaded` | `comment list/add` |
| **Time Tracking** | `start`, `stop`, `get_current`, `get_entries`, `get_task_entries`, `get_task_time_in_status`, `get_bulk_time_in_status`, `add` | `time start/stop/status/entries/add/report` |
| **Tags** | `add`, `remove` | `tag add/remove` |
| **Dependencies** | `add`, `remove` | `dependency add/remove` |
| **Custom Fields** | `get` | `custom-fields` |
| **Hierarchy** | `workspace`, `space`, `folder`, `list` | `workspace`, `hierarchy`, `space`, `folder`, `list get/create/fields` |
| **Users** | `find_member`, `get_members` | `user info/find`, `workspace members` |
| **Task Links** | `add`, `remove` | — |
| **Task Lists** | `add_to_list`, `remove_from_list` | — |
| **Reminders** | `create`, `search`, `update` | — |
| **Chat** | `get_channels`, `get_messages`, `get_replies`, `send` | — |
| **Documents** | `create`, `create_page`, `get_pages`, `list_pages`, `update_page` | — |
| **Folders/Lists** | `update`, `create_folder`, `create_list`, `create_list_in_folder` | `list create` |
| **Attachments** | `attach_file` | — |
| **Time Entry** | `get` (single) | — |

Operations marked as — are not yet implemented.

## First-Time Setup

Set these environment variables in your shell profile (e.g. `~/.zshrc` or `~/.bashrc`):

```bash
export CLICKUP_API_KEY="pk_YOUR_TOKEN_HERE"
export CLICKUP_TEAM_ID="529"   # optional; defaults to 529 (Ventura)
```

Then reload:

```bash
source ~/.zshrc
```

### Finding your ClickUp Team ID

```bash
python3 scripts/clickup.py workspace spaces
```

## Usage

See [SKILL.md](SKILL.md) for the full command reference.

Quick examples:

```bash
python3 scripts/clickup.py task get 86c9k6jxf
python3 scripts/clickup.py task list 901522906120
python3 scripts/clickup.py time status
python3 scripts/clickup.py time start 86c9k6jxf
python3 scripts/clickup.py hierarchy --team 12345
```
