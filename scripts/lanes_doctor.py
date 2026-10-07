"""`/lanes:doctor` — is the lanes setup in this repo healthy?

One line per check: `OK` / `WARN` / `FAIL` / `SKIP`, a label, a detail written to be
read aloud. Exit 1 on any FAIL, or on any WARN with `--strict`.

Checks, in order:
  position   where the session is (toplevel, branch, main clone or worktree) — informational
  config     `.claude/lanes/config.toml` present, parses, validates; mode summary
  tracked    the config is committed (a config only one machine can see protects nobody)
  version    installed plugin version vs the `plugin_version` the repo expects
  stubs      the three extension-point files exist
  backlog    the backlog directory exists; `--check` runs when the tracker ships with the plugin
  views      the generated INDEX.md / index.html are gitignored (a tracked copy conflicts at every rebase)
  claims     every `in-progress` issue classified: live / setting up / reserved / STALE CANDIDATE
  settings   the tracked `.claude/settings.json` is unmodified against HEAD (`marketplace remove` empties it)
  settings lanes  it declares lanes' marketplace and enables lanes — in HEAD and in the working tree
  marketplace     this machine's registered marketplace source (repo, ref) matches the declared one,
                  and the installed commit is the marketplace clone's tip (no fetch)

The claims check is the one with teeth, and it only ever REPORTS. A claim younger than
the 15-minute floor is never a candidate, whatever else the evidence says: a lane that is
still setting up has no worktree and no branch yet, which is exactly the evidence
signature of an abandoned one, and only age separates them. A candidate is a question
for the owning session or the operator — the doctor never edits an issue file.

Usage:
    python3 lanes_doctor.py [--root PATH] [--strict] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _console import use_utf8_console  # noqa: E402
import lanes_config as lc              # noqa: E402

OK, WARN, FAIL, SKIP = "OK", "WARN", "FAIL", "SKIP"

MARKER_RE = re.compile(r"IN-PROGRESS \((\d{4}-\d{2}-\d{2})(?: (\d{2}:\d{2}))?")
KIND_RE = re.compile(r"\*\*(WORKTREE PENDING|RESERVED, NOT STARTED|ACTIVE LANE)\.?\*\*")
WORKTREE_RE = re.compile(r"worktree ([A-Za-z0-9._-]+)")
BRANCH_RE = re.compile(r"branch ([A-Za-z0-9._/-]+)")


@dataclass
class Check:
    status: str
    label: str
    detail: str


# ------------------------------------------------------------------ helpers
def _git(args, cwd) -> Optional[str]:
    try:
        done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def parse_frontmatter(text: str) -> dict:
    """Flat `key: value` frontmatter between the leading `---` fences. Values unquoted."""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    out = {}
    for line in text[3:end].splitlines():
        if ":" not in line or line.startswith((" ", "\t")):
            continue
        key, _, value = line.partition(":")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key.strip()] = value
    return out


def body_after_frontmatter(text: str) -> str:
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    return text[end + 4:] if end >= 0 else text


def worktree_names(root: Path) -> set:
    out = _git(["worktree", "list", "--porcelain"], root) or ""
    return {Path(line[len("worktree "):]).name for line in out.splitlines() if line.startswith("worktree ")}


def branch_exists(root: Path, branch: str) -> bool:
    local = _git(["branch", "--list", branch], root)
    remote = _git(["branch", "-r", "--list", f"*/{branch}"], root)
    return bool(local) or bool(remote)


# ------------------------------------------------------------------- checks
def check_position(root: Path) -> Check:
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], root) or "?"
    common = _git(["rev-parse", "--git-common-dir"], root) or ".git"
    main_clone = Path(os.path.realpath(root / common)).parent
    kind = "main clone" if os.path.realpath(root) == os.path.realpath(main_clone) else f"worktree of {main_clone}"
    return Check(OK, "position", f"{root} on `{branch}` ({kind})")


def check_config(loaded: lc.Loaded) -> tuple[Check, dict]:
    cfg = lc.resolve(loaded.raw)
    if not loaded.found:
        return Check(FAIL, "config", f"{lc.CONFIG_REL} not found — run /lanes:init (defaults would be solo mode)"), cfg
    if loaded.parse_error:
        return Check(FAIL, "config", f"does not parse: {loaded.parse_error}"), cfg
    if loaded.errors:
        return Check(FAIL, "config", "; ".join(p.message for p in loaded.errors)), cfg
    detail = lc.describe_mode(cfg)
    if loaded.warnings:
        return Check(WARN, "config", detail + " — " + "; ".join(p.message for p in loaded.warnings)), cfg
    return Check(OK, "config", detail), cfg


def check_tracked(root: Path, loaded: lc.Loaded) -> Check:
    if not loaded.found:
        return Check(SKIP, "tracked", "no config to track yet")
    if _git(["ls-files", "--error-unmatch", lc.CONFIG_REL], root) is not None:
        return Check(OK, "tracked", f"{lc.CONFIG_REL} is committed")
    ignored = subprocess.run(["git", "check-ignore", "-q", "--", lc.CONFIG_REL], cwd=root,
                             capture_output=True).returncode == 0
    why = "gitignored" if ignored else "untracked"
    hint = (" (if the rule is `.claude/`, make it `.claude/*` with `!.claude/settings.json` and `!.claude/lanes/`)"
            if ignored else "")
    return Check(WARN, "tracked", f"{lc.CONFIG_REL} is {why} — the config only protects machines that can see it; commit it{hint}")


def check_version(cfg: dict) -> Check:
    installed = lc.installed_version()
    expected = cfg.get("plugin_version")
    if installed is None:
        return Check(WARN, "version", "cannot read the installed plugin's manifest")
    if not expected:
        return Check(WARN, "version", f"installed {installed}; the repo pins none — set `plugin_version` so drift is visible")
    if installed == expected:
        return Check(OK, "version", f"installed {installed} == expected {expected}")
    return Check(WARN, "version", f"installed {installed} but this repo expects {expected} — update the plugin or the pin, "
                                  f"so two machines do not run two protocols")


def check_stubs(root: Path) -> Check:
    lanes_dir = root / lc.LANES_DIR_REL
    missing = [f for f in lc.EXTENSION_FILES if not (lanes_dir / f).is_file()]
    if not missing:
        return Check(OK, "stubs", "preflight.md, lane-setup.md, pre-land.md present")
    return Check(WARN, "stubs", f"missing {', '.join(missing)} — /lanes:init writes them")


def check_backlog(root: Path, cfg: dict) -> list:
    backlog = root / cfg["backlog_dir"]
    if not backlog.is_dir():
        return [Check(WARN, "backlog", f"{cfg['backlog_dir']} does not exist yet")]
    issues = [p for p in backlog.rglob("*.md") if p.name not in ("INDEX.md", "README.md")]
    out = [Check(OK, "backlog", f"{cfg['backlog_dir']}: {len(issues)} issue files")]
    views = [f"{cfg['backlog_dir']}/INDEX.md", f"{cfg['backlog_dir']}/index.html"]
    unignored = [v for v in views if subprocess.run(["git", "check-ignore", "-q", "--", v], cwd=root,
                                                    capture_output=True).returncode != 0]
    if unignored:
        out.append(Check(WARN, "views", f"not gitignored: {', '.join(unignored)} — every worktree rewrites the "
                                        f"generated views, so a tracked copy conflicts at every rebase; add them to .gitignore"))
    else:
        out.append(Check(OK, "views", "the generated views are gitignored"))
    checker = lc.plugin_root() / "scripts" / "backlog_index.py"
    if not checker.is_file():
        out.append(Check(SKIP, "backlog --check", "the tracker scripts are not in this plugin version yet"))
        return out
    try:
        done = subprocess.run([sys.executable, str(checker), "--check"], cwd=root, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        out.append(Check(FAIL, "backlog --check", f"could not run: {exc}"))
        return out
    last = (done.stdout.strip().splitlines() or done.stderr.strip().splitlines() or ["(no output)"])[-1]
    out.append(Check(OK if done.returncode == 0 else FAIL, "backlog --check", last))
    return out


def classify_claim(issue_id: str, text: str, now: datetime, root: Path, worktrees: set) -> Check:
    body = body_after_frontmatter(text)
    m = MARKER_RE.search(body)
    if not m:
        return Check(WARN, f"claim {issue_id}", "status in-progress but no ⏳ IN-PROGRESS marker in the body — "
                                                "the frontmatter and the marker are written together; ask the owner")
    date, hhmm = m.group(1), m.group(2)
    kind_m = KIND_RE.search(body[m.start():m.start() + 400])
    kind = kind_m.group(1) if kind_m else None
    try:
        stamp = datetime.strptime(f"{date} {hhmm}" if hhmm else date, "%Y-%m-%d %H:%M" if hhmm else "%Y-%m-%d")
    except ValueError:
        return Check(WARN, f"claim {issue_id}", f"marker timestamp {date} {hhmm or ''} does not parse; treated as live")
    age = now - stamp
    age_txt = f"{int(age.total_seconds() // 60)} min" if hhmm else f"dated {date} (no time; age unknown)"
    floor = timedelta(minutes=lc.CLAIM_AGE_FLOOR_MINUTES)
    if hhmm and age < floor:
        return Check(OK, f"claim {issue_id}", f"{kind or 'claimed'} {age_txt} ago — younger than the "
                                              f"{lc.CLAIM_AGE_FLOOR_MINUTES}-minute floor, live by rule")
    if kind == "WORKTREE PENDING":
        return Check(OK, f"claim {issue_id}", f"WORKTREE PENDING, {age_txt} — claimed, setting up; route around it")
    if kind == "RESERVED, NOT STARTED":
        return Check(OK, f"claim {issue_id}", f"RESERVED, {age_txt} — queued behind another lane")
    if kind == "ACTIVE LANE":
        wt = WORKTREE_RE.search(body[m.start():m.start() + 400])
        br = BRANCH_RE.search(body[m.start():m.start() + 400])
        wt_name, br_name = (wt.group(1) if wt else None), (br.group(1) if br else None)
        evidence = []
        if wt_name and wt_name in worktrees:
            evidence.append(f"worktree {wt_name} present")
        if br_name and branch_exists(root, br_name):
            evidence.append(f"branch {br_name} exists")
        if evidence:
            return Check(OK, f"claim {issue_id}", f"ACTIVE LANE, {age_txt} — {'; '.join(evidence)}")
        return Check(WARN, f"claim {issue_id}",
                     f"STALE-CLAIM CANDIDATE: ACTIVE LANE {age_txt} ago, no worktree"
                     f"{' ' + wt_name if wt_name else ''} here and no branch{' ' + br_name if br_name else ''} "
                     f"anywhere — a QUESTION for the owner or the operator, never a takeover")
    return Check(WARN, f"claim {issue_id}", f"marker {age_txt} has no PENDING / RESERVED / ACTIVE kind; ask the owner")


def check_claims(root: Path, cfg: dict, now: Optional[datetime] = None) -> list:
    backlog = root / cfg["backlog_dir"]
    if not backlog.is_dir():
        return [Check(SKIP, "claims", "no backlog directory")]
    now = now or datetime.now()
    worktrees = worktree_names(root)
    exempt = set(cfg["claim_marker_exempt"])
    out = []
    for path in sorted(backlog.rglob("*.md")):
        if path.name in ("INDEX.md", "README.md"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        fm = parse_frontmatter(text)
        if fm.get("status") != "in-progress":
            continue
        issue_id = fm.get("id") or path.stem.split("-")[0]
        if issue_id in exempt:
            continue
        out.append(classify_claim(issue_id, text, now, root, worktrees))
    if not out:
        return [Check(OK, "claims", "no in-progress issues")]
    return out


SETTINGS_REL = ".claude/settings.json"


def plugins_dir() -> Path:
    """Where Claude Code keeps plugin state on this machine. `LANES_PLUGINS_DIR` is the
    test seam; else derived from this plugin's own cache path
    (`<plugins>/cache/<marketplace>/<name>/<version>`); else `$CLAUDE_CONFIG_DIR/plugins`;
    else `~/.claude/plugins`."""
    env = os.environ.get("LANES_PLUGINS_DIR")
    if env:
        return Path(env)
    root = lc.plugin_root()
    if len(root.parents) > 3 and root.parents[2].name == "cache":
        return root.parents[3]
    base = os.environ.get("CLAUDE_CONFIG_DIR")
    return (Path(base) if base else Path.home() / ".claude") / "plugins"


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _lanes_marketplace(data) -> Optional[str]:
    """The marketplace lanes is enabled from (`lanes@<mkt>`), '' for a bare `lanes`, or
    None when lanes is not enabled."""
    enabled = (data or {}).get("enabledPlugins") or {}
    keys = list(enabled) if isinstance(enabled, (dict, list)) else []
    for k in keys:
        name, _, mkt = str(k).partition("@")
        if name == "lanes" and (not isinstance(enabled, dict) or enabled[k] is not False):
            return mkt
    return None


def _declared_source(data, mkt: str) -> Optional[dict]:
    src = (((data or {}).get("extraKnownMarketplaces") or {}).get(mkt) or {}).get("source")
    return src if isinstance(src, dict) else None


def _lanes_problem(data) -> Optional[str]:
    """Why this settings document would not get lanes installed for the next person."""
    mkt = _lanes_marketplace(data)
    if mkt is None:
        return "enabledPlugins does not list lanes"
    if mkt and _declared_source(data, mkt) is None:
        return f"enabledPlugins names `lanes@{mkt}` but extraKnownMarketplaces does not declare `{mkt}`"
    return None


def check_settings(root: Path) -> list:
    """Three checks on the tracked `.claude/settings.json` (LANES-16). `claude plugin
    marketplace remove` silently empties it (LANES-15), so the file is checked against
    HEAD, and this machine's registered source is checked against what it declares."""
    settings = root / SETTINGS_REL
    tracked = _git(["ls-files", "--error-unmatch", SETTINGS_REL], root) is not None
    head_text = _git(["show", f"HEAD:{SETTINGS_REL}"], root) if tracked else None
    if not settings.is_file() and head_text is None:
        return [Check(WARN, "settings", f"{SETTINGS_REL} absent — nothing prompts the next person to install lanes")]
    checks = []

    # 1. the tracked file, modified in the working tree
    if not tracked:
        checks.append(Check(WARN, "settings", f"{SETTINGS_REL} is not committed — only this clone is prompted to install lanes"))
    else:
        try:
            dirty = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", SETTINGS_REL], cwd=root,
                                   capture_output=True, timeout=15).returncode == 1
        except (OSError, subprocess.TimeoutExpired):
            dirty = False
        checks.append(Check(WARN, "settings",
                            f"{SETTINGS_REL} is modified in the working tree — `claude plugin marketplace remove` "
                            f"empties it; `git checkout -- {SETTINGS_REL}` unless the change is intended")
                      if dirty else Check(OK, "settings", f"{SETTINGS_REL} matches HEAD"))

    # 2. lanes declared and enabled — committed AND working tree
    wt = _load_json(settings) if settings.is_file() else None
    head = None
    if head_text is not None:
        try:
            head = json.loads(head_text)
        except ValueError:
            head = None
    problems = []
    if head_text is not None:
        why = "unparseable" if head is None else _lanes_problem(head)
        if why:
            problems.append(f"committed (HEAD): {why} — a fresh clone gets no lanes and no position guard")
    if settings.is_file():
        why = "unreadable or not JSON" if wt is None else _lanes_problem(wt)
        if why:
            problems.append(f"working tree: {why}")
    checks.append(Check(WARN, "settings lanes", "; ".join(problems)) if problems
                  else Check(OK, "settings lanes", "enabledPlugins pins lanes for the next person"))

    # 3. this machine's registered source vs the declared one
    declared_doc = head if head is not None else wt
    mkt = _lanes_marketplace(declared_doc)
    declared = _declared_source(declared_doc, mkt) if mkt else None
    if declared is None:
        checks.append(Check(SKIP, "marketplace", "no lanes marketplace declared — nothing to compare"))
        return checks
    pdir = plugins_dir()
    known = _load_json(pdir / "known_marketplaces.json")
    entry = (known or {}).get(mkt) if isinstance(known, dict) else None
    if not entry:
        checks.append(Check(WARN, "marketplace",
                            f"`{mkt}` is declared but not registered on this machine ({pdir}) — "
                            f"`claude plugin marketplace add {declared.get('repo', '?')}"
                            + (f"@{declared['ref']}" if declared.get("ref") else "") + "`"))
        return checks
    have = entry.get("source") or {}
    mismatch = [f"{k} `{declared.get(k) or '(default branch)'}` but this machine has `{have.get(k) or '(default branch)'}`"
                for k in ("repo", "ref") if (declared.get(k) or None) != (have.get(k) or None)]
    if mismatch:
        checks.append(Check(WARN, "marketplace",
                            f"`{mkt}`: the repo declares " + "; ".join(mismatch)
                            + " — remove and re-add the marketplace, then `git checkout -- "
                            + SETTINGS_REL + "` (remove empties it)"))
        return checks
    where = f"`{mkt}` source matches ({have.get('repo')}" + (f"@{have['ref']}" if have.get("ref") else "") + ")"
    clone_tip = _git(["rev-parse", "HEAD"], Path(entry["installLocation"])) if entry.get("installLocation") else None
    installed = _load_json(pdir / "installed_plugins.json")
    rows = ((installed or {}).get("plugins", installed) or {}).get(f"lanes@{mkt}") if isinstance(installed, dict) else None
    row = None
    for r in rows or []:
        if r.get("scope") == "project" and Path(r.get("projectPath", "")).resolve() == root.resolve():
            row = r
    for r in rows or []:
        row = row or (r if r.get("scope") == "user" else None)
    sha = (row or {}).get("gitCommitSha")
    if sha and clone_tip and sha != clone_tip:
        checks.append(Check(WARN, "marketplace",
                            f"{where}, but lanes is installed at {sha[:7]} and the marketplace clone is at "
                            f"{clone_tip[:7]} — `claude plugin update lanes@{mkt}` (both scopes)"))
    else:
        checks.append(Check(OK, "marketplace", where + (f", installed at its tip {sha[:7]}" if sha and clone_tip else "")))
    return checks


