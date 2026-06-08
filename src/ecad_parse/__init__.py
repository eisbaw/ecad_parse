"""ecad_parse - ODB++ netlist and BOM extractors.

Pure-stdlib parsers for the ODB++ v8 directory tree exported by Valor NPI
(and similar) from Cadence Allegro. Consumes the inner ODB++ tree that
typically ships inside a PLM-released fab-package zip:

    <plm-id>.zip                            # top PLM package
      PCB*_ODB_*.zip                        # ODB wrapper
        <board>.tgz                         # ODB tarball
          <jobname>/                        # <-- ODB++ root (input to this lib)
            misc/ steps/ symbols/ ...

The library exposes two CLIs:
    ecad-netlist <odb-root>   - by-net + by-refdes + CSV
    ecad-bom     <odb-root>   - BOM grouped by manufacturer part number
"""

__version__ = "0.1.0"
