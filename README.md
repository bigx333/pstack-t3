# pstack-t3

[![ci](https://github.com/creedants/pstack-t3/actions/workflows/ci.yml/badge.svg)](https://github.com/creedants/pstack-t3/actions/workflows/ci.yml)
[![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![upstream pstack 0.15.6](https://img.shields.io/badge/upstream%20pstack-0.15.6-555.svg)](upstream.json)

**Rigorous, multi-model engineering workflows for [T3 Code](https://t3.codes), on whatever models you have.**

pstack-t3 is [Lauren Tan's pstack](https://github.com/cursor/plugins/tree/main/pstack), ported from Cursor to T3 Code. pstack turns one agent into a careful engineering team. It reproduces bugs before fixing them, designs before coding, sends a diff to several different models to break it, and proves the change works before calling it done.

Upstream runs on Cursor's subagents and cloud agents. pstack-t3 runs on T3's orchestrator V2, so any thread can lead (Claude, Codex, Grok, or Cursor), and the work fans out across all of them.

```
$interrogate review this branch.
```

> Resolved `interrogate reviewers`. Launched four reviewers with identical read-only briefs.
> A: Codex / gpt-6.1-sol. B: Claude / claude-opus-5-5. C: Cursor / Auto. D: Grok / grok-4.7.
>
> **Act on.** 1. Incorrect even-length median (A, B, C, D). `stats.py:5` uses `// 2`, flooring the average. 2. The regression test asserts the bug (A, B, C, D).
>
> All four reviewers independently identified both blockers. **The commit should not pass review.**

*An actual run: a Codex-led thread reviewing a planted bug that its own tests passed.*

## Quick start

You need T3 Code, git, and Python 3.10 or later.

```bash
git clone https://github.com/creedants/pstack-t3.git ~/pstack-t3
cd ~/pstack-t3
python3 scripts/install.py           # link the skills into every provider T3 runs
python3 scripts/install.py doctor    # confirm each provider sees them
```

Keep the checkout on disk, because the install links to it. Then start a new T3 thread.

1. Run `$setup-pstack`. It reads the models you have, asks for a reasoning budget, and picks a provider and model for each role. Skip it and sensible defaults apply.
2. Use `$poteto-mode` for anything that needs rigor.

```
$poteto-mode this pr has a subtle bug where the scroll drifts every 750ms even when idle. repro first, then fix and verify.
```

```
$poteto-mode i'm going to bed. land the stack even if ci flakes. i want everything merged by morning.
```

## What's inside

`$poteto-mode` reads your request, picks one of 22 playbooks (bug fix, feature, refactor, perf, investigation, babysit a PR, ship a stack, autonomous run, orchestrate a multi-day project, and more), and calls the other skills as its steps need them. You can also call them directly.

| Skill | Use it when |
| --- | --- |
| `$poteto-mode` | Any non-trivial task. The main entry point. |
| `$interrogate` | You have a diff and want several different models to try to break it. |
| `$swarm` | You want parallel workers over separate slices, or a race, with one combined report. |
| `$arena` | You want several attempts at the same artifact, then the best parts grafted into one. |
| `$architect` | You're about to write code across a boundary and want the shape settled first. |
| `$how` / `$why` | You want a walkthrough of a subsystem, or the reasons behind it. |
| `$blast-radius` | A small change looks safe and you want proof of what else it could break. |
| `$recall` | You're resuming work and want your context rebuilt from past T3 threads. |
| `$reflect` | A task is done and you want its lessons turned into skill edits. |
| `$setup-pstack` | You want to choose models per role, or change the budget. |

Plus the principle skills (`principle-prove-it-works`, `principle-fix-root-causes`, and 22 more), `unslop`, `technical-writing`, `tdd`, and verification-skill generators. Every skill is listed in [`skills/`](skills).

## How it works with T3

T3 Code gives every agent the same orchestration tools, whichever provider runs it. pstack-t3 teaches each model to use them the pstack way.

| pstack needs | T3 provides |
| --- | --- |
| Parallel workers on chosen models | `delegate_task`, with `task_status` and `task_cancel` |
| Which models exist right now | `orchestrator_capabilities` |
| Long-lived owners in their own worktree | `t3_thread_launch` with a worktree strategy |
| Overnight and recurring checks | `schedule_task` |
| Past context | `t3_thread_search` and `t3_thread_read` |
| Proof a UI change works | The `preview_*` tools |
| PR tracking | `link_pull_request` |

The [`pstack-runtime`](t3/runtime.md) skill holds this whole mapping in one place, and every other skill links to it.

**Model choice.** Nothing names a model you don't have. Each pstack role, such as `interrogate reviewers` or `bug-fix`, resolves against T3's live model list. By default, single-worker roles use the thread's own model. Review panels get one seat per model family you can run, so a panel of Claude, GPT, and Grok catches what one family misses. `$setup-pstack` writes your choices to `~/.config/pstack-t3/roles.json`, and a repository can override them in `.pstack/t3-roles.json`. To see what a role resolves to:

```bash
python3 skills/pstack-runtime/scripts/roles.py show --role "interrogate reviewers"
```

## Install details

| Provider | User directory | Project directory |
| --- | --- | --- |
| Claude | `~/.claude/skills` (or `$CLAUDE_CONFIG_DIR/skills`) | `.claude/skills` |
| Codex | `~/.agents/skills` | `.agents/skills` |
| Grok | `~/.grok/skills` | `.grok/skills` |
| Cursor | `~/.cursor/skills` | `.cursor/skills` |

- The installer refuses to overwrite skills that already exist, such as another pstack copy. `--replace` moves them aside, and `python3 scripts/install.py uninstall` puts them back.
- `--project /path/to/repo` installs for one repository. `--harness claude,codex` limits the providers. `--dry-run` prints the plan.
- **Prefer the user install.** When a name exists at both scopes, Claude and Grok load the user copy, so another pstack at user scope shadows a project install. `doctor` reports shadowed and stale copies.

**Why skills, not an MCP server or a plugin?** T3 already gives every provider its orchestration server, so pstack-t3 needs no server of its own. T3's `$` picker lists each provider's native skills, which is why installing there makes `$poteto-mode` appear whichever model you pick. A Claude Code plugin would namespace the skills and hide them from that picker, and the other providers have no plugin format.

## What changed from upstream

| Upstream (Cursor) | pstack-t3 (T3) |
| --- | --- |
| `Task` subagents with `subagent_type` and `model` | `delegate_task` children with a `role` and a resolved `target` |
| Cloud agents | Local child tasks, or `t3_thread_launch` threads bound to their own worktree |
| A Cursor rule file of model slugs | `roles.json` resolved against T3's live catalog |
| A fixed default panel of four Cursor models | One seat per model family you can run |
| `/loop`, automations, hourly ticks | `schedule_task` |
| Cursor transcripts and cloud-agent URLs | T3 threads |
| `control-ui` from `cursor-team-kit` | T3 preview and device tools |
| Cursor's built-in `create-skill` | `pstack-author-skill`, for every provider |
| A worktree audit that reads Cursor's chat storage on macOS | Git inventory on Linux and macOS, plus T3 thread bindings |
| | `link_pull_request` on every PR a playbook opens or drives |

The playbooks, principles, rubrics, and their wording are otherwise upstream's.

## Develop

```bash
pip install pyyaml                           # used by the build check
python3 scripts/build.py                     # regenerate skills/ from vendor/ + t3/
python3 -m unittest discover -s tests -v
python3 scripts/sync_upstream.py             # pull a newer upstream pstack
```

`vendor/pstack` is upstream, byte-identical to the commit in [`upstream.json`](upstream.json). All T3 changes live in `t3/`. Each override records the upstream file it was ported from, so after a sync the build names every override that needs re-porting. The build also fails on Cursor-only leftovers, broken links, and invalid frontmatter. See [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md).

## Credits and license

pstack is by [Lauren Tan (poteto)](https://x.com/poteto). The skills, playbooks, principles, and their wording are hers. pstack-t3 changes how they reach models, not what they ask of them.

MIT licensed. See [LICENSE](LICENSE). The upstream license is preserved in [`vendor/pstack/LICENSE`](vendor/pstack/LICENSE).

pstack-t3 is an independent project. It is not affiliated with or endorsed by Lauren Tan, Cursor, T3 Tools, Anthropic, OpenAI, or xAI.
