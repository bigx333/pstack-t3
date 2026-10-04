**What changed and why.**

**How you verified it.** For a skill behavior change, name the provider that led the T3 thread and what it did.

- [ ] `python3 scripts/build.py` passes and the regenerated `skills/` is committed.
- [ ] `python3 -m unittest discover -s tests -v` passes.
- [ ] No edits to `vendor/` or hand edits to `skills/`.
- [ ] `CHANGELOG.md` has a line under Unreleased for any user-facing change.
