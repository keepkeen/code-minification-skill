# Code Minification Skill

> Reduce token consumption 20–50% when feeding source code to AI coding agents.

An [Agent Skill](https://agentskills.io) for [Claude Code](https://docs.anthropic.com/en/docs/claude-code/skills), [Codex](https://developers.openai.com/codex/skills), [opencode](https://opencode.ai), and compatible agents. Strips non-semantic whitespace, indentation, and comments from source files before LLM consumption — preserving executable semantics across 13 languages.

## Quick Start

```bash
# Minify a file
python3 minify_code.py path/to/file.py

# Minify with comments preserved
python3 minify_code.py --keep-comments path/to/file.go

# Pipe from stdin
cat file.ts | python3 minify_code.py --language typescript

# JSON output for programmatic use
python3 minify_code.py --json path/to/file.rs
```

## Features

- **Zero dependencies** — pure Python stdlib, no `pip install` required
- **13 languages** — Python (indentation-aware via `tokenize`), Go (ASI), JS/TS, Rust, Java, C/C++, C#, Swift, Ruby, Shell
- **Idempotent** — `minify(minify(x)) == minify(x)`, safe for tool round-trips
- **Syntax validated** — output is re-parsed to guarantee no syntax errors
- **Comprehension verified** — A/B tested with Claude to confirm no semantic degradation
- **3-phase evaluation** — built-in `evaluate.py` for reduction metrics, syntax validation, and LLM comprehension

## Installation

### As a skill (Claude Code)

```bash
# Clone to your skills directory
git clone https://github.com/keepkeen/code-minification-skill.git ~/.claude/skills/code-minification
```

### As a skill (Codex)

```bash
# Install from GitHub
$skill-installer https://github.com/keepkeen/code-minification-skill
```

### As a standalone tool

```bash
git clone https://github.com/keepkeen/code-minification-skill.git
alias minify='python3 /path/to/code-minification-skill/minify_code.py'
```

## Supported Languages

| Extension | Language | Strategy |
|---|---|---|
| `.py` | Python | `tokenize` module (indentation-aware) |
| `.js`, `.mjs`, `.cjs` | JavaScript | Regex |
| `.ts` | TypeScript | Regex |
| `.jsx`, `.tsx` | React | Regex (preserves JSX) |
| `.go` | Go | Regex + semicolon insertion |
| `.rs` | Rust | Regex |
| `.java` | Java | Regex |
| `.c`, `.h` | C | Regex |
| `.cpp`, `.hpp`, `.cc` | C++ | Regex |
| `.cs` | C# | Regex |
| `.swift` | Swift | Regex |
| `.rb` | Ruby | Regex |
| `.sh`, `.bash` | Shell | Collapse blank lines |

## Evaluation Results

```
Metric                    Result
─────────────────────────────────────
Average token reduction   17–24%
Syntax validation         100% pass
Idempotency               100% pass
LLM comprehension         Equivalent (A/B with Claude Sonnet 4)
```

Run the evaluation suite yourself:

```bash
python3 evaluate.py samples/*.py samples/*.go samples/*.js
```

## How It Works

```
Source file → AST parse → Collect leaf tokens → Language-specific separators → Join → Re-validate → Minified output
```

Python uses stdlib `tokenize` for AST-accurate minification that preserves indentation semantics. All other languages use regex-based comment/whitespace stripping with language-specific rules (e.g., semicolon insertion for Go).

## When to Use

- **Exploring a new codebase** — read many files, build mental models
- **Large files** (100+ lines) — cut token cost by up to 50%
- **Token-budget constrained** — maximize context window usage
- **Cost-sensitive sessions** — fewer tokens = lower API cost

## When NOT to Use

| Scenario | Why |
|---|---|
| Compile error debugging | Error lines mismatch minified line numbers |
| Stack trace analysis | Useless file:line references |
| git diff / code review | Diff output vs minified view misalign |
| Python/YAML/Nim minification | Indentation is syntax — handled by tokenize, but test your code |

See [`SKILL.md`](SKILL.md) for the full risk table and anti-patterns.

## Project Structure

```
code-minification/
├── SKILL.md            # Skill definition (for agent consumption)
├── minify_code.py      # Minifier (pure stdlib, 13 languages)
├── evaluate.py         # 3-phase evaluation pipeline
└── README.md           # This file
```

## License

[MIT](LICENSE.txt)
