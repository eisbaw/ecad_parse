"""Graph-shaped query over an ODB++ netlist.

The netlist is a bipartite graph: *nets* ↔ *components*, with edges being
pin-connections. This module exposes that graph and lets you fetch subgraphs
by glob pattern + hop-distance, in a form that is friendly to scripted or
LLM-driven consumers (compact, structured, with explicit pruning of
high-fanout nodes so a power-rail does not drag the whole board into a
two-hop query).

CLI usage::

    ecad-query <odb-root> <pattern> [<pattern>...] [options]

Pattern syntax is ``<type>:<glob>``:

    net:GND       - net named exactly "GND"
    net:3V3*      - all nets matching the glob "3V3*"
    ref:U1        - component U1
    ref:C*        - every component whose refdes starts with C
    pin:U1.5      - resolves to whichever net pin U1.5 is on

Multiple patterns union (OR).

Pruning: when expanding BFS through a *net* with more than ``--prune-fanout``
pins (default 50), the net is recorded as visited but its further neighbours
are not enqueued. This prevents power/ground rails from dominating queries.
Components are never pruned -- you cannot have a million-pin component.
"""

from __future__ import annotations

import argparse
import collections
import fnmatch
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from ._odb import (
    find_odb_root,
    iter_components,
    read_net_dict,
    read_pkg_pins,
    resolve_pin_name,
)


# A node is identified by a (type, id) tuple. Type is "net" or "ref".
Node = tuple[str, str]


@dataclass
class NetlistGraph:
    """Bipartite netlist graph built from an ODB++ tree."""

    net_to_pins: dict[str, list[tuple[str, str]]]      # net  -> [(refdes, pin), ...]
    ref_to_pins: dict[str, list[tuple[str, str]]]      # ref  -> [(pin, net),    ...]
    parts_meta:  dict[str, dict]                       # ref  -> {"side", "props"}

    @classmethod
    def from_odb(cls, odb_root: Path, include_none: bool = False) -> "NetlistGraph":
        nets = read_net_dict(odb_root)
        pkgs = read_pkg_pins(odb_root)
        net_to_pins: dict[str, list] = collections.defaultdict(list)
        ref_to_pins: dict[str, list] = collections.defaultdict(list)
        meta: dict[str, dict] = {}

        for cmp in iter_components(odb_root):
            meta[cmp.refdes] = {"side": cmp.side, "props": cmp.props}
            for pin_idx, net_id in cmp.pins:
                pin_name = resolve_pin_name(pkgs, cmp.pkg_idx, pin_idx)
                net_name = nets.get(net_id, f"<UNK_NET_{net_id}>")
                if not include_none and net_name == "$NONE$":
                    continue
                net_to_pins[net_name].append((cmp.refdes, pin_name))
                ref_to_pins[cmp.refdes].append((pin_name, net_name))

        return cls(dict(net_to_pins), dict(ref_to_pins), meta)

    # ----- queries -------------------------------------------------------

    def match(self, pattern: str) -> list[Node]:
        """Resolve a pattern string into a list of seed nodes."""
        if ":" not in pattern:
            raise ValueError(
                f"pattern must be 'type:glob' (e.g. net:GND, ref:U1*, pin:U1.5); "
                f"got {pattern!r}"
            )
        t, glob = pattern.split(":", 1)
        if t == "net":
            return [("net", n) for n in sorted(self.net_to_pins)
                    if fnmatch.fnmatchcase(n, glob)]
        if t == "ref":
            return [("ref", r) for r in sorted(self.parts_meta)
                    if fnmatch.fnmatchcase(r, glob)]
        if t == "pin":
            m = re.match(r"^([^.]+)\.(.+)$", glob)
            if not m:
                raise ValueError(
                    f"pin pattern must be '<refdes>.<pin>'; got {glob!r}"
                )
            refdes, pin = m.group(1), m.group(2)
            for p, net_name in self.ref_to_pins.get(refdes, []):
                if p == pin:
                    return [("net", net_name)]
            return []
        raise ValueError(
            f"unknown pattern type {t!r}; expected one of net, ref, pin"
        )

    def neighbors(self, node: Node):
        """Yield neighbours of a node. Net→refs and ref→nets."""
        t, key = node
        if t == "net":
            for refdes, _pin in self.net_to_pins.get(key, []):
                yield ("ref", refdes)
        elif t == "ref":
            for _pin, net_name in self.ref_to_pins.get(key, []):
                yield ("net", net_name)

    def fanout(self, node: Node) -> int:
        t, key = node
        if t == "net":
            return len(self.net_to_pins.get(key, []))
        return len(self.ref_to_pins.get(key, []))

    def bfs(self, seeds: list[Node], hops: int, prune_fanout: int):
        """Bipartite BFS up to ``hops`` levels.

        Returns ``(levels, pruned)`` where ``levels`` is a list whose index
        is the hop-distance and entries are the nodes discovered at that
        distance (level 0 = seeds), and ``pruned`` is a list of
        ``(net_name, fanout)`` pairs for nets we visited but refused to
        expand through.
        """
        visited: set[Node] = set(seeds)
        levels: list[list[Node]] = [list(dict.fromkeys(seeds))]  # dedupe, preserve order
        frontier: list[Node] = list(visited)
        pruned: list[tuple[str, int]] = []

        for _h in range(hops):
            next_frontier: list[Node] = []
            for node in frontier:
                # Pruning only applies to nets (components are inherently bounded).
                if node[0] == "net" and prune_fanout > 0:
                    f = self.fanout(node)
                    if f > prune_fanout:
                        pruned.append((node[1], f))
                        continue
                for nbr in self.neighbors(node):
                    if nbr not in visited:
                        visited.add(nbr)
                        next_frontier.append(nbr)
            if not next_frontier:
                break
            levels.append(next_frontier)
            frontier = next_frontier

        return levels, pruned

    def edges_touching(self, nodes: list[Node]):
        """Return (net, refdes, pin, internal) edges touching any node in
        ``nodes``. *Internal* = both endpoints are in ``nodes``; *boundary* =
        one endpoint is outside. Internal edges are listed first so that a
        ``--max-show`` cap surfaces the structurally informative ones.
        """
        reached_refs = {n[1] for n in nodes if n[0] == "ref"}
        reached_nets = {n[1] for n in nodes if n[0] == "net"}
        seen = set()
        internal: list[tuple[str, str, str, bool]] = []
        boundary: list[tuple[str, str, str, bool]] = []
        for n in nodes:
            t, key = n
            if t == "net":
                for refdes, pin in self.net_to_pins.get(key, []):
                    e = (key, refdes, pin)
                    if e in seen:
                        continue
                    seen.add(e)
                    is_internal = refdes in reached_refs
                    (internal if is_internal else boundary).append(e + (is_internal,))
            elif t == "ref":
                for pin, net_name in self.ref_to_pins.get(key, []):
                    e = (net_name, key, pin)
                    if e in seen:
                        continue
                    seen.add(e)
                    is_internal = net_name in reached_nets
                    (internal if is_internal else boundary).append(e + (is_internal,))
        return internal + boundary


