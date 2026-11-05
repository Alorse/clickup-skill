import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import sys
from . import NetworkForbidden
import ssl
import tempfile
import traceback
import unittest
from unittest import mock
import urllib.error
import urllib.request

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "clickup.py"
SOURCE_TEXT = None  # In-memory baseline/mutation injection; never used by the CLI.
TOKEN = "pk_FAKE_SENSITIVE_SENTINEL_7"
TASK = {"id": "abc123", "name": "Example", "status": {"status": "open"},
        "description": "complete description", "custom_fields": [{"id": "field", "value": 3}],
        "list": {"id": "123"}, "date": "1700000000000"}


def load_cli():
    spec = importlib.util.spec_from_file_location("clickup_under_test", SCRIPT)
    cli = importlib.util.module_from_spec(spec)
    if SOURCE_TEXT is None:
        spec.loader.exec_module(cli)
    else:
        exec(compile(SOURCE_TEXT, str(SCRIPT), "exec"), cli.__dict__)
    return cli


def response(data):
    return io.BytesIO(json.dumps(data).encode())


class CLITest(unittest.TestCase):
    def setUp(self):
        self.cli = load_cli()
        self.env = mock.patch.dict(os.environ, {"CLICKUP_API_TOKEN": TOKEN,
                                   "CLICKUP_API_KEY": TOKEN, "CLICKUP_TEAM_ID": "42"}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.requests = []
        self.answer = TASK
        self.effect = None
        self.opener = mock.Mock()
        self.opener.open.side_effect = self.open
        self.build = mock.patch("urllib.request.build_opener", return_value=self.opener).start()
        mock.patch("urllib.request.urlopen", side_effect=self.open).start()
        mock.patch("time.sleep").start()
        self.addCleanup(mock.patch.stopall)

    def open(self, request, data=None, timeout=None):
        self.requests.append((request, data, timeout))
        if self.effect:
            return self.effect(request, data, timeout)
        return response(self.answer)

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with mock.patch.object(sys, "argv", ["clickup", *args]), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                result = self.cli.main()
                if isinstance(result, int):
                    code = result
            except SystemExit as exc:
                code = exc.code or 0
            except Exception:
                code = 99
                traceback.print_exc()
        return code, out.getvalue(), err.getvalue()

    def error(self, code, body=None):
        def fail(request, data, timeout):
            raise urllib.error.HTTPError(request.full_url, code, TOKEN,
                                         {"Retry-After": "1"}, response(body or {"error": TOKEN}))
        self.effect = fail


class SecurityTests(CLITest):
    def test_new_token_source(self):
        os.environ.pop("CLICKUP_API_KEY")
        code, out, err = self.run_cli("task", "get", "abc123")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.requests[0][0].get_header("Authorization"), TOKEN)

    def test_insecure_token_file_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credential"
            path.write_text(TOKEN)
            path.chmod(0o644)
            code, out, err = self.run_cli("--token-file", str(path), "task", "get", "abc123")
            self.assertEqual(code, 2)
            self.assertIn("token file", err)
            self.assertFalse(self.requests)

    def test_http_errors_do_not_dump_response(self):
        self.error(401)
        code, out, err = self.run_cli("task", "get", "abc123")
        self.assertNotIn(TOKEN, out + err)
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(err)["error"]["http_status"], 401)

    def test_transport_errors_are_sanitized(self):
        self.effect = mock.Mock(side_effect=urllib.error.URLError(TOKEN))
        code, out, err = self.run_cli("task", "get", "abc123")
        self.assertNotIn(TOKEN, out + err)
        self.assertEqual(code, 5)

    def test_invalid_json_is_sanitized(self):
        self.effect = lambda *a: io.BytesIO(TOKEN.encode())
        code, out, err = self.run_cli("task", "get", "abc123")
        self.assertEqual(code, 6)
        self.assertNotIn(TOKEN, out + err)

    def test_rate_limit_exit(self):
        self.error(429)
        code, out, err = self.run_cli("task", "get", "abc123")
        self.assertEqual(code, 4)
        self.assertEqual(len(self.requests), 1)  # do not retry writes or hide rate limits
        self.assertEqual(json.loads(err)["error"]["retry_after"], "1")

    def test_redirect_and_proxy_policy(self):
        self.run_cli("task", "get", "abc123")
        self.assertTrue(self.build.called)
        handlers = self.build.call_args.args
        redirects = [h for h in handlers if isinstance(h, urllib.request.HTTPRedirectHandler)]
        self.assertEqual(len(redirects), 1)
        request = urllib.request.Request("https://api.clickup.com/api/v2/task/abc123",
                                         headers={"Authorization": TOKEN})
        self.assertIsNone(redirects[0].redirect_request(request, None, 302, "Found", {},
                                                       "https://other.invalid/"))
        proxies = [h for h in handlers if isinstance(h, urllib.request.ProxyHandler)]
        self.assertEqual(proxies[0].proxies, {})
        https = [h for h in handlers if isinstance(h, urllib.request.HTTPSHandler)][0]
        self.assertTrue(https._context.check_hostname)
        self.assertEqual(https._context.verify_mode, ssl.CERT_REQUIRED)
        self.assertEqual(self.requests[0][2], 30)

    def test_path_injection_refused(self):
        for value in ("../abc", "abc?x=y", "abc#frag", "abc/def", "%2f", "abc\n"):
            with self.subTest(value=value):
                self.requests.clear()
                code, out, err = self.run_cli("task", "get", value)
                self.assertEqual(code, 2)
                self.assertFalse(self.requests)

    def test_token_must_not_be_sent_in_url_or_body(self):
        for args in (("task", "get", TOKEN),
                     ("task", "list", "123", "--statuses", TOKEN),
                     ("comment", "add", "abc123", TOKEN)):
            with self.subTest(args=args[:2]):
                self.requests.clear()
                code, out, err = self.run_cli(*args)
                self.assertEqual(code, 2)
                self.assertFalse(self.requests)
                self.assertNotIn(TOKEN, out + err)

    def test_success_redacts_echoed_token(self):
        self.answer = dict(TASK, name=TOKEN, description=TOKEN, custom_fields=[{TOKEN: TOKEN}])
        code, out, err = self.run_cli("task", "get", "abc123")
        self.assertEqual(code, 0)
        self.assertNotIn(TOKEN, out + err)
        self.assertEqual(json.loads(out)["description"], "[REDACTED]")

    def test_parser_does_not_echo_argv_secrets(self):
        code, out, err = self.run_cli("--token", TOKEN, "task", "get", "abc123")
        self.assertEqual(code, 2)
        self.assertNotIn(TOKEN, out + err)

    def test_non_loopback_guard(self):
        with socket.socket() as connection:
            with self.assertRaisesRegex(NetworkForbidden, "non-loopback"):
                connection.connect(("192.0.2.1", 443))



