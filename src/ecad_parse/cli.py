"""Unified `ecad` dispatcher.

Thin shim that exposes a single binary with three subcommands:

    ecad netlist <odb-root> [...]
    ecad bom     <odb-root> [...]
    ecad query   <odb-root> <pattern> [...]

Per-subcommand argument parsing lives in the existing per-module main()
functions; this dispatcher only routes argv and prints top-level help.

The standalone `ecad-netlist` / `ecad-bom` / `ecad-query` entry points
remain available for backwards compatibility — they are the same
functions this dispatcher calls into.
"""

from __future__ import annotations

import sys

from . import bom, netlist, query

_SUBCOMMANDS = {
    "netlist": netlist.main,
    "bom":     bom.main,
    "query":   query.main,
}

_USAGE = """\
usage: ecad <command> [<args>]

Extract netlists, BOMs, and graph-shaped queries from an ODB++ v8 tree
(as exported by Valor NPI from Cadence Allegro).

Commands:
  netlist   Dump the full netlist (by-net / by-refdes / CSV) to disk.
  bom       Group components into a Bill of Materials by part number.
  query     Graph-shaped queries (net:NAME, ref:REFDES --hops N) for
            slicing the netlist without loading it all.

Run 'ecad <command> --help' for command-specific options.
"""


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if argv and argv[0] in ("-h", "--help"):
        sys.stdout.write(_USAGE)
        return 0

    if not argv:
        sys.stderr.write(_USAGE)
        return 2

    cmd, *rest = argv
    if cmd not in _SUBCOMMANDS:
        sys.stderr.write(f"ecad: unknown command: {cmd!r}\n\n")
        sys.stderr.write(_USAGE)
        return 2

    # Make per-subcommand argparse show "usage: ecad <cmd> ..." instead of
    # "usage: ecad ..." — argparse derives prog from sys.argv[0].
    sys.argv[0] = f"ecad {cmd}"
    return _SUBCOMMANDS[cmd](rest)


if __name__ == "__main__":
    sys.exit(main())
