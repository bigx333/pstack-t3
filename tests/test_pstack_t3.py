import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "t3/scripts"))
sys.path.insert(0, str(ROOT / "scripts"))

import check  # noqa: E402
import roles  # noqa: E402

CATALOG = json.loads((ROOT / "tests/fixtures/catalog.json").read_text())


def config(budget="default", **assigned):
    return {"budget": budget, "roles": assigned, "sources": {name: "test" for name in assigned}}


class RolesTest(unittest.TestCase):
    def test_single_roles_default_to_inherit(self):
        result = roles.resolve(config(), CATALOG, ["swarm workers"])
        self.assertEqual(result["roles"]["swarm workers"]["seats"], ["inherit"])

    def test_panel_default_is_one_seat_per_runnable_provider_with_parent_inheriting(self):
        seats = roles.resolve(config(), CATALOG, ["interrogate reviewers"])["roles"]["interrogate reviewers"]["seats"]
        self.assertEqual(seats, [
            "inherit",
            {"providerInstanceId": "codex", "model": "gpt-6.1-sol"},
            {"providerInstanceId": "grok", "model": "grok-4.7"},
        ])

    def test_panel_skips_a_provider_serving_a_family_already_seated(self):
        cursor = {"providerInstanceId": "cursor", "canRunChildTask": True, "constraints": [],
                  "models": [{"id": "claude-opus-5-5", "options": None}]}
        catalog = {**CATALOG, "providers": CATALOG["providers"] + [cursor]}
        seats = roles.resolve(config(), catalog, ["verifiers"])["roles"]["verifiers"]["seats"]
        self.assertNotIn({"providerInstanceId": "cursor", "model": "claude-opus-5-5"}, seats)
        self.assertEqual(len(seats), 3)

    def test_null_model_options_are_treated_as_none(self):
        provider = {"providerInstanceId": "pi", "canRunChildTask": True, "constraints": [], "models": [{"id": "pi-1", "options": None}]}
        catalog = {**CATALOG, "providers": CATALOG["providers"] + [provider]}
        entry = roles.resolve(config("large", **{"bug-fix": [{"providerInstanceId": "pi", "model": "pi-1"}]}), catalog, ["bug-fix"])["roles"]["bug-fix"]
        self.assertEqual(entry["seats"], [{"providerInstanceId": "pi", "model": "pi-1"}])

    def test_validate_rejects_option_values_the_catalog_lacks(self):
        seat = {"providerInstanceId": "codex", "model": "gpt-6.1-sol", "options": {"reasoningEffort": "banana", "serviceTier": True}}
        problems = roles.validate(config(**{"bug-fix": [seat]}), CATALOG)
        self.assertEqual(len(problems), 2, problems)

    def test_budget_makes_inherit_explicit_so_the_cap_applies(self):
        seats = roles.resolve(config("small"), CATALOG, ["bug-fix"])["roles"]["bug-fix"]["seats"]
        self.assertEqual(seats, [{"providerInstanceId": "claudeAgent", "model": "claude-opus-5-5", "options": {"effort": "medium"}}])
        self.assertEqual(roles.resolve(config(), CATALOG, ["bug-fix"])["roles"]["bug-fix"]["seats"], ["inherit"])

    def test_budget_understands_extra_high_and_keeps_none(self):
        model = {"id": "m", "options": [{"id": "reasoning_effort", "type": "select", "options": [{"id": "none"}, {"id": "low"}, {"id": "high"}, {"id": "extra-high"}]}]}
        self.assertEqual(roles.apply_budget({"model": "m"}, model, "unlimited")["options"], {"reasoning_effort": "extra-high"})
        self.assertEqual(roles.apply_budget({"model": "m", "options": {"reasoning_effort": "none"}}, model, "small")["options"], {"reasoning_effort": "none"})
        self.assertEqual(roles.apply_budget({"model": "m", "options": {"reasoning_effort": "extra-high"}}, model, "small")["options"], {"reasoning_effort": "low"})

    def test_snapshot_parent_comes_from_the_caller_not_the_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            snapshot = base / "pstack-t3" / "catalog.json"
            snapshot.parent.mkdir()
            snapshot.write_text(json.dumps(CATALOG))
            env = {**os.environ, "XDG_CONFIG_HOME": str(base)}
            run = lambda *extra: json.loads(subprocess.run([sys.executable, str(ROOT / "t3/scripts/roles.py"), "show", "--cwd", directory, "--role", "verifiers", *extra],
                                                           env=env, capture_output=True, text=True, check=True).stdout)
            seats = run("--parent", "codex/gpt-6.1-sol")["roles"]["verifiers"]["seats"]
            self.assertEqual(seats[0], "inherit")
            self.assertIn({"providerInstanceId": "claudeAgent", "model": "claude-opus-5-5"}, seats)
            self.assertNotIn({"providerInstanceId": "codex", "model": "gpt-6.1-sol"}, seats)

    def test_panel_with_one_runnable_provider_is_three_inherit_seats(self):
        catalog = {**CATALOG, "providers": [p for p in CATALOG["providers"] if p["providerInstanceId"] == "claudeAgent"]}
        seats = roles.resolve(config(), catalog, ["arena runners"])["roles"]["arena runners"]["seats"]
        self.assertEqual(seats, ["inherit", "inherit", "inherit"])

    def test_without_catalog_panels_are_reported_for_the_agent_to_expand(self):
        entry = roles.resolve(config(), None, ["verifiers"])["roles"]["verifiers"]
        self.assertEqual(entry["seats"], "default-panel")

    def test_unrunnable_provider_falls_back_to_inherit_with_a_note(self):
        entry = roles.resolve(config(**{"swarm workers": [{"providerInstanceId": "cursor", "model": "default"}]}), CATALOG, ["swarm workers"])["roles"]["swarm workers"]
        self.assertEqual(entry["seats"], ["inherit"])
        self.assertIn("not authenticated", entry["notes"][0])

    def test_missing_model_falls_back_to_first_model_of_the_provider(self):
        entry = roles.resolve(config(**{"bug-fix": [{"providerInstanceId": "codex", "model": "gpt-9"}]}), CATALOG, ["bug-fix"])["roles"]["bug-fix"]
        self.assertEqual(entry["seats"], [{"providerInstanceId": "codex", "model": "gpt-6.1-sol"}])
        self.assertIn("gpt-9", entry["notes"][0])

    def test_budget_caps_explicit_effort_and_skips_special_values(self):
        seat = {"providerInstanceId": "codex", "model": "gpt-6.1-sol", "options": {"reasoningEffort": "ultra"}}
        resolved = roles.resolve(config("large", **{"bug-fix": [seat]}), CATALOG, ["bug-fix"])["roles"]["bug-fix"]["seats"][0]
        self.assertEqual(resolved["options"], {"reasoningEffort": "xhigh"})
        claude = {"providerInstanceId": "claudeAgent", "model": "claude-opus-5-5"}
        resolved = roles.resolve(config("unlimited", **{"bug-fix": [claude]}), CATALOG, ["bug-fix"])["roles"]["bug-fix"]["seats"][0]
        self.assertEqual(resolved["options"], {"effort": "max"})

    def test_budget_keeps_a_lower_explicit_choice(self):
        seat = {"providerInstanceId": "grok", "model": "grok-4.7", "options": {"reasoningEffort": "low"}}
        resolved = roles.resolve(config("large", **{"bug-fix": [seat]}), CATALOG, ["bug-fix"])["roles"]["bug-fix"]["seats"][0]
        self.assertEqual(resolved["options"], {"reasoningEffort": "low"})

    def test_budget_leaves_models_without_effort_alone(self):
        seat = {"providerInstanceId": "claudeAgent", "model": "claude-haiku-4-5", "options": {"thinking": True}}
        resolved = roles.resolve(config("small", **{"bug-fix": [seat]}), CATALOG, ["bug-fix"])["roles"]["bug-fix"]["seats"][0]
        self.assertEqual(resolved["options"], {"thinking": True})

    def test_parse_seat(self):
        self.assertEqual(roles.parse_seat("inherit"), "inherit")
        self.assertEqual(roles.parse_seat("codex/gpt-6.1-sol?reasoningEffort=high&fast=true"),
                         {"providerInstanceId": "codex", "model": "gpt-6.1-sol", "options": {"reasoningEffort": "high", "fast": True}})
        with self.assertRaises(roles.RolesError):
            roles.parse_seat("gpt-6.1-sol")

    def test_single_role_rejects_two_seats(self):
        with self.assertRaises(roles.RolesError):
            roles.check_shape({"roles": {"bug-fix": ["inherit", "inherit"]}}, "test")

    def test_project_roles_override_user_roles_per_role(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "user.json").write_text(json.dumps({"budget": "small", "roles": {"bug-fix": ["inherit"], "hillclimb": ["inherit"]}}))
            (base / "project.json").write_text(json.dumps({"roles": {"bug-fix": [{"providerInstanceId": "grok", "model": "grok-4.7"}]}}))
            merged = roles.merged_config(base, base / "user.json", base / "project.json")
        self.assertEqual(merged["budget"], "small")
        self.assertEqual(merged["roles"]["bug-fix"][0]["providerInstanceId"], "grok")
        self.assertEqual(merged["roles"]["hillclimb"], ["inherit"])

    def test_write_refuses_seats_outside_the_catalog_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "roles.json"
            catalog = str(ROOT / "tests/fixtures/catalog.json")
            bad = roles.main(["write", "--config", str(target), "--catalog", catalog, "--set", "bug-fix=cursor/default"])
            self.assertEqual(bad, 2)
            self.assertFalse(target.exists())
            args = ["write", "--config", str(target), "--catalog", catalog, "--budget", "large", "--set", "interrogate reviewers=inherit;codex/gpt-6.1-sol"]
            self.assertEqual(roles.main(args), 0)
            first = target.read_text()
            self.assertEqual(roles.main(args), 0)
            self.assertEqual(target.read_text(), first)
            self.assertEqual(json.loads(first)["roles"]["interrogate reviewers"][1]["model"], "gpt-6.1-sol")


