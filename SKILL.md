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

Token is read from `$CLICKUP_API_KEY` (set in settings.json).

## Commands

### Tasks
```
task get <id>
task create <list_id> --name <n> [--description <d>] [--markdown <md>] [--parent <task_id>] [--assignees <ids>] [--priority <1-4>] [--due-date <YYYY-MM-DD>] [--tags <t1,t2>] [--status <s>]
task update <id> [--name <n>] [--description <d>] [--markdown <md>] [--status <s>] [--priority <1-4>] [--due-date <YYYY-MM-DD>] [--assignees <ids>]
task delete <id>
task list <list_id> [--statuses <s1,s2>] [--include-closed]
```

### Comments
```
comment list <task_id>
comment add <task_id> <text> [--notify-all]
```

### Folders, Lists, Spaces
```
hierarchy [--space <id>]       # View workspace tree
space get <id>
folder get <id>
list get <list_id>
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
python3 ~/.claude/skills/clickup/scripts/clickup.py user find alex
python3 ~/.claude/skills/clickup/scripts/clickup.py folder 7363089
python3 ~/.claude/skills/clickup/scripts/clickup.py comment list 86c9k6jxf
```

## Key IDs

| ID | Name |
|----|------|
| 529 | Ventura (workspace) |
| 3215874 | Teams (space) |
| 7363089 | Across Departments (folder) |
| 901522906120 | vMeets (list) |
| 2440239 | Alfredo Ortegón (user) |
| 88724563 | Alex Callisaya (user) |

Priority: `1`=urgent, `2`=high, `3`=normal, `4`=low.
