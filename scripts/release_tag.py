"""A pinned version is a released version: its `<name>--v<version>` tag is on the plugin's remote.

Part of the `lanes` plugin. Stdlib-only; runs on any machine with no virtualenv.

Usage:
  python3 release_tag.py --ensure [--push] [--remote origin]   # from a plugin checkout: tag HEAD's version if untagged
  python3 release_tag.py --check <version>                     # is <version>'s tag on the plugin's remote?

Why (LANES-33). A consumer's CI checks the plugin out at the tag matching its pin
(readlines' backlog gate, INFRA-78), so a release without a tag breaks that CI on every
push that follows. Nothing minted the tag: 0.4.4-0.4.9 were tagged by hand, releases moved
to `next` (LANES-14) and the habit stopped, and twenty pins went out untagged -- about 250
consecutive red backlog runs, read by the operator as "CI runs dozens of times an hour".

So the tag is made by two mechanisms and checked by two more:

  --ensure   the release mints it. The plugin's `release-tag` workflow runs it on every push
             to `main` and `next`; a session releasing by hand can run it first. Idempotent:
             a version already tagged on the remote is left alone, wherever its tag points.
  --check    `lanes_land.py` refuses a landing that pins an untagged version, and the doctor
             warns on one, both through `tag_on_remote()`.

The tag name is the one `claude plugin tag` mints (`{name}--v{version}`), annotated, with
the release commit's subject as its message -- the shape of every tag before this script.

`LANES_RELEASE_REMOTE` overrides the remote `--check` asks (default: the manifest's
`repository`). Set and EMPTY, it turns the lookup off: an offline machine, or a test.
"""
from __future__ import annotations

import argparse, json, os, subprocess, sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _console import use_utf8_console  # noqa: E402

REMOTE_ENV = "LANES_RELEASE_REMOTE"
MANIFEST_REL = ".claude-plugin/plugin.json"


def _git(*args, cwd=None, timeout=30):
    """(returncode, stdout, stderr); never raises, never prompts for credentials."""
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    try:
        p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                           encoding="utf-8", timeout=timeout, env=env)
    except (OSError, subprocess.SubprocessError) as e:
        return 1, "", str(e)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def manifest(root: Optional[Path] = None) -> dict:
    """The plugin manifest under `root` (default: this plugin's own), or {} if unreadable."""
    root = root if root is not None else Path(__file__).resolve().parent.parent
    try:
        with open(root / MANIFEST_REL, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def tag_name(version: str, name: Optional[str] = None) -> str:
    return f"{name or manifest().get('name') or 'lanes'}--v{version}"


def release_remote() -> Optional[str]:
    """Where a pin's tag is looked up: the env override, else the manifest's `repository`.
    None when the lookup is off (override set and empty) or there is nowhere to look."""
    if REMOTE_ENV in os.environ:
        return os.environ[REMOTE_ENV].strip() or None
    return manifest().get("repository") or None


def tag_on_remote(version: str, remote: Optional[str] = None) -> Optional[bool]:
    """True / False: the tag is / is not on the remote. None: the lookup is off or failed."""
    remote = remote if remote is not None else release_remote()
    if not remote:
        return None
    ref = f"refs/tags/{tag_name(version)}"
    rc, out, _ = _git("ls-remote", "--tags", remote, ref)
    if rc:
        return None
    return any(line.split("\t")[-1] == ref for line in out.splitlines())


def ensure(root: Path, remote: str = "origin", push: bool = False) -> tuple[int, str]:
    """Tag HEAD with the version in its manifest unless that version is already tagged on
    `remote`. (exit status, line to print)."""
    m = manifest(root)
    version, name = m.get("version"), m.get("name")
    if not version or not name:
        return 1, f"{root / MANIFEST_REL}: no name/version to tag"
    tag = tag_name(version, name)
    rc, out, err = _git("ls-remote", "--tags", remote, f"refs/tags/{tag}", cwd=root)
    if rc:
        return 1, f"cannot read tags on {remote}: {err or rc}"
    if out:
        return 0, f"{tag} is already on {remote}"
    if _git("rev-parse", "--verify", "--quiet", f"refs/tags/{tag}", cwd=root)[0] == 0:
        _, at, _ = _git("rev-parse", "--short", f"{tag}^{{commit}}", cwd=root)
        made = f"{tag} exists locally at {at}"
    else:
        _, subject, _ = _git("log", "-1", "--format=%s", cwd=root)
        rc, _, err = _git("tag", "-a", tag, "-m", subject or tag, cwd=root)
        if rc:
            return 1, f"could not create {tag}: {err}"
        _, at, _ = _git("rev-parse", "--short", "HEAD", cwd=root)
        made = f"tagged {tag} at {at}"
    if not push:
        return 0, f"{made} (not pushed; --push sends it to {remote})"
    rc, _, err = _git("push", "-q", remote, f"refs/tags/{tag}", cwd=root, timeout=120)
    if rc:
        return 1, f"{made}, but the push to {remote} failed: {err}"
    return 0, f"{made}, pushed to {remote}"


def main(argv=None) -> int:
    use_utf8_console()
    ap = argparse.ArgumentParser(description="lanes: a pinned version is a released (tagged) version")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--ensure", action="store_true", help="tag HEAD's manifest version if it has no tag on the remote")
    mode.add_argument("--check", metavar="VERSION", help="exit 0 when VERSION's tag is on the plugin's remote")
    ap.add_argument("--push", action="store_true", help="with --ensure: push the tag")
    ap.add_argument("--remote", default="origin", help="with --ensure: the remote (default: origin)")
    ap.add_argument("--root", default=".", help="with --ensure: the plugin checkout (default: cwd)")
    args = ap.parse_args(argv)
    if args.ensure:
        status, line = ensure(Path(args.root).resolve(), args.remote, args.push)
        print(line, file=sys.stdout if status == 0 else sys.stderr)
        return status
    found = tag_on_remote(args.check)
    where = release_remote() or "(lookup off)"
    if found is None:
        print(f"could not check {tag_name(args.check)} on {where}", file=sys.stderr)
        return 2
    print(f"{tag_name(args.check)} {'is' if found else 'is NOT'} on {where}")
    return 0 if found else 1


if __name__ == "__main__":
    sys.exit(main())
