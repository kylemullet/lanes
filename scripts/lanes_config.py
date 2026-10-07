"""Config loader for the `lanes` plugin: `.claude/lanes/config.toml`.

Every key is optional. The defaults mean SOLO MODE: an empty `operators` list says
"whoever is here certifies and edits everything", and every two-operator rule in the
protocol degrades to a no-op, never an error. A config exercise per repo is the
adoption cost that would stop this being used, so a fresh project runs on defaults.

Three things are deliberately NOT configurable, because the integrity gate reads them
by name and a rename would break it silently: the status vocabulary, the resolution
vocabulary, and the 15-minute claim-age floor. They are module constants here.

Design constraint carried from the inventory that preceded this file: the backlog
scripts' unit tests `monkeypatch.setattr` module-level globals (ROOT, BACKLOG, ...),
so a loader must resolve config ONCE into plain values that a caller can assign to
module globals, never inside each function. `resolve()` returns exactly that: a flat
dict of final values.

Stdlib only (`tomllib`, Python 3.11+). Format: TOML — the stdlib has no YAML parser,
JSON has no comments, and the template is half comments.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

LANES_DIR_REL = ".claude/lanes"
CONFIG_REL = f"{LANES_DIR_REL}/config.toml"
EXTENSION_FILES = ("preflight.md", "lane-setup.md", "pre-land.md")

# ---- protocol constants: read by name in the gate and the skills; never config ----
STATUSES = ("in-progress", "open", "blocked", "paused", "verified", "closed")
LIVE_STATUSES = ("in-progress", "open", "blocked", "paused")   # verified is landed, not live
RESOLUTIONS = ("done", "duplicate", "superseded", "wont-do")
CLAIM_AGE_FLOOR_MINUTES = 15
SHARED_ASSIGNEE = "shared"
CLAUDE_REPORTER = "claude"

DEFAULTS: dict[str, Any] = {
    "plugin_version": None,
    "backlog": {
        "dir": "docs/backlog",
        "projects": ["CORE", "INFRA", "DOC"],
        "types": ["story", "bug", "spike", "qa", "decision", "chore", "epic"],
        "priorities": ["critical", "high", "normal", "low"],
        "docs_lane_prefixes": None,          # None -> git.main_direct_paths
        "claim_marker_exempt": [],
        "resolution_required_from": None,    # None -> always required
        "view_port": 8099,
    },
    "git": {
        "main_branch": "main",
        "land_requires_ok": True,
        "main_direct_paths": ["docs/", ".claude/lanes/", "*.md"],
    },
    "tests": {
        "command": "pytest -q",
        "required_before_land": True,
        "rebase_rerun_command": None,
    },
    "worktrees": {
        "port_command": None,
    },
    "operators": [],
    "lanes": {
        "code": [],
        "code_owner": None,
    },
}

# (type, required) per key; a table's unknown keys are warnings, never errors.
_SCHEMA: dict[str, dict[str, tuple]] = {
    "backlog": {
        "dir": (str, False), "projects": (list, False), "types": (list, False),
        "priorities": (list, False), "docs_lane_prefixes": (list, False),
        "claim_marker_exempt": (list, False), "resolution_required_from": (str, False),
        "view_port": (int, False),
    },
    "git": {"main_branch": (str, False), "land_requires_ok": (bool, False), "main_direct_paths": (list, False)},
    "tests": {"command": (str, False), "required_before_land": (bool, False), "rebase_rerun_command": (str, False)},
    "worktrees": {"port_command": (str, False)},
    "lanes": {"code": (list, False), "code_owner": (str, False)},
}
_OPERATOR_FIELDS = {
    "name": (str, True), "platform": (str, True), "id": (str, True), "short": (str, True),
    "certifies": (bool, False), "may_edit_code": (bool, False),
}
_TOP_LEVEL_SCALARS = {"plugin_version": (str, False)}
_PROJECT_RE = re.compile(r"^[A-Z][A-Z0-9]*$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+([-+][0-9A-Za-z.-]+)?$")


@dataclass(frozen=True)
class Problem:
    level: str      # "error" | "warning"
    message: str

    def __str__(self) -> str:
        return f"{self.level}: {self.message}"


@dataclass
class Loaded:
    root: Optional[Path]            # repo toplevel, or None outside a repo
    path: Optional[Path]            # the config file's path, found or not
    found: bool
    raw: dict                       # parsed TOML (empty when not found)
    problems: list = field(default_factory=list)
    parse_error: Optional[str] = None

    @property
    def errors(self) -> list:
        return [p for p in self.problems if p.level == "error"]

    @property
    def warnings(self) -> list:
        return [p for p in self.problems if p.level == "warning"]


# ---------------------------------------------------------------- git helpers
def _git(args, cwd=None) -> Optional[str]:
    try:
        done = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode != 0:
        return None
    return done.stdout.strip()


def repo_root(cwd=None) -> Optional[Path]:
    """`git rev-parse --show-toplevel` of `cwd` — a worktree answers with ITSELF."""
    out = _git(["rev-parse", "--show-toplevel"], cwd=cwd)
    return Path(out) if out else None


def git_user_name(cwd=None) -> str:
    return _git(["config", "user.name"], cwd=cwd) or ""


def slug(text: str) -> str:
    """`Kyle Mullet` -> `kyle-mullet`; the solo operator's derived `short`."""
    s = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-")
    return s or "operator"


