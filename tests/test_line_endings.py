"""Every text write the plugin makes into a target repo is LF on every platform (LANES-45).

`Path.write_text()` and `open(..., "w")` translate "\n" to `os.linesep` unless `newline` is
passed. On the Zephyr (Windows) the backfill close rewrote an issue file as CRLF and git warned
on the close commit; the minted stubs and claim markers came out the same way. The guard is
static: this test parses every script and refuses a text write that neither passes `newline=`
nor goes through `lanes_config.write_lf`, because a macOS or Linux run can never observe the
translation it prevents.
"""
import ast
from pathlib import Path

import lanes_config as lc

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
TEXT_MODES = set("wax")


def _text_writes_without_newline(source: str, name: str) -> list[str]:
    """`<file>:<line>` for each `.write_text(...)` or text-mode `open(...)` lacking `newline=`."""
    out = []
    for node in ast.walk(ast.parse(source, filename=name)):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        is_write_text = isinstance(fn, ast.Attribute) and fn.attr == "write_text"
        is_open = (isinstance(fn, ast.Name) and fn.id == "open") or (isinstance(fn, ast.Attribute) and fn.attr == "open")
        if not (is_write_text or is_open):
            continue
        if is_open:
            mode = None
            if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                mode = node.args[1].value
            for kw in node.keywords:
                if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                    mode = kw.value.value
            if not isinstance(mode, str) or "b" in mode or not (set(mode) & TEXT_MODES):
                continue                                     # a read, or bytes: no translation
        if not any(kw.arg == "newline" for kw in node.keywords):
            out.append(f"{name}:{node.lineno}")
    return out


def test_every_text_write_in_scripts_passes_newline_or_uses_write_lf():
    """LANES-45: the INFRA-108 close, the minted stub and the claim markers all wrote CRLF on
    Windows because the call site left `newline` to the platform."""
    bare = []
    for path in sorted(SCRIPTS.glob("*.py")):
        bare += _text_writes_without_newline(path.read_text(encoding="utf-8"), path.name)
    assert bare == [], "route these through lanes_config.write_lf or pass newline=: " + ", ".join(bare)


def test_the_scan_catches_the_shapes_the_scripts_used():
    src = (
        'p.write_text(x, encoding="utf-8")\n'                      # the backfill close, the stub
        'with open(p, "w", encoding="utf-8") as fh:\n    fh.write(x)\n'
        'open(p, mode="a").write(x)\n'
        'p.write_text(x, encoding="utf-8", newline="")\n'          # fine: no translation
        'with open(p, "w", encoding="utf-8", newline="\\n") as fh:\n    pass\n'
        'with open(p, "rb") as fh:\n    pass\n'                    # fine: bytes
        'p.read_text(encoding="utf-8")\n'
    )
    assert _text_writes_without_newline(src, "x.py") == ["x.py:1", "x.py:2", "x.py:4"]


def test_write_lf_writes_lf_bytes_and_never_lets_the_platform_translate(tmp_path, monkeypatch):
    seen = {}
    real_open = open

    def spy(path, *args, **kwargs):
        seen.update(kwargs)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(lc, "open", spy, raising=False)
    target = tmp_path / "issue.md"
    lc.write_lf(target, "---\nid: UI-1\n---\n\n# UI-1 — a thing\n")
    assert seen["newline"] == "\n" and seen["encoding"] == "utf-8"
    raw = target.read_bytes()
    assert b"\r" not in raw and raw.endswith(b"\n") and raw.count(b"\n") == 5


def test_the_writers_that_tripped_on_windows_go_through_write_lf():
    """The three sites named in the incident, by reading the source: the stub, the backfill
    close, the views. A spelling change here is a deliberate one, so the test names them."""
    new = (SCRIPTS / "backlog_new.py").read_text(encoding="utf-8")
    assert "bidx.lc.write_lf(path, content)" in new and "path.write_text(content" not in new
    index = (SCRIPTS / "backlog_index.py").read_text(encoding="utf-8")
    assert "lc.write_lf(path, _rewrite_frontmatter(body, updates))" in index
    assert "lc.write_lf(INDEX, render_index(issues))" in index
    assert "lc.write_lf(HTML_VIEW, render_html(" in index
