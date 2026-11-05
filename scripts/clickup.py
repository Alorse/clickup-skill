#!/usr/bin/env python3
"""ClickUp CLI — stdlib-only JSON wrapper around the REST API.

Credentials: CLICKUP_API_TOKEN or --token-file PATH (before the command).
Only explicit write commands may send non-GET requests. Human approval is
an orchestration responsibility, not something a CLI can infer.
"""

import os
import sys
import json
import re
import ssl
import stat
import urllib.parse
import urllib.request
import urllib.error
import argparse
from datetime import datetime, timezone

API_BASE = "https://api.clickup.com/api/v2"
REQUEST_TIMEOUT = 30
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_PAGES = 10000
_TEAM_ID = None
_TOKEN = None
_WRITE_ALLOWED = False
WRITE_COMMANDS = {
    ("task", "create"), ("task", "update"), ("task", "delete"), ("task", "move"),
    ("comment", "add"), ("list", "create"), ("tag", "add"), ("tag", "remove"),
    ("dependency", "add"), ("dependency", "remove"),
    ("time", "start"), ("time", "stop"), ("time", "add"),
}


class CLIError(Exception):
    """Only constant, non-sensitive messages belong in this exception."""
    def __init__(self, message, code=2, **details):
        super().__init__(message)
        self.code = code
        self.details = {"message": message, **details}


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's message may contain an argv value (including a secret).
        raise CLIError("invalid arguments; use --help for command syntax")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Refuse even same-host redirects: no credential forwarding or replay.
        return None


def load_token(path=None):
    if path:
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077
                        or info.st_uid != os.getuid()):
                    raise CLIError("token file must be owned by this user and private (mode 0600)")
                raw = stream.read(4098)
            token = raw.decode("ascii").rstrip("\r\n")
        except (OSError, UnicodeError):
            raise CLIError("cannot read private regular token file") from None
    else:
        token = os.environ.get("CLICKUP_API_TOKEN", "")
    if not token:
        raise CLIError("set CLICKUP_API_TOKEN or use --token-file; CLICKUP_API_KEY is no longer accepted")
    if len(token) > 4096 or not re.fullmatch(r"[!-~]+", token):
        raise CLIError("invalid credential format")
    return token


