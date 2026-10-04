"""`/lanes:init` — scaffold `.claude/lanes/config.toml` and the three extension-point stubs.

Writes nothing that already exists unless `--force` is given, and says which files it
wrote and which it left alone. The config it writes is the solo-mode template with
the installed plugin version pinned in `plugin_version`, so `/lanes:doctor` can detect
drift from day one.

Usage:
    python3 lanes_init.py [--root PATH] [--force] [--projects CORE,INFRA,DOC]
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _console import use_utf8_console  # noqa: E402
import lanes_config as lc              # noqa: E402

_PROJECT_RE = re.compile(r"^[A-Z][A-Z0-9]*$")


def render_config(template: str, version: str, projects: list) -> str:
    quoted = ", ".join(f'"{p}"' for p in projects)
    return template.replace("{{PLUGIN_VERSION}}", version).replace("{{PROJECTS}}", quoted)


def parse_projects(text: str | None) -> list:
    if not text:
        return list(lc.DEFAULTS["backlog"]["projects"])
    projects = [p.strip().upper() for p in text.split(",") if p.strip()]
    bad = [p for p in projects if not _PROJECT_RE.match(p)]
    if bad:
        raise SystemExit(f"--projects: {bad!r} must match [A-Z][A-Z0-9]* (IDs read as PREFIX-N)")
    if not projects:
        raise SystemExit("--projects: no prefixes given")
    return projects


def is_ignored(root: Path, rel: str) -> bool:
    try:
        done = subprocess.run(["git", "check-ignore", "-q", "--", rel], cwd=root,
                              capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return done.returncode == 0


def scaffold(root: Path, force: bool, projects: list, templates: Path | None = None) -> dict:
    """Write the files. Returns {"wrote": [...], "kept": [...], "warnings": [...]}."""
    templates = templates or (lc.plugin_root() / "templates")
    lanes_dir = root / lc.LANES_DIR_REL
    lanes_dir.mkdir(parents=True, exist_ok=True)
    version = lc.installed_version() or "0.0.0"
    out = {"wrote": [], "kept": [], "warnings": []}

    def put(name: str, content: str):
        target = lanes_dir / name
        rel = target.relative_to(root).as_posix()
        if target.exists() and not force:
            out["kept"].append(rel)
            return
        target.write_text(content, encoding="utf-8", newline="\n")
        out["wrote"].append(rel)

    put("config.toml", render_config((templates / "config.toml").read_text(encoding="utf-8"), version, projects))
    for stub in lc.EXTENSION_FILES:
        put(stub, (templates / stub).read_text(encoding="utf-8"))

    if is_ignored(root, lc.CONFIG_REL):
        out["warnings"].append(
            f"{lc.CONFIG_REL} is gitignored in this repo. The config must be TRACKED: every operator "
            f"and machine reads the same file from git. If the rule is `.claude/`, change it to `.claude/*` "
            f"and add `!.claude/settings.json` and `!.claude/lanes/` -- git cannot re-include a file whose "
            f"parent directory is excluded."
        )
    loaded = lc.load(root=root)
    for p in loaded.errors:
        out["warnings"].append(f"the written config fails validation: {p.message}")
    return out


def main(argv=None) -> int:
    use_utf8_console()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", help="repository to initialize (default: the one containing the cwd)")
    ap.add_argument("--force", action="store_true", help="overwrite files that already exist")
    ap.add_argument("--projects", help="comma-separated issue ID prefixes, e.g. CORE,INFRA,DOC")
    args = ap.parse_args(argv)

    root = lc.repo_root(cwd=args.root) if args.root else lc.repo_root()
    if root is None:
        print("lanes init: not inside a git repository (the config is tracked, so it needs one)", file=sys.stderr)
        return 1
    projects = parse_projects(args.projects)
    result = scaffold(root, args.force, projects)

    for rel in result["wrote"]:
        print(f"wrote  {rel}")
    for rel in result["kept"]:
        print(f"kept   {rel}  (exists; --force overwrites)")
    for w in result["warnings"]:
        print(f"WARN   {w}")
    cfg = lc.resolve(lc.load(root=root).raw)
    print()
    print(f"mode: {lc.describe_mode(cfg)}")
    print(f"projects: {', '.join(cfg['projects'])}   main branch: {cfg['main_branch']}   tests: {cfg['test_command']}")
    print()
    print("next: review .claude/lanes/config.toml (main_branch, tests.command, main_direct_paths),")
    print("      fill [[operators]] only if more than one person or machine works this repo,")
    print("      commit the .claude/lanes/ directory, then run /lanes:doctor.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
