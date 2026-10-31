"""Every skill's and command's frontmatter parses under a STRICT YAML reader (LANES-74).

Claude Code reads a `SKILL.md` or `commands/*.md` frontmatter as YAML. Its lenient releases
accepted `description: The startup sequence: pulls ...`; the strict ones reject it (`: ` inside
an unquoted plain scalar is a mapping indicator) and, in the validator's own words, load the
skill "with empty metadata (all frontmatter fields silently dropped)". A skill with no
description does not trigger, so on a strict release the protocol's startup and shutdown
sequences would stop answering "GA" and "wrap up" with no error anywhere. The lanes `ci` ran
the strict validator and was red for ten releases while the local, lenient one passed.

The suite is stdlib + pytest, so the check is a small strict reader for the flat mappings a
frontmatter is: one `key: value` per line, a value either double-quoted (YAML escapes, no bare
`"` inside), single-quoted (`''` is the one escape), a balanced flow collection, or a plain
scalar that carries no `: ` or ` #`, does not start with an indicator, and does not end with
`:`. Anything else is a parse error here, as it is in the strict validator.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FRONTMATTER_FILES = sorted(ROOT.glob("skills/*/SKILL.md")) + sorted(ROOT.glob("commands/*.md"))

_KEY_RE = re.compile(r"^([A-Za-z_][\w.-]*):(?:[ \t]+(.*))?$")
# Characters YAML forbids at the start of a plain scalar (block context), plus the
# backtick and `@`, which it reserves.
_PLAIN_FORBIDDEN_FIRST = set('-?:,[]{}#&*!|>\'"%@`')


class FrontmatterError(ValueError):
    pass


_ESCAPES = {'"': '"', "\\": "\\", "n": "\n", "t": "\t", "/": "/", " ": " "}


def _double_quoted(value, where):
    out, i, n = [], 1, len(value)
    while i < n:
        c = value[i]
        if c == "\\":
            if i + 1 >= n or value[i + 1] not in _ESCAPES:
                raise FrontmatterError(f"{where}: unknown escape {value[i:i + 2]!r} in a double-quoted value")
            out.append(_ESCAPES[value[i + 1]])
            i += 2
            continue
        if c == '"':
            if value[i + 1:].strip():
                raise FrontmatterError(f"{where}: text after the closing quote: {value[i + 1:]!r}")
            return "".join(out)
        out.append(c)
        i += 1
    raise FrontmatterError(f"{where}: double-quoted value never closes")


def _single_quoted(value, where):
    i, n = 1, len(value)
    while i < n:
        if value[i] == "'":
            if i + 1 < n and value[i + 1] == "'":
                i += 2
                continue
            if value[i + 1:].strip():
                raise FrontmatterError(f"{where}: text after the closing quote: {value[i + 1:]!r}")
            return value[1:i].replace("''", "'")
        i += 1
    raise FrontmatterError(f"{where}: single-quoted value never closes")


def _flow(value, where):
    pairs = {"[": "]", "{": "}"}
    stack, quote = [], None
    for c in value:
        if quote:
            if c == quote:
                quote = None
            continue
        if c in "\"'":
            quote = c
        elif c in pairs:
            stack.append(pairs[c])
        elif c in pairs.values():
            if not stack or stack.pop() != c:
                raise FrontmatterError(f"{where}: unbalanced flow collection")
    if stack or quote:
        raise FrontmatterError(f"{where}: unbalanced flow collection")
    return value


def _plain(value, where):
    if value[0] in _PLAIN_FORBIDDEN_FIRST:
        raise FrontmatterError(f"{where}: a plain scalar cannot start with {value[0]!r}")
    if ": " in value or value.endswith(":"):
        raise FrontmatterError(f"{where}: ': ' inside an unquoted value is a mapping indicator — quote the value")
    if " #" in value:
        raise FrontmatterError(f"{where}: ' #' inside an unquoted value starts a comment — quote the value")
    return value


def parse_frontmatter(text, where="frontmatter"):
    """Return the flat mapping between the `---` fences, or raise FrontmatterError."""
    if not text.startswith("---\n"):
        raise FrontmatterError(f"{where}: no opening fence")
    try:
        block = text.split("---\n", 2)[1]
    except IndexError:
        raise FrontmatterError(f"{where}: no closing fence") from None
    out = {}
    for n, line in enumerate(block.splitlines(), 2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0] in " \t":
            raise FrontmatterError(f"{where}:{n}: indented line — block scalars and nested maps are not flat frontmatter")
        m = _KEY_RE.match(line)
        if not m:
            raise FrontmatterError(f"{where}:{n}: not a `key: value` line: {line!r}")
        key, value = m.group(1), (m.group(2) or "").rstrip()
        if key in out:
            raise FrontmatterError(f"{where}:{n}: duplicate key {key!r}")
        if not value:
            out[key] = ""
        elif value[0] == '"':
            out[key] = _double_quoted(value, f"{where}:{n}")
        elif value[0] == "'":
            out[key] = _single_quoted(value, f"{where}:{n}")
        elif value[0] in "[{":
            out[key] = _flow(value, f"{where}:{n}")
        else:
            out[key] = _plain(value, f"{where}:{n}")
    return out


# --- the reader itself rejects what the strict validator rejected ---------------------------

def test_the_reader_rejects_a_mapping_indicator_inside_a_plain_scalar():
    """The exact shape CI flagged for ten releases: an unquoted description with a `: ` in it."""
    bad = "---\nname: x\ndescription: Use at the start. The startup sequence: pulls the main branch.\n---\n"
    with pytest.raises(FrontmatterError, match="mapping indicator"):
        parse_frontmatter(bad)


@pytest.mark.parametrize("value", [
    '"unterminated',
    '"a bare " quote inside"',
    "'unterminated",
    "- looks like a list item",
    "ends with a colon:",
    "a trailing # comment",
    "[unbalanced",
])
def test_the_reader_rejects_other_strict_failures(value):
    with pytest.raises(FrontmatterError):
        parse_frontmatter(f"---\nk: {value}\n---\n")


@pytest.mark.parametrize("value, expected", [
    ('"Quoted: with \\"escapes\\" and a colon: inside"', 'Quoted: with "escapes" and a colon: inside'),
    ("'Single: with ''one'' escape'", "Single: with 'one' escape"),
    ("plain text with no indicators, a URL http://x/y and 2–3 dashes", "plain text with no indicators, a URL http://x/y and 2–3 dashes"),
    ("[a, b]", "[a, b]"),
])
def test_the_reader_accepts_the_quoted_and_plain_shapes_the_files_use(value, expected):
    assert parse_frontmatter(f"---\nk: {value}\n---\n")["k"] == expected


# --- every component file --------------------------------------------------------------------

@pytest.mark.parametrize("path", FRONTMATTER_FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_frontmatter_parses_strictly(path):
    fm = parse_frontmatter(path.read_text(encoding="utf-8"), str(path.relative_to(ROOT)))
    assert fm.get("description", "").strip(), f"{path.relative_to(ROOT)}: no description — nothing would trigger it"
    if path.name == "SKILL.md":
        assert fm.get("name") == path.parent.name, "a skill's `name` is its directory"


def test_the_component_set_is_not_empty():
    names = {p.parent.name if p.name == "SKILL.md" else p.stem for p in FRONTMATTER_FILES}
    assert {"session-startup", "worktree-increment", "session-closeout"} <= names
    assert len(FRONTMATTER_FILES) >= 8
