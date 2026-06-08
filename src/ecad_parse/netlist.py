"""Extract a logical netlist from an ODB++ tree.

Produces up to three outputs:
  --by-net      <NET> (N pins) / <refdes>.<pin> [T|B]   (human-friendly)
  --by-refdes   <refdes> [side] VALUE MPN / <pin>  <net>   (component view)
  --csv         net,refdes,pin,side                    (scriptable)

If no --out-* flag is given, all three are written next to the ODB root.
"""

from __future__ import annotations

import argparse
import collections
import csv
import re
import sys
from pathlib import Path

from ._odb import (
    find_odb_root,
    iter_components,
    read_net_dict,
    read_pkg_pins,
    resolve_pin_name,
)


# Sort pins so "1" < "2" < "10" and "A1" < "A2" < "B1"
_PIN_SPLIT = re.compile(r"(\d+)")


def _pin_sort_key(pin: str):
    parts = _PIN_SPLIT.split(pin)
    return tuple((int(p) if p.isdigit() else p) for p in parts)


def build(odb_root: Path):
    """Return (net_conns, parts) where:
    net_conns[net_name] -> list of (refdes, pin_name, side)
    parts[refdes]       -> dict with side, props
    """
    nets = read_net_dict(odb_root)
    pkg_pins = read_pkg_pins(odb_root)
    net_conns: dict[str, list[tuple[str, str, str]]] = collections.defaultdict(list)
    parts: dict[str, dict] = {}
    for cmp in iter_components(odb_root):
        parts[cmp.refdes] = {"side": cmp.side, "props": cmp.props}
        for pin_idx, net_id in cmp.pins:
            pin_name = resolve_pin_name(pkg_pins, cmp.pkg_idx, pin_idx)
            net_name = nets.get(net_id, f"<UNK_NET_{net_id}>")
            net_conns[net_name].append((cmp.refdes, pin_name, cmp.side))
    return net_conns, parts


def write_by_net(out: Path, net_conns, parts, include_none: bool):
    total = sum(len(v) for v in net_conns.values())
    nets_named = sum(1 for n in net_conns if n != "$NONE$")
    with out.open("w") as f:
        f.write(f"# Logical netlist  ({len(parts)} components, {nets_named} nets, {total} pin connections)\n")
        f.write("# Format: <NET>  (N pins)\n#     <refdes>.<pin>  [T|B]\n#\n")
        for net in sorted(net_conns):
            if net == "$NONE$" and not include_none:
                continue
            conns = sorted(net_conns[net], key=lambda x: (x[0], _pin_sort_key(x[1])))
            f.write(f"{net}  ({len(conns)} pins)\n")
            for r, p, s in conns:
                f.write(f"    {r}.{p}  [{s}]\n")


def write_by_refdes(out: Path, net_conns, parts):
    by_ref: dict[str, dict[str, str]] = collections.defaultdict(dict)
    for net, conns in net_conns.items():
        if net == "$NONE$":
            continue
        for r, p, _s in conns:
            by_ref[r][p] = net
    with out.open("w") as f:
        f.write("# refdes -> pin -> net  (joined view; useful for component lookup)\n#\n")
        for r in sorted(by_ref):
            meta = parts.get(r, {})
            props = meta.get("props", {})
            hdr = f"{r}  [{meta.get('side', '?')}]"
            if props.get("VALUE"):
                hdr += f"  VALUE='{props['VALUE']}'"
            if props.get("MPN"):
                hdr += f"  MPN={props['MPN']}"
            f.write(hdr + "\n")
            for p in sorted(by_ref[r], key=_pin_sort_key):
                f.write(f"    {p}  {by_ref[r][p]}\n")


def write_csv(out: Path, net_conns, include_none: bool):
    with out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["net", "refdes", "pin", "side"])
        for net in sorted(net_conns):
            if net == "$NONE$" and not include_none:
                continue
            for r, p, s in sorted(net_conns[net], key=lambda x: (x[0], _pin_sort_key(x[1]))):
                w.writerow([net, r, p, s])


_NETLIST_EPILOG = """\
When to use this command
------------------------
  ecad-netlist    Dump the entire netlist to files. Use when you want the
                  complete connectivity on disk for grep, diff, or feeding
                  downstream tools.
  ecad-bom        Group components into a Bill of Materials by part number.
  ecad-query      Ask narrow graph-shaped questions (e.g. "what is U7
                  connected to within 2 hops?") -- much more efficient than
                  loading the full netlist when you only need a slice.

Default behaviour (no --by-net / --by-refdes / --csv given): writes all
three outputs (netlist.txt, netlist_by_refdes.txt, netlist.csv) next to
the ODB++ root. Pass specific flags to control destinations individually.

Output formats
--------------
  by-net      <NET>  (N pins) header, then "<refdes>.<pin>  [T|B]" lines.
              Human-friendly; good for visual inspection or grep "GND".
  by-refdes   "<refdes>  [side]  VALUE='..' MPN=.." header, then
              "<pin>  <net>" lines. Useful when you have a refdes in hand
              and want to know what each pin connects to.
  csv         RFC-4180 "net,refdes,pin,side" rows. Use for scripted joins,
              spreadsheet import, or diffing two netlists.

Examples
--------
  ecad-netlist <odb-root>                        # write all three next to root
  ecad-netlist <odb-root> --csv out.csv          # only the CSV, custom path
  ecad-netlist <odb-root> --include-none         # keep unconnected pins too
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        epilog=_NETLIST_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("odb_root", type=Path, help="ODB++ job dir (contains misc/, steps/, ...)")
    ap.add_argument("--by-net", type=Path, metavar="PATH",
                    help="output: human-friendly by-net listing")
    ap.add_argument("--by-refdes", type=Path, metavar="PATH",
                    help="output: component-keyed listing")
    ap.add_argument("--csv", type=Path, metavar="PATH",
                    help="output: net,refdes,pin,side CSV")
    ap.add_argument("--include-none", action="store_true",
                    help="include the $NONE$ (unconnected) pseudo-net")
    args = ap.parse_args(argv)

    root = find_odb_root(args.odb_root)

    # Default: write all three next to the ODB root if no --out-* flag given.
    if not (args.by_net or args.by_refdes or args.csv):
        base = root.parent
        args.by_net = base / "netlist.txt"
        args.by_refdes = base / "netlist_by_refdes.txt"
        args.csv = base / "netlist.csv"

    net_conns, parts = build(root)
    if args.by_net:
        write_by_net(args.by_net, net_conns, parts, args.include_none)
        print(f"wrote {args.by_net}", file=sys.stderr)
    if args.by_refdes:
        write_by_refdes(args.by_refdes, net_conns, parts)
        print(f"wrote {args.by_refdes}", file=sys.stderr)
    if args.csv:
        write_csv(args.csv, net_conns, args.include_none)
        print(f"wrote {args.csv}", file=sys.stderr)

    total = sum(len(v) for v in net_conns.values())
    nets_named = sum(1 for n in net_conns if n != "$NONE$")
    print(f"{len(parts)} components, {nets_named} nets, {total} pin connections",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