# ------------------------------------------------------------------ loading
def read_toml(path: Path) -> tuple[dict, Optional[str]]:
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh), None
    except tomllib.TOMLDecodeError as exc:
        return {}, f"{path}: {exc}"
    except OSError as exc:
        return {}, f"{path}: {exc}"


def load(root: Optional[Path] = None, cwd=None) -> Loaded:
    """Find and parse the repo's config. Missing is NOT an error: it means defaults."""
    root = root if root is not None else repo_root(cwd)
    path = (root / CONFIG_REL) if root else None
    if path is None or not path.is_file():
        return Loaded(root=root, path=path, found=False, raw={})
    raw, err = read_toml(path)
    if err:
        return Loaded(root=root, path=path, found=True, raw={}, parse_error=err,
                      problems=[Problem("error", err)])
    return Loaded(root=root, path=path, found=True, raw=raw, problems=validate(raw))


# --------------------------------------------------------------- validation
def validate(raw: dict) -> list:
    """Shape and cross-key rules over the parsed TOML. Returns Problems, worst first."""
    problems: list[Problem] = []
    err = lambda m: problems.append(Problem("error", m))      # noqa: E731
    warn = lambda m: problems.append(Problem("warning", m))   # noqa: E731

    if not isinstance(raw, dict):
        return [Problem("error", "config is not a table")]

    known_top = set(_SCHEMA) | set(_TOP_LEVEL_SCALARS) | {"operators"}
    for key in raw:
        if key not in known_top:
            warn(f"unknown top-level key `{key}` (ignored)")

    for key, (typ, _req) in _TOP_LEVEL_SCALARS.items():
        if key in raw and not isinstance(raw[key], typ):
            err(f"`{key}` must be a {typ.__name__}")
    pv = raw.get("plugin_version")
    if isinstance(pv, str) and not _SEMVER_RE.match(pv):
        warn(f"`plugin_version` {pv!r} is not MAJOR.MINOR.PATCH; doctor compares it literally")

    for section, keys in _SCHEMA.items():
        table = raw.get(section)
        if table is None:
            continue
        if not isinstance(table, dict):
            err(f"`[{section}]` must be a table")
            continue
        for key in table:
            if key not in keys:
                warn(f"unknown key `{section}.{key}` (ignored)")
        for key, (typ, _req) in keys.items():
            if key in table and not isinstance(table[key], typ):
                err(f"`{section}.{key}` must be a {typ.__name__}")
            if key in table and typ is list and isinstance(table[key], list):
                if not all(isinstance(x, str) for x in table[key]):
                    err(f"`{section}.{key}` must be a list of strings")

    backlog = raw.get("backlog") if isinstance(raw.get("backlog"), dict) else {}
    projects = backlog.get("projects")
    if isinstance(projects, list):
        if not projects:
            err("`backlog.projects` is empty: no issue ID prefix can be minted")
        for p in projects:
            if isinstance(p, str) and not _PROJECT_RE.match(p):
                err(f"`backlog.projects` entry {p!r} must match [A-Z][A-Z0-9]* (IDs read as PREFIX-N)")
        if len(set(projects)) != len(projects):
            err("`backlog.projects` has duplicates")
    types = backlog.get("types")
    if isinstance(types, list):
        if "epic" not in types:
            err("`backlog.types` must include \"epic\": the epic roll-up and the dangling-epic check read it by name")
        if not types:
            err("`backlog.types` is empty")
    priorities = backlog.get("priorities")
    if isinstance(priorities, list) and not priorities:
        err("`backlog.priorities` is empty")
    rrf = backlog.get("resolution_required_from")
    if isinstance(rrf, str) and not _DATE_RE.match(rrf):
        err(f"`backlog.resolution_required_from` must be YYYY-MM-DD, got {rrf!r}")
    port = backlog.get("view_port")
    if isinstance(port, int) and not (1024 <= port <= 65535):
        err(f"`backlog.view_port` {port} is outside 1024..65535")
    if "statuses" in backlog:
        err("`backlog.statuses` is not configurable: in-progress / verified / closed are read by name in the gate")
    if "resolutions" in backlog:
        err("`backlog.resolutions` is not configurable: wont-do is read by name in the gate")

    git_t = raw.get("git") if isinstance(raw.get("git"), dict) else {}
    mb = git_t.get("main_branch")
    if isinstance(mb, str) and not mb.strip():
        err("`git.main_branch` is empty")

    ops = raw.get("operators", [])
    if not isinstance(ops, list):
        err("`operators` must be an array of tables ([[operators]])")
        ops = []
    # A row is a MACHINE: `id` and the (name, platform) pair are unique. `short` is the
    # PERSON (assignee token, `--who`), so one person on two machines is two rows sharing
    # one short (LANES-3) -- a distinct short per machine would split their queue.
    ids, pairs = set(), set()
    any_certifies = False
    for i, row in enumerate(ops):
        where = f"operators[{i}]"
        if not isinstance(row, dict):
            err(f"{where} must be a table")
            continue
        for key in row:
            if key not in _OPERATOR_FIELDS:
                warn(f"unknown key `{where}.{key}` (ignored)")
        for key, (typ, required) in _OPERATOR_FIELDS.items():
            if key not in row:
                if required:
                    err(f"{where} is missing `{key}`")
            elif not isinstance(row[key], typ):
                err(f"{where}.{key} must be a {typ.__name__}")
        oid, short = row.get("id"), row.get("short")
        if isinstance(oid, str):
            if oid in ids:
                err(f"duplicate operator id {oid!r}")
            ids.add(oid)
        if isinstance(short, str) and short in (SHARED_ASSIGNEE, CLAUDE_REPORTER):
            err(f"operator short {short!r} collides with a reserved token")
        pair = (row.get("name"), row.get("platform"))
        if all(isinstance(x, str) for x in pair):
            if pair in pairs:
                err(f"two operators share name+platform {pair!r}: a machine must resolve to one row")
            pairs.add(pair)
        if row.get("certifies") is True:
            any_certifies = True
    if ops and not any_certifies:
        warn("no operator has `certifies = true`: nothing can land on the main branch")

    lanes_t = raw.get("lanes") if isinstance(raw.get("lanes"), dict) else {}
    owner = lanes_t.get("code_owner")
    if lanes_t and not ops:
        warn("`[lanes]` has no effect in solo mode (no operators listed)")
    if isinstance(owner, str) and ops and owner not in ids:
        err(f"`lanes.code_owner` {owner!r} is not an operators[].id")

    order = {"error": 0, "warning": 1}
    problems.sort(key=lambda p: order[p.level])
    return problems


