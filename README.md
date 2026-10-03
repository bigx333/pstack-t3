# pstack-t3

[Lauren Tan's pstack](https://github.com/cursor/plugins/tree/main/pstack), ported to run natively in [T3 Code](https://t3.codes) on any model.

pstack is a set of engineering skills: `poteto-mode` and its 22 playbooks, plus `swarm`, `arena`, `interrogate`, `architect`, `how`, `why`, `reflect`, and the principles. Upstream drives Cursor's `Task` tool, Cursor cloud agents, `/loop`, and a Cursor rule file of model slugs. pstack-t3 replaces each of those with T3's orchestrator V2 tools, so the same workflows run from a Claude, Codex, Grok, Cursor, or OpenCode thread and fan out across all of them.

This is an independent adaptation under the MIT license. It is not an official Cursor, T3, OpenAI, Anthropic, or xAI project.

## Why a skills pack, not an MCP server or a plugin

- T3 already injects its orchestrator MCP server (`t3-code`) into every provider. pstack-t3 needs no server of its own. It teaches each model to use the one that is there.
- T3's `$` picker lists each provider's native skills. Installing into each provider's skill directory makes `$poteto-mode` appear in every composer, whichever model is selected.
- A Claude Code plugin would namespace the skills (`pstack:swarm`), and T3's picker scans only plain skill directories, so plugin skills would be hidden. Other providers have no plugin format at all.

## What changes from upstream

| Upstream (Cursor) | pstack-t3 (T3 orchestrator V2) |
| --- | --- |
| `Task` subagents with `subagent_type`, `model`, `run_in_background` | `delegate_task` child tasks with `role`, a resolved `target`, `mode: "async"`, and a `clientRequestId` |
| Cloud agents | Local child tasks. PR owners that outlive a turn become `t3_thread_launch` threads bound to their own worktree |
| `~/.cursor/rules/pstack-models.mdc` with Cursor model slugs | `~/.config/pstack-t3/roles.json` with seats from the live `orchestrator_capabilities` catalog, resolved by `roles.py` |
| Hard-coded default panel (Fable, Sol, Grok, Opus) | One panel seat per provider you have runnable, so diversity comes from the providers you actually have |
| `/loop`, automations, hourly ticks | `schedule_task` |
| Cursor transcripts and cloud-agent URLs | T3 threads, read with `t3_thread_search` and `t3_thread_read` |
| `control-ui` from `cursor-team-kit` | T3 preview tools (`preview_open`, `preview_snapshot`, `preview_click`, recordings) and `device_*` tools |
| Cursor's built-in `create-skill` | `pstack-author-skill`, model-agnostic |
| Worktree audit that scans Cursor chat storage on macOS | Git inventory on Linux and macOS, plus a check for T3 threads bound to each worktree |
| — | `link_pull_request` on every PR a playbook opens or drives |
| Different model per reviewer | Different model family per reviewer, compared by model and not by provider, because one provider can serve another's models |

[`t3/runtime.md`](t3/runtime.md), installed as the `pstack-runtime` skill, holds every mapping in one place. The other skills link to it.

## Install

Requires Python 3.10+, git, and T3 Code. Keep this checkout on disk, because the install links to it.

```bash
git clone https://github.com/creedants/pstack-t3.git ~/Projects/pstack-t3
cd ~/Projects/pstack-t3
python3 scripts/install.py            # user scope, every provider
python3 scripts/install.py doctor     # confirm every provider sees pstack-t3
```

| Provider | User directory | Project directory |
| --- | --- | --- |
| Claude | `~/.claude/skills` (or `$CLAUDE_CONFIG_DIR/skills`) | `.claude/skills` |
| Codex | `~/.agents/skills` | `.agents/skills` |
| Grok | `~/.grok/skills` | `.grok/skills` |
| Cursor | `~/.cursor/skills` | `.cursor/skills` |

- `--project /path/to/repo` installs for one repository instead.
- `--harness claude,codex` limits the providers.
- The installer refuses to overwrite skills that already exist, such as another pstack copy. `--replace` moves them aside and records them, and `python3 scripts/install.py uninstall` puts them back.
- Directories that resolve to the same real path are linked once.
- `--dry-run` prints the plan.

Start a new T3 thread after installing so the provider rescans its skills.

### User scope wins

When the same skill name exists in both scopes, Claude and Grok load the user copy. Codex loaded the project copy in testing. A project install is therefore shadowed by any other pstack you have at user scope. Prefer the user install, and use `--replace` to move an older pstack aside. `python3 scripts/install.py doctor --project <repo>` reports shadowed names.

## Get started

1. In any T3 thread, run `$setup-pstack`. It reads the live catalog, asks for a budget, proposes which provider and model fills each role, checks each seat with a smoke delegation, and writes `~/.config/pstack-t3/roles.json`.
2. Use `$poteto-mode` for anything that needs rigor.

```
$poteto-mode this pr has a subtle bug where the scroll drifts every 750ms even when idle. repro first, then fix and verify.
```

```
$interrogate review this branch.
```

```
$poteto-mode i'm going to bed. land the stack even if ci flakes. i want everything merged by morning.
```

Without setup, single-seat roles inherit the thread's model and panels use one seat per runnable provider. Nothing ever names a model you do not have.

## Roles

`roles.py` resolves a role to `delegate_task` targets:

```bash
python3 skills/pstack-runtime/scripts/roles.py show --role "interrogate reviewers"
```

```json
{
  "budget": "large",
  "catalog": true,
  "roles": {
    "interrogate reviewers": {
      "source": "/home/you/.config/pstack-t3/roles.json",
      "seats": [
        "inherit",
        {"providerInstanceId": "codex", "model": "gpt-6.1-sol", "options": {"reasoningEffort": "xhigh"}},
        {"providerInstanceId": "grok", "model": "grok-4.7", "options": {"reasoningEffort": "xhigh"}}
      ]
    }
  }
}
```

- A project can override any role in `.pstack/t3-roles.json`.
- The budget (`default`, `small`, `medium`, `large`, `unlimited`) sets each seat's reasoning option to its level. A seat that names a lower level keeps it.
- A seat whose provider is not runnable inherits the parent, and a model T3 dropped falls back to that provider's first model. Each fallback is reported, never silent.

## Develop

The build check needs PyYAML (`pip install pyyaml`). Installing and `roles.py` need only the standard library.

```bash
python3 scripts/build.py                     # regenerate skills/ from vendor/ + t3/
python3 -m unittest discover -s tests -v
python3 scripts/sync_upstream.py             # pull a newer upstream pstack
```

`vendor/pstack` is upstream, byte-identical to the commit in [`upstream.json`](upstream.json). T3 changes live in `t3/`. `t3/overrides/` replaces upstream files wholesale, and `t3/overrides.lock.json` records the upstream digest each override was ported from. After a sync, the build fails on every override whose upstream file changed, until you re-port it and run `build.py --update-lock`. `scripts/check.py` fails the build on Cursor leftovers, broken links, and bad frontmatter. See [AGENTS.md](AGENTS.md) for the porting rules.

## Credits

pstack is by [Lauren Tan (poteto)](https://x.com/poteto). The skills, playbooks, principles, and their wording are hers. pstack-t3 changes how they reach models, not what they ask of them.
