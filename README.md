# ecad_parse

Tiny pure-stdlib Python library for pulling **netlists** and **BOMs** out of
an **ODB++ v8** manufacturing tree (as exported by Valor NPI from Cadence
Allegro and shipped inside typical PLM fab-release zips).

> Naming caveat — these parsers consume ODB++ specifically, not raw schematic
> sources (`pstxnet.dat` / `pstxprt.dat`). If you ever extend it to read those
> the name still fits; if you don't, `odb_tools/` would be more precise.

## What it does *not* do

- It does **not** parse the schematic — only the fab/manufacturing output.
  Anything DRC-stripped before fab won't appear.
- It does **not** verify ODB++ format conformance; it expects a well-formed
  Valor-NPI-shaped tree. Other exporters may need small adjustments.

## Input

An ODB++ job directory — the thing that lives inside `<board>.tgz` after
unwrapping the typical PLM bundle:

```
<plm-id>.zip
└── PCB*_ODB_*.zip
    └── <board>.tgz
        └── <jobname>/         <-- pass this dir to the CLIs
            ├── misc/info
            ├── steps/cad/eda/data
            ├── steps/cad/netlists/cadnet/netlist
            ├── steps/cad/layers/comp_+_top/components
            ├── steps/cad/layers/comp_+_bot/components
            └── symbols/ ...
```

The CLI accepts either the `<jobname>` dir directly or its parent.

## Install / run

Pure stdlib — no dependencies. Two ways to invoke:

```bash
# A) uv (preferred, hermetic venv driven by pyproject.toml)
uv sync
uv run ecad-netlist <odb-root>
uv run ecad-bom     <odb-root> --format md

# B) bare python (no install)
PYTHONPATH=src python -m ecad_parse.netlist <odb-root>
PYTHONPATH=src python -m ecad_parse.bom     <odb-root>
```

Inside the flake's dev-shell `uv` is already on `$PATH`:

```bash
nix develop
uv sync
just smoke <odb-root>
```

## Output

### `ecad-netlist`

Three files are written next to the ODB root by default
(`netlist.txt`, `netlist_by_refdes.txt`, `netlist.csv`). Override any of
them with `--by-net PATH` / `--by-refdes PATH` / `--csv PATH`. Pass
`--include-none` to keep the `$NONE$` (unconnected) pseudo-net.

CSV columns: `net, refdes, pin, side`. Pin names are the real schematic
names (joined from `eda/data` PKG/PIN definitions), not raw ODB++ 0-based
pin indices.

### `ecad-bom`

One BOM file grouped by a configurable part-number property
(`--pn-key`, default `MPN`). Components without that property —
typically `MEC*` mechanicals / fiducials — collapse into a single
`<none>` group so they don't silently disappear. Formats:

- `--format csv` (default) — columns: `mpn, qty, value, package,
  part_name, parent_ppt_part, height, link, refdeses`
- `--format md` — markdown table, truncates long refdes lists at 100 chars
- `--format txt` — human-friendly, full refdes list per line

ODB++ exporters disagree on the property name for the part number. If
your exporter writes something other than `MPN` (some write
`MFR_PN`, `PART_NUMBER`, or custom names), pass `--pn-key <YOUR_KEY>`.

## Data model

`_odb.py` exposes three primitives reused by both CLIs:

- `read_net_dict(odb_root)` → `{net_id: net_name}` from
  `steps/cad/netlists/cadnet/netlist`
- `read_pkg_pins(odb_root)` → `pkg_pins[pkg_idx] = [pin_name, ...]` from the
  PKG/PIN blocks in `steps/cad/eda/data`
- `iter_components(odb_root)` → yields `Component(refdes, part_name, side,
  pkg_idx, props, pins=[(pin_idx, net_id), ...])` from both
  `comp_+_top/components` and `comp_+_bot/components`

`resolve_pin_name(pkg_pins, pkg_idx, pin_idx)` translates an ODB++ 0-based
pin index into the schematic pin name. Out-of-range falls back to
`#<idx>` so callers can spot misaligned indices.

## Known limitations

- ODB++ schema version pinned to v8 (verified against Valor NPI 2504).
  Earlier exports may differ.
- The `eda/data` PKG list is assumed to be in encounter order and to share
  index space with CMP records' `pkg_idx`. True for every Valor export
  inspected so far; if it ever breaks, the symptom will be wrong pin
  names with otherwise-correct net assignments.
- Only `comp_+_top` / `comp_+_bot` are walked. Some flows place
  through-hole components on a third layer — extend `iter_components`
  if that comes up.
