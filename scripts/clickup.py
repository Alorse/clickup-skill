#!/usr/bin/env python3
"""
ClickUp CLI — token-efficient wrapper around the REST API.
Usage: python3 clickup.py <command> [args...]

Commands:
  task get <id>
  task create <list_id> --name <n> [--description <d>] [--assignees <ids>] [--priority <1-4>] [--due-date <YYYY-MM-DD>] [--tags <t1,t2>] [--status <s>]
  task update <id> [--name <n>] [--description <d>] [--status <s>] [--priority <1-4>] [--due-date <YYYY-MM-DD>] [--assignees <ids>]
  task delete <id>
  task list <list_id> [--statuses <s1,s2>] [--include-closed] [--page <n>]
  task search [--team <id>] [--assignees <ids>] [--statuses <s1,s2>] [--include-closed]

  comment list <task_id>
  comment add <task_id> <text> [--notify-all]

  hierarchy [--space <id>]
  space get <id>
  folder get <id>
  list get <id>
  list create <space_id> --name <n> [--content <c>]
  list fields <list_id>

  user info
  user find <name-or-email>

  workspace members [--team <id>]
  workspace spaces [--team <id>]

  tag add <task_id> <tag_name>
  tag remove <task_id> <tag_name>

  dependency add <task_id> --depends-on <id> [--type waiting_on|blocking]
  dependency remove <task_id> --depends-on <id> [--type waiting_on|blocking]

  time status
  time start <task_id> [--description <d>] [--billable]
  time stop [--description <d>]
  time add <task_id> --start <YYYY-MM-DD HH:MM> [--duration <Xd Ym>] [--end <YYYY-MM-DD HH:MM>]
  time entries <task_id>
  time report --from <YYYY-MM-DD> --to <YYYY-MM-DD> [--assignee <id>]

  custom-fields <list_id>
"""

import os
import sys
import json
import urllib.request
import urllib.error
import argparse
from datetime import datetime, timezone

API_BASE = "https://api.clickup.com/api/v2"
DEFAULT_TEAM = "529"  # Ventura

def api(path, method="GET", data=None, params=None):
    token = os.environ.get("CLICKUP_API_KEY", "")
    if not token:
        print("Error: CLICKUP_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    url = f"{API_BASE}{path}"
    if params:
        qs = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
        url += f"?{qs}"

    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", token)
    if data is not None:
        req.add_header("Content-Type", "application/json")
        body = json.dumps(data).encode()
    else:
        body = None

    try:
        with urllib.request.urlopen(req, data=body, timeout=30) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        try:
            detail = json.loads(err)
        except json.JSONDecodeError:
            detail = {"raw": err}
        print(f"HTTP {e.code}: {detail}", file=sys.stderr)
        sys.exit(1)

def date_to_epoch(d):
    """Convert YYYY-MM-DD to epoch ms."""
    dt = datetime.strptime(d, "%Y-%m-%d")
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)

def dt_to_epoch(dt_str):
    """Convert YYYY-MM-DD HH:MM to epoch ms."""
    dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)

def parse_duration(dur_str):
    """Parse '1h 30m' or '90m' to minutes."""
    import re
    total = 0
    m = re.search(r"(\d+)h", dur_str)
    if m:
        total += int(m.group(1)) * 60
    m = re.search(r"(\d+)m", dur_str)
    if m:
        total += int(m.group(1))
    return total * 60 * 1000  # epoch ms

# ─── Tasks ────────────────────────────────────────────────────────────────