# ---------------------------------------------------------------- resolving
def _merged(raw: dict) -> dict:
    out: dict[str, Any] = {}
    for key, default in DEFAULTS.items():
        if isinstance(default, dict):
            table = raw.get(key) if isinstance(raw.get(key), dict) else {}
            out[key] = {k: table.get(k, v) for k, v in default.items()}
        elif isinstance(default, list):
            out[key] = list(raw.get(key, default))
        else:
            out[key] = raw.get(key, default)
    return out


def machine_row(operators: list, user_name: str, platform: Optional[str] = None) -> dict:
    """The operators[] row this machine is, or a synthesized one.

    Solo mode (no rows): the machine certifies and edits everything, id `<user>+<platform>`,
    short derived from the git user name. Two-operator mode with an UNKNOWN pair: the
    row is synthesized with every permission False — the skills treat that as "ask,
    don't guess".
    """
    platform = platform or sys.platform
    for row in operators:
        if row.get("name") == user_name and row.get("platform") == platform:
            return {
                "name": user_name, "platform": platform, "id": row["id"], "short": row["short"],
                "certifies": bool(row.get("certifies", False)),
                "may_edit_code": bool(row.get("may_edit_code", True)),
                "known": True,
            }
    solo = not operators
    return {
        "name": user_name, "platform": platform,
        "id": f"{user_name or 'operator'}+{platform}",
        "short": slug(user_name),
        "certifies": solo, "may_edit_code": solo, "known": False,
    }


