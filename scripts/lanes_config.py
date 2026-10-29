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
# How the operator reads the backlog view (LANES-11): a bookmarked file:// page every
# backlog write regenerates, or the --serve page that re-parses per request (INFRA-43).
VIEW_MODES = ("file", "serve")
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
        "required_lines": [],                # [[backlog.required_lines]] (LANES-48)
        "view_port": 8099,
        "view_mode": "file",                 # "file" | "serve" (LANES-11)
    },
    "git": {
        "main_branch": "main",
        "land_requires_ok": True,
        "main_direct_paths": ["docs/", ".claude/lanes/", "*.md"],
        "ok_free_paths": None,               # None -> [backlog.dir + "/"] (LANES-5)
        "commit_guard": True,                # the pre-commit shim (LANES-1)
        "permanent_branches": [],            # never reported as unlanded (LANES-67); fnmatch patterns
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
        "required_lines": (list, False),
        "view_port": (int, False), "view_mode": (str, False),
    },
    "git": {"main_branch": (str, False), "land_requires_ok": (bool, False), "main_direct_paths": (list, False),
            "ok_free_paths": (list, False), "commit_guard": (bool, False), "permanent_branches": (list, False)},
    "tests": {"command": (str, False), "required_before_land": (bool, False), "rebase_rerun_command": (str, False)},
    "worktrees": {"port_command": (str, False)},
    "lanes": {"code": (list, False), "code_owner": (str, False)},
}
_OPERATOR_FIELDS = {
    "name": (str, True), "platform": (str, True), "id": (str, True), "short": (str, True),
    "certifies": (bool, False), "may_edit_code": (bool, False),
    "retired": (bool, False), "retired_on": (str, False),     # LANES-27
}
_REQUIRED_LINE_FIELDS = {
    "label": (str, True), "projects": (list, False), "types": (list, False), "since": (str, True),
}
# Lists of TABLES, validated field by field rather than as lists of strings.
_TABLE_LISTS = {("backlog", "required_lines")}
_TOP_LEVEL_SCALARS = {"plugin_version": (str, False)}
_PROJECT_RE = re.compile(r"^[A-Z][A-Z0-9]*$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_LABEL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9 _-]*$")
BUILT_IN_LINES = ("Docs",)     # the doc loop's line (INFRA-41): conditional on the change, never configured
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
            if key in table and typ is list and isinstance(table[key], list) and (section, key) not in _TABLE_LISTS:
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
    mode = backlog.get("view_mode")
    if isinstance(mode, str) and mode not in VIEW_MODES:
        err(f"`backlog.view_mode` must be one of {', '.join(VIEW_MODES)}, got {mode!r}")
    _validate_required_lines(backlog, err, warn)
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
        if row.get("retired") is True:
            # A retired row is history: its short keeps closed issues valid, and it grants nothing.
            granted = [k for k in ("certifies", "may_edit_code") if row.get(k) is True]
            if granted:
                warn(f"{where} is retired but sets {', '.join(f'`{k} = true`' for k in granted)} — "
                     "ignored: a retired row grants nothing")
            if isinstance(row.get("retired_on"), str) and not _DATE_RE.match(row["retired_on"]):
                err(f"{where}.retired_on must be YYYY-MM-DD")
            continue
        if row.get("retired_on") is not None:
            warn(f"{where}.retired_on is set but `retired` is not true")
        if row.get("certifies") is True:
            any_certifies = True
    if any(isinstance(r, dict) and r.get("retired") is not True for r in ops) and not any_certifies:
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