def cmd_task(args):
    sub = args.sub
    if sub == "get":
        res = api(f"/task/{args.task_id}")
        t = res
        print(f"ID: {t['id']}")
        print(f"Name: {t['name']}")
        print(f"Status: {t['status']['status']}")
        p = t.get("priority") or {}
        print(f"Priority: {p.get('priority', 'none')}")
        due = t.get("due_date")
        if due:
            print(f"Due: {datetime.fromtimestamp(int(due)/1000, tz=timezone.utc).strftime('%Y-%m-%d')}")
        print(f"Creator: {t.get('creator',{}).get('username','?')}")
        print(f"Assignees: {', '.join(a['username'] for a in t.get('assignees',[]))}")
        print(f"Tags: {', '.join(g['name'] for g in t.get('tags',[]))}")
        print(f"List: {t.get('list',{}).get('name','?')}")
        print(f"Folder: {t.get('folder',{}).get('name','?')}")
        print(f"URL: https://app.clickup.com/t/{t['id']}")
        desc = t.get("description", "")
        if desc:
            print(f"\nDescription:\n{desc}")

    elif sub == "create":
        payload = {"name": args.name}
        if args.description:
            payload["description"] = args.description
        if args.description_file:
            with open(args.description_file) as f:
                payload["markdown_content"] = f.read()
        if args.assignees:
            payload["assignees"] = [int(x) for x in args.assignees.split(",")]
        if args.priority is not None:
            payload["priority"] = int(args.priority)
        if args.due_date:
            payload["due_date"] = date_to_epoch(args.due_date)
        if args.tags:
            payload["tags"] = args.tags.split(",")
        if args.status:
            payload["status"] = args.status
        if args.parent:
            payload["parent"] = args.parent
        res = api(f"/list/{args.list_id}/task", method="POST", data=payload)
        print(f"Created: {res.get('id')} — {res.get('name')}")

    elif sub == "update":
        payload = {}
        if args.name:
            payload["name"] = args.name
        if args.markdown_description:
            payload["markdown_content"] = args.markdown_description
        elif args.description:
            payload["description"] = args.description
        if args.description_file:
            with open(args.description_file) as f:
                payload["markdown_content"] = f.read()
        if args.status:
            payload["status"] = args.status
        if args.priority is not None:
            payload["priority"] = int(args.priority)
        if args.due_date:
            payload["due_date"] = date_to_epoch(args.due_date)
        if args.assignees:
            payload["assignees"] = [int(x) for x in args.assignees.split(",")]
        if not payload:
            print("Nothing to update")
            return
        res = api(f"/task/{args.task_id}", method="PUT", data=payload)
        print(f"Updated: {res.get('id')}")

    elif sub == "delete":
        api(f"/task/{args.task_id}", method="DELETE")
        print(f"Deleted: {args.task_id}")

    elif sub == "list":
        params = {}
        if args.statuses:
            params["statuses"] = args.statuses
        if args.include_closed:
            params["include_closed"] = "true"
        if args.page is not None:
            params["page"] = str(args.page)
        res = api(f"/list/{args.list_id}/task", params=params)
        tasks = res.get("tasks", [])
        print(f"Tasks ({len(tasks)}):")
        for t in tasks:
            due = ""
            if t.get("due_date"):
                due = f" due:{datetime.fromtimestamp(int(t['due_date'])/1000).strftime('%m-%d')}"
            print(f"  {t['id']} [{t['status']['status']}]{due} — {t['name'][:80]}")

    elif sub == "search":
        # Filter tasks by list. Use hierarchy to find all lists first if needed.
        print("Use 'task list <list_id>' to view tasks in a specific list.")
        print("Use 'hierarchy' to discover list IDs.")

# ─── Comments ─────────────────────────────────────────────────────────────

def cmd_comment(args):
    if args.sub == "list":
        res = api(f"/task/{args.task_id}/comment")
        for c in res.get("comments", []):
            u = c.get("user", {})
            date = datetime.fromtimestamp(int(c["date"])/1000).strftime("%Y-%m-%d %H:%M")
            print(f"[{date}] {u.get('username','?')}: {c.get('comment_text','')}")
    elif args.sub == "add":
        data = {"comment_text": args.text}
        if args.notify_all:
            data["notify_all"] = True
        res = api(f"/task/{args.task_id}/comment", method="POST", data=data)
        print(f"Comment added: {res.get('id')}")

# ─── Hierarchy ────────────────────────────────────────────────────────────

