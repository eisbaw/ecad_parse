"""Shared ODB++ v8 parser primitives.

Only covers the subset needed by netlist.py and bom.py:
- net dictionary       (steps/cad/netlists/cadnet/netlist)
- package pin lists    (steps/cad/eda/data, PKG ... PIN ...)
- component placements (steps/cad/layers/comp_+_{top,bot}/components)

Reference for the file formats: ODB++ Format Specification, sections on
``netlist``, ``eda/data`` and ``components`` files. The token layout used
below was cross-verified against a Valor-NPI-2504 export.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


# CMP positional layout (before the ';' attribute block):
#   CMP <pkg_idx> <x> <y> <rot> <mirror> <ref_des> <part_name> [...]
_CMP_REFDES_IDX = 6
_CMP_PARTNAME_IDX = 7

# TOP positional layout:
#   TOP <pin_idx> <x> <y> <rot> <mirror> <net_id> <subnet_id> <toeprint>
_TOP_PIN_IDX = 1
_TOP_NETID_IDX = 6

_PRP_RE = re.compile(r"^PRP\s+(\S+)\s+'(.*)'\s*$")
_NETDICT_RE = re.compile(r"^\$(\d+)\s+(\S.*)$")


@dataclass
class Component:
    """One placed component (a CMP record + its TOP children)."""

    refdes: str
    part_name: str
    side: str  # "T" or "B"
    pkg_idx: int
    props: dict[str, str] = field(default_factory=dict)
    # list of (pin_index_into_pkg, net_id) — pin name needs PKG lookup
    pins: list[tuple[int, int]] = field(default_factory=list)


def read_net_dict(odb_root: Path) -> dict[int, str]:
    """Return {net_id: net_name} from steps/cad/netlists/cadnet/netlist."""
    path = odb_root / "steps" / "cad" / "netlists" / "cadnet" / "netlist"
    nets: dict[int, str] = {}
    with path.open() as f:
        for ln in f:
            m = _NETDICT_RE.match(ln)
            if m:
                nets[int(m.group(1))] = m.group(2).strip()
    return nets


def read_pkg_pins(odb_root: Path) -> list[list[str]]:
    """Return pkg_pins[pkg_idx] = [pin_name_0, pin_name_1, ...].

    PKG blocks in steps/cad/eda/data appear in encounter order, which matches
    the PKG index space referenced by CMP records in components/.
    """
    path = odb_root / "steps" / "cad" / "eda" / "data"
    pkgs: list[list[str]] = []
    cur: list[str] | None = None
    with path.open() as f:
        for ln in f:
            if ln.startswith("PKG "):
                cur = []
                pkgs.append(cur)
            elif ln.startswith("PIN ") and cur is not None:
                # PIN <name> S x y rot mirror ... ID=...
                cur.append(ln.split()[1])
    return pkgs


def iter_components(odb_root: Path):
    """Yield Component objects from both comp_+_top and comp_+_bot.

    A single pass over each file; CMP record state is reset at every CMP.
    Yields exactly one Component per CMP, after its trailing PRP/TOP block
    has been fully consumed.
    """
    for layer, side in [("comp_+_top", "T"), ("comp_+_bot", "B")]:
        path = odb_root / "steps" / "cad" / "layers" / layer / "components"
        if not path.exists():
            continue
        cur: Component | None = None
        with path.open() as f:
            for ln in f:
                if ln.startswith("CMP "):
                    if cur is not None:
                        yield cur
                    head = ln.split(";", 1)[0].split()
                    cur = Component(
                        refdes=head[_CMP_REFDES_IDX],
                        part_name=head[_CMP_PARTNAME_IDX],
                        side=side,
                        pkg_idx=int(head[1]),
                    )
                elif cur is not None and ln.startswith("PRP "):
                    m = _PRP_RE.match(ln.rstrip())
                    if m:
                        cur.props[m.group(1)] = m.group(2)
                elif cur is not None and ln.startswith("TOP "):
                    t = ln.split()
                    cur.pins.append((int(t[_TOP_PIN_IDX]), int(t[_TOP_NETID_IDX])))
        if cur is not None:
            yield cur


def resolve_pin_name(pkg_pins: list[list[str]], pkg_idx: int, pin_idx: int) -> str:
    """Translate (pkg_idx, ODB++ 0-based pin index) into the schematic pin name.

    Falls back to ``#<idx>`` if the package or index is out of range, so
    callers can spot misaligned indices instead of silently dropping data.
    """
    if 0 <= pkg_idx < len(pkg_pins) and 0 <= pin_idx < len(pkg_pins[pkg_idx]):
        return pkg_pins[pkg_idx][pin_idx]
    return f"#{pin_idx}"


def find_odb_root(path: Path) -> Path:
    """Accept either the ODB root itself or its parent. Validates by checking
    for ``misc/info`` (mandatory in any ODB++ job)."""
    path = path.resolve()
    candidates = [path] + (
        [p for p in path.iterdir() if p.is_dir()] if path.is_dir() else []
    )
    for c in candidates:
        if (c / "misc" / "info").is_file():
            return c
    raise FileNotFoundError(
        f"no ODB++ root found at or under {path} (expected misc/info)"
    )