class CredentialTests(CLITest):
    def test_token_file_success_and_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credential"
            path.write_text(TOKEN + "\n")
            path.chmod(0o600)
            os.environ["CLICKUP_API_TOKEN"] = "unused"
            code, out, err = self.run_cli("--token-file", str(path), "task", "get", "abc123")
            self.assertEqual(code, 0, err)
            self.assertEqual(self.requests[0][0].get_header("Authorization"), TOKEN)
            self.assertEqual(path.read_text(), TOKEN + "\n")

    def test_token_files_reject_permissions_symlink_directory_missing_fifo(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credential"
            path.write_text(TOKEN)
            for mode in (0o640, 0o604, 0o660, 0o644):
                path.chmod(mode)
                code, out, err = self.run_cli("--token-file", str(path), "task", "get", "abc123")
                self.assertEqual(code, 2)
                self.assertFalse(self.requests)
            path.chmod(0o600)
            link = Path(directory) / "link"
            link.symlink_to(path)
            fifo = Path(directory) / "fifo"
            os.mkfifo(fifo, 0o600)
            for candidate in (link, Path(directory), path.with_name("missing"), fifo):
                code, out, err = self.run_cli("--token-file", str(candidate), "task", "get", "abc123")
                self.assertEqual(code, 2)
                self.assertFalse(self.requests)
                self.assertNotIn(TOKEN, out + err)

    def test_missing_legacy_and_malformed_credentials(self):
        os.environ.pop("CLICKUP_API_TOKEN")
        code, out, err = self.run_cli("task", "get", "abc123")
        self.assertEqual(code, 2)  # legacy key is not used
        self.assertFalse(self.requests)
        os.environ.pop("CLICKUP_API_KEY")
        for value in ("", "bad\r\nheader", "bad space", "a" * 4097, "nonascii-\u00e9"):
            os.environ["CLICKUP_API_TOKEN"] = value
            code, out, err = self.run_cli("task", "get", "abc123")
            self.assertEqual(code, 2)
            self.assertFalse(self.requests)

    def test_escaped_credential_must_not_enter_body(self):
        for value in ('sensitive"quoted', "sensitive\\backslash"):
            with self.subTest(value=value):
                os.environ["CLICKUP_API_TOKEN"] = value
                self.requests.clear()
                code, out, err = self.run_cli("comment", "add", "abc123", value)
                self.assertEqual(code, 2)
                self.assertFalse(self.requests)
                self.assertNotIn(value, out + err)


class FeatureTests(CLITest):
    def test_task_details_json_is_lossless(self):
        code, out, err = self.run_cli("task", "get", "abc123")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), TASK)

    def test_list_and_workspace_pagination_filters(self):
        for args, path in ((("task", "list", "123"), "/list/123/task"),
                           (("task", "search", "--team", "42"), "/team/42/task")):
            with self.subTest(args=args):
                self.requests.clear()
                def pages(request, data, timeout):
                    from urllib.parse import parse_qs, urlsplit
                    self.assertTrue(urlsplit(request.full_url).path.endswith(path))
                    query = parse_qs(urlsplit(request.full_url).query)
                    self.assertEqual(query["statuses[]"], ["open", "in progress"])
                    self.assertEqual(query["assignees[]"], ["7", "8"])
                    self.assertEqual(query["include_closed"], ["true"])
                    page = int(query["page"][0])
                    return response({"tasks": [dict(TASK, id=f"task{page}")], "last_page": page == 2})
                self.effect = pages
                code, out, err = self.run_cli(*args, "--statuses", "open,in progress",
                                             "--assignees", "7,8", "--include-closed")
                self.assertEqual(code, 0, err)
                self.assertEqual(len(self.requests), 3)
                result = json.loads(out)
                self.assertEqual(len(result["tasks"]), 3)
                self.assertTrue(result["complete"])
                self.assertIsNone(result["next_page"])

    def test_page_mode_is_explicitly_incomplete(self):
        self.answer = {"tasks": [TASK]}
        code, out, err = self.run_cli("task", "list", "123", "--page", "2")
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.requests), 1)
        self.assertFalse(json.loads(out)["complete"])
        self.assertEqual(json.loads(out)["next_page"], 3)

    def test_task_pages_continue_without_last_page_flag(self):
        answers = [{"tasks": [TASK]}, {"tasks": []}]
        self.effect = lambda *a: response(answers.pop(0))
        code, out, err = self.run_cli("task", "search", "--team", "42", "--assignees", "7")
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.requests), 2)
        self.assertTrue(json.loads(out)["complete"])

    def test_comment_pagination_uses_date_and_id(self):
        answers = [{"comments": [{"id": "20", "date": "200", "comment_text": "new"},
                                  {"id": "10", "date": "100", "comment_text": "old"}]},
                   {"comments": [{"id": "9", "date": "100", "comment_text": "same timestamp"}]},
                   {"comments": []}]
        self.effect = lambda *a: response(answers.pop(0))
        code, out, err = self.run_cli("comment", "list", "abc123")
        self.assertEqual(code, 0, err)
        self.assertEqual(len(json.loads(out)["comments"]), 3)
        from urllib.parse import parse_qs, urlsplit
        query = parse_qs(urlsplit(self.requests[1][0].full_url).query)
        self.assertEqual(query, {"start": ["100"], "start_id": ["10"]})
        query = parse_qs(urlsplit(self.requests[2][0].full_url).query)
        self.assertEqual(query, {"start": ["100"], "start_id": ["9"]})

    def test_comment_single_page_resume(self):
        self.answer = {"comments": [{"id": "10", "date": "100"}]}
        code, out, err = self.run_cli("comment", "list", "abc123", "--single-page",
                                     "--start", "200", "--start-id", "20")
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(json.loads(out)["next_cursor"], {"start": "100", "start_id": "10"})
        self.assertFalse(json.loads(out)["complete"])

    def test_pagination_repetition_and_limits_fail_without_partial_output(self):
        for command, answer in ((("task", "list", "123"), {"tasks": [TASK]}),
                                (("comment", "list", "abc123"), {"comments": [{"id": "1", "date": "100"}]})):
            self.answer = answer
            for limit in (1, 3):
                self.cli.MAX_PAGES = limit
                code, out, err = self.run_cli(*command)
                self.assertEqual(code, 6, err)
                self.assertEqual(out, "")

    def test_create_update_and_comment_payloads(self):
        commands = [
            (("task", "create", "123", "--name", "New", "--description", "Description",
              "--assignees", "7,8", "--due-date", "2026-01-02", "--status", "open"), "POST",
             {"name": "New", "description": "Description", "assignees": [7, 8],
              "due_date": 1767312000000, "status": "open"}),
            (("task", "update", "abc123", "--status", "done", "--description", "",
              "--assignees", "7", "--remove-assignees", "8", "--due-date", "2026-01-02"), "PUT",
             {"status": "done", "description": "", "assignees": {"add": [7], "rem": [8]},
              "due_date": 1767312000000}),
            (("comment", "add", "abc123", "Approved text", "--notify-all"), "POST",
             {"comment_text": "Approved text", "notify_all": True}),
        ]
        for command, method, payload in commands:
            self.requests.clear()
            code, out, err = self.run_cli(*command)
            self.assertEqual(code, 0, err)
            self.assertEqual(len(self.requests), 1)
            request, data, timeout = self.requests[0]
            self.assertEqual(request.get_method(), method)
            self.assertEqual(json.loads(data), payload)
            self.assertEqual(json.loads(out), TASK)

    def test_custom_task_ids_and_parent_list_inheritance(self):
        self.answer = TASK
        code, out, err = self.run_cli("task", "create", "--parent", "ABC-12", "--name", "Child")
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.requests), 2)
        self.assertIn("custom_task_ids=true", self.requests[0][0].full_url)
        self.assertIn("team_id=42", self.requests[0][0].full_url)
        self.assertEqual(json.loads(self.requests[1][1])["parent"], "abc123")
        self.assertTrue(self.requests[1][0].full_url.endswith("/list/123/task"))

    def test_invalid_inputs_make_no_request(self):
        commands = [("task", "list", "abc"), ("task", "list", "123", "--page", "-1"),
                    ("task", "list", "123", "--assignees", "7,abc"),
                    ("task", "search", "--team", "42/evil"),
                    ("task", "create", "123", "--name", "N", "--priority", "5"),
                    ("task", "update", "abc123", "--due-date", "invalid"),
                    ("comment", "list", "abc123", "--start", "100"),
                    ("comment", "list", "abc123", "--start", "-1", "--start-id", "10")]
        for command in commands:
            self.requests.clear()
            code, out, err = self.run_cli(*command)
            self.assertEqual(code, 2, err)
            self.assertFalse(self.requests)

    def test_time_add_remains_compatible(self):
        code, out, err = self.run_cli("time", "add", "abc123", "--start", "2026-01-02 10:00",
                                     "--duration", "1h 30m")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(self.requests[-1][1])["duration"], "5400000")


