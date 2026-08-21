---
name: clickup
description: |
  ClickUp API access via prebuilt script. Use when the user mentions:
  - ClickUp tasks, subtasks, lists, folders, spaces, workspaces
  - time tracking, comments, reminders, dependencies, tags
  - creating/updating/deleting ClickUp items
  - searching or filtering ClickUp tasks
---

# ClickUp CLI

Script: `python3 ~/.claude/skills/clickup/scripts/clickup.py <cmd> [args]`

Token is read from `$CLICKUP_API_KEY`. Set it in your shell (e.g. `~/.zshrc`) for global access.

**Workspace (team) ID.** Nothing is hardcoded: commands that need a workspace take
it from `--team`, else `$CLICKUP_TEAM_ID`, else a live lookup of the workspaces the
token can reach. The lookup only decides when there is exactly one — with several
the script lists them and stops, so set `CLICKUP_TEAM_ID` once to skip both the
prompt and the extra request.

**Custom task IDs (e.g. `ABC-1234`) work anywhere a `<task_id>` is accepted.** An ID
shaped `PREFIX-NUMBER` is resolved via `custom_task_ids=true&team_id=<workspace>`;
hyphen-free hashes like `86c9k6jxf` are used as-is. No flag needed.

Other IDs are looked up, never memorized: `list find <name>` for a list,
`user find <name-or-email>` for a person, `hierarchy` for the whole tree.

## Commands

### Tasks
```
task get <id>                  # Shows list/folder/space IDs and parent
task create [list_id] --name <n> [--description <d>] [--markdown <md>] [--parent <task_id>] [--assignees <ids>] [--priority <1-4>] [--due-date <YYYY-MM-DD>] [--tags <t1,t2>] [--status <s>]
task update <id> [--name <n>] [--description <d>] [--markdown <md>] [--status <s>] [--priority <1-4>] [--due-date <YYYY-MM-DD>] [--assignees <ids>]
task delete <id>
task list <list_id> [--statuses <s1,s2>] [--include-closed]
task search [--team <id>] [--assignees <ids>] [--statuses <s1,s2>] [--include-closed] [--space-ids] [--folder-ids] [--list-ids] [--due-date-gt <date>] [--due-date-lt <date>]
task move <task_id> --list-id <list_id>
```

**Creating subtasks — no list_id needed.** With `--parent`, `list_id` can be
omitted: the script resolves it from the parent task (and resolves a custom parent
ID to its native one, which the create endpoint requires).
```bash
python3 ~/.claude/skills/clickup/scripts/clickup.py task create --parent 86ca6t7y8 --name "Subtask title" --markdown "..."
```
If you do need a list_id explicitly, `task get <id>` prints it (`List: name (id: ...)`),
or resolve one by name with `list find <name>`.

### Comments
```
comment list <task_id>
comment add <task_id> <text> [--notify-all] [--mention <ids-names-or-emails>]
```

**Tagging users (@mentions):** a plain `@Name` in the text does NOT notify anyone —
ClickUp stores it as literal text. To tag someone for real, pass `--mention` with
their user ID, name, or email (comma-separated for several). Names and emails are
resolved against workspace members; an unmatched or ambiguous one aborts, so nobody
is silently left un-notified — pass a numeric ID to disambiguate.
```bash
python3 ~/.claude/skills/clickup/scripts/clickup.py comment add 86ca141ey "Summary text" --mention "Jane Doe"
python3 ~/.claude/skills/clickup/scripts/clickup.py comment add 86ca141ey "Summary" --mention jane.doe@example.com
python3 ~/.claude/skills/clickup/scripts/clickup.py comment add 86ca141ey "Summary" --mention 12345678,"John Roe"
```

### Folders, Lists, Spaces
```
hierarchy [--space <id>]       # View workspace tree
space get <id>
folder get <id>
list get <list_id>
list find <name>               # Resolve a list name to its list_id (whole workspace)
list create <space_id> --name <n> [--content <c>] [--folder <folder_id>]
list fields <list_id>          # Custom field definitions
```

### Users & Workspace
```
user info                      # Current user
user find <name-or-email>      # Find user ID
workspace members [--team <id>]
workspace spaces [--team <id>]
```

### Tags & Dependencies
```
tag add <task_id> <tag_name>
tag remove <task_id> <tag_name>
dependency add <task_id> --depends-on <id> [--type waiting_on|blocking]
```

### Time Tracking
```
time status                    # Current running timer
time start <task_id> [--description <d>] [--billable]
time stop [--description <d>]
time add <task_id> --start <YYYY-MM-DD HH:MM> [--duration <1h 30m>] [--end <YYYY-MM-DD HH:MM>]
time entries <task_id>
time report --from <YYYY-MM-DD> --to <YYYY-MM-DD> [--assignee <id>]
```

### Custom Fields
```
custom-fields <list_id>
```

## Examples

```bash
python3 ~/.claude/skills/clickup/scripts/clickup.py task get 86c9k6jxf
python3 ~/.claude/skills/clickup/scripts/clickup.py user find jane
python3 ~/.claude/skills/clickup/scripts/clickup.py list find "Sprint Backlog"
python3 ~/.claude/skills/clickup/scripts/clickup.py comment list 86c9k6jxf
```

Priority: `1`=urgent, `2`=high, `3`=normal, `4`=low.
