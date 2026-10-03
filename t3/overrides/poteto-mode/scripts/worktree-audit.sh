#!/usr/bin/env bash
# Read-only worktree prune audit for Linux and macOS. Classifies every git
# worktree by size, last commit age, last checkout activity, merge state,
# uncommitted work, upstream state, PR state, and whether T3 created it.
# Emits a table sorted by size with a suggested bucket. Never deletes anything;
# deletion stays a human-gated step in the playbook, and the playbook checks
# T3 thread bindings with T3's tools, which this script cannot see.
#
# Usage: worktree-audit.sh [repo-path]   (defaults to the current repo)
# Env:   TRUNK=<branch>  override the trunk branch (default: origin/HEAD, else main)
#        T3_HOME=<dir>   T3's data dir (default: ~/.t3); worktrees live in $T3_HOME/worktrees
#        RECENT_DAYS=<n> activity window for verify-recent (default: 4)
set -u

repo="${1:-$(git rev-parse --show-toplevel 2>/dev/null)}"
[ -z "$repo" ] && { echo "not in a git repo; pass a repo path" >&2; exit 1; }
cd "$repo" || exit 1

t3_worktrees="${T3_HOME:-$HOME/.t3}/worktrees"
recent_days="${RECENT_DAYS:-4}"
now=$(date +%s)

# Epoch seconds to YYYY-MM-DD. GNU date takes -d @N, BSD date takes -r N.
fmt_day() {
	date -d "@$1" '+%Y-%m-%d' 2>/dev/null || date -r "$1" '+%Y-%m-%d' 2>/dev/null || echo "?"
}

# Kilobytes to a short human size. du -sk is the same on GNU and BSD.
human() {
	awk -v k="$1" 'BEGIN {
		split("K M G T", u, " "); i = 1
		while (k >= 1024 && i < 4) { k /= 1024; i++ }
		printf (k < 10 && i > 1) ? "%.1f%s" : "%d%s", k, u[i]
	}'
}

# Main worktree is the first entry; everything else is a candidate.
main_wt=$(git worktree list --porcelain | sed -n 's/^worktree //p' | head -1)

trunk="${TRUNK:-$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##')}"
trunk="${trunk:-main}"

# origin/<trunk> drives the merge check. Best-effort; stale is fine for a first pass.
git fetch origin "$trunk" --quiet 2>/dev/null \
	|| echo "warn: could not fetch origin/$trunk; MERGED may be stale" >&2
git rev-parse --verify --quiet "origin/$trunk" >/dev/null \
	|| echo "warn: origin/$trunk does not exist; MERGED shows ?" >&2

# PR state by branch, fetched once. Empty if gh or jq is unavailable.
prs=$(mktemp)
trap 'rm -f "$prs"' EXIT
if command -v gh >/dev/null && command -v jq >/dev/null; then
	gh pr list --author "@me" --state all --limit 1000 \
		--json number,state,headRefName 2>/dev/null > "$prs" || echo "[]" > "$prs"
else
	echo "warn: gh or jq missing; PR shows -" >&2
	echo "[]" > "$prs"
fi

printf "SIZE\tAGE\tACTIVE\tMERGED\tDIRTY\tREMOTE\tPR\tT3\tBUCKET\tWORKTREE\n"

# Paths are read whole, so a worktree path with spaces survives.
git worktree list --porcelain | sed -n 's/^worktree //p' | while IFS= read -r wt; do
	[ "$wt" = "$main_wt" ] && continue

	case "$wt" in "$t3_worktrees"/*) t3=yes ;; *) t3=no ;; esac

	# A registered worktree whose directory is gone is metadata only.
	if [ ! -d "$wt" ]; then
		printf "0\t-\t-\t-\t-\t-\t-\t%s\tprunable-missing\t%s\n" "$t3" "$wt"
		continue
	fi

	size_kb=$(du -sk "$wt" 2>/dev/null | awk '{print $1}')
	size_kb="${size_kb:-0}"
	head=$(git -C "$wt" rev-parse HEAD 2>/dev/null)
	head_ts=$(git -C "$wt" log -1 --format='%ct' HEAD 2>/dev/null)
	age=$([ -n "$head_ts" ] && echo "$(( (now - head_ts) / 86400 ))d" || echo "?")

	# Newest HEAD reflog entry: the last commit, checkout, reset, or rebase in
	# this worktree. Catches a worktree in use whose commits are old.
	active_ts=$(git -C "$wt" reflog -1 --format='%ct' HEAD 2>/dev/null)
	active_ts="${active_ts:-${head_ts:-0}}"
	active=$([ "$active_ts" -gt 0 ] && fmt_day "$active_ts" || echo "?")
	recent=no
	[ "$active_ts" -gt 0 ] && [ $(( (now - active_ts) / 86400 )) -le "$recent_days" ] && recent=yes

	# Squash-merged branches are not ancestors of trunk, so PR state is the
	# real signal; merge-base only catches fast-forward/rebase merges.
	if ! git rev-parse --verify --quiet "origin/$trunk" >/dev/null; then merged="?"
	elif git merge-base --is-ancestor "$head" "origin/$trunk" 2>/dev/null; then merged=YES
	else merged=no; fi

	# Distinguish real WIP (tracked edits) from disposable untracked scratch.
	porcelain=$(git -C "$wt" status --porcelain 2>/dev/null)
	if [ -z "$porcelain" ]; then dirty=clean
	elif printf '%s\n' "$porcelain" | grep -qv '^??'; then
		dirty="wip:$(printf '%s\n' "$porcelain" | grep -cv '^??')"
	else dirty="scratch:$(printf '%s\n' "$porcelain" | grep -c '^??')"; fi

	# Compare against the configured upstream, else origin/<branch>.
	branch=$(git -C "$wt" symbolic-ref --quiet --short HEAD 2>/dev/null || echo "")
	if [ -z "$branch" ]; then remote=detached
	else
		upstream=$(git -C "$wt" rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null)
		if [ -z "$upstream" ] && git -C "$wt" show-ref --verify --quiet "refs/remotes/origin/$branch"; then
			upstream="origin/$branch"
		fi
		if [ -z "$upstream" ]; then remote=no-remote
		elif [ "$(git -C "$wt" rev-parse "$upstream" 2>/dev/null)" = "$head" ]; then remote=pushed
		else remote="ahead$(git -C "$wt" rev-list --count "$upstream..HEAD" 2>/dev/null)"; fi
	fi

	pr=""
	[ -n "$branch" ] && pr=$(jq -r --arg b "$branch" \
		'.[] | select(.headRefName==$b) | "#\(.number)/\(.state)"' "$prs" 2>/dev/null | head -1)
	[ -z "$pr" ] && pr="-"

	case "$dirty" in wip:*) bucket=hold-wip ;; *)
		case "$pr" in *OPEN*) bucket=hold-open-pr ;; *)
			if [ "$recent" = yes ]; then bucket=verify-recent
			elif [ "$merged" = YES ] || [ "$pr" != "-" ]; then bucket=safe
			else bucket=review; fi ;;
		esac ;;
	esac

	printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n" \
		"$size_kb" "$age" "$active" "$merged" "$dirty" "$remote" "$pr" "$t3" "$bucket" "$wt"
done | sort -t "$(printf '\t')" -k1,1nr | while IFS="$(printf '\t')" read -r kb rest; do
	printf "%s\t%s\n" "$(human "$kb")" "$rest"
done