# Every leaf command, including legacy writes, exercised without a live service.
COMMANDS = [
    ("task", "get", "abc123"),
    ("task", "create", "123", "--name", "N"),
    ("task", "update", "abc123", "--status", "done"),
    ("task", "delete", "abc123"), ("task", "list", "123"),
    ("task", "search", "--team", "42", "--assignees", "7"),
    ("task", "move", "abc123", "--list-id", "123"),
    ("comment", "list", "abc123"), ("comment", "add", "abc123", "text"),
    ("comment", "add", "abc123", "text", "--mention", "7"),
    ("hierarchy",), ("hierarchy", "--space", "123"),
    ("space", "123"), ("folder", "123"),
    ("list", "get", "123"), ("list", "find", "example"),
    ("list", "create", "123", "--name", "N"),
    ("list", "create", "123", "--name", "N", "--folder", "456"),
    ("list", "fields", "123"), ("user", "info"), ("user", "find", "example"),
    ("workspace", "members"), ("workspace", "spaces"),
    ("tag", "add", "abc123", "tag/name?#"), ("tag", "remove", "abc123", "tag"),
    ("dependency", "add", "abc123", "--depends-on", "def456"),
    ("dependency", "remove", "abc123", "--depends-on", "def456", "--type", "blocking"),
    ("time", "status"), ("time", "start", "abc123"), ("time", "stop"),
    ("time", "add", "abc123", "--start", "2026-01-02 10:00", "--duration", "1h"),
    ("time", "entries", "abc123"),
    ("time", "report", "--from", "2026-01-01", "--to", "2026-01-02"),
    ("custom-fields", "123"),
]


