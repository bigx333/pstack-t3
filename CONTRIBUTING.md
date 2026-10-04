# Contributing

Issues and pull requests are welcome.

## Where changes go

- **A skill behaves wrong in T3.** Change its port in `t3/overrides/`, or `t3/runtime.md` if the problem is how pstack maps onto T3's tools. Never edit `skills/` or `vendor/` by hand. `skills/` is generated, and `vendor/pstack` must stay byte-identical to upstream.
- **The engineering content itself (a playbook step, a principle, a rubric).** That belongs upstream in [cursor/plugins](https://github.com/cursor/plugins/tree/main/pstack). pstack-t3 picks it up on the next sync.
- **Installer or roles resolver.** `scripts/install.py` and `t3/scripts/roles.py`, with a test in `tests/`.

[AGENTS.md](AGENTS.md) has the porting rules. Agents working on this repo should read it first.

## Before you open a PR

```bash
pip install pyyaml
python3 scripts/build.py
python3 -m unittest discover -s tests -v
```

Commit the regenerated `skills/` with your change. Add a line under Unreleased in `CHANGELOG.md` for any user-facing change. CI fails if `skills/` does not match what the build produces.

If you changed a skill's behavior, run it in a real T3 thread and say in the PR which provider led and what it did.

## Syncing upstream

```bash
python3 scripts/sync_upstream.py
```

The build then lists each override whose upstream file changed. Re-port each one against the new upstream text, then run `python3 scripts/build.py --update-lock`.

## Releasing

1. Rename Unreleased in `CHANGELOG.md` to the new version.
2. Commit, tag `vX.Y.Z`, and push the tag.
3. Run `gh release create vX.Y.Z --notes-file <that changelog section>`.

Cut a release after each upstream sync and any user-facing fix.
