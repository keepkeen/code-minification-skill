#!/usr/bin/env python3
"""
Evaluate code-minification skill: measure token reduction and verify
semantic preservation.

Phase 1 — Token reduction metrics (no API cost)
  python3 evaluate.py --phase=reduction sample.py sample.go sample.js

Phase 2 — Syntax validation (no API cost)
  python3 evaluate.py --phase=syntax sample.py sample.go sample.js

Phase 3 — LLM comprehension A/B test (requires API key)
  python3 evaluate.py --phase=llm --api-key=$ANTHROPIC_API_KEY *.py

Full report:
  python3 evaluate.py sample.py sample.go sample.js
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True

SCRIPT_DIR = os.path.dirname(__file__)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

import minify_code

MINIFIER = os.path.join(os.path.dirname(__file__), "minify_code.py")


# ---------------------------------------------------------------------------
# Phase 1: Token reduction
# ---------------------------------------------------------------------------

def _minify_path(path: str) -> dict | None:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        source = f.read()
    language = minify_code.detect_language(path)
    if not language:
        return None
    output = minify_code.minify(source, language)
    original_chars = len(source)
    minified_chars = len(output)
    ratio = 1.0 - (minified_chars / original_chars) if original_chars > 0 else 0.0
    return {
        "language": language,
        "original_chars": original_chars,
        "minified_chars": minified_chars,
        "reduction_ratio": round(ratio, 3),
        "comments_stripped": True,
        "output": output,
    }


def phase_reduction(file_paths: list[str]) -> list[dict]:
    results = []
    for path in file_paths:
        result = _minify_path(path)
        if result is None:
            results.append({
                "file": os.path.basename(path),
                "language": "unsupported",
                "original_chars": os.path.getsize(path),
                "minified_chars": os.path.getsize(path),
                "reduction_ratio": 0.0,
                "skipped": True,
            })
            continue
        # Estimate token count: ~4 chars per token for code
        result["original_tokens"] = result["original_chars"] // 4
        result["minified_tokens"] = result["minified_chars"] // 4
        result["file"] = os.path.basename(path)
        results.append(result)
    return results


# ---------------------------------------------------------------------------
# Phase 2: Syntax validation
# ---------------------------------------------------------------------------

def _run_stdin_parser(cmd: list[str], code: str, timeout: int = 10) -> tuple[bool | None, str]:
    try:
        result = subprocess.run(
            cmd,
            input=code,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return None, f"({cmd[0]} not installed, skipped)"
    except subprocess.TimeoutExpired:
        return False, "timeout"
    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip()
    return True, ""


def _run_file_parser(cmd_template: list[str], code: str, suffix: str, timeout: int = 10, filename: str | None = None) -> tuple[bool | None, str]:
    exe = cmd_template[0]
    if shutil.which(exe) is None:
        return None, f"({exe} not installed, skipped)"
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, filename or ("input" + suffix))
        with open(path, "w", encoding="utf-8") as f:
            f.write(code)
        cmd = [arg.format(file=path, dir=tmpdir) for arg in cmd_template]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return False, "timeout"
        if result.returncode != 0:
            return False, (result.stderr or result.stdout).strip()
        return True, ""


def _java_filename(code: str) -> str:
    match = re.search(r"\bpublic\s+(?:final\s+|abstract\s+)?(?:class|interface|enum|record)\s+([A-Za-z_]\w*)", code)
    if match:
        return match.group(1) + ".java"
    return "Input.java"


def _check_parseable(code: str, language: str) -> tuple[bool | None, str]:
    """Check if minified code is syntactically valid using available parsers.

    Returns:
        True: syntax checked and valid.
        False: syntax checked and invalid.
        None: no suitable parser was available for this standalone script.
    """
    if language == "python":
        try:
            compile(code, "<minified>", "exec")
            return True, ""
        except SyntaxError as e:
            return False, str(e)
    if language == "go":
        return _run_stdin_parser(["gofmt", "-e"], code)
    if language == "javascript":
        return _run_stdin_parser(["node", "--input-type=module", "--check", "-"], code)
    if language == "typescript":
        return None, "(node --check cannot parse TypeScript, skipped)"
    if language == "rust":
        return _run_file_parser(
            ["rustc", "--edition=2021", "--crate-type", "lib", "--emit=metadata", "{file}", "-o", "{dir}/lib.rmeta"],
            code,
            ".rs",
        )
    if language == "java":
        return _run_file_parser(["javac", "-Xlint:none", "-d", "{dir}/out", "{file}"], code, ".java", filename=_java_filename(code))
    if language == "c":
        return _run_stdin_parser(["clang", "-x", "c", "-fsyntax-only", "-"], code)
    if language == "cpp":
        return _run_stdin_parser(["clang++", "-std=c++20", "-x", "c++", "-fsyntax-only", "-"], code)
    if language == "swift":
        return _run_file_parser(["swiftc", "-parse", "{file}"], code, ".swift")
    if language == "ruby":
        return _run_stdin_parser(["ruby", "-c"], code)
    if language == "shell":
        return _run_stdin_parser(["bash", "-n"], code)
    return None, "(no parser available)"


def phase_syntax(file_paths: list[str]) -> list[dict]:
    results = []
    for path in file_paths:
        with open(path) as f:
            original = f.read()

        result = _minify_path(path)
        if result is None:
            results.append({
                "file": os.path.basename(path),
                "language": "unsupported",
                "original_parseable": None,
                "original_parse_note": "(unsupported file type)",
                "minified_parseable": None,
                "parse_error": "(unsupported file type)",
                "idempotent": True,
            })
            continue
        language = result["language"]
        minified = result["output"]

        # Check original is parseable (baseline)
        orig_ok, orig_err = _check_parseable(original, language)
        if orig_ok is False:
            min_ok, min_err = None, "baseline is not parseable by this parser: " + orig_err
        else:
            min_ok, min_err = _check_parseable(minified, language)

        # Idempotency check
        idempotent = minify_code.minify(minified, language) == minified

        results.append({
            "file": os.path.basename(path),
            "language": language,
            "original_parseable": orig_ok,
            "original_parse_note": orig_err,
            "minified_parseable": min_ok,
            "parse_error": min_err if min_ok is not True else "",
            "idempotent": idempotent,
        })
    return results


# ---------------------------------------------------------------------------
# Phase 3: LLM comprehension A/B test
# ---------------------------------------------------------------------------

LLM_COMPREHENSION_PROMPT = """\
Given the following source code, answer these questions concisely:

1. What is the main purpose of this code?
2. List all classes/types defined.
3. List all functions/methods defined.
4. Describe the control flow of the main entry point.

Code:
```{language}
{code}
```

Respond with a JSON object with keys: purpose, types, functions, control_flow.
"""


def phase_llm(file_paths: list[str], api_key: str) -> list[dict]:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)

    results = []
    for path in file_paths:
        with open(path) as f:
            original = f.read()

        result = _minify_path(path)
        if result is None:
            continue
        language = result["language"]
        minified = result["output"]

        def ask(code: str, label: str) -> str:
            resp = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=500,
                temperature=0,
                messages=[{
                    "role": "user",
                    "content": LLM_COMPREHENSION_PROMPT.format(
                        language=language, code=code
                    ),
                }],
            )
            return resp.content[0].text

        original_response = ask(original, "original")
        minified_response = ask(minified, "minified")

        results.append({
            "file": os.path.basename(path),
            "language": language,
            "original_response": original_response,
            "minified_response": minified_response,
        })
    return results


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def print_report(phases: dict) -> None:
    if "reduction" in phases:
        data = phases["reduction"]
        print("=" * 60)
        print("Phase 1: Token Reduction")
        print("=" * 60)
        print(f"{'File':<20} {'Lang':<10} {'Orig chars':<12} {'Min chars':<12} {'Reduction':<10}")
        print("-" * 64)
        total_orig = 0
        total_min = 0
        for r in data:
            if r.get("skipped"):
                print(f"{r['file']:<20} {'SKIP':<10} {r['original_chars']:<12} {'':<12} {'unsupported':>10}")
                continue
            ratio = r["reduction_ratio"]
            total_orig += r["original_chars"]
            total_min += r["minified_chars"]
            bar = "█" * int(ratio * 40) + "░" * (40 - int(ratio * 40))
            print(f"{r['file']:<20} {r['language']:<10} {r['original_chars']:<12} {r['minified_chars']:<12} {ratio:>7.1%}")
            print(f"{'':>20} {'':<10} {'':<12} {'':<12} {bar}")
        overall = 1 - total_min / total_orig
        print("-" * 64)
        print(f"{'TOTAL':<20} {'':<10} {total_orig:<12} {total_min:<12} {overall:>7.1%}")

    if "syntax" in phases:
        data = phases["syntax"]
        print()
        print("=" * 60)
        print("Phase 2: Syntax Validation & Idempotency")
        print("=" * 60)
        print(f"{'File':<20} {'Lang':<10} {'Parseable':<35} {'Idempotent':<12}")
        print("-" * 54)
        all_pass = True
        for r in data:
            parse_ok = r["minified_parseable"]
            idem = r["idempotent"]
            if parse_ok is True:
                parse_status = "OK"
            elif parse_ok is False:
                parse_status = "FAIL " + r.get("parse_error", "")
            else:
                parse_status = "SKIP " + r.get("parse_error", "")
            idem_status = "✅" if idem else "❌"
            msg = f"{r['file']:<20} {r['language']:<10} {parse_status:<35} {idem_status:<12}"
            print(msg)
            if parse_ok is False or not idem:
                all_pass = False
        print("-" * 54)
        if all_pass:
            print("All checked parsers pass, and all files are idempotent.")
        else:
            print("Some files failed checks — review above.")

    if "llm" in phases:
        data = phases["llm"]
        print()
        print("=" * 60)
        print("Phase 3: LLM Comprehension A/B")
        print("=" * 60)
        for r in data:
            print(f"\n--- {r['file']} ({r['language']}) ---")
            print("  Original response:")
            for line in r["original_response"].strip().split("\n"):
                print(f"    {line}")
            print("  Minified response:")
            for line in r["minified_response"].strip().split("\n"):
                print(f"    {line}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate code-minification skill effectiveness."
    )
    parser.add_argument("files", nargs="+", help="Source files to evaluate")
    parser.add_argument("--phase", choices=["reduction", "syntax", "llm", "all"],
                        default="all", help="Which phase to run")
    parser.add_argument("--api-key", help="Anthropic API key for LLM phase")
    args = parser.parse_args()

    missing = [f for f in args.files if not os.path.isfile(f)]
    if missing:
        print(f"Files not found: {missing}", file=sys.stderr)
        sys.exit(1)

    if not os.path.isfile(MINIFIER):
        print(f"Minifier not found at {MINIFIER}", file=sys.stderr)
        sys.exit(1)

    phases = {}

    if args.phase in ("reduction", "all"):
        phases["reduction"] = phase_reduction(args.files)

    if args.phase in ("syntax", "all"):
        phases["syntax"] = phase_syntax(args.files)

    if args.phase in ("llm", "all"):
        if not args.api_key:
            print("Phase 3 (LLM) requires --api-key to be set.", file=sys.stderr)
        else:
            phases["llm"] = phase_llm(args.files, args.api_key)

    print_report(phases)


if __name__ == "__main__":
    main()
