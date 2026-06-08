"""Extract a BOM from an ODB++ tree.

Groups CMP placements by a configurable part-number property (``--pn-key``,
defaulting to ``MPN`` — manufacturer part number); components without that
property — typically ``MEC*`` mechanicals, fiducials — collapse into a
``<none>`` group so they don't silently disappear from the BOM.

Each BOM row has:
    mpn, qty, value, package, parent_ppt_part, refdeses

Refdeses are concatenated with ``;`` and sorted natural (R1 < R2 < R10).

ODB++ exporters disagree on the property name for the part number. ``MPN``
is the industry-common default; use ``--pn-key <YOUR_KEY>`` to point at a
different property without editing the source.
"""

from __future__ import annotations

import argparse
import collections
import csv
import re
import sys
from pathlib import Path

from ._odb import find_odb_root, iter_components


_REFDES_SPLIT = re.compile(r"(\d+)")


def _refdes_sort_key(refdes: str):
    parts = _REFDES_SPLIT.split(refdes)
    return tuple((int(p) if p.isdigit() else p) for p in parts)


def build(odb_root: Path, pn_key: str = "MPN"):
    """Group components into BOM rows keyed by ``pn_key``.

    Returns a list of dicts, sorted by qty descending then part number.
    """
    groups: dict[tuple, list[str]] = collections.defaultdict(list)
    meta_by_key: dict[tuple, dict] = {}

    for cmp in iter_components(odb_root):
        props = cmp.props
        key = (
            props.get(pn_key, "<none>"),
            props.get("VALUE", ""),
            props.get("PARENT_PART_TYPE", ""),
            props.get("PARENT_PPT_PART", ""),
        )
        groups[key].append(cmp.refdes)
        if key not in meta_by_key:
            meta_by_key[key] = {
                "part_name": props.get("PART_NAME", cmp.part_name),
                "height": props.get("HEIGHT", ""),
                "link": props.get("LINK", ""),
            }

    rows = []
    for (mpn, value, package, ppt_part), refdeses in groups.items():
        meta = meta_by_key[(mpn, value, package, ppt_part)]
        rows.append({
            "mpn": mpn,
            "qty": len(refdeses),
            "value": value,
            "package": package,
            "parent_ppt_part": ppt_part,
            "part_name": meta["part_name"],
            "height": meta["height"],
            "link": meta["link"],
            "refdeses": ";".join(sorted(refdeses, key=_refdes_sort_key)),
        })

    rows.sort(key=lambda r: (-r["qty"], r["mpn"]))
    return rows


_FIELD_ORDER = [
    "mpn", "qty", "value", "package", "part_name",
    "parent_ppt_part", "height", "link", "refdeses",
]


def write_csv(out: Path, rows):
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_FIELD_ORDER)
        w.writeheader()
        w.writerows(rows)


def write_md(out: Path, rows):
    cols = ["mpn", "qty", "value", "package", "refdeses"]
    with out.open("w") as f:
        f.write("| " + " | ".join(cols) + " |\n")
        f.write("|" + "|".join("---" for _ in cols) + "|\n")
        for r in rows:
            refs = r["refdeses"]
            if len(refs) > 100:
                refs = refs[:97] + "..."
            f.write("| " + " | ".join(str(r[c]) if c != "refdeses" else refs
                                     for c in cols) + " |\n")


def write_txt(out: Path, rows):
    with out.open("w") as f:
        total_qty = sum(r["qty"] for r in rows)
        f.write(f"# BOM ({len(rows)} unique lines, {total_qty} placements)\n#\n")
        for r in rows:
            f.write(f"{r['mpn']:14s}  qty={r['qty']:4d}  "
                    f"value={r['value'] or '-':10s}  pkg={r['package'] or '-':16s}  "
                    f"part={r['parent_ppt_part'] or r['part_name']}\n")
            f.write(f"    refdeses: {r['refdeses']}\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("odb_root", type=Path, help="ODB++ job dir (contains misc/, steps/, ...)")
    ap.add_argument("--out", type=Path, metavar="PATH",
                    help="output file (default: bom.<fmt> next to ODB root)")
    ap.add_argument("--format", choices=["csv", "md", "txt"], default="csv",
                    help="output format (default: csv)")
    ap.add_argument("--pn-key", default="MPN", metavar="PROP",
                    help="ODB++ property name to use as the part number key "
                         "(default: MPN)")
    args = ap.parse_args(argv)

    root = find_odb_root(args.odb_root)
    out = args.out or (root.parent / f"bom.{args.format}")

    rows = build(root, pn_key=args.pn_key)
    writer = {"csv": write_csv, "md": write_md, "txt": write_txt}[args.format]
    writer(out, rows)

    total_qty = sum(r["qty"] for r in rows)
    no_pn = sum(r["qty"] for r in rows if r["mpn"] == "<none>")
    print(f"wrote {out}", file=sys.stderr)
    print(f"{len(rows)} unique BOM lines, {total_qty} placements"
          f" ({no_pn} without {args.pn_key})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
