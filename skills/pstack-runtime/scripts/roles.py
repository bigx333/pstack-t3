#!/usr/bin/env python3
"""Resolve pstack-t3 roles into T3 delegate_task targets.

Roles map a pstack role name to a list of seats. A seat is "inherit" or a
target {"providerInstanceId", "model", "options"} drawn from the catalog that
T3's orchestrator_capabilities tool returns.
"""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

SINGLE_ROLES = [
    "feature, refactoring",
    "bug-fix",
    "perf-issue",
    "hillclimb",
    "judgment and prose",
    "hardest tasks",
    "how explorer",
    "how explainer",
    "why investigators",
    "why synthesizer",
    "reflect tooling",
    "reflect judgment, divergent, synthesizer",
    "swarm workers",
]
PANEL_ROLES = [
    "arena runners",
    "arena cross-judge pool",
    "architect runners",
    "interrogate reviewers",
    "verifiers",
]
ROLES = SINGLE_ROLES + PANEL_ROLES
BUDGETS = {"default": None, "small": "medium", "medium": "high", "large": "xhigh", "unlimited": "max-available"}
EFFORT_IDS = ("effort", "reasoningEffort", "reasoning")
LADDER = ["low", "medium", "high", "xhigh", "max", "ultra"]
SPECIAL = {"ultracode", "ultrathink"}
INHERIT = "inherit"


class RolesError(Exception):
    pass


def user_config_path():
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "pstack-t3" / "roles.json"


def snapshot_path():
    return user_config_path().with_name("catalog.json")


def project_config_path(cwd):
    current = Path(cwd).resolve()
    for directory in [current, *current.parents]:
        candidate = directory / ".pstack" / "t3-roles.json"
        if candidate.is_file():
            return candidate
        if (directory / ".git").exists():
            return directory / ".pstack" / "t3-roles.json"
    return current / ".pstack" / "t3-roles.json"


def load_json(path):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as error:
        raise RolesError(f"{path}: invalid JSON: {error}") from error


def load_catalog(path):
    data = json.load(sys.stdin) if str(path) == "-" else load_json(path)
    if data is None:
        raise RolesError(f"{path}: catalog not found")
    if "providers" not in data:
        raise RolesError(f"{path}: not an orchestrator_capabilities result (no providers)")
    return data


def parse_seat(text):
    """Parse `inherit` or `provider/model[?option=value&option=value]`."""
    text = text.strip()
    if text == INHERIT:
        return INHERIT
    head, _, query = text.partition("?")
    provider, slash, model = head.partition("/")
    if not slash or not provider or not model:
        raise RolesError(f"seat {text!r}: expected 'inherit' or 'provider/model[?option=value]'")
    options = {}
    for pair in filter(None, query.split("&")):
        key, equals, value = pair.partition("=")
        if not equals:
            raise RolesError(f"seat {text!r}: option {pair!r} needs a value")
        options[key] = {"true": True, "false": False}.get(value, value)
    seat = {"providerInstanceId": provider, "model": model}
    if options:
        seat["options"] = options
    return seat


def check_shape(config, origin):
    if not isinstance(config, dict):
        raise RolesError(f"{origin}: expected an object")
    budget = config.get("budget", "default")
    if budget not in BUDGETS:
        raise RolesError(f"{origin}: budget {budget!r} is not one of {', '.join(BUDGETS)}")
    roles = config.get("roles", {})
    if not isinstance(roles, dict):
        raise RolesError(f"{origin}: roles must be an object")
    for name, seats in roles.items():
        if name not in ROLES:
            raise RolesError(f"{origin}: unknown role {name!r}")
        if not isinstance(seats, list) or not seats:
            raise RolesError(f"{origin}: role {name!r} needs a non-empty list of seats")
        if name in SINGLE_ROLES and len(seats) != 1:
            raise RolesError(f"{origin}: role {name!r} takes exactly one seat")
        for seat in seats:
            if seat == INHERIT:
                continue
            if not isinstance(seat, dict) or not seat.get("providerInstanceId") or not seat.get("model"):
                raise RolesError(f"{origin}: role {name!r} has a seat without providerInstanceId and model")
    return config


