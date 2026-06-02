#!/usr/bin/env python3
"""Minify source code by stripping non-semantic whitespace and comments.

Reduces token consumption for LLM processing by 20-50% while preserving
the semantic skeleton of the code.

Usage:
    python3 minify_code.py path/to/file.py
    python3 minify_code.py --keep-comments path/to/file.go
    cat file.ts | python3 minify_code.py --language typescript
    python3 minify_code.py --json path/to/file.rs

Language support: python, javascript, typescript, go, rust, java, c, cpp,
                  csharp, swift, ruby, shell, jsx, tsx
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tokenize
import io


LANGUAGE_EXTENSIONS = {
    '.py': 'python',
    '.js': 'javascript', '.mjs': 'javascript', '.cjs': 'javascript',
    '.ts': 'typescript',
    '.jsx': 'jsx',
    '.tsx': 'tsx',
    '.go': 'go',
    '.rs': 'rust',
    '.java': 'java',
    '.c': 'c', '.h': 'c',
    '.cpp': 'cpp', '.hpp': 'cpp', '.cc': 'cpp', '.cxx': 'cpp',
    '.cs': 'csharp',
    '.swift': 'swift',
    '.rb': 'ruby',
    '.sh': 'shell', '.bash': 'shell',
}


def detect_language(filepath: str, forced: str | None = None) -> str | None:
    if forced:
        return forced
    ext = os.path.splitext(filepath)[1].lower()
    return LANGUAGE_EXTENSIONS.get(ext)


# ---------------------------------------------------------------------------
# Shared regex patterns
# ---------------------------------------------------------------------------

_RE_HASH_COMMENT = re.compile(r'(?m)^\s*#.*$')
_RE_BLANK_LINES = re.compile(r'\n{2,}')


def _append(chars: list[str], protected: list[bool], text: str, is_protected: bool) -> None:
    chars.extend(text)
    protected.extend([is_protected] * len(text))


def _parse_quoted(source: str, start: int, quote: str, triple: bool = False) -> int:
    n = len(source)
    i = start + (3 if triple else 1)
    while i < n:
        if source[i] == "\\":
            i += 2
            continue
        if triple and source.startswith(quote * 3, i):
            return i + 3
        if not triple and source[i] == quote:
            return i + 1
        i += 1
    return n


def _parse_backtick(source: str, start: int) -> int:
    n = len(source)
    i = start + 1
    while i < n:
        if source[i] == "\\":
            i += 2
            continue
        if source[i] == "`":
            return i + 1
        i += 1
    return n


def _parse_cpp_raw_string(source: str, start: int) -> int | None:
    if not source.startswith('R"', start):
        return None
    open_paren = source.find("(", start + 2)
    if open_paren == -1:
        return None
    delimiter = source[start + 2:open_paren]
    if len(delimiter) > 32:
        return None
    close = ")" + delimiter + '"'
    end = source.find(close, open_paren + 1)
    if end == -1:
        return None
    return end + len(close)


def _parse_rust_raw_string(source: str, start: int) -> int | None:
    i = start
    if source.startswith("br", i):
        i += 2
    elif source.startswith("r", i):
        i += 1
    else:
        return None

    hashes = 0
    while i < len(source) and source[i] == "#":
        hashes += 1
        i += 1
    if i >= len(source) or source[i] != '"':
        return None

    close = '"' + ("#" * hashes)
    end = source.find(close, i + 1)
    if end == -1:
        return None
    return end + len(close)


def _last_word(chars: list[str]) -> str:
    i = len(chars) - 1
    while i >= 0 and chars[i].isspace():
        i -= 1
    end = i + 1
    while i >= 0 and (chars[i].isalnum() or chars[i] == "_"):
        i -= 1
    return "".join(chars[i + 1:end])


def _regex_literal_allowed(chars: list[str]) -> bool:
    i = len(chars) - 1
    while i >= 0 and chars[i].isspace():
        i -= 1
    if i < 0:
        return True
    if chars[i] in "([{=:;,!&|?+-*%^~<>":
        return True
    return _last_word(chars) in {
        "return", "throw", "case", "delete", "typeof", "void", "new",
        "yield", "await", "else", "do", "in", "of",
    }


def _parse_regex_literal(source: str, start: int) -> int:
    n = len(source)
    i = start + 1
    in_class = False
    while i < n:
        c = source[i]
        if c == "\\":
            i += 2
            continue
        if c == "[":
            in_class = True
        elif c == "]":
            in_class = False
        elif c == "/" and not in_class:
            i += 1
            while i < n and (source[i].isalpha() or source[i].isdigit()):
                i += 1
            return i
        elif c == "\n":
            return start + 1
        i += 1
    return start + 1


def _find_block_comment_end(source: str, start: int, nested: bool = False) -> int:
    if not nested:
        return source.find("*/", start + 2)

    depth = 1
    i = start + 2
    n = len(source)
    while i + 1 < n:
        pair = source[i:i + 2]
        if pair == "/*":
            depth += 1
            i += 2
            continue
        if pair == "*/":
            depth -= 1
            if depth == 0:
                return i
            i += 2
            continue
        i += 1
    return -1


def _strip_c_style_comments(
    source: str,
    keep_comments: bool = False,
    *,
    js_like: bool = False,
    backtick_strings: bool = False,
    triple_double_strings: bool = False,
    rust_raw_strings: bool = False,
    cpp_raw_strings: bool = False,
    nested_block_comments: bool = False,
) -> tuple[list[str], list[bool]]:
    chars: list[str] = []
    protected: list[bool] = []
    i = 0
    n = len(source)

    while i < n:
        c = source[i]
        nxt = source[i + 1] if i + 1 < n else ""

        if cpp_raw_strings and c == "R" and nxt == '"':
            end = _parse_cpp_raw_string(source, i)
            if end is not None:
                _append(chars, protected, source[i:end], True)
                i = end
                continue

        if rust_raw_strings and c in {"r", "b"}:
            end = _parse_rust_raw_string(source, i)
            if end is not None:
                _append(chars, protected, source[i:end], True)
                i = end
                continue

        if triple_double_strings and source.startswith('"""', i):
            end = _parse_quoted(source, i, '"', triple=True)
            _append(chars, protected, source[i:end], True)
            i = end
            continue

        if c in {'"', "'"}:
            end = _parse_quoted(source, i, c)
            _append(chars, protected, source[i:end], True)
            i = end
            continue

        if backtick_strings and c == "`":
            end = _parse_backtick(source, i)
            _append(chars, protected, source[i:end], True)
            i = end
            continue

        if c == "/" and nxt == "/" and not keep_comments:
            end = source.find("\n", i + 2)
            if end == -1:
                break
            _append(chars, protected, "\n", False)
            i = end + 1
            continue

        if c == "/" and nxt == "*" and not keep_comments:
            end = _find_block_comment_end(source, i, nested_block_comments)
            if end == -1:
                break
            comment = source[i:end + 2]
            _append(chars, protected, "\n" if "\n" in comment else " ", False)
            i = end + 2
            continue

        if js_like and c == "/" and nxt not in {"/", "*"} and _regex_literal_allowed(chars):
            end = _parse_regex_literal(source, i)
            if end > i + 1:
                _append(chars, protected, source[i:end], True)
                i = end
                continue

        _append(chars, protected, c, False)
        i += 1

    return chars, protected


