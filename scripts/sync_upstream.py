#!/usr/bin/env python3
"""Replace vendor/pstack with a newer upstream revision and report override drift.

After syncing, `python3 scripts/build.py` lists every override whose upstream
file changed. Re-port each one, then run `build.py --update-lock`.
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "upstream.json"


def run(*command, cwd=None):
    return subprocess.run(command, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ref", default="main", help="upstream branch, tag, or commit")
    args = parser.parse_args()
    meta = json.loads(UPSTREAM.read_text())
    with tempfile.TemporaryDirectory(prefix="pstack-upstream-") as temporary:
        checkout = Path(temporary) / "plugins"
        run("git", "clone", "--filter=blob:none", "--no-checkout", meta["repository"], str(checkout))
        run("git", "sparse-checkout", "set", meta["path"], cwd=checkout)
        run("git", "checkout", args.ref, cwd=checkout)
        commit = run("git", "rev-parse", "HEAD", cwd=checkout)
        source = checkout / meta["path"]
        plugin = json.loads((source / ".cursor-plugin/plugin.json").read_text())
        vendor = ROOT / "vendor/pstack"
        shutil.rmtree(vendor)
        shutil.copytree(source, vendor)
    previous = meta["commit"]
    meta.update(commit=commit, version=plugin.get("version", meta.get("version")))
    UPSTREAM.write_text(json.dumps(meta, indent=2) + "\n")
    print(f"vendor/pstack: {previous[:12]} -> {commit[:12]} ({meta['version']})")
    result = subprocess.run([sys.executable, str(ROOT / "scripts/build.py")], capture_output=True, text=True)
    print(result.stdout + result.stderr)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
