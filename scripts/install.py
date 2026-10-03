#!/usr/bin/env python3
"""Install pstack-t3 skills into every provider skill directory T3 reads.

T3's `$` picker lists each provider's native skills, so pstack-t3 links its
generated skills into each provider's directory. Every link and every entry
moved aside is recorded in a manifest so `uninstall` restores the prior state.
"""

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
HARNESSES = ("claude", "codex", "grok", "cursor")


def skill_dirs(scope_root, user):
    home = Path(os.environ.get("HOME", str(Path.home())))
    claude = Path(os.environ["CLAUDE_CONFIG_DIR"]) if user and os.environ.get("CLAUDE_CONFIG_DIR") else (home / ".claude" if user else scope_root / ".claude")
    base = home if user else scope_root
    return {
        "claude": claude / "skills",
        "codex": base / ".agents" / "skills",
        "grok": base / ".grok" / "skills",
        "cursor": base / ".cursor" / "skills",
    }


def state_dir(scope_root, user):
    if user:
        config = Path(os.environ.get("XDG_CONFIG_HOME") or Path(os.environ.get("HOME", str(Path.home()))) / ".config")
        return config / "pstack-t3"
    return scope_root / ".pstack"


def ours(path):
    return path.is_symlink() and Path(os.readlink(path)).resolve().parent == SKILLS.resolve()


def describe(path):
    if path.is_symlink():
        return f"link to {os.readlink(path)}"
    return "directory" if path.is_dir() else "file"


def load_manifest(file):
    if file.exists():
        return json.loads(file.read_text())
    return {"links": [], "backups": []}


def save_manifest(file, manifest):
    file.parent.mkdir(parents=True, exist_ok=True)
    temporary = file.with_suffix(".tmp")
    temporary.write_text(json.dumps(manifest, indent=2) + "\n")
    os.replace(temporary, file)


def plan(targets, names):
    """Return (actions, conflicts). Directories sharing a real path are visited once."""
    actions, conflicts, seen = [], [], set()
    for harness, directory in targets.items():
        real = directory.resolve()
        if real in seen:
            continue
        seen.add(real)
        for name in names:
            link = directory / name
            if ours(link):
                continue
            if link.exists() or link.is_symlink():
                conflicts.append((harness, link))
            actions.append((harness, link))
    return actions, conflicts


def install(args):
    if not SKILLS.is_dir():
        sys.exit("skills/ is missing; run python3 scripts/build.py first")
    user = args.project is None
    scope = Path(args.project).resolve() if args.project else None
    targets = {h: d for h, d in skill_dirs(scope, user).items() if h in args.harness}
    names = sorted(p.name for p in SKILLS.iterdir() if (p / "SKILL.md").is_file())
    actions, conflicts = plan(targets, names)
    if conflicts and not args.replace:
        lines = [f"  {harness}: {link} ({describe(link)})" for harness, link in conflicts]
        sys.exit("these skills already exist; rerun with --replace to move them aside (uninstall restores them):\n" + "\n".join(lines))
    if args.dry_run:
        for harness, link in actions:
            print(f"would link {link} -> {SKILLS / link.name}" + (f" (replacing {describe(link)})" if (harness, link) in conflicts else ""))
        print(f"{len(actions)} links planned")
        return
    state = state_dir(scope, user)
    manifest_file = state / "install-manifest.json"
    manifest = load_manifest(manifest_file)
    backup_root = state / "backups" / time.strftime("%Y%m%dT%H%M%S")
    for harness, link in actions:
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.exists() or link.is_symlink():
            backup = backup_root / harness / link.name
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(link), str(backup))
            manifest["backups"].append({"original": str(link), "backup": str(backup)})
        link.symlink_to(SKILLS / link.name, target_is_directory=True)
        manifest["links"].append(str(link))
        save_manifest(manifest_file, manifest)
    print(f"linked {len(actions)} skills into {', '.join(sorted(set(h for h, _ in actions))) or 'nothing (already installed)'}")
    print(f"manifest: {manifest_file}")


def uninstall(args):
    user = args.project is None
    scope = Path(args.project).resolve() if args.project else None
    manifest_file = state_dir(scope, user) / "install-manifest.json"
    manifest = load_manifest(manifest_file)
    removed = 0
    for entry in manifest["links"]:
        link = Path(entry)
        if ours(link):
            link.unlink()
            removed += 1
    restored = 0
    for entry in reversed(manifest["backups"]):
        original, backup = Path(entry["original"]), Path(entry["backup"])
        if (backup.exists() or backup.is_symlink()) and not (original.exists() or original.is_symlink()):
            shutil.move(str(backup), str(original))
            restored += 1
    if manifest_file.exists():
        manifest_file.unlink()
    print(f"removed {removed} links, restored {restored} entries")


def doctor(args):
    user = args.project is None
    scope = Path(args.project).resolve() if args.project else None
    names = sorted(p.name for p in SKILLS.iterdir() if (p / "SKILL.md").is_file()) if SKILLS.is_dir() else []
    healthy = True
    for harness, directory in skill_dirs(scope, user).items():
        if harness not in args.harness:
            continue
        installed = [n for n in names if ours(directory / n)]
        foreign = [n for n in names if (directory / n).exists() and not ours(directory / n)]
        missing = [n for n in names if not (directory / n).exists()]
        healthy &= not foreign and not missing
        print(f"{harness:7} {directory}: {len(installed)}/{len(names)} pstack-t3" +
              (f", {len(foreign)} shadowed by other copies ({', '.join(foreign[:5])}{'...' if len(foreign) > 5 else ''})" if foreign else "") +
              (f", {len(missing)} missing" if missing else ""))
    return 0 if healthy else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("install", "uninstall", "doctor"), nargs="?", default="install")
    parser.add_argument("--project", help="install into this repository instead of the user's skill directories")
    parser.add_argument("--harness", default="all", help="comma list of " + ",".join(HARNESSES) + ", or all")
    parser.add_argument("--replace", action="store_true", help="move conflicting skills aside; uninstall restores them")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    args.harness = HARNESSES if args.harness == "all" else tuple(h.strip() for h in args.harness.split(","))
    unknown = set(args.harness) - set(HARNESSES)
    if unknown:
        parser.error(f"unknown harness {', '.join(sorted(unknown))}")
    return {"install": install, "uninstall": uninstall, "doctor": doctor}[args.command](args) or 0


if __name__ == "__main__":
    sys.exit(main())