def _strip_hash_comments(source: str, keep_comments: bool = False) -> tuple[list[str], list[bool]]:
    chars: list[str] = []
    protected: list[bool] = []
    i = 0
    n = len(source)
    while i < n:
        c = source[i]
        if c in {'"', "'", "`"}:
            end = _parse_backtick(source, i) if c == "`" else _parse_quoted(source, i, c)
            _append(chars, protected, source[i:end], True)
            i = end
            continue
        if c == "#" and not keep_comments:
            end = source.find("\n", i + 1)
            if end == -1:
                break
            _append(chars, protected, "\n", False)
            i = end + 1
            continue
        _append(chars, protected, c, False)
        i += 1
    return chars, protected


def _normalize_layout(chars: list[str], protected: list[bool], *, strip_leading: bool = True, collapse_spaces: bool = True) -> str:
    lines: list[tuple[list[str], list[bool]]] = []
    cur_chars: list[str] = []
    cur_protected: list[bool] = []
    for c, p in zip(chars, protected):
        if c == "\n" and not p:
            lines.append((cur_chars, cur_protected))
            cur_chars, cur_protected = [], []
        else:
            cur_chars.append(c)
            cur_protected.append(p)
    lines.append((cur_chars, cur_protected))

    out_lines: list[str] = []
    previous_blank = False
    for line_chars, line_protected in lines:
        start = 0
        end = len(line_chars)
        if strip_leading:
            while start < end and not line_protected[start] and line_chars[start] in " \t":
                start += 1
        while end > start and not line_protected[end - 1] and line_chars[end - 1] in " \t":
            end -= 1

        pieces: list[str] = []
        in_space = False
        has_non_space = False
        for c, p in zip(line_chars[start:end], line_protected[start:end]):
            if not p and c in " \t":
                if collapse_spaces and not in_space:
                    pieces.append(" ")
                elif not collapse_spaces:
                    pieces.append(c)
                in_space = True
                continue
            pieces.append(c)
            in_space = False
            if p or not c.isspace():
                has_non_space = True

        if not has_non_space:
            if not previous_blank and out_lines:
                out_lines.append("")
            previous_blank = True
            continue
        out_lines.append("".join(pieces))
        previous_blank = False

    return "\n".join(out_lines).strip()


# ---------------------------------------------------------------------------
# Generic minifier for C-family / JS / Rust / etc.
# Comments stripped, leading+trailing whitespace removed, blank lines collapsed
# ---------------------------------------------------------------------------