# ----- renderers ---------------------------------------------------------


def _node_str(node: Node) -> str:
    """A stable string form of a node, suitable for keys and labels."""
    return f"{node[0]}:{node[1]}"


def render_text(g: NetlistGraph, seeds, levels, pruned, max_show: int,
                internal_only: bool, out):
    out.write(f"# {len(seeds)} seed(s) -> {sum(len(l) for l in levels)} nodes across "
              f"{len(levels)} hop(s), prune_fanout pruned {len(pruned)} net(s)\n\n")
    for hop, nodes in enumerate(levels):
        out.write(f"## hop {hop}  ({len(nodes)} node(s))\n")
        shown = nodes[:max_show] if max_show > 0 else nodes
        for n in shown:
            fan = g.fanout(n)
            out.write(f"  {_node_str(n):40s}  fanout={fan}\n")
        if max_show > 0 and len(nodes) > max_show:
            out.write(f"  ... ({len(nodes) - max_show} more elided; "
                      f"--max-show {max_show} cap)\n")
        out.write("\n")

    if pruned:
        out.write(f"## pruned high-fanout nets ({len(pruned)})\n")
        for net, fan in pruned[:max_show] if max_show > 0 else pruned:
            out.write(f"  net:{net}  fanout={fan}\n")
        out.write("\n")

    # Edges across all reached nodes; internal edges first.
    all_nodes = [n for level in levels for n in level]
    edges = g.edges_touching(all_nodes)
    n_internal = sum(1 for e in edges if e[3])
    n_boundary = len(edges) - n_internal
    if internal_only:
        edges = [e for e in edges if e[3]]
        out.write(f"## edges  ({n_internal} internal; "
                  f"{n_boundary} boundary suppressed by --internal-only)\n")
    else:
        out.write(f"## edges  ({len(edges)} total: {n_internal} internal + "
                  f"{n_boundary} boundary)\n")
    for net, refdes, pin, is_int in (edges[:max_show] if max_show > 0 else edges):
        marker = "  " if is_int else "~ "  # ~ = boundary (one endpoint outside reached set)
        out.write(f"  {marker}net:{net}  <->  ref:{refdes}.{pin}\n")
    if max_show > 0 and len(edges) > max_show:
        out.write(f"  ... ({len(edges) - max_show} more elided)\n")