def resolve(raw: dict, user_name: Optional[str] = None, platform: Optional[str] = None) -> dict:
    """Defaults + raw + derived values, flattened for assignment to module globals.

    Keys: ROOT-independent values only (the caller supplies ROOT). Derived:
    `solo`, `machine`, `assignees`, `reporters`, `docs_lane_prefixes`.
    """
    merged = _merged(raw)
    operators = merged["operators"]
    user_name = git_user_name() if user_name is None else user_name
    machine = machine_row(operators, user_name, platform)
    # Distinct, in table order: several machine rows may share one person's short.
    shorts = list(dict.fromkeys(r["short"] for r in operators if isinstance(r.get("short"), str))) or [machine["short"]]
    docs_lane = merged["backlog"]["docs_lane_prefixes"]
    if docs_lane is None:
        docs_lane = list(merged["git"]["main_direct_paths"])
    return {
        "plugin_version": merged["plugin_version"],
        "backlog_dir": merged["backlog"]["dir"],
        "projects": list(merged["backlog"]["projects"]),
        "types": list(merged["backlog"]["types"]),
        "priorities": list(merged["backlog"]["priorities"]),
        "statuses": list(STATUSES),
        "live_statuses": list(LIVE_STATUSES),
        "resolutions": list(RESOLUTIONS),
        "docs_lane_prefixes": list(docs_lane),
        "claim_marker_exempt": list(merged["backlog"]["claim_marker_exempt"]),
        "resolution_required_from": merged["backlog"]["resolution_required_from"],
        "view_port": merged["backlog"]["view_port"],
        "main_branch": merged["git"]["main_branch"],
        "land_requires_ok": merged["git"]["land_requires_ok"],
        "main_direct_paths": list(merged["git"]["main_direct_paths"]),
        "test_command": merged["tests"]["command"],
        "tests_required_before_land": merged["tests"]["required_before_land"],
        "rebase_rerun_command": merged["tests"]["rebase_rerun_command"],
        "port_command": merged["worktrees"]["port_command"],
        "operators": operators,
        "code_lane_paths": list(merged["lanes"]["code"]),
        "code_owner": merged["lanes"]["code_owner"],
        "solo": not operators,
        "machine": machine,
        "assignees": shorts + [SHARED_ASSIGNEE],
        "reporters": [CLAUDE_REPORTER] + shorts,
        "claim_age_floor_minutes": CLAIM_AGE_FLOOR_MINUTES,
    }


def plugin_root() -> Path:
    return Path(__file__).resolve().parent.parent


def installed_version() -> Optional[str]:
    """The version in this plugin's own manifest, or None if unreadable."""
    import json
    manifest = plugin_root() / ".claude-plugin" / "plugin.json"
    try:
        with open(manifest, encoding="utf-8") as fh:
            return json.load(fh).get("version")
    except (OSError, ValueError):
        return None


def describe_mode(cfg: dict) -> str:
    m = cfg["machine"]
    if cfg["solo"]:
        return f"solo mode — this machine ({m['id']}) certifies and edits everything"
    who = "known" if m["known"] else "NOT in the operators table"
    perms = []
    if m["certifies"]:
        perms.append("certifies")
    if m["may_edit_code"]:
        perms.append("edits code")
    return (f"{len(cfg['operators'])} operators — this machine is {m['id']} ({who}; "
            f"{', '.join(perms) if perms else 'no permissions'})")
