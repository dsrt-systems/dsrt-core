"""
Python Sandbox Runner Template (C3 §26-27).

This module provides the text of the runner script that is injected
into each sandboxed Python execution. The runner:

  1. Reads user code from a file (never from stdin, never via -c)
  2. Executes it in a restricted globals dict
  3. Captures stdout, stderr, and any returned value
  4. Writes a result JSON to a known path
  5. Exits with a deterministic exit code

The runner is written to the sandbox cwd as `_dsrt_runner.py` and invoked
by the subprocess. It never imports from the main DSRT codebase.
"""

from __future__ import annotations


# The runner script is kept as a string template so it can be written
# to disk as-is and executed in complete isolation from the DSRT process.
RUNNER_SCRIPT: str = '''
"""
DSRT Sandboxed Python Runner.

Executes user code safely and writes structured results to a JSON file.
This script runs inside a fresh python subprocess with -I -S flags set.
"""

import json
import sys
import traceback


def _run():
    code_path = sys.argv[1]
    result_path = sys.argv[2]

    try:
        with open(code_path, "r", encoding="utf-8") as f:
            user_code = f.read()
    except Exception as e:
        _write_result(result_path, success=False, error=f"Cannot read code file: {e}")
        return 1

    # Prepare restricted globals. We expose __builtins__ because almost all
    # legitimate code needs them (print, len, dict, etc.), but we omit the
    # user from having access to the DSRT process internals.
    user_globals = {
        "__name__": "__dsrt_sandbox__",
        "__builtins__": __builtins__,
    }

    result_value = None
    error_message = None
    error_type = None
    success = True

    try:
        # Compile with the file name set to <sandbox> so tracebacks are clean
        compiled = compile(user_code, "<sandbox>", "exec")
        exec(compiled, user_globals)

        # If the user set a "result" variable, capture it
        if "result" in user_globals:
            try:
                # Try JSON-serializing it
                result_value = user_globals["result"]
                json.dumps(result_value, default=str)
            except (TypeError, ValueError):
                # Not JSON-serializable; coerce to string
                result_value = repr(user_globals["result"])

    except SystemExit as e:
        success = (e.code == 0 or e.code is None)
        if not success:
            error_message = f"SystemExit({e.code})"
            error_type = "SystemExit"
    except BaseException as e:
        success = False
        error_type = type(e).__name__
        error_message = str(e)
        # Print traceback to stderr so it's captured
        traceback.print_exc()

    _write_result(
        result_path,
        success=success,
        result=result_value,
        error=error_message,
        error_type=error_type,
    )
    return 0 if success else 2


def _write_result(path, *, success, result=None, error=None, error_type=None):
    payload = {
        "success": success,
        "result": result,
        "error": error,
        "error_type": error_type,
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, default=str)
    except Exception:
        # If we can't write the result, we just exit — the caller will
        # notice the missing result file and treat it as a failure.
        pass


if __name__ == "__main__":
    sys.exit(_run())
'''.lstrip()