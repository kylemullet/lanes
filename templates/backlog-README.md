# Backlog

One file per issue, `<PROJECT>/<ID>-<slug>.md`, kept by the
[lanes](https://github.com/kylemullet/lanes) plugin. The project prefixes, statuses and
issue types are set in `.claude/lanes/config.toml`.

- `/lanes:new <PROJECT> "<title>"` mints an issue with the next free ID.
- `/lanes:claim <ID> …` claims a slice before a lane starts; the skills release it.
- `/lanes:doctor` checks the backlog's integrity along with the rest of the setup.

`INDEX.md` and `index.html` in this folder are generated local views, rewritten by every
lanes script that writes the backlog. The `.gitignore` beside this file keeps them out of
git: never commit them.
