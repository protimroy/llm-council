"""Verification runner for falsifiable claims.

Executes controlled Python snippets derived from claim test_logic.
Uses AST-based validation for robust safety checks, then runs code in an
isolated subprocess with Linux namespace sandboxing when available.

SAFETY CONSTRAINTS:
- Only Python checks are supported
- Strict timeout (default 5 seconds)
- No network access (banned imports: socket, requests, urllib, httpx)
- No filesystem writes (banned: open with write modes, shutil)
- No arbitrary code execution (banned: exec, eval, __import__, compile)
- No package installation
- No access to environment variables (stripped env)
- AST-based validation (with string-based fallback for syntax errors)
- Namespace sandboxing via ``unshare`` when available
- Restricted builtins and module imports inside the runner
- Hard resource limits for CPU, memory, file size, and open files
- Parallel execution with bounded concurrency
"""

import ast
import asyncio
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
from typing import List, Tuple

from .models import (
    VerificationTarget, VerificationTargetType,
    VerificationResult, VerificationReport, VerificationStatus,
    PostVerificationAction,
)

logger = logging.getLogger(__name__)

# ─── Safety Constants ────────────────────────────────────────────────────────

MAX_TIMEOUT_SECONDS = 30
DEFAULT_TIMEOUT_SECONDS = 5
MAX_CONCURRENT_VERIFICATIONS = 3

SANDBOX_MEMORY_LIMIT_BYTES = 256 * 1024 * 1024
SANDBOX_FILE_SIZE_LIMIT_BYTES = 1 * 1024 * 1024
SANDBOX_NOFILE_LIMIT = 32

SANDBOX_ALLOWED_MODULES = {
    "math",
    "statistics",
    "decimal",
    "fractions",
    "random",
    "itertools",
    "functools",
    "operator",
    "collections",
    "json",
    "re",
    "string",
    "datetime",
    "time",
}

UNSHARE_BINARY = shutil.which("unshare")
SANDBOX_STRATEGY = "unshare" if UNSHARE_BINARY else "isolated-subprocess"

# ─── AST-Based Code Validation ───────────────────────────────────────────────

# Modules that are NEVER allowed in verification code
BANNED_MODULES = {
    # Network access
    "socket", "requests", "urllib", "httpx", "http", "ftplib", "smtplib",
    "poplib", "imaplib", "nntplib", "telnetlib", "xmlrpc",
    # OS/filesystem access
    "os", "sys", "subprocess", "shutil", "pathlib", "glob", "tempfile",
    "signal", "resource", "ctypes", "multiprocessing",
    # Dangerous builtins
    "pickle", "shelve", "marshal", "codecs", "builtins", "importlib",
    # Package management
    "pip", "setuptools", "distutils",
    # Crypto/key access
    "hashlib", "hmac", "secrets", "ssl",
}

# Banned function calls (builtins)
BANNED_FUNCTIONS = {
    "exec", "eval", "compile", "__import__", "open",
    "globals", "locals", "vars", "dir",
    "getattr", "setattr", "delattr", "hasattr",
    "type", "super", "classmethod",
    "input", "breakpoint",
}

# Banned attribute accesses
BANNED_ATTRIBUTES = {
    ("os", "system"), ("os", "popen"), ("os", "spawn"), ("os", "environ"),
    ("os", "getenv"), ("os", "putenv"), ("os", "unsetenv"),
    ("sys", "exit"), ("sys", "argv"),
    ("subprocess", "run"), ("subprocess", "call"), ("subprocess", "Popen"),
}

# String patterns for fallback validation (used when AST parsing fails)
BANNED_PATTERNS = [
    # Network access
    "import socket", "import requests", "import urllib", "import httpx",
    "from socket", "from requests", "from urllib", "from httpx",
    # Filesystem writes
    "import shutil", "from shutil",
    # Dangerous builtins
    "exec(", "eval(", "__import__(", "compile(",
    # OS access
    "import os", "from os", "os.system", "os.popen", "os.spawn", "subprocess",
    # Path manipulation
    "import pathlib", "from pathlib",
    # Environment access
    "os.environ", "os.getenv",
    # Dynamic code
    "globals(", "locals(", "getattr(", "setattr(", "delattr(",
]