def cmd_hierarchy(args):
    if args.space:
        res = api(f"/space/{args.space}?include_lists=true")
        print(f"Space: {res['name']} ({res['id']})")
        for f in res.get("folders", []):
            print(f"  └ Folder: {f['name']} ({f['id']})")
            for l in f.get("lists", []):
                print(f"      └ List: {l['name']} ({l['id']})")
        for l in res.get("lists", []):
            print(f"  └ (root) List: {l['name']} ({l['id']})")
    else:
        res = api(f"/team/{DEFAULT_TEAM}/space")
        for s in res.get("spaces", []):
            print(f"Space: {s['name']} ({s['id']})")

def cmd_space(args):
    res = api(f"/space/{args.space_id}")
    print(f"ID: {res['id']}\nName: {res['name']}")

def cmd_folder(args):
    res = api(f"/folder/{args.folder_id}")
    print(f"Folder: {res['name']} ({res['id']})")
    for l in res.get("lists", []):
        print(f"  List: {l['name']} ({l['id']})")

def cmd_list(args):
    if args.sub == "get":
        res = api(f"/list/{args.list_id}")
        print(f"ID: {res['id']}\nName: {res['name']}\nContent: {res.get('content','')}")
    elif args.sub == "create":
        data = {"name": args.name}
        if args.content:
            data["content"] = args.content
        if args.folder:
            res = api(f"/folder/{args.folder}/list", method="POST", data=data)
        else:
            res = api(f"/space/{args.space_id}/list", method="POST", data=data)
        print(f"Created list: {res.get('id')} — {res.get('name')}")
    elif args.sub == "fields":
        res = api(f"/list/{args.list_id}/field")
        for f in res.get("fields", []):
            print(f"  {f['name']} ({f['id']}) type={f['type']}")

# ─── User ─────────────────────────────────────────────────────────────────

def cmd_user(args):
    if args.sub == "info":
        res = api("/user")
        u = res["user"]
        print(f"ID: {u['id']}\nName: {u['username']}\nEmail: {u['email']}")
    elif args.sub == "find":
        res = api("/team")
        q = args.name_or_email.lower()
        found = []
        for t in res.get("teams", []):
            for m in t.get("members", []):
                u = m.get("user", {})
                name = u.get("username") or ""
                email = u.get("email") or ""
                if q in name.lower() or q in email.lower():
                    found.append((t["name"], u["id"], u["username"], u.get("email", "")))
        for team, uid, name, email in found:
            print(f"  [{team}] {name} ({email}) — ID: {uid}")

# ─── Workspace ────────────────────────────────────────────────────────────

def cmd_workspace(args):
    tid = args.team or DEFAULT_TEAM
    if args.sub == "members":
        res = api("/team")
        for t in res.get("teams", []):
            if str(t["id"]) == str(tid):
                for m in t.get("members", []):
                    u = m.get("user", {})
                    print(f"  {u.get('id')}: {u.get('username','?')} ({u.get('email','?')})")
    elif args.sub == "spaces":
        res = api(f"/team/{tid}/space")
        for s in res.get("spaces", []):
            print(f"  {s['id']}: {s['name']}")

# ─── Tags ─────────────────────────────────────────────────────────────────

def cmd_tag(args):
    if args.sub == "add":
        api(f"/task/{args.task_id}/tag/{args.tag_name}", method="POST")
        print(f"Tag '{args.tag_name}' added to {args.task_id}")
    elif args.sub == "remove":
        api(f"/task/{args.task_id}/tag/{args.tag_name}", method="DELETE")
        print(f"Tag '{args.tag_name}' removed from {args.task_id}")

# ─── Dependencies ─────────────────────────────────────────────────────────

def cmd_dependency(args):
    t = args.type or "waiting_on"
    if args.sub == "add":
        data = {"depends_on": args.depends_on} if t == "waiting_on" else {"dependency_of": args.depends_on}
        api(f"/task/{args.task_id}/dependency", method="POST", data=data)
        print(f"Dependency added: {args.task_id} {t} {args.depends_on}")
    elif args.sub == "remove":
        api(f"/task/{args.task_id}/dependency?depends_on={args.depends_on}", method="DELETE")
        print(f"Dependency removed")

# ─── Time Tracking ────────────────────────────────────────────────────────