def fixture(request, data=None, timeout=None):
    """Complete API-shaped fixture, deliberately contains echoed credentials."""
    return response({**TASK, "name": TOKEN, "description": TOKEN, "custom_fields": [{TOKEN: TOKEN}],
                     "tasks": [], "comments": [], "fields": [{"id": "field", "name": TOKEN, "type": "text"}],
                     "spaces": [{"id": "123", "name": TOKEN}], "folders": [],
                     "lists": [{"id": "123", "name": "example" + TOKEN}],
                     "user": {"id": "7", "username": TOKEN, "email": TOKEN},
                     "data": [], "teams": [{"id": "42", "name": TOKEN, "members": [
                         {"user": {"id": "7", "username": "example", "email": TOKEN}}]}]})


class TokenLeakTests(CLITest):
    def test_all_commands_success_and_error_paths_never_echo_token(self):
        # 34 invocations per mode; verify requests and JSON, not just exit status.
        modes = ("success", 301, 302, 303, 307, 308, 400, 401, 403, 404, 429, 500,
                 "network", "timeout", "invalid-json", "invalid-shape", "internal")
        count = 0
        for mode in modes:
            for command in COMMANDS:
                with self.subTest(mode=mode, command=command[:2]):
                    self.requests.clear()
                    if mode == "success":
                        self.effect = fixture
                        expected = 0
                    elif isinstance(mode, int):
                        self.error(mode)
                        expected = 4 if mode == 429 else 3
                    elif mode == "network":
                        self.effect = mock.Mock(side_effect=urllib.error.URLError(TOKEN))
                        expected = 5
                    elif mode == "timeout":
                        self.effect = mock.Mock(side_effect=TimeoutError(TOKEN))
                        expected = 5
                    elif mode == "invalid-json":
                        self.effect = lambda *a: io.BytesIO(TOKEN.encode())
                        expected = 6
                    elif mode == "invalid-shape":
                        self.effect = lambda *a: response([TOKEN])
                        expected = 6
                    else:
                        self.effect = mock.Mock(side_effect=RuntimeError(TOKEN))
                        expected = 6
                    code, out, err = self.run_cli(*command)
                    count += 1
                    self.assertNotIn(TOKEN, out + err)
                    self.assertEqual(code, expected, err)
                    json.loads(out if code == 0 else err)
                    self.assertFalse(err if code == 0 else out)
                    self.assertTrue(self.requests)
                    for request, data, timeout in self.requests:
                        self.assertEqual(request.get_header("Authorization"), TOKEN)
                        self.assertEqual(request.host, "api.clickup.com")
                        self.assertTrue(request.full_url.startswith("https://api.clickup.com/api/v2/"))
                        self.assertNotIn(TOKEN, request.full_url)
                        self.assertNotIn(TOKEN, (data or b"").decode())
                        for key, value in request.header_items():
                            if key.lower() != "authorization":
                                self.assertNotIn(TOKEN, value)
                    if (command[0], command[1] if len(command) > 1 else None) not in self.cli.WRITE_COMMANDS:
                        self.assertTrue(all(r[0].get_method() == "GET" for r in self.requests))
        self.assertEqual(count, len(COMMANDS) * len(modes))

    def test_bad_arguments_and_dates_do_not_echo_token(self):
        for command in (("unknown", TOKEN), ("task", "get", TOKEN),
                        ("task", "update", "abc123", "--due-date", TOKEN),
                        ("task", "list", "123", "--page", TOKEN),
                        ("comment", "add", "abc123", "text", "--mention", TOKEN)):
            self.effect = fixture
            code, out, err = self.run_cli(*command)
            self.assertEqual(code, 2)
            self.assertNotIn(TOKEN, out + err)