class _SafetyVisitor(ast.NodeVisitor):
    """AST visitor that checks for unsafe code patterns."""

    def __init__(self):
        self.violations: List[str] = []

    def _check_banned_module(self, module_name: str) -> None:
        """Check if a module name is in the banned list."""
        # Check the top-level module (e.g., "os" from "os.path")
        top_level = module_name.split(".")[0]
        if top_level in BANNED_MODULES:
            self.violations.append(f"Banned import: {module_name}")

    def visit_Import(self, node: ast.Import) -> None:
        """Check import statements."""
        for alias in node.names:
            self._check_banned_module(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Check from...import statements."""
        if node.module:
            self._check_banned_module(node.module)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        """Check function calls for banned functions."""
        # Check direct function calls: exec(...), eval(...), open(...)
        if isinstance(node.func, ast.Name):
            if node.func.id in BANNED_FUNCTIONS:
                # Allow open() for read-only access — checked separately
                if node.func.id == "open":
                    self._check_open_write(node)
                else:
                    self.violations.append(f"Banned function call: {node.func.id}()")

        # Check attribute calls: os.system(...), subprocess.run(...)
        if isinstance(node.func, ast.Attribute):
            # Check for banned attribute patterns
            if isinstance(node.func.value, ast.Name):
                obj_name = node.func.value.id
                attr_name = node.func.attr
                if (obj_name, attr_name) in BANNED_ATTRIBUTES:
                    self.violations.append(f"Banned attribute access: {obj_name}.{attr_name}()")

        self.generic_visit(node)

    def _check_open_write(self, node: ast.Call) -> None:
        """Check if an open() call has write mode arguments."""
        # open(file, mode) — check if mode includes 'w', 'a', or 'x'
        if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
            mode = str(node.args[1].value)
            if any(m in mode for m in ["w", "a", "x"]):
                self.violations.append(f"File write mode detected: open(..., '{mode}')")
        # Check keyword arguments for mode
        for kw in node.keywords:
            if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                mode = str(kw.value.value)
                if any(m in mode for m in ["w", "a", "x"]):
                    self.violations.append(f"File write mode detected: open(..., mode='{mode}')")

    def visit_Attribute(self, node: ast.Attribute) -> None:
        """Check attribute access for banned patterns."""
        if isinstance(node.value, ast.Name):
            obj_name = node.value.id
            attr_name = node.attr
            if (obj_name, attr_name) in BANNED_ATTRIBUTES:
                self.violations.append(f"Banned attribute access: {obj_name}.{attr_name}")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        """Check for __import__ and other banned names used as references."""
        if node.id in ("__import__",):
            self.violations.append(f"Banned name reference: {node.id}")
        self.generic_visit(node)


def _validate_code_ast(code: str) -> Tuple[bool, str]:
    """Validate code using AST analysis.

    Parses the code into an AST tree and walks it to detect
    unsafe patterns like banned imports, function calls, and
    attribute accesses.

    Args:
        code: The Python code to validate.

    Returns:
        Tuple of (is_safe, reason). If is_safe is False, reason explains why.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        # If we can't parse it, fall back to string-based validation
        return False, f"Code has syntax errors and cannot be safely analyzed: {e}"

    visitor = _SafetyVisitor()
    visitor.visit(tree)

    if visitor.violations:
        # Return the first violation
        return False, visitor.violations[0]

    return True, "Code passed AST-based safety validation"


def _validate_code_string(code: str) -> Tuple[bool, str]:
    """Fallback string-based validation for code that cannot be AST-parsed.

    This is less robust than AST validation and can be bypassed by
    obfuscated code. It serves as a safety net only.

    Args:
        code: The Python code to validate.

    Returns:
        Tuple of (is_safe, reason). If is_safe is False, reason explains why.
    """
    if not code or not code.strip():
        return False, "Empty code snippet"

    for pattern in BANNED_PATTERNS:
        if pattern in code:
            return False, f"Banned pattern found: {pattern}"

    # Check for file write patterns
    if "open(" in code:
        import re
        open_matches = re.findall(r'open\s*\([^)]*\)', code)
        for match in open_matches:
            if any(mode in match for mode in ["'w'", '"w"', "'a'", '"a"', "'x'", '"x"']):
                return False, f"File write detected in: {match}"

    return True, "Code passed string-based safety validation (AST fallback)"


def _validate_code(code: str) -> Tuple[bool, str]:
    """Validate that a Python code snippet is safe to execute.

    Uses AST-based analysis as the primary method. Falls back to
    string-based pattern matching if AST parsing fails.

    Args:
        code: The Python code to validate.

    Returns:
        Tuple of (is_safe, reason). If is_safe is False, reason explains why.
    """
    if not code or not code.strip():
        return False, "Empty code snippet"

    # Try AST-based validation first (more robust)
    is_safe, reason = _validate_code_ast(code)
    if not is_safe:
        # If AST validation found a real violation (not just syntax error),
        # return it immediately
        if "syntax errors" not in reason.lower():
            return False, reason
        # If it's a syntax error, fall back to string-based validation
        # which can still catch obvious patterns
        return _validate_code_string(code)

    return True, reason


def _build_sandbox_wrapper(code: str, timeout: int) -> str:
    """Build the wrapper script executed inside the sandbox.

    The wrapper sets hard resource limits, exposes only a safe subset of
    builtins, restricts imports to a small allowlist, and then executes the
    validated user code.
    """
    safe_builtin_names = [
        "abs", "all", "any", "bool", "chr", "dict", "enumerate", "filter",
        "float", "int", "isinstance", "len", "list", "map", "max", "min",
        "object", "pow", "print", "range", "repr", "reversed", "round",
        "set", "sorted", "str", "sum", "tuple", "zip", "Exception",
        "BaseException", "AssertionError", "ValueError", "TypeError",
        "ImportError", "RuntimeError", "TimeoutError", "ZeroDivisionError",
    ]
    safe_builtins_entries = ",\n    ".join(
        [f'"{name}": builtins.{name}' for name in safe_builtin_names]
    )
    allowed_modules = sorted(SANDBOX_ALLOWED_MODULES)
    cpu_limit = max(1, timeout)

    return f"""import builtins
import resource
import signal

ALLOWED_MODULES = set({allowed_modules!r})


def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):
    top_level = name.split('.', 1)[0]
    if top_level not in ALLOWED_MODULES:
        raise ImportError(f"Import of {{name}} is not allowed in verification sandbox")
    return builtins.__import__(name, globals, locals, fromlist, level)


SAFE_BUILTINS = {{
    {safe_builtins_entries},
    "__import__": _safe_import,
}}

resource.setrlimit(resource.RLIMIT_CPU, ({cpu_limit}, {cpu_limit}))
resource.setrlimit(resource.RLIMIT_AS, ({SANDBOX_MEMORY_LIMIT_BYTES}, {SANDBOX_MEMORY_LIMIT_BYTES}))
resource.setrlimit(resource.RLIMIT_FSIZE, ({SANDBOX_FILE_SIZE_LIMIT_BYTES}, {SANDBOX_FILE_SIZE_LIMIT_BYTES}))
resource.setrlimit(resource.RLIMIT_NOFILE, ({SANDBOX_NOFILE_LIMIT}, {SANDBOX_NOFILE_LIMIT}))

try:
    resource.setrlimit(resource.RLIMIT_NPROC, (1, 1))
except (AttributeError, OSError, ValueError):
    pass

try:
    signal.alarm({cpu_limit + 1})
except (AttributeError, ValueError):
    pass

globals_dict = {{
    "__name__": "__main__",
    "__builtins__": SAFE_BUILTINS,
}}

code_obj = compile({code!r}, "<verification>", "exec")
exec(code_obj, globals_dict, globals_dict)
"""


def _build_sandbox_command(wrapper_path: str) -> Tuple[List[str], str]:
    """Build the subprocess command used to run sandboxed verification code."""
    python_command = [sys.executable, "-I", wrapper_path]

    if UNSHARE_BINARY:
        return (
            [
                UNSHARE_BINARY,
                "--user",
                "--map-root-user",
                "--net",
                "--pid",
                "--fork",
                "--mount-proc",
                *python_command,
            ],
            "unshare",
        )

    return (python_command, "isolated-subprocess")


def _run_python_snippet(
    code: str,
    timeout: int = DEFAULT_TIMEOUT_SECONDS
) -> Tuple[str, str, int, bool, str]:
    """Run a Python code snippet in a subprocess with strict isolation.

    Args:
        code: The Python code to execute.
        timeout: Maximum execution time in seconds.

    Returns:
        Tuple of (stdout, stderr, returncode, timed_out, sandbox_strategy).
    """
    wrapper_code = _build_sandbox_wrapper(code, timeout)

    with tempfile.TemporaryDirectory(prefix="llm_council_verify_") as temp_dir:
        wrapper_path = os.path.join(temp_dir, "runner.py")
        with open(wrapper_path, "w", encoding="utf-8") as wrapper_file:
            wrapper_file.write(wrapper_code)

        minimal_env = {
            "PYTHONPATH": "",
            "PYTHONNOUSERSITE": "1",
            "HOME": temp_dir,
            "TMPDIR": temp_dir,
        }

        command, strategy = _build_sandbox_command(wrapper_path)

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=minimal_env,
                cwd=temp_dir,
            )
            return result.stdout, result.stderr, result.returncode, False, strategy

        except subprocess.TimeoutExpired:
            return "", "Execution timed out", -1, True, strategy

        except OSError as exc:
            if strategy == "unshare":
                logger.warning("unshare sandbox unavailable at runtime, falling back to isolated subprocess: %s", exc)
                fallback_command = [sys.executable, "-I", wrapper_path]
                try:
                    result = subprocess.run(
                        fallback_command,
                        capture_output=True,
                        text=True,
                        timeout=timeout,
                        env=minimal_env,
                        cwd=temp_dir,
                    )
                    return result.stdout, result.stderr, result.returncode, False, "isolated-subprocess-fallback"
                except subprocess.TimeoutExpired:
                    return "", "Execution timed out", -1, True, "isolated-subprocess-fallback"
                except Exception as fallback_exc:
                    return "", f"Execution error: {fallback_exc}", -1, False, "isolated-subprocess-fallback"

            return "", f"Execution error: {exc}", -1, False, strategy

        except Exception as exc:
            return "", f"Execution error: {exc}", -1, False, strategy


