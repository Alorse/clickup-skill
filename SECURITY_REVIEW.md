# ClickUp CLI security review and gap analysis

Reviewed the entire `scripts/clickup.py` (lines 1–700) at baseline
`c36319587e9ba36e32d477ea758cb1880aba142f`. Findings below use **baseline**
line numbers, not the revised file. Scope: a shell-invoked agent, personal API
credential provisioned out of band, no live API access during verification.

## Findings

| Severity | Baseline location | Finding | Disposition |
|---|---|---|---|
| High | `scripts/clickup.py:115-126` | Default urllib redirect handling can copy Authorization to another origin. Environment proxy settings are also inherited. | Fixed: refuse every redirect, disable proxies, pin the HTTPS origin. |
| High | `scripts/clickup.py:134-140` | HTTP errors dump arbitrary JSON/raw bodies, which can echo credentials; reason/transport exceptions are not sanitized. | Fixed: constant JSON errors, no response-body dumps, no traceback/exception text. |
| Medium | `scripts/clickup.py:178-202,362-366,681` | Success output and argparse errors can echo the token if it appears in API content or accidental argv input. | Fixed: recursive output redaction, non-echoing parser errors, refuse active credential in argv/URL/body. |
| Medium | `scripts/clickup.py:97-100` | Only legacy `CLICKUP_API_KEY`; requested token-file source and permission checks absent. | Fixed: `CLICKUP_API_TOKEN` or private, owned, nonsymlink regular file, checked on the open descriptor; legacy key refused. Upstream had no token argv option; none is introduced. |
| Medium | `scripts/clickup.py:178,211,278,308,489-492,591-679` | IDs interpolated into paths without validation; tag names unescaped. | Fixed: native/custom task-ID and numeric resource-ID validation, including follow-up IDs from API data; encode tag path segment. |
| Medium | `scripts/clickup.py:129-140` | 429 shares exit 1 with other failures and automatic retries also replay writes. | Fixed: distinct exit codes, safe numeric Retry-After, no automatic retries. |
| Medium | `scripts/clickup.py:278-285,308-315,362-366` | Reads silently return only one task/comment page. | Fixed: automatic traversal, explicit partial-page metadata, repeated-page/cursor detection and visible limits. |
| Low | `scripts/clickup.py:127` | Unbounded response read. | Fixed: 16 MiB/page limit; traversal capped at 10,000 pages, errors instead of partial success. |
| Info | `scripts/clickup.py:64,115-126` | Token originates in environment and normally goes only to Authorization on a fixed HTTPS URL. TLS verification and 30-second timeout are already enabled. | Retained/strengthened: explicit default TLS context, fixed-origin checks and socket timeout. |
| Info | `scripts/clickup.py:175-579,683-697` | No read command performs a write. No shell/eval/subprocess calls or application file writes. | Retained; explicit write-command allowlist now also enforced at the request boundary. Token file is read-only, never copied to a temp file. |

No identified baseline vulnerability remains intentionally unfixed. No live
request, real credential, push, or main-checkout edit was needed. Test fixtures
use synthetic credentials only; tests may write those fixtures to temporary
files to exercise the file-input contract. The CLI itself does not write files.

## Workflow gaps and commands

All commands below now return JSON. Existing command spellings are retained;
human text output is intentionally replaced with structured output.

| Workflow | Baseline gap | Revised command |
|---|---|---|
| Backlog list | Single page, no assignee filter, abbreviated text | `task list LIST_ID --statuses "open,in progress" --include-closed --assignees USER_ID` (all pages); `--page N` for one page |
| Assigned tasks across workspace | Search/assignees existed, but only one page/text | `task search --team TEAM_ID --assignees USER_ID` (all pages, same status/closed filters) |
| Task detail | Description existed; custom fields discarded by text renderer | `task get TASK_ID` returns complete API object, including description and custom fields |
| Task comments | Single page/text | `comment list TASK_ID`; cursor resume via `--single-page`, `--start MS --start-id ID` |
| Add comment | Already existed, text result | `comment add TASK_ID "Approved comment"` |
| Update task | Status, additive assignees, due date, description existed; no removals; empty description ignored | `task update TASK_ID --status done --assignees USER_ID --remove-assignees OTHER_ID --due-date YYYY-MM-DD --description ""` |
| Create task | Already existed, text result | `task create LIST_ID --name "Approved title" --description "Description"` |

Every write command requires explicit human approval in the agent's calling
workflow. The CLI prevents reads from issuing writes, but cannot establish who
approved a deliberately invoked write command. See README/SKILL for exit codes
and the full write-command inventory.

## Verification and limitations

Unittest uses urllib mocks, plus a loopback server exercising urllib's real
redirect pipeline. A process-wide guard blocks external DNS and non-loopback
connect/connect_ex; its exception cannot be swallowed by the CLI's generic
error handler. The token-leak matrix covers every leaf command and 17 success,
HTTP, transport and malformed-response modes. In-memory mutation checks remove
redirect refusal, HTTP-body sanitization, file privacy, and read/write isolation;
each must fail its targeted regression test.

Credential redaction covers the active token as supplied, not arbitrary encoded,
fragmented, or transformed versions returned by a malicious service. TLS relies
on the host trust store. A compromised host/agent can read its own environment,
credential file or process memory. No live-service contract testing was performed.
Socket timeout is not an overall traversal deadline. Pagination is not a snapshot:
concurrent edits can move tasks between pages. Aggregated results consume memory.
Threaded comment replies and exhaustive pagination of other legacy collections
are outside the requested workflows. Human approval and untrusted-content handling
must also be enforced by the caller. Independent approval belongs to the separate
review stage, not this implementer report.