def cmd_time(args):
    tid = DEFAULT_TEAM
    if args.sub == "status":
        res = api(f"/team/{tid}/time_entries/current")
        if res.get("data"):
            e = res["data"]
            print(f"Running on task {e.get('task',{}).get('id','?')}: {e.get('description','')}")
        else:
            print("No timer running")
    elif args.sub == "start":
        data = {"task_id": args.task_id}
        if args.description:
            data["description"] = args.description
        if args.billable:
            data["billable"] = True
        res = api(f"/team/{tid}/time_entries/start", method="POST", data=data)
        print(f"Timer started on {args.task_id}")
    elif args.sub == "stop":
        data = {}
        if args.description:
            data["description"] = args.description
        res = api(f"/team/{tid}/time_entries/stop", method="POST", data=data)
        print("Timer stopped")
    elif args.sub == "add":
        start_ms = dt_to_epoch(args.start)
        data = {"task_id": args.task_id, "start": str(start_ms)}
        if args.duration:
            data["duration"] = str(parse_duration(args.duration))
        elif args.end:
            end_ms = dt_to_epoch(args.end)
            data["end"] = str(end_ms)
            data["duration"] = str(end_ms - start_ms)
        api(f"/team/{tid}/time_entries", method="POST", data=data)
        print(f"Time entry added to {args.task_id}")
    elif args.sub == "entries":
        res = api(f"/task/{args.task_id}/time_entries")
        for e in res.get("data", []):
            dur = int(e.get("duration", 0)) // 1000
            h, m = dur // 3600, (dur % 3600) // 60
            desc = e.get("description", "") or ""
            print(f"  {h}h {m:02d}m — {desc}")
    elif args.sub == "report":
        from_ms = date_to_epoch(args.from_date)
        to_ms = date_to_epoch(args.to_date)
        params = {"start_date": str(from_ms), "end_date": str(to_ms)}
        if args.assignee:
            params["assignee"] = args.assignee
        res = api(f"/team/{tid}/time_entries", params=params)
        total = 0
        for e in res.get("data", []):
            dur = int(e.get("duration", 0)) // 1000
            h, m = dur // 3600, (dur % 3600) // 60
            desc = e.get("description", "") or ""
            uid = e.get("user", {}).get("id", "?")
            print(f"  [{uid}] {h}h {m:02d}m — {desc}")
            total += dur
        th, tm = total // 3600, (total % 3600) // 60
        print(f"\nTotal: {th}h {tm:02d}m")

# ─── Custom Fields ────────────────────────────────────────────────────────

def cmd_custom_fields(args):
    res = api(f"/list/{args.list_id}/field")
    for f in res.get("fields", []):
        print(f"  {f['name']} ({f['id']})")
        print(f"    Type: {f['type']}")
        if f.get("type_config", {}).get("options"):
            for o in f["type_config"]["options"]:
                print(f"    Option: {o.get('name','')} = {o.get('orderindex','')}")

# ─── Main ─────────────────────────────────────────────────────────────────

