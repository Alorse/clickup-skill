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

Supply the personal API token **out of band** as `CLICKUP_API_TOKEN`, or have
an operator provision a private token file owned by the invoking user (mode
`0600`). Do not put credentials in shell commands, examples, shell history, or
agent prompts. `--token-file PATH` takes a **path**, never a token, and must
precede the command. It overrides the environment. Symlinks, nonregular files,
files owned by another user, and any group/other permissions are refused.

`CLICKUP_API_KEY` is no longer accepted; migrate to `CLICKUP_API_TOKEN`.
Upstream did not have an argv-token option; this fork also refuses `--token`
and `--api-key` (and rejects the active token if accidentally supplied in argv).
`CLICKUP_TEAM_ID` remains an optional numeric workspace ID.

### Command on PATH (optional)

The script is executable (shebang included), so you can symlink it once and use the short `clickup` command anywhere — same pattern the examples in SKILL.md use:

```bash
ln -s "$(pwd)/scripts/clickup.py" ~/.local/bin/clickup
```

### Workspace (team) ID

`CLICKUP_TEAM_ID` is optional. Commands that need a workspace resolve it from
`--team`, then `$CLICKUP_TEAM_ID`, then a live lookup of the workspaces your token
can reach. If the token sees exactly one workspace, that one is used and you never
have to configure anything. If it sees several or none, it returns a JSON error rather than guessing.
Set the variable or use `--team` to select a workspace and save a lookup.

## Security and agent contract

- All successful commands emit **one JSON value**, including full task details
  (description and custom fields). Errors are JSON on stderr; stdout is empty
  on failure. `--help` is human-readable. This replaces upstream's text output.
- Credentials go only in `Authorization` to the fixed
  `https://api.clickup.com/api/v2` origin. TLS certificate/hostname verification
  stays enabled; environment proxies are ignored; **all redirects are refused**.
  No API-base override, subprocesses, shell/eval calls, or application file writes.
- Requests have a 30-second socket timeout. No automatic retries, especially for
  writes: an ambiguous failure may already have committed a change. HTTP bodies,
  URLs, reason phrases and tracebacks are never dumped. Echoed active credentials
  are redacted in JSON (including object keys); credentials in URL/body are refused.
- Exit codes: `0` success; `2` arguments/credentials; `3` HTTP/redirect failure;
  `4` rate limited (429); `5` transport/TLS/timeout; `6` invalid API response or
  pagination/internal failure. Errors include `http_status` when applicable;
  429 also includes a safe numeric `retry_after` in seconds when supplied.
- Read commands only issue GETs. Only explicit write commands can issue other
  methods: `task create/update/delete/move`, `comment add`, `list create`,
  `tag add/remove`, `dependency add/remove`, `time start/stop/add`.
  **The calling agent must obtain explicit human approval before invoking any
  of these.** The CLI cannot verify human approval and does not turn reads into writes.
- Native task IDs are alphanumeric; custom IDs use `PREFIX-NUMBER`; resource/user
  IDs are numeric. Invalid IDs, negative page/cursor values and malformed dates
  fail without echoing their values. API response IDs used in follow-up paths are
  validated too.

### Pagination

`task list` and `task search` fetch **all pages by default**, keeping filters on
every request. They stop on `last_page: true` or an empty page, not a short page.
`--page N` explicitly requests one zero-based page and includes `complete` and
`next_page` in the result. These keys describe completion of traversal, not a
transactional snapshot of a changing backlog.

`comment list` fetches all top-level task comments, using both the oldest
comment's `date` and `id` as the next `start`/`start_id` cursor. `--single-page`
returns `next_cursor`; pass it back using `--start MS --start-id ID` to resume.
Threaded replies are not included. Comments and tasks are deduplicated by ID.
Responses are limited to 16 MiB per page and traversals to 10,000 pages; repeated
pages/cursors or exceeded limits fail visibly with no partial success output.
Results are aggregated in memory; large traversals may need substantial memory.
Other legacy collection commands are not promised exhaustive pagination.

## Offline verification

```bash
python3 -m py_compile scripts/clickup.py
python3 -m unittest                         # unittest discovery, no live API
python3 -m unittest tests.test_clickup.TokenLeakTests
python3 -m tests.mutations                  # in-memory mutations; source untouched
```

Tests use urllib mocks plus a loopback-only redirect server, synthetic tokens,
and a process-wide guard rejecting non-loopback connects. See
[SECURITY_REVIEW.md](SECURITY_REVIEW.md) for baseline findings and scope.

## Usage

See [SKILL.md](SKILL.md) for the full command reference.

Quick examples:

```bash
python3 scripts/clickup.py task get 86c9k6jxf
python3 scripts/clickup.py task list 123456 --statuses "open,in progress" --include-closed --assignees 789
python3 scripts/clickup.py task search --team 123 --assignees 789
python3 scripts/clickup.py comment list 86c9k6jxf
python3 scripts/clickup.py --token-file /secure/clickup-token task get 86c9k6jxf
python3 scripts/clickup.py time status
python3 scripts/clickup.py hierarchy --team 12345
```