def _generic_minify(source: str, keep_comments: bool = False, language: str | None = None) -> str:
    chars, protected = _strip_c_style_comments(
        source,
        keep_comments,
        js_like=language in {"javascript", "typescript", "jsx", "tsx"},
        backtick_strings=language in {"javascript", "typescript", "jsx", "tsx", "go"},
        triple_double_strings=language == "swift",
        rust_raw_strings=language == "rust",
        cpp_raw_strings=language in {"c", "cpp"},
        nested_block_comments=language in {"rust", "swift"},
    )
    return _normalize_layout(chars, protected)


# ---------------------------------------------------------------------------
# Python: use stdlib tokenize — respects indentation as syntax
# ---------------------------------------------------------------------------

def _python_minify(source: str, keep_comments: bool = False) -> str:
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except tokenize.TokenError:
        return _generic_minify(source, keep_comments)

    out = []
    indent_level = 0
    prev_was_newline = True

    for tok in tokens:
        typ, val, start, end, line = tok

        if typ == tokenize.ENCODING or typ == tokenize.NL:
            continue
        if typ == tokenize.ENDMARKER:
            break
        if typ == tokenize.COMMENT:
            if keep_comments:
                if out and not prev_was_newline:
                    out.append('\n')
                out.append(' ' * indent_level + val)
                prev_was_newline = False
            continue
        if typ == tokenize.INDENT:
            indent_level += 1
            if out and not prev_was_newline:
                out.append('\n')
            out.append(' ' * indent_level)
            prev_was_newline = False
            continue
        if typ == tokenize.DEDENT:
            indent_level = max(0, indent_level - 1)
            continue
        if typ == tokenize.NEWLINE:
            out.append('\n')
            prev_was_newline = True
            continue

        s = val

        if prev_was_newline:
            if indent_level > 0:
                out.append(' ' * indent_level)
        elif out:
            last_char = out[-1][-1] if out[-1] else ''
            first_char = s[0] if s else ''
            if (last_char.isalnum() or last_char == '_') and \
               (first_char.isalnum() or first_char == '_'):
                out.append(' ')

        out.append(s)
        prev_was_newline = False

    result = ''.join(out)

    result = _RE_BLANK_LINES.sub('\n', result)
    result = result.strip()
    return result


def _go_minify(source: str, keep_comments: bool = False) -> str:
    # Keep newlines in standalone mode. Go's semicolon insertion is easy to
    # get wrong without a parser, and preserving line boundaries keeps raw
    # strings and formatter round-trips intact.
    return _generic_minify(source, keep_comments, "go")


# ---------------------------------------------------------------------------
# Shell: only strip comments and trailing whitespace, keep newline structure
# ---------------------------------------------------------------------------

def _shell_minify(source: str, keep_comments: bool = False) -> str:
    result = source
    if not keep_comments:
        result = _RE_HASH_COMMENT.sub('', result)
    lines = [line.rstrip() for line in result.splitlines()]
    return _RE_BLANK_LINES.sub('\n', "\n".join(lines)).strip()


def _ruby_minify(source: str, keep_comments: bool = False) -> str:
    chars, protected = _strip_hash_comments(source, keep_comments)
    return _normalize_layout(chars, protected)


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_LANGUAGE_MINIFIERS = {
    'python': _python_minify,
    'go': _go_minify,
    'shell': _shell_minify,
    'ruby': _ruby_minify,
}


def minify(source: str, language: str | None, keep_comments: bool = False) -> str:
    minifier = _LANGUAGE_MINIFIERS.get(language)
    if minifier:
        return minifier(source, keep_comments)
    return _generic_minify(source, keep_comments, language)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description='Minify source code by stripping non-semantic whitespace and comments.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument('path', nargs='?', help='Source file path')
    parser.add_argument('--language', '-l', help='Force language instead of auto-detection')
    parser.add_argument('--keep-comments', '-k', action='store_true', help='Preserve comments')
    parser.add_argument('--json', '-j', action='store_true', help='JSON output with metrics')

    args = parser.parse_args()

    if args.path:
        if not os.path.isfile(args.path):
            print(f'Error: file not found: {args.path}', file=sys.stderr)
            sys.exit(1)
        with open(args.path, 'r', encoding='utf-8', errors='replace') as f:
            source = f.read()
        language = detect_language(args.path, args.language)
        source_name = args.path
    else:
        if sys.stdin.isatty():
            print('Error: provide a file path or pipe code via stdin', file=sys.stderr)
            sys.exit(1)
        source = sys.stdin.read()
        language = args.language
        source_name = '<stdin>'

    if not language:
        print(f'Error: unable to detect language for {source_name}. '
              f'Use --language to specify.', file=sys.stderr)
        sys.exit(1)

    original_chars = len(source)
    result = minify(source, language, args.keep_comments)
    minified_chars = len(result)
    ratio = 1.0 - (minified_chars / original_chars) if original_chars > 0 else 0.0

    if args.json:
        output = {
            'language': language,
            'original_chars': original_chars,
            'minified_chars': minified_chars,
            'reduction_ratio': round(ratio, 3),
            'comments_stripped': not args.keep_comments,
            'output': result,
        }
        json.dump(output, sys.stdout, indent=2)
        print()
    else:
        print(result, end='')


if __name__ == '__main__':
    main()
