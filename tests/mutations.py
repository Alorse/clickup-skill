"""Offline, in-memory mutations. A surviving mutation makes this gate fail."""
import io
import unittest
from . import test_clickup as tests


def main():
    original = tests.SCRIPT.read_text()
    mutations = [
        ("redirect protection removed", "urllib.request.ProxyHandler({}), NoRedirect(),",
         "urllib.request.ProxyHandler({}),", "SecurityTests.test_redirect_and_proxy_policy"),
        ("HTTP body dumped", "status = exc.code", 'status = exc.code\n        print(exc.read().decode(), file=sys.stderr)',
         "SecurityTests.test_http_errors_do_not_dump_response"),
        ("file privacy check removed", "info.st_mode & 0o077", "False",
         "CredentialTests.test_token_files_reject_permissions_symlink_directory_missing_fifo"),
        ("read/write guard removed", 'if method != "GET" and not _WRITE_ALLOWED:', 'if False:',
         "PolicyTests.test_read_context_refuses_non_get_even_with_credential"),
    ]
    killed = 0
    try:
        for name, before, after, test in mutations:
            if original.count(before) != 1:
                raise AssertionError("mutation anchor must match exactly once")
            tests.SOURCE_TEXT = original.replace(before, after, 1)
            suite = unittest.defaultTestLoader.loadTestsFromName(test, tests)
            result = unittest.TextTestRunner(stream=io.StringIO()).run(suite)
            dead = bool(result.failures) and not result.errors
            print(f"{name}: {'KILLED' if dead else 'SURVIVED/ERROR'} ({result.testsRun} test)")
            killed += dead
    finally:
        tests.SOURCE_TEXT = None
    print(f"Mutations killed: {killed}/{len(mutations)}")
    return 0 if killed == len(mutations) else 1


if __name__ == "__main__":
    raise SystemExit(main())