def main():
    import urllib.parse  # late import for api()

    parser = argparse.ArgumentParser(description="ClickUp CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    # task
    tp = sub.add_parser("task")
    tsp = tp.add_subparsers(dest="sub", required=True)
    tsp.add_parser("get").add_argument("task_id")
    tc = tsp.add_parser("create")
    tc.add_argument("list_id"); tc.add_argument("--name", required=True); tc.add_argument("--description")
    tc.add_argument("--description-file"); tc.add_argument("--parent"); tc.add_argument("--assignees")
    tc.add_argument("--priority", type=int); tc.add_argument("--due-date")
    tc.add_argument("--tags"); tc.add_argument("--status")
    tu = tsp.add_parser("update")
    tu.add_argument("task_id"); tu.add_argument("--name"); tu.add_argument("--description")
    tu.add_argument("--markdown-description"); tu.add_argument("--description-file")
    tu.add_argument("--status"); tu.add_argument("--priority", type=int); tu.add_argument("--due-date")
    tu.add_argument("--assignees")
    tsp.add_parser("delete").add_argument("task_id")
    tl = tsp.add_parser("list")
    tl.add_argument("list_id"); tl.add_argument("--statuses"); tl.add_argument("--include-closed", action="store_true")
    tl.add_argument("--page", type=int)
    ts = tsp.add_parser("search")
    ts.add_argument("--team", default=DEFAULT_TEAM); ts.add_argument("--assignees")
    ts.add_argument("--statuses"); ts.add_argument("--include-closed", action="store_true")

    # comment
    cp = sub.add_parser("comment")
    csp = cp.add_subparsers(dest="sub", required=True)
    csp.add_parser("list").add_argument("task_id")
    ca = csp.add_parser("add")
    ca.add_argument("task_id"); ca.add_argument("text"); ca.add_argument("--notify-all", action="store_true")

    # hierarchy
    hp = sub.add_parser("hierarchy")
    hp.add_argument("--space")

    # space/folder/list
    sp = sub.add_parser("space"); sp.add_argument("space_id")
    fp = sub.add_parser("folder"); fp.add_argument("folder_id")
    lp = sub.add_parser("list")
    lsp = lp.add_subparsers(dest="sub", required=True)
    lsp.add_parser("get").add_argument("list_id")
    lc = lsp.add_parser("create")
    lc.add_argument("space_id"); lc.add_argument("--name", required=True); lc.add_argument("--content"); lc.add_argument("--folder")
    lsp.add_parser("fields").add_argument("list_id")

    # user
    up = sub.add_parser("user")
    usp = up.add_subparsers(dest="sub", required=True)
    usp.add_parser("info")
    usp.add_parser("find").add_argument("name_or_email")

    # workspace
    wp = sub.add_parser("workspace")
    wsp = wp.add_subparsers(dest="sub", required=True)
    wsp.add_parser("members").add_argument("--team")
    wsp.add_parser("spaces").add_argument("--team")

    # tag
    tgp = sub.add_parser("tag")
    tgsp = tgp.add_subparsers(dest="sub", required=True)
    tga = tgsp.add_parser("add"); tga.add_argument("task_id"); tga.add_argument("tag_name")
    tgr = tgsp.add_parser("remove"); tgr.add_argument("task_id"); tgr.add_argument("tag_name")

    # dependency
    dp = sub.add_parser("dependency")
    dsp = dp.add_subparsers(dest="sub", required=True)
    da = dsp.add_parser("add"); da.add_argument("task_id"); da.add_argument("--depends-on", required=True); da.add_argument("--type")
    dr = dsp.add_parser("remove"); dr.add_argument("task_id"); dr.add_argument("--depends-on", required=True); dr.add_argument("--type")

    # time
    tmp = sub.add_parser("time")
    tmsp = tmp.add_subparsers(dest="sub", required=True)
    tmsp.add_parser("status")
    tms = tmsp.add_parser("start"); tms.add_argument("task_id"); tms.add_argument("--description"); tms.add_argument("--billable", action="store_true")
    tmst = tmsp.add_parser("stop"); tmst.add_argument("--description")
    tma = tmsp.add_parser("add"); tma.add_argument("task_id"); tma.add_argument("--start", required=True)
    tma.add_argument("--duration"); tma.add_argument("--end")
    tmsp.add_parser("entries").add_argument("task_id")
    tmr = tmsp.add_parser("report"); tmr.add_argument("--from", dest="from_date", required=True)
    tmr.add_argument("--to", dest="to_date", required=True); tmr.add_argument("--assignee")

    # custom-fields
    cfp = sub.add_parser("custom-fields")
    cfp.add_argument("list_id")

    args = parser.parse_args()

    dispatch = {
        "task": cmd_task,
        "comment": cmd_comment,
        "hierarchy": cmd_hierarchy,
        "space": cmd_space,
        "folder": cmd_folder,
        "list": cmd_list,
        "user": cmd_user,
        "workspace": cmd_workspace,
        "tag": cmd_tag,
        "dependency": cmd_dependency,
        "time": cmd_time,
        "custom-fields": cmd_custom_fields,
    }
    dispatch[args.command](args)

if __name__ == "__main__":
    main()