def merged_config(cwd, user_path=None, project_path=None):
    user_path = Path(user_path) if user_path else user_config_path()
    project_path = Path(project_path) if project_path else project_config_path(cwd)
    user = check_shape(load_json(user_path) or {}, user_path)
    project = check_shape(load_json(project_path) or {}, project_path)
    roles, sources = {}, {}
    for origin, config in ((user_path, user), (project_path, project)):
        for name, seats in config.get("roles", {}).items():
            roles[name] = seats
            sources[name] = str(origin)
    budget = project.get("budget") or user.get("budget") or "default"
    return {"budget": budget, "roles": roles, "sources": sources}


def providers_by_id(catalog):
    return {provider["providerInstanceId"]: provider for provider in catalog["providers"]}


def runnable(provider):
    return bool(provider and provider.get("canRunChildTask") and provider.get("models"))


def find_model(provider, model_id):
    return next((model for model in provider.get("models", []) if model["id"] == model_id), None)


def effort_option(model):
    return next((option for option in model.get("options", []) if option["id"] in EFFORT_IDS and option.get("type") == "select"), None)


def apply_budget(seat, model, budget):
    cap = BUDGETS[budget]
    option = effort_option(model) if model else None
    if cap is None or option is None:
        return seat
    values = [choice["id"] for choice in option["options"] if choice["id"] not in SPECIAL and choice["id"] in LADDER]
    if not values:
        return seat
    ceiling = max(values, key=LADDER.index) if cap == "max-available" else cap
    allowed = [value for value in values if LADDER.index(value) <= LADDER.index(ceiling)]
    if not allowed:
        allowed = [min(values, key=LADDER.index)]
    current = (seat.get("options") or {}).get(option["id"])
    chosen = current if current in allowed else max(allowed, key=LADDER.index)
    return {**seat, "options": {**(seat.get("options") or {}), option["id"]: chosen}}


def default_seats(name, catalog):
    if name in SINGLE_ROLES:
        return [INHERIT]
    parent = catalog.get("inheritedProviderInstanceId")
    seats = []
    for provider in catalog["providers"]:
        if not runnable(provider):
            continue
        if provider["providerInstanceId"] == parent:
            seats.append(INHERIT)
        else:
            seats.append({"providerInstanceId": provider["providerInstanceId"], "model": provider["models"][0]["id"]})
    if len(seats) <= 1:
        return [INHERIT, INHERIT, INHERIT]
    return seats


def resolve_seat(seat, catalog, budget):
    """Return (resolved seat, note or None)."""
    if seat == INHERIT:
        return INHERIT, None
    providers = providers_by_id(catalog)
    provider = providers.get(seat["providerInstanceId"])
    if not runnable(provider):
        reason = "; ".join(provider.get("constraints", [])) if provider else "not in catalog"
        return INHERIT, f"{seat['providerInstanceId']} is not runnable ({reason}); seat inherits the parent"
    model = find_model(provider, seat["model"])
    note = None
    if model is None:
        model = provider["models"][0]
        note = f"{seat['providerInstanceId']}/{seat['model']} is not in the catalog; using {model['id']}"
        seat = {"providerInstanceId": provider["providerInstanceId"], "model": model["id"]}
    known = {option["id"] for option in model.get("options", [])}
    options = {key: value for key, value in (seat.get("options") or {}).items() if key in known}
    dropped = sorted(set(seat.get("options") or {}) - known)
    if dropped:
        note = (note + "; " if note else "") + f"dropped unknown options {', '.join(dropped)}"
    seat = {key: value for key, value in seat.items() if key != "options"}
    if options:
        seat["options"] = options
    return apply_budget(seat, model, budget), note