# --------------------------------------------------------------------- main
def run(root: Path, now: Optional[datetime] = None) -> list:
    loaded = lc.load(root=root)
    checks = [check_position(root)]
    cfg_check, cfg = check_config(loaded)
    checks.append(cfg_check)
    checks.append(check_tracked(root, loaded))
    checks.append(check_version(cfg))
    checks.append(check_stubs(root))
    checks.extend(check_backlog(root, cfg))
    checks.extend(check_claims(root, cfg, now))
    checks.extend(check_settings(root))
    return checks


def exit_code(checks: list, strict: bool) -> int:
    if any(c.status == FAIL for c in checks):
        return 1
    if strict and any(c.status == WARN for c in checks):
        return 1
    return 0


def main(argv=None) -> int:
    use_utf8_console()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", help="repository to check (default: the one containing the cwd)")
    ap.add_argument("--strict", action="store_true", help="warnings also fail (exit 1)")
    ap.add_argument("--json", action="store_true", help="emit the checks as JSON")
    args = ap.parse_args(argv)

    root = lc.repo_root(cwd=args.root) if args.root else lc.repo_root()
    if root is None:
        print("lanes doctor: not inside a git repository", file=sys.stderr)
        return 1
    checks = run(root)
    if args.json:
        print(json.dumps([asdict(c) for c in checks], indent=2, ensure_ascii=False))
    else:
        width = max(len(c.label) for c in checks)
        for c in checks:
            print(f"{c.status:<5} {c.label:<{width}}  {c.detail}")
        n_ok = sum(c.status == OK for c in checks)
        n_warn = sum(c.status == WARN for c in checks)
        n_fail = sum(c.status == FAIL for c in checks)
        print(f"\n{n_ok} ok, {n_warn} warn, {n_fail} fail")
    return exit_code(checks, args.strict)


if __name__ == "__main__":
    sys.exit(main())