def _validate_required_lines(backlog: dict, err, warn) -> None:
    """`[[backlog.required_lines]]`: one table per Resolution line a project requires (LANES-48).

    `label` and `since` are required. `since` is the cut-over: without it every issue
    closed before the rule existed would fail the day it turned on, the way INFRA-41's
    `Docs:` line and the `resolution_required_from` field both needed one. `projects` and
    `types` narrow it; omitted means every one, and an empty list is an error rather than
    a rule that silently applies to nothing."""
    rules = backlog.get("required_lines")
    if not isinstance(rules, list):
        return
    projects = backlog.get("projects") if isinstance(backlog.get("projects"), list) else DEFAULTS["backlog"]["projects"]
    types = backlog.get("types") if isinstance(backlog.get("types"), list) else DEFAULTS["backlog"]["types"]
    seen = set()
    for i, rule in enumerate(rules):
        where = f"backlog.required_lines[{i}]"
        if not isinstance(rule, dict):
            err(f"`{where}` must be a table ([[backlog.required_lines]])")
            continue
        for key in rule:
            if key not in _REQUIRED_LINE_FIELDS:
                warn(f"unknown key `{where}.{key}` (ignored)")
        for key, (typ, required) in _REQUIRED_LINE_FIELDS.items():
            if key not in rule:
                if required:
                    err(f"`{where}` is missing `{key}`")
            elif not isinstance(rule[key], typ):
                err(f"`{where}.{key}` must be a {typ.__name__}")
        label = rule.get("label")
        if isinstance(label, str):
            if not _LABEL_RE.match(label):
                err(f"`{where}.label` {label!r} must be a word or words, no colon (the line reads `{label}:`)")
            elif label.lower() in (b.lower() for b in BUILT_IN_LINES):
                err(f"`{where}.label` {label!r} is built in: the doc loop requires it when a change reaches "
                    "outside `backlog.docs_lane_prefixes`, and configuring it would change that rule")
            elif label.lower() in seen:
                err(f"`{where}.label` {label!r} is configured twice")
            seen.add(label.lower())
        since = rule.get("since")
        if isinstance(since, str) and not _DATE_RE.match(since):
            err(f"`{where}.since` must be YYYY-MM-DD, got {since!r}")
        for key, allowed in (("projects", projects), ("types", types)):
            vals = rule.get(key)
            if not isinstance(vals, list):
                continue
            if not vals:
                err(f"`{where}.{key}` is empty — omit it to mean every one")
            unknown = [v for v in vals if v not in allowed]
            if unknown:
                err(f"`{where}.{key}` names {', '.join(repr(v) for v in unknown)}, not in `backlog.{key}`")


def required_lines(backlog: dict) -> list:
    """The well-formed `[[backlog.required_lines]]` rules, normalized. A malformed one is
    `validate()`'s finding (the doctor fails on it); it is left out here, never guessed at.

    Each: `label`, `projects` / `types` (a tuple, or None for every one), `since`."""
    out = []
    for rule in backlog.get("required_lines") or []:
        if not isinstance(rule, dict):
            continue
        label, since = rule.get("label"), rule.get("since")
        if not (isinstance(label, str) and _LABEL_RE.match(label) and isinstance(since, str)
                and _DATE_RE.match(since)) or label.lower() in (b.lower() for b in BUILT_IN_LINES):
            continue
        scope = {}
        for key in ("projects", "types"):
            vals = rule.get(key)
            scope[key] = tuple(vals) if isinstance(vals, list) and vals else None
        out.append({"label": label, "projects": scope["projects"], "types": scope["types"], "since": since})
    return out


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
    for row in active_operators(operators):   # a retired row never matches the running machine
        if row.get("name") == user_name and row.get("platform") == platform:
            return {
                "name": user_name, "platform": platform, "id": row["id"], "short": row["short"],
                "certifies": bool(row.get("certifies", False)),
                "may_edit_code": bool(row.get("may_edit_code", True)),
                "known": True,
            }
    solo = not active_operators(operators)
    return {
        "name": user_name, "platform": platform,
        "id": f"{user_name or 'operator'}+{platform}",
        "short": slug(user_name),
        "certifies": solo, "may_edit_code": solo, "known": False,
    }


def active_operators(operators: list) -> list:
    """The rows that still work here: every row without `retired = true` (LANES-27)."""
    return [r for r in operators if isinstance(r, dict) and r.get("retired") is not True]