def redact(value):
    if isinstance(value, str):
        return value.replace(_TOKEN, "[REDACTED]") if _TOKEN else value
    if isinstance(value, dict):
        return {redact(k): redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def contains_token(value):
    if isinstance(value, str):
        return _TOKEN in value
    if isinstance(value, dict):
        return any(contains_token(k) or contains_token(v) for k, v in value.items())
    if isinstance(value, list):
        return any(contains_token(v) for v in value)
    return False


def emit(value, stream=None):
    print(json.dumps(redact(value), ensure_ascii=False), file=stream or sys.stdout)


def valid_id(value, task=False):
    value = str(value)
    pattern = r"(?:[A-Za-z0-9]+|[A-Z]+-[0-9]+)" if task else r"[0-9]+"
    if not re.fullmatch(pattern, value):
        raise CLIError("invalid ID")
    return value


def validate_args(args):
    for key, value in vars(args).items():
        if value is None:
            continue
        if key in ("task_id", "parent", "depends_on"):
            valid_id(value, task=True)
        elif key in ("list_id", "space_id", "folder_id", "team", "space", "folder", "assignee", "start_id"):
            valid_id(value)
        elif key in ("assignees", "remove_assignees", "space_ids", "folder_ids", "list_ids"):
            for item in value.split(","):
                valid_id(item.strip())
        elif (key == "page" or (key == "start" and args.command == "comment")) and value < 0:
            raise CLIError("page and comment start must be nonnegative")
        elif key == "priority" and value not in (1, 2, 3, 4):
            raise CLIError("priority must be 1 through 4")
    if args.command == "comment" and args.sub == "list":
        if (args.start is None) != (args.start_id is None):
            raise CLIError("provide --start and --start-id together")


def resolve_team(explicit=None):
    """Resolve explicit workspace, environment, or an unambiguous API result."""
    global _TEAM_ID
    if explicit:
        return valid_id(explicit)
    if _TEAM_ID:
        return _TEAM_ID
    env = os.environ.get("CLICKUP_TEAM_ID", "")
    if env:
        _TEAM_ID = valid_id(env)
    else:
        teams = api("/team").get("teams", [])
        if len(teams) != 1:
            raise CLIError("set CLICKUP_TEAM_ID or --team: workspace lookup is not unambiguous")
        _TEAM_ID = valid_id(teams[0]["id"])
    return _TEAM_ID


def api(path, method="GET", data=None, params=None, array_params=None):
    """Send credentials only in Authorization, over verified HTTPS, without proxies/redirects."""
    if method != "GET" and not _WRITE_ALLOWED:
        raise CLIError("write request requires an explicit write command")
    if not _TOKEN:
        raise CLIError("missing credential")
    if (API_BASE != "https://api.clickup.com/api/v2" or not path.startswith("/")
            or path.startswith("//") or any(c in path for c in "?#\\\r\n")
            or any(part in (".", "..") for part in path.split("/"))):
        raise CLIError("invalid API destination")
    pairs = []
    for key, value in (params or {}).items():
        if key in (array_params or []):
            pairs.extend((key + "[]", item.strip()) for item in value.split(",") if item.strip())
        else:
            pairs.append((key, str(value)))
    url = API_BASE + path
    if pairs:
        url += "?" + urllib.parse.urlencode(pairs)
    text = json.dumps(data, ensure_ascii=False) if data is not None else ""
    # Also reject accidental copy/paste of the active token into content/filters.
    if _TOKEN in urllib.parse.unquote(url) or contains_token(data):
        raise CLIError("credential is not allowed in request URL or body")
    req = urllib.request.Request(url, method=method)
    req.add_header("Authorization", _TOKEN)
    body = text.encode("utf-8") if data is not None else None
    if body is not None:
        req.add_header("Content-Type", "application/json")
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}), NoRedirect(),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    try:
        with opener.open(req, data=body, timeout=REQUEST_TIMEOUT) as resp:
            raw = resp.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise CLIError("API response exceeds size limit", 6)
        result = json.loads(raw.decode("utf-8")) if raw else {}
        if not isinstance(result, dict):
            raise CLIError("API returned an unexpected JSON shape", 6)
        return result
    except urllib.error.HTTPError as exc:
        # Never read/print response bodies, URLs, reason phrases or exception text.
        status = exc.code
        retry = exc.headers.get("Retry-After", "") if exc.headers else ""
        exc.close()
        if status == 429:
            details = {"http_status": status}
            if re.fullmatch(r"[0-9]{1,9}", retry) and _TOKEN not in retry:
                details["retry_after"] = retry
            raise CLIError("rate limited; retry only after waiting", 4, **details) from None
        raise CLIError("redirect refused" if 300 <= status < 400 else "HTTP request failed",
                       3, http_status=status) from None
    except (urllib.error.URLError, OSError, TimeoutError):
        raise CLIError("network or TLS request failed", 5) from None
    except (ValueError, UnicodeError):
        raise CLIError("API returned invalid JSON", 6) from None


def date_to_epoch(d):
    return int(datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)