def resolve(config, catalog=None, names=None):
    names = names or ROLES
    result = {"budget": config["budget"], "catalog": bool(catalog), "roles": {}}
    for name in names:
        if name not in ROLES:
            raise RolesError(f"unknown role {name!r}")
        configured = config["roles"].get(name)
        source = config["sources"].get(name, "default")
        entry = {"source": source}
        if configured is None and catalog is None:
            entry["seats"] = [INHERIT] if name in SINGLE_ROLES else "default-panel"
            if name in PANEL_ROLES:
                entry["note"] = "one seat per runnable provider from orchestrator_capabilities, first listed model; parent provider seat inherits"
        else:
            seats = configured if configured is not None else default_seats(name, catalog)
            if catalog is None:
                entry["seats"] = seats
            else:
                resolved, notes = [], []
                for seat in seats:
                    value, note = resolve_seat(seat, catalog, config["budget"])
                    resolved.append(value)
                    if note:
                        notes.append(note)
                entry["seats"] = resolved
                if notes:
                    entry["notes"] = notes
        result["roles"][name] = entry
    return result


def write_atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, suffix=".tmp") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    os.replace(handle.name, path)


def validate(config, catalog):
    problems = []
    for name, seats in config["roles"].items():
        for seat in seats:
            _, note = resolve_seat(seat, catalog, config["budget"])
            if note:
                problems.append(f"{name}: {note}")
    return problems


def command_show(args):
    config = merged_config(args.cwd, args.config, args.project_config)
    catalog_path = args.catalog or (snapshot_path() if snapshot_path().is_file() else None)
    catalog = load_catalog(catalog_path) if catalog_path else None
    print(json.dumps(resolve(config, catalog, [args.role] if args.role else None), indent=2))


def command_validate(args):
    config = merged_config(args.cwd, args.config, args.project_config)
    problems = validate(config, load_catalog(args.catalog))
    for problem in problems:
        print(problem)
    if not problems:
        print("ok")
    return 1 if problems else 0


def command_write(args):
    catalog = load_catalog(args.catalog)
    target = project_config_path(args.cwd) if args.project else (Path(args.config) if args.config else user_config_path())
    existing = check_shape(load_json(target) or {}, target) if args.keep else {}
    roles = dict(existing.get("roles", {}))
    for assignment in args.set or []:
        name, equals, value = assignment.partition("=")
        name = name.strip()
        if not equals or name not in ROLES:
            raise RolesError(f"--set {assignment!r}: expected '<role>=<seat>[;<seat>...]' with a known role")
        roles[name] = [parse_seat(part) for part in value.split(";") if part.strip()]
    config = check_shape({"version": 1, "budget": args.budget or existing.get("budget", "default"), "roles": roles}, target)
    problems = validate({"budget": config["budget"], "roles": roles, "sources": {}}, catalog)
    if problems and not args.force:
        raise RolesError("refusing to write; these seats do not match the catalog:\n" + "\n".join(problems))
    write_atomic(target, config)
    if not args.project and not args.config:
        write_atomic(snapshot_path(), catalog)
    print(f"wrote {target}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("show", "validate", "write"):
        command = sub.add_parser(name)
        command.add_argument("--cwd", default=os.getcwd())
        command.add_argument("--config", help="user roles file (default ~/.config/pstack-t3/roles.json)")
        if name != "write":
            command.add_argument("--project-config", help="project roles file (default <repo>/.pstack/t3-roles.json)")
        command.add_argument("--catalog", required=name != "show", help="saved orchestrator_capabilities JSON, or - for stdin")
    sub.choices["show"].add_argument("--role")
    write = sub.choices["write"]
    write.add_argument("--budget", choices=list(BUDGETS))
    write.add_argument("--set", action="append", help="'<role>=<seat>[;<seat>]', seat = inherit | provider/model[?option=value]")
    write.add_argument("--project", action="store_true", help="write the project file instead of the user file")
    write.add_argument("--keep", action="store_true", help="keep roles already in the target file")
    write.add_argument("--force", action="store_true", help="write even if seats do not match the catalog")
    args = parser.parse_args(argv)
    try:
        return {"show": command_show, "validate": command_validate, "write": command_write}[args.command](args) or 0
    except RolesError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