def resolve(raw: dict, user_name: Optional[str] = None, platform: Optional[str] = None) -> dict:
    """Defaults + raw + derived values, flattened for assignment to module globals.

    Keys: ROOT-independent values only (the caller supplies ROOT). Derived:
    `solo`, `machine`, `assignees`, `reporters`, `docs_lane_prefixes`.
    """
    merged = _merged(raw)
    operators = merged["operators"]
    user_name = git_user_name() if user_name is None else user_name
    machine = machine_row(operators, user_name, platform)
    # Distinct, in table order: several machine rows may share one person's short. ACTIVE
    # shorts are what live work may name and what new issues are offered; EVERY short that
    # is or was an operator stays valid on history (LANES-27), so a departure needs no edit
    # to the issues that already name the person.
    active = active_operators(operators)
    shorts = list(dict.fromkeys(r["short"] for r in active if isinstance(r.get("short"), str))) or [machine["short"]]
    every = list(dict.fromkeys(shorts + [r["short"] for r in operators
                                        if isinstance(r, dict) and isinstance(r.get("short"), str)]))
    retired_shorts = [x for x in every if x not in shorts]
    docs_lane = merged["backlog"]["docs_lane_prefixes"]
    if docs_lane is None:
        docs_lane = list(merged["git"]["main_direct_paths"])
    # What may reach the main branch with no operator OK (LANES-5): the backlog alone by
    # default. Deliberately NOT main_direct_paths -- the standing docs are main-direct too,
    # but they change rules every session reads as ground truth, so they keep the OK.
    ok_free = merged["git"]["ok_free_paths"]
    if ok_free is None:
        ok_free = [merged["backlog"]["dir"].strip("/") + "/"]
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
        "required_lines": required_lines(merged["backlog"]),
        "view_port": merged["backlog"]["view_port"],
        "view_mode": merged["backlog"]["view_mode"],
        "main_branch": merged["git"]["main_branch"],
        "land_requires_ok": merged["git"]["land_requires_ok"],
        "main_direct_paths": list(merged["git"]["main_direct_paths"]),
        "ok_free_paths": list(ok_free),
        "permanent_branches": list(merged["git"]["permanent_branches"]),
        "test_command": merged["tests"]["command"],
        "tests_required_before_land": merged["tests"]["required_before_land"],
        "rebase_rerun_command": merged["tests"]["rebase_rerun_command"],
        "port_command": merged["worktrees"]["port_command"],
        "operators": operators,
        "code_lane_paths": list(merged["lanes"]["code"]),
        "code_owner": merged["lanes"]["code_owner"],
        "solo": not active,
        "machine": machine,
        "assignees": shorts + [SHARED_ASSIGNEE],
        "reporters": [CLAUDE_REPORTER] + shorts,
        "retired_shorts": retired_shorts,
        "historical_assignees": every + [SHARED_ASSIGNEE],
        "historical_reporters": [CLAUDE_REPORTER] + every,
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


# The id suffix a suggested row gets, in the spelling machine ids already use (`kyle-mac`).
PLATFORM_SUFFIX = {"darwin": "mac", "win32": "win", "linux": "linux"}


def _toml_row(row: dict) -> str:
    """One operators row on one line, its keys in the order a row is written."""
    def val(v):
        return ("true" if v else "false") if isinstance(v, bool) else f'"{v}"'
    keys = ("name", "platform", "id", "short", "certifies", "may_edit_code")
    return ", ".join(f"{k} = {val(row[k])}" for k in keys)


def unknown_machine_advice(cfg: dict) -> Optional[str]:
    """What settles an unknown machine in a multi-operator repo (LANES-71), or None when it
    is known or the repo is in solo mode.

    A row is a person's permissions, so the one open question is whose machine this is. An
    active row with this git user name on another platform usually answers it: the row's
    platform was a guess, or this is that person's second machine, so the advice names the
    row to correct or the one to add, with that person's short and permissions. Otherwise
    the advice is the question itself, over the active rows' shorts and "someone new". A
    retired row is never offered (LANES-27), and neither is another person's permissions.
    """
    m = cfg["machine"]
    if cfg["solo"] or m["known"]:
        return None
    name, platform = m["name"] or "", m["platform"]
    suffix = PLATFORM_SUFFIX.get(platform, slug(platform))
    head = f"`{name}` on {platform} has no operator row, so this machine has no permissions"
    tail = "a config change for the certifying operator to make or OK"
    kin = [r for r in active_operators(cfg["operators"]) if r.get("name") == name]
    if kin:
        short = kin[0]["short"]
        row = {"name": name, "platform": platform, "id": f"{short}-{suffix}", "short": short,
               "certifies": all(bool(r.get("certifies", False)) for r in kin),
               "may_edit_code": all(bool(r.get("may_edit_code", True)) for r in kin)}
        rows = ", ".join(f"{r['id']} ({r.get('platform')})" for r in kin)
        fix = (f"if {kin[0]['id']}'s platform was a guess, change it to {platform}; if {short} works on both, "
               if len(kin) == 1 else "")
        return (f"{head}. `{name}` is {short}'s git user name, on {rows}: {fix}add a row: {_toml_row(row)}. "
                f"It is {tail}.")
    shorts = list(dict.fromkeys(r["short"] for r in active_operators(cfg["operators"]) if r.get("short")))
    row = {"name": name, "platform": platform, "id": f"<short>-{suffix}", "short": "<short>",
           "certifies": False, "may_edit_code": False}
    return (f"{head}, and no active row has that git user name. Ask which operator this is ({' or '.join(shorts)}) "
            f"or whether it is someone new, and nothing else; then add a row: {_toml_row(row)}. It is {tail}.")


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
    retired = [r.get("id") for r in cfg["operators"] if isinstance(r, dict) and r.get("retired") is True]
    count = f"{len(cfg['operators']) - len(retired)} operators" + (
        f" + {len(retired)} retired ({', '.join(str(x) for x in retired)})" if retired else "")
    return (f"{count} — this machine is {m['id']} ({who}; "
            f"{', '.join(perms) if perms else 'no permissions'})")