class InstallTest(unittest.TestCase):
    def run_install(self, home, *args):
        env = {**os.environ, "HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config")}
        env.pop("CLAUDE_CONFIG_DIR", None)
        return subprocess.run([sys.executable, str(ROOT / "scripts/install.py"), *args], env=env, capture_output=True, text=True)

    def setUp(self):
        if not (ROOT / "skills/pstack-runtime/SKILL.md").exists():
            subprocess.run([sys.executable, str(ROOT / "scripts/build.py")], check=True)

    def test_install_refuses_conflicts_then_replace_and_uninstall_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            existing = home / ".claude/skills/swarm"
            existing.mkdir(parents=True)
            (existing / "SKILL.md").write_text("mine")
            refused = self.run_install(home)
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("swarm", refused.stderr)
            self.assertFalse((home / ".grok/skills/poteto-mode").exists())
            replaced = self.run_install(home, "--replace")
            self.assertEqual(replaced.returncode, 0, replaced.stderr)
            for harness in (".claude", ".agents", ".grok", ".cursor"):
                self.assertTrue((home / harness / "skills/poteto-mode/SKILL.md").exists(), harness)
            self.assertEqual(self.run_install(home, "doctor").returncode, 0)
            again = self.run_install(home)
            self.assertEqual(again.returncode, 0, again.stderr)
            self.assertIn("already installed", again.stdout)
            self.assertEqual(self.run_install(home, "uninstall").returncode, 0)
            self.assertEqual((existing / "SKILL.md").read_text(), "mine")
            self.assertFalse((home / ".grok/skills/poteto-mode").exists())

    def test_uninstall_dry_run_changes_nothing_and_harness_filter_is_respected(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            self.assertEqual(self.run_install(home, "--harness", "codex,grok").returncode, 0)
            dry = self.run_install(home, "uninstall", "--dry-run")
            self.assertIn("would remove", dry.stdout)
            self.assertTrue((home / ".agents/skills/swarm").is_symlink())
            self.assertEqual(self.run_install(home, "uninstall", "--harness", "codex").returncode, 0)
            self.assertFalse((home / ".agents/skills/swarm").exists())
            self.assertTrue((home / ".grok/skills/swarm").is_symlink())
            self.assertEqual(self.run_install(home, "uninstall").returncode, 0)
            self.assertFalse((home / ".grok/skills/swarm").exists())

    def test_blocked_restore_keeps_its_backup_recorded(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            mine = home / ".grok/skills/swarm"
            mine.mkdir(parents=True)
            (mine / "SKILL.md").write_text("mine")
            self.assertEqual(self.run_install(home, "--harness", "grok", "--replace").returncode, 0)
            (mine).unlink()
            mine.mkdir()
            (mine / "SKILL.md").write_text("squatter")
            self.run_install(home, "uninstall")
            self.assertEqual((mine / "SKILL.md").read_text(), "squatter")
            shutil.rmtree(mine)
            self.run_install(home, "uninstall")
            self.assertEqual((mine / "SKILL.md").read_text(), "mine")

    def test_two_replacements_in_one_second_keep_both_backups(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            target = home / ".grok/skills/swarm"
            target.parent.mkdir(parents=True)
            for text in ("first", "second"):
                if target.is_symlink():
                    target.unlink()
                target.write_text(text)
                self.assertEqual(self.run_install(home, "--harness", "grok", "--replace").returncode, 0)
            backups = sorted(p.read_text() for p in (home / ".config/pstack-t3/backups").rglob("swarm"))
            self.assertEqual(backups, ["first", "second"])

    def test_shared_real_directory_is_linked_once(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            shared = home / "shared"
            shared.mkdir()
            (home / ".grok").mkdir()
            (home / ".cursor").mkdir()
            (home / ".grok/skills").symlink_to(shared)
            (home / ".cursor/skills").symlink_to(shared)
            result = self.run_install(home, "--harness", "grok,cursor")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((shared / "swarm/SKILL.md").exists())


class BuildTest(unittest.TestCase):
    def test_generated_tree_passes_check(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "skills"
            result = subprocess.run([sys.executable, str(ROOT / "scripts/build.py"), "--out", str(out)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(check.check_tree(out), [])
            self.assertTrue((out / "pstack-runtime/scripts/roles.py").exists())
            for skill_md in out.glob("*/SKILL.md"):
                self.assertNotIn("disable-model-invocation", skill_md.read_text().split("---")[1], skill_md)

    def test_check_flags_cursor_leftovers(self):
        with tempfile.TemporaryDirectory() as directory:
            skill = Path(directory) / "demo"
            skill.mkdir()
            (skill / "SKILL.md").write_text("---\nname: demo\ndescription: d\n---\n\nSpawn with `subagent_type: generalPurpose`.\n")
            findings = check.check_tree(directory)
        self.assertTrue(any("subagent_type" in finding for finding in findings))


if __name__ == "__main__":
    unittest.main()
