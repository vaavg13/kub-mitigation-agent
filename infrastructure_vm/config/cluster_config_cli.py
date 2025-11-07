#!/usr/bin/env python3
"""Thin CLI helpers for querying cluster.json and rewriting kubeconfig files."""

import argparse
import json
import sys
from pathlib import Path


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def dig(obj, query: str):
    current = obj
    for part in query.split("."):
        if isinstance(current, list):
            index = int(part)
            current = current[index]
        else:
            current = current.get(part)
    return current


def command_value(args) -> None:
    data = load_config(args.config)
    value = dig(data, args.query)
    if isinstance(value, (dict, list)):
        raise SystemExit("complex value")
    if value is None:
        raise SystemExit("value not found")
    print(value)


def resolve_role(node: dict) -> str:
    role = (node.get("role") or "").lower()
    if role == "server":
        return "server"
    return "worker"


def command_node_names(args) -> None:
    data = load_config(args.config)
    target_role = args.role
    for node in data.get("nodes", []):
        role = resolve_role(node)
        if target_role != "all" and role != target_role:
            continue
        print(node["name"])


def command_server_field(args) -> None:
    data = load_config(args.config)
    for node in data.get("nodes", []):
        if resolve_role(node) == "server":
            if args.field not in node:
                raise SystemExit(f"field '{args.field}' not present on server node")
            print(node[args.field])
            return
    raise SystemExit("server node not found")


def command_worker_names(args) -> None:
    args.role = "worker"
    command_node_names(args)


def command_node_labels(args) -> None:
    data = load_config(args.config)
    for node in data.get("nodes", []):
        name = node["name"]
        labels = node.get("labels") or {}
        for key, value in labels.items():
            print(f"{name}|{key}|{value}")


def command_node_taints(args) -> None:
    data = load_config(args.config)
    for node in data.get("nodes", []):
        name = node["name"]
        for taint in node.get("taints", []):
            key = taint["key"]
            effect = taint["effect"]
            value = taint.get("value", "")
            print(f"{name}|{key}|{value}|{effect}")


def command_rewrite_kubeconfig(args) -> None:
    source_path = Path(args.source)
    destination_path = Path(args.destination)
    content = source_path.read_text(encoding="utf-8")
    replaced = content.replace("https://127.0.0.1:6443", f"https://{args.server_ip}:6443")
    destination_path.write_text(replaced, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    value_parser = subparsers.add_parser("value", help="Return a scalar value at a dotted path")
    value_parser.add_argument("config", help="Path to cluster.json")
    value_parser.add_argument("query", help="Dotted key path (list indices allowed)")
    value_parser.set_defaults(func=command_value)

    node_names_parser = subparsers.add_parser("node-names", help="List node names optionally filtered by role")
    node_names_parser.add_argument("config")
    node_names_parser.add_argument("--role", choices=["all", "server", "worker"], default="all")
    node_names_parser.set_defaults(func=command_node_names)

    server_field_parser = subparsers.add_parser("server-field", help="Return a field from the first server node")
    server_field_parser.add_argument("config")
    server_field_parser.add_argument("field")
    server_field_parser.set_defaults(func=command_server_field)

    worker_names_parser = subparsers.add_parser("worker-names", help="List worker node names")
    worker_names_parser.add_argument("config")
    worker_names_parser.set_defaults(func=command_worker_names)

    node_labels_parser = subparsers.add_parser("node-labels", help="Emit node labels as name|key|value")
    node_labels_parser.add_argument("config")
    node_labels_parser.set_defaults(func=command_node_labels)

    node_taints_parser = subparsers.add_parser("node-taints", help="Emit node taints as name|key|value|effect")
    node_taints_parser.add_argument("config")
    node_taints_parser.set_defaults(func=command_node_taints)

    rewrite_parser = subparsers.add_parser("rewrite-kubeconfig", help="Rewrite server endpoint in kubeconfig")
    rewrite_parser.add_argument("source")
    rewrite_parser.add_argument("server_ip")
    rewrite_parser.add_argument("destination")
    rewrite_parser.set_defaults(func=command_rewrite_kubeconfig)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())