async def run_single_verification(target: VerificationTarget) -> VerificationResult:
    """Verify a single verification target.

    Args:
        target: The VerificationTarget to verify.

    Returns:
        VerificationResult with status, summary, and logs.
    """
    # Not testable — skip immediately
    if target.target_type == VerificationTargetType.not_testable:
        logger.info(f"Target {target.target_id}: not_testable, skipping")
        return VerificationResult(
            target_id=target.target_id,
            source_claim_id=target.source_claim_id,
            status=VerificationStatus.not_testable,
            summary=f"Claim '{target.source_claim_id}' is not testable with available methods.",
            notes="No test_logic provided or target_type is not_testable."
        )

    # No test logic provided
    if not target.test_logic or not target.test_logic.strip():
        logger.info(f"Target {target.target_id}: no test_logic, marking not_testable")
        return VerificationResult(
            target_id=target.target_id,
            source_claim_id=target.source_claim_id,
            status=VerificationStatus.not_testable,
            summary=f"Claim '{target.source_claim_id}' has no test logic.",
            notes="test_logic field is empty."
        )

    # Validate code safety
    is_safe, reason = _validate_code(target.test_logic)
    if not is_safe:
        logger.warning(f"Target {target.target_id}: unsafe code — {reason}")
        return VerificationResult(
            target_id=target.target_id,
            source_claim_id=target.source_claim_id,
            status=VerificationStatus.skipped,
            summary=f"Verification skipped: {reason}",
            notes=f"Safety validation failed for claim '{target.source_claim_id}'."
        )

    # Run the code
    timeout = min(target.timeout_seconds, MAX_TIMEOUT_SECONDS)
    start_time = time.time()

    # Run in executor to avoid blocking the event loop
    loop = asyncio.get_event_loop()
    stdout, stderr, returncode, timed_out, sandbox_strategy = await loop.run_in_executor(
        None, _run_python_snippet, target.test_logic, timeout
    )

    execution_time_ms = int((time.time() - start_time) * 1000)

    if timed_out:
        logger.warning(f"Target {target.target_id}: timed out after {timeout}s")
        return VerificationResult(
            target_id=target.target_id,
            source_claim_id=target.source_claim_id,
            status=VerificationStatus.timeout,
            summary=f"Verification timed out after {timeout} seconds.",
            raw_logs=stderr,
            execution_time_ms=execution_time_ms,
            notes=f"Code execution exceeded {timeout}s limit in {sandbox_strategy}."
        )

    # Determine status based on return code
    if returncode == 0:
        status = VerificationStatus.passed
        summary = f"Claim '{target.source_claim_id}' passed verification."
        logger.info(f"Target {target.target_id}: PASSED")
    else:
        status = VerificationStatus.failed
        summary = f"Claim '{target.source_claim_id}' failed verification (exit code {returncode})."
        logger.info(f"Target {target.target_id}: FAILED (exit code {returncode})")

    raw_logs = f"STDOUT:\n{stdout}\nSTDERR:\n{stderr}" if stdout or stderr else ""

    return VerificationResult(
        target_id=target.target_id,
        source_claim_id=target.source_claim_id,
        status=status,
        summary=summary,
        raw_logs=raw_logs,
        execution_time_ms=execution_time_ms,
        derived_evidence_strength="strong" if status == VerificationStatus.passed else "weak",
        notes=f"Executed in {execution_time_ms}ms using {sandbox_strategy}."
    )


