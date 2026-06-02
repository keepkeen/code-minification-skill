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

_RE_BLOCK_COMMENT = re.compile(r'/\*[\s\S]*?\*/')
_RE_LINE_COMMENT = re.compile(r'//[^\n]*')
_RE_HASH_COMMENT = re.compile(r'(?m)^\s*#.*$')
_RE_TRAILING_WS = re.compile(r'[ \t]+$', re.MULTILINE)
_RE_LEADING_WS = re.compile(r'^[ \t]+', re.MULTILINE)
_RE_BLANK_LINES = re.compile(r'\n{2,}')
_RE_MULTI_SPACE = re.compile(r'[ \t]{2,}')


# ---------------------------------------------------------------------------
# Generic minifier for C-family / JS / Rust / etc.
# Comments stripped, leading+trailing whitespace removed, blank lines collapsed
# ---------------------------------------------------------------------------

def _generic_minify(source: str, keep_comments: bool = False) -> str:
    result = source
    if not keep_comments:
        result = _RE_BLOCK_COMMENT.sub('', result)
        result = _RE_LINE_COMMENT.sub('', result)
    result = _RE_TRAILING_WS.sub('', result)
    result = _RE_LEADING_WS.sub('', result)
    result = _RE_BLANK_LINES.sub('\n', result)
    result = result.strip()
    return result


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


# ---------------------------------------------------------------------------
# Go: strip comments, collapse whitespace, insert ; per Go's ASI rules
# ---------------------------------------------------------------------------

_GO_ASI_TRIGGER = re.compile(
    r'(?:'
    r'[a-zA-Z0-9_\x80-\xff]'
    r'|"|\x60|\''
    r'|\)|\]|\}'
    r'|--|\+\+'
    r'|$'
    r')$'
)


def _go_minify(source: str, keep_comments: bool = False) -> str:
    result = _generic_minify(source, keep_comments)
    lines = result.split('\n')
    tokens = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        if _GO_ASI_TRIGGER.search(s):
            s = s.rstrip(';') + ';'
        tokens.append(s)
    text = ' '.join(tokens)
    text = _RE_MULTI_SPACE.sub(' ', text)
    return text


# ---------------------------------------------------------------------------
# Shell: only strip comments and trailing whitespace, keep newline structure
# ---------------------------------------------------------------------------

def _shell_minify(source: str, keep_comments: bool = False) -> str:
    result = source
    if not keep_comments:
        result = _RE_HASH_COMMENT.sub('', result)
    result = _RE_TRAILING_WS.sub('', result)
    result = _RE_BLANK_LINES.sub('\n', result)
    result = result.strip()
    return result


# ---------------------------------------------------------------------------
# Ruby: strip comments, collapse blank lines
# ---------------------------------------------------------------------------

_RUBY_COMMENT_RE = re.compile(r'#[^\n]*')


def _ruby_minify(source: str, keep_comments: bool = False) -> str:
    result = source
    if not keep_comments:
        result = _RUBY_COMMENT_RE.sub('', result)
    result = _RE_TRAILING_WS.sub('', result)
    result = _RE_LEADING_WS.sub('', result)
    result = _RE_BLANK_LINES.sub('\n', result)
    result = result.strip()
    return result


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
    return _generic_minify(source, keep_comments)


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