class PolicyTests(CLITest):
    def test_read_context_refuses_non_get_even_with_credential(self):
        self.cli._TOKEN = TOKEN
        self.cli._WRITE_ALLOWED = False
        for method in ("POST", "PUT", "DELETE", "PATCH"):
            with self.assertRaises(Exception):
                self.cli.api("/task/abc123", method, {"name": "N"})
        self.assertFalse(self.requests)

    def test_no_write_is_retried(self):
        for status in (429, 500):
            self.requests.clear()
            self.error(status)
            code, out, err = self.run_cli("comment", "add", "abc123", "text")
            self.assertEqual(code, 4 if status == 429 else 3)
            self.assertEqual(len(self.requests), 1)

    def test_invalid_environment_workspace_refused(self):
        os.environ["CLICKUP_TEAM_ID"] = "42/evil"
        code, out, err = self.run_cli("workspace", "spaces")
        self.assertEqual(code, 2)
        self.assertFalse(self.requests)

    def test_response_size_limit(self):
        self.effect = lambda *a: io.BytesIO(b" " * (16 * 1024 * 1024 + 1))
        code, out, err = self.run_cli("task", "get", "abc123")
        self.assertEqual(code, 6)
        self.assertEqual(out, "")
        self.assertIn("size limit", err)

    def test_destination_restrictions(self):
        self.cli._TOKEN = TOKEN
        for base, path in (("http://api.clickup.com/api/v2", "/task/abc123"),
                           ("https://other.invalid/api/v2", "/task/abc123"),
                           (self.cli.API_BASE, "//other.invalid/task"),
                           (self.cli.API_BASE, "/task/../team")):
            with mock.patch.object(self.cli, "API_BASE", base):
                with self.assertRaises(Exception):
                    self.cli.api(path)
        self.assertFalse(self.requests)

    def test_workspace_resolution_unambiguous_only(self):
        os.environ.pop("CLICKUP_TEAM_ID")
        for teams, expected in (([], 2), ([{"id": "42"}, {"id": "43"}], 2), ([{"id": "42"}], 0)):
            self.answer = {"teams": teams, "spaces": []}
            code, out, err = self.run_cli("workspace", "spaces")
            self.assertEqual(code, expected, err)

    def test_malicious_response_ids_refused_before_followup(self):
        self.answer = dict(TASK, id="../evil")
        code, out, err = self.run_cli("task", "create", "--parent", "ABC-12", "--name", "Child")
        self.assertEqual(code, 2)
        self.assertEqual(len(self.requests), 1)

    def test_empty_update_performs_no_write(self):
        code, out, err = self.run_cli("task", "update", "abc123")
        self.assertEqual(code, 0)
        self.assertFalse(self.requests)
        self.assertFalse(json.loads(out)["updated"])