def render_json(g: NetlistGraph, seeds, levels, pruned, max_show: int, args, out):
    all_nodes = [n for level in levels for n in level]
    edges = g.edges_touching(all_nodes)
    n_internal = sum(1 for e in edges if e[3])
    if args.internal_only:
        edges = [e for e in edges if e[3]]
    edges_shown = edges[:max_show] if max_show > 0 else edges

    payload = {
        "query": {
            "patterns": args.pattern,
            "hops": args.hops,
            "prune_fanout": args.prune_fanout,
            "max_show": args.max_show,
        },
        "stats": {
            "graph_nets":       len(g.net_to_pins),
            "graph_components": len(g.parts_meta),
            "graph_edges":      sum(len(v) for v in g.net_to_pins.values()),
            "seeds":            len(seeds),
            "reached_by_hop":   [len(l) for l in levels],
            "reached_total":    sum(len(l) for l in levels),
            "pruned_nets":      len(pruned),
            "edges_total":      len(edges),
            "edges_internal":   n_internal,
            "edges_boundary":   (0 if args.internal_only else len(edges) - n_internal),
            "edges_shown":      len(edges_shown),
            "internal_only":    args.internal_only,
            "truncated":        len(edges) > len(edges_shown),
        },
        "seeds": [
            {"type": n[0], "id": n[1], "fanout": g.fanout(n)} for n in seeds
        ],
        "levels": [
            {
                "hop": hop,
                "count": len(nodes),
                "nodes": [
                    {"type": n[0], "id": n[1], "fanout": g.fanout(n)}
                    for n in (nodes[:max_show] if max_show > 0 else nodes)
                ],
                "truncated": max_show > 0 and len(nodes) > max_show,
            }
            for hop, nodes in enumerate(levels)
        ],
        "pruned": [
            {"net": net, "fanout": fan} for net, fan in pruned
        ],
        "edges": [
            {"net": net, "refdes": refdes, "pin": pin, "internal": is_int}
            for net, refdes, pin, is_int in edges_shown
        ],
    }
    json.dump(payload, out, indent=2)
    out.write("\n")


# ----- CLI ---------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        epilog=(
            "Examples:\n"
            "  ecad-query <odb> net:GND\n"
            "  ecad-query <odb> ref:U7 --hops 1\n"
            "  ecad-query <odb> 'ref:U*' --format json\n"
            "  ecad-query <odb> pin:U1.5 --hops 2 --prune-fanout 30\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("odb_root", type=Path,
                    help="ODB++ job dir (contains misc/, steps/, ...)")
    ap.add_argument("pattern", nargs="+",
                    help="one or more 'type:glob' patterns "
                         "(type ∈ {net, ref, pin}); multiple patterns union")
    ap.add_argument("--hops", type=int, default=0,
                    help="BFS expansion depth (default: 0 = just the matches)")
    ap.add_argument("--format", choices=["text", "json"], default="text",
                    help="output format (default: text)")
    ap.add_argument("--prune-fanout", type=int, default=50,
                    help="BFS: do not expand through nets with > N pins "
                         "(default: 50; use 0 to disable pruning)")
    ap.add_argument("--max-show", type=int, default=100,
                    help="cap edges/nodes shown per section "
                         "(default: 100; use 0 for unlimited)")
    ap.add_argument("--include-none", action="store_true",
                    help="include the $NONE$ pseudo-net (unconnected pins)")
    ap.add_argument("--internal-only", action="store_true",
                    help="drop boundary edges (one endpoint outside the reached "
                         "set). Output then describes only the topology of the "
                         "induced subgraph -- useful when an LLM needs the "
                         "structure but not the fanout")
    args = ap.parse_args(argv)

    root = find_odb_root(args.odb_root)
    g = NetlistGraph.from_odb(root, include_none=args.include_none)

    seeds: list[Node] = []
    seen_seeds: set[Node] = set()
    for pat in args.pattern:
        for n in g.match(pat):
            if n not in seen_seeds:
                seen_seeds.add(n)
                seeds.append(n)

    if not seeds:
        print(f"ecad-query: no matches for patterns {args.pattern}", file=sys.stderr)
        return 1

    levels, pruned = g.bfs(seeds, args.hops, args.prune_fanout)

    if args.format == "json":
        render_json(g, seeds, levels, pruned, args.max_show, args, sys.stdout)
    else:
        render_text(g, seeds, levels, pruned, args.max_show,
                    args.internal_only, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