async def run_verification(
    targets: List[VerificationTarget],
    max_concurrent: int = MAX_CONCURRENT_VERIFICATIONS
) -> VerificationReport:
    """Run verification for a list of targets.

    Targets are executed in parallel (up to max_concurrent at a time)
    using asyncio.gather with a semaphore for concurrency control.

    Args:
        targets: List of VerificationTarget objects to verify.
        max_concurrent: Maximum number of concurrent verifications (default 3).

    Returns:
        VerificationReport with results and summary.
    """
    if not targets:
        return VerificationReport(
            decision_source="no_targets",
            targets_run=0,
            summary="No verification targets provided.",
            recommended_next_step=PostVerificationAction.synthesize_now
        )

    # Semaphore to limit concurrent executions
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _verify_with_semaphore(target: VerificationTarget) -> VerificationResult:
        """Run a single verification with semaphore-based concurrency control."""
        async with semaphore:
            return await run_single_verification(target)

    # Run all verifications in parallel with concurrency limit
    tasks = [_verify_with_semaphore(target) for target in targets]

    # Use return_exceptions=True to prevent one failure from stopping others
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    # Process results
    results: List[VerificationResult] = []
    passed = 0
    failed = 0
    errors = 0
    timeouts = 0
    not_testable = 0
    skipped = 0

    for i, result in enumerate(raw_results):
        if isinstance(result, Exception):
            # Unexpected error during verification
            target = targets[i]
            logger.error(f"Unexpected error verifying target {target.target_id}: {result}")
            results.append(VerificationResult(
                target_id=target.target_id,
                source_claim_id=target.source_claim_id,
                status=VerificationStatus.error,
                summary=f"Unexpected error: {result}",
                notes="Verification runner encountered an exception."
            ))
            errors += 1
        else:
            results.append(result)
            # Count by status
            if result.status == VerificationStatus.passed:
                passed += 1
            elif result.status == VerificationStatus.failed:
                failed += 1
            elif result.status == VerificationStatus.timeout:
                timeouts += 1
            elif result.status == VerificationStatus.not_testable:
                not_testable += 1
            elif result.status == VerificationStatus.skipped:
                skipped += 1
            else:
                errors += 1

    # Determine recommended next step
    if errors > 0:
        recommended = PostVerificationAction.unresolved
    elif failed > 0:
        recommended = PostVerificationAction.request_second_round
    else:
        recommended = PostVerificationAction.synthesize_now

    summary = (
        f"Ran {len(targets)} verification targets: "
        f"{passed} passed, {failed} failed, {not_testable} not testable, "
        f"{timeouts} timed out, {skipped} skipped, {errors} errors."
    )

    logger.info(f"Verification report: {summary}")

    return VerificationReport(
        decision_source="fast_judge",
        targets_run=len(targets),
        results=results,
        passed_count=passed,
        failed_count=failed,
        error_count=errors,
        timeout_count=timeouts,
        not_testable_count=not_testable,
        summary=summary,
        recommended_next_step=recommended
    )