class RedirectIntegrationTests(unittest.TestCase):
    def test_real_urllib_redirect_pipeline_never_forwards_authorization(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading
        cli = load_cli()
        seen = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append((self.path, self.headers.get("Authorization")))
                self.send_response(int(self.path[1:].split("?")[0]) if self.path != "/target" else 200)
                self.send_header("Location", "http://192.0.2.1/target" if "?cross" in self.path else "/target")
                self.end_headers()
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            # Exactly the production handler set; only the test URL uses HTTP loopback.
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), cli.NoRedirect(),
                        urllib.request.HTTPSHandler(context=ssl.create_default_context()))
            for status in (301, 302, 303, 307, 308):
                for suffix in ("", "?cross"):
                    request = urllib.request.Request(f"http://127.0.0.1:{server.server_port}/{status}{suffix}",
                                                      headers={"Authorization": TOKEN})
                    with self.assertRaises(urllib.error.HTTPError) as caught:
                        opener.open(request, timeout=2)
                    caught.exception.close()
            self.assertEqual(len(seen), 10)
            self.assertFalse(any(path == "/target" for path, token in seen))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


class ExtraRegressionTests(CLITest):
    def test_duplicate_task_ids_within_page_are_deduplicated(self):
        self.answer = {"tasks": [TASK, TASK], "last_page": True}
        code, out, err = self.run_cli("task", "list", "123")
        self.assertEqual(code, 0, err)
        self.assertEqual(len(json.loads(out)["tasks"]), 1)

    def test_credential_in_server_derived_body_refused(self):
        # Not an argv copy: a server echo must not be sent back in mention text.
        self.effect = lambda *a: response({"teams": [{"members": [
            {"user": {"id": "7", "username": TOKEN}}]}]})
        code, out, err = self.run_cli("comment", "add", "abc123", "text", "--mention", "7")
        self.assertEqual(code, 2, err)
        self.assertEqual(len(self.requests), 1)  # lookup GET only, no comment POST
        self.assertNotIn(TOKEN, out + err)

    def test_external_dns_guard_cannot_be_swallowed(self):
        with self.assertRaises(NetworkForbidden):
            socket.getaddrinfo("api.clickup.com", 443)

    def test_wrong_owner_token_file_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credential"
            path.write_text(TOKEN)
            path.chmod(0o600)
            real_stat = os.stat(path)
            info = mock.Mock(st_mode=real_stat.st_mode, st_uid=os.getuid() + 1)
            with mock.patch("os.fstat", return_value=info):
                code, out, err = self.run_cli("--token-file", str(path), "task", "get", "abc123")
            self.assertEqual(code, 2)
            self.assertFalse(self.requests)

    def test_unsafe_retry_after_not_echoed(self):
        def fail(request, *args):
            raise urllib.error.HTTPError(request.full_url, 429, TOKEN,
                                         {"Retry-After": TOKEN}, response({"error": TOKEN}))
        self.effect = fail
        code, out, err = self.run_cli("task", "get", "abc123")
        self.assertEqual(code, 4)
        self.assertNotIn(TOKEN, out + err)
        self.assertNotIn("retry_after", json.loads(err)["error"])