def dt_to_epoch(d):
    return int(datetime.strptime(d, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp() * 1000)


def parse_duration(value):
    if not re.fullmatch(r"(?:[0-9]+h(?:\s+[0-9]+m)?|[0-9]+m)", value):
        raise CLIError("duration must be hours/minutes, for example 1h 30m")
    hours = re.search(r"([0-9]+)h", value)
    minutes = re.search(r"([0-9]+)m", value)
    return ((int(hours[1]) * 60 if hours else 0) + (int(minutes[1]) if minutes else 0)) * 60000


def _is_custom_id(task_id):
    return bool(re.fullmatch(r"[A-Z]+-[0-9]+", task_id))


def _custom_task_params(task_id):
    valid_id(task_id, task=True)
    return {"custom_task_ids": "true", "team_id": resolve_team()} if _is_custom_id(task_id) else {}


def task_pages(path, params, arrays, page=None):
    tasks, seen = [], set()
    current = page if page is not None else 0
    for count in range(1, MAX_PAGES + 1):
        res = api(path, params={**params, "page": current}, array_params=arrays)
        batch = res.get("tasks")
        if not isinstance(batch, list):
            raise CLIError("API returned invalid task page", 6)
        complete = not batch or res.get("last_page") is True
        ids = [str(t["id"]) for t in batch]
        if batch and all(tid in seen for tid in ids):
            raise CLIError("task pagination did not advance; no partial output returned", 6)
        for task in batch:
            tid = str(task["id"])
            if tid not in seen:
                tasks.append(task)
                seen.add(tid)
        if complete or page is not None:
            return {"tasks": tasks, "pages": count, "page": current,
                    "complete": complete, "next_page": None if complete else current + 1}
        current += 1
    raise CLIError("task pagination limit exceeded; no partial output returned", 6)


# ─── Tasks ────────────────────────────────────────────────────────────────

def cmd_task(args):
    sub = args.sub
    if sub == "get":
        return api(f"/task/{args.task_id}", params=_custom_task_params(args.task_id))
    if sub in ("list", "search"):
        params = {}
        arrays = ["statuses", "assignees", "space_ids", "project_ids", "list_ids"]
        for key in ("statuses", "assignees", "space_ids", "folder_ids", "list_ids"):
            value = getattr(args, key, None)
            if value:
                params["project_ids" if key == "folder_ids" else key] = value
        if args.include_closed:
            params["include_closed"] = "true"
        for key in ("due_date_gt", "due_date_lt"):
            if getattr(args, key, None):
                params[key] = date_to_epoch(getattr(args, key))
        path = f"/list/{args.list_id}/task" if sub == "list" else f"/team/{resolve_team(args.team)}/task"
        return task_pages(path, params, arrays, args.page)
    if sub in ("create", "update"):
        payload = {}
        for key in ("name", "description", "status", "priority"):
            if getattr(args, key, None) is not None:
                payload[key] = getattr(args, key)
        if args.markdown is not None:
            payload.pop("description", None)
            payload["markdown_content"] = args.markdown
        if args.due_date:
            payload["due_date"] = date_to_epoch(args.due_date)
        if args.assignees:
            ids = [int(x) for x in args.assignees.split(",")]
            payload["assignees"] = ids if sub == "create" else {"add": ids}
        if sub == "update":
            if args.remove_assignees:
                payload.setdefault("assignees", {})["rem"] = [int(x) for x in args.remove_assignees.split(",")]
            if not payload:
                return {"updated": False, "reason": "nothing to update"}
            return api(f"/task/{args.task_id}", "PUT", payload, _custom_task_params(args.task_id))
        list_id, parent_id = args.list_id, args.parent
        if parent_id and (not list_id or _is_custom_id(parent_id)):
            parent = api(f"/task/{parent_id}", params=_custom_task_params(parent_id))
            parent_id = valid_id(parent["id"], task=True)
            list_id = list_id or parent.get("list", {}).get("id")
        if not list_id:
            raise CLIError("provide list_id or a parent with a list")
        if parent_id:
            payload["parent"] = parent_id
        if args.tags:
            payload["tags"] = args.tags.split(",")
        return api(f"/list/{valid_id(list_id)}/task", "POST", payload)
    if sub == "delete":
        return api(f"/task/{args.task_id}", "DELETE", params=_custom_task_params(args.task_id))
    if sub == "move":
        return api(f"/list/{args.list_id}/task/{args.task_id}", "POST", params=_custom_task_params(args.task_id))


# ─── Comments ─────────────────────────────────────────────────────────────

def _resolve_mentions(tokens):
    members = {}
    for team in api("/team").get("teams", []):
        for member in team.get("members", []):
            user = member.get("user", {})
            if user.get("id") is not None:
                members[int(valid_id(user["id"]))] = user
    resolved = []
    for raw in tokens:
        raw = raw.strip()
        if re.fullmatch(r"[0-9]+", raw):
            uid = int(raw)
        else:
            query = raw.lower()
            hits = [uid for uid, user in members.items() if query and
                    (query in (user.get("username") or "").lower() or
                     query in (user.get("email") or "").lower())]
            if len(hits) != 1:
                raise CLIError("mention is unmatched or ambiguous; use a numeric user ID")
            uid = hits[0]
        resolved.append({"id": uid, "username": members.get(uid, {}).get("username") or ""})
    return resolved


def cmd_comment(args):
    path = f"/task/{args.task_id}/comment"
    params = _custom_task_params(args.task_id)
    if args.sub == "list":
        comments, seen = [], set()
        cursor = (str(args.start), str(args.start_id)) if args.start is not None else None
        cursors = {cursor} if cursor else set()
        for count in range(1, MAX_PAGES + 1):
            if cursor:
                params.update(start=cursor[0], start_id=cursor[1])
            res = api(path, params=params)
            batch = res.get("comments")
            if not isinstance(batch, list):
                raise CLIError("API returned invalid comment page", 6)
            if not batch:
                return {"comments": comments, "pages": count, "complete": True, "next_cursor": None}
            for comment in batch:
                cid = valid_id(comment["id"])
                if cid not in seen:
                    comments.append(comment)
                    seen.add(cid)
            last = batch[-1]
            cursor = (valid_id(last["date"]), valid_id(last["id"]))
            if cursor in cursors:
                raise CLIError("comment pagination did not advance; no partial output returned", 6)
            cursors.add(cursor)
            if args.single_page:
                return {"comments": comments, "pages": count, "complete": False,
                        "next_cursor": {"start": cursor[0], "start_id": cursor[1]}}
        raise CLIError("comment pagination limit exceeded; no partial output returned", 6)
    mentions = _resolve_mentions(args.mention.split(",")) if args.mention else []
    if mentions:
        fragments = [{"text": "@" + m["username"], "type": "tag", "user": {"id": m["id"]}} for m in mentions]
        fragments.append({"text": " " + args.text})
        data = {"comment": fragments}
    else:
        data = {"comment_text": args.text}
    if args.notify_all:
        data["notify_all"] = True
    return api(path, "POST", data, params)


# ─── Hierarchy, users, tags, dependencies, time ─────────────────────────────

def cmd_hierarchy(args):
    if args.space:
        return api(f"/space/{args.space}", params={"include_lists": "true"})
    return api(f"/team/{resolve_team(args.team)}/space")


def cmd_space(args):
    return api(f"/space/{args.space_id}")


def cmd_folder(args):
    return api(f"/folder/{args.folder_id}")


def cmd_list(args):
    if args.sub == "get":
        return api(f"/list/{args.list_id}")
    if args.sub == "fields":
        return api(f"/list/{args.list_id}/field")
    if args.sub == "create":
        data = {"name": args.name}
        if args.content is not None:
            data["content"] = args.content
        path = f"/folder/{args.folder}/list" if args.folder else f"/space/{args.space_id}/list"
        return api(path, "POST", data)
    matches = []
    for space in api(f"/team/{resolve_team(args.team)}/space").get("spaces", []):
        sid = valid_id(space["id"])
        lists = api(f"/space/{sid}/list").get("lists", [])
        for folder in api(f"/space/{sid}/folder").get("folders", []):
            lists.extend(folder.get("lists", []))
        matches.extend(item for item in lists if args.name.lower() in item["name"].lower())
    return {"lists": matches}


def cmd_user(args):
    if args.sub == "info":
        return api("/user")
    query = args.name_or_email.lower()
    matches = []
    for team in api("/team").get("teams", []):
        for member in team.get("members", []):
            user = member.get("user", {})
            if query in (user.get("username") or "").lower() or query in (user.get("email") or "").lower():
                matches.append({"team_id": team["id"], "user": user})
    return {"users": matches}


def cmd_workspace(args):
    tid = resolve_team(args.team)
    if args.sub == "spaces":
        return api(f"/team/{tid}/space")
    for team in api("/team").get("teams", []):
        if str(team["id"]) == tid:
            return {"members": team.get("members", [])}
    return {"members": []}


def cmd_tag(args):
    tag = urllib.parse.quote(args.tag_name, safe="")
    return api(f"/task/{args.task_id}/tag/{tag}", "POST" if args.sub == "add" else "DELETE",
               params=_custom_task_params(args.task_id))


def cmd_dependency(args):
    key = "depends_on" if args.type != "blocking" else "dependency_of"
    data = {key: args.depends_on}
    params = _custom_task_params(args.task_id)
    if args.sub == "add":
        return api(f"/task/{args.task_id}/dependency", "POST", data, params)
    return api(f"/task/{args.task_id}/dependency", "DELETE", params={**params, **data})


def cmd_time(args):
    tid = resolve_team(args.team)
    path = f"/team/{tid}/time_entries"
    if args.sub == "status":
        return api(path + "/current")
    if args.sub in ("start", "stop"):
        data = {}
        if args.sub == "start":
            data["task_id"] = args.task_id
            if args.billable:
                data["billable"] = True
        if args.description is not None:
            data["description"] = args.description
        return api(path + "/" + args.sub, "POST", data)
    if args.sub == "entries":
        return api(f"/task/{args.task_id}/time_entries", params=_custom_task_params(args.task_id))
    if args.sub == "report":
        params = {"start_date": date_to_epoch(args.from_date), "end_date": date_to_epoch(args.to_date)}
        if args.assignee:
            params["assignee"] = args.assignee
        return api(path, params=params)
    start = dt_to_epoch(args.start)
    data = {"task_id": args.task_id, "start": str(start)}
    if args.duration:
        duration = parse_duration(args.duration)
    elif args.end:
        duration = dt_to_epoch(args.end) - start
        data["end"] = str(dt_to_epoch(args.end))
    else:
        raise CLIError("provide --duration or --end")
    if duration <= 0:
        raise CLIError("duration must be positive")
    data["duration"] = str(duration)
    return api(path, "POST", data)


def cmd_custom_fields(args):
    return api(f"/list/{args.list_id}/field")


# ─── Main ─────────────────────────────────────────────────────────────────

def _main():

    parser = SafeParser(description="ClickUp CLI — JSON output; credentials never accepted as argv values", allow_abbrev=False)
    parser.add_argument("--token-file", help="Private credential file; place before command")
    sub = parser.add_subparsers(dest="command", required=True)

    # task
    tp = sub.add_parser("task")
    tsp = tp.add_subparsers(dest="sub", required=True)
    tsp.add_parser("get").add_argument("task_id")
    tc = tsp.add_parser("create")
    tc.add_argument("list_id", nargs="?"); tc.add_argument("--name", required=True); tc.add_argument("--description")
    tc.add_argument("--markdown"); tc.add_argument("--parent"); tc.add_argument("--assignees")
    tc.add_argument("--priority", type=int); tc.add_argument("--due-date")
    tc.add_argument("--tags"); tc.add_argument("--status")
    tu = tsp.add_parser("update")
    tu.add_argument("task_id"); tu.add_argument("--name"); tu.add_argument("--description")
    tu.add_argument("--markdown")
    tu.add_argument("--status"); tu.add_argument("--priority", type=int); tu.add_argument("--due-date")
    tu.add_argument("--assignees"); tu.add_argument("--remove-assignees")
    tsp.add_parser("delete").add_argument("task_id")
    tl = tsp.add_parser("list")
    tl.add_argument("list_id"); tl.add_argument("--statuses"); tl.add_argument("--include-closed", action="store_true")
    tl.add_argument("--page", type=int); tl.add_argument("--assignees")
    ts = tsp.add_parser("search")
    ts.add_argument("--team"); ts.add_argument("--assignees")
    ts.add_argument("--statuses"); ts.add_argument("--include-closed", action="store_true")
    ts.add_argument("--space-ids"); ts.add_argument("--folder-ids"); ts.add_argument("--list-ids")
    ts.add_argument("--due-date-gt"); ts.add_argument("--due-date-lt")
    ts.add_argument("--page", type=int)
    tm = tsp.add_parser("move")
    tm.add_argument("task_id"); tm.add_argument("--list-id", required=True)

    # comment
    cp = sub.add_parser("comment")
    csp = cp.add_subparsers(dest="sub", required=True)
    cl = csp.add_parser("list")
    cl.add_argument("task_id"); cl.add_argument("--start", type=int); cl.add_argument("--start-id")
    cl.add_argument("--single-page", action="store_true")
    ca = csp.add_parser("add")
    ca.add_argument("task_id"); ca.add_argument("text"); ca.add_argument("--notify-all", action="store_true")
    ca.add_argument("--mention", help="Comma-separated user IDs, names, or emails to @mention (real, notifying mention; ambiguous names abort)")

    # hierarchy
    hp = sub.add_parser("hierarchy")
    hp.add_argument("--space")
    hp.add_argument("--team")

    # space/folder/list
    sp = sub.add_parser("space"); sp.add_argument("space_id")
    fp = sub.add_parser("folder"); fp.add_argument("folder_id")
    lp = sub.add_parser("list")
    lsp = lp.add_subparsers(dest="sub", required=True)
    lsp.add_parser("get").add_argument("list_id")
    lf = lsp.add_parser("find")
    lf.add_argument("name"); lf.add_argument("--team")
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
    da = dsp.add_parser("add"); da.add_argument("task_id"); da.add_argument("--depends-on", required=True); da.add_argument("--type", choices=("waiting_on", "blocking"))
    dr = dsp.add_parser("remove"); dr.add_argument("task_id"); dr.add_argument("--depends-on", required=True); dr.add_argument("--type", choices=("waiting_on", "blocking"))

    # time
    tmp = sub.add_parser("time")
    tmp.add_argument("--team")
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
    global _TOKEN, _TEAM_ID, _WRITE_ALLOWED
    _TOKEN = load_token(args.token_file)
    if any(_TOKEN in value for value in sys.argv[1:]):
        raise CLIError("credential values are not allowed in argv")
    _TEAM_ID = None
    _WRITE_ALLOWED = (args.command, getattr(args, "sub", None)) in WRITE_COMMANDS
    validate_args(args)
    emit(dispatch[args.command](args))


def main():
    global _TOKEN, _WRITE_ALLOWED
    _TOKEN, _WRITE_ALLOWED = None, False
    try:
        _main()
        return 0
    except CLIError as exc:
        emit({"error": exc.details}, sys.stderr)
        return exc.code
    except (ValueError, OverflowError):
        emit({"error": {"message": "invalid date or numeric value"}}, sys.stderr)
        return 2
    except Exception:
        # Do not expose traceback, exception text, response data or credentials.
        emit({"error": {"message": "unexpected API response or internal failure"}}, sys.stderr)
        return 6
    finally:
        _TOKEN, _WRITE_ALLOWED = None, False


if __name__ == "__main__":
    sys.exit(main())
