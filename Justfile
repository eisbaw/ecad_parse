# ecad_parse - ODB++ netlist & BOM extractors

# Install the package in editable mode into a uv-managed venv
sync:
    uv sync

# Run the netlist extractor (writes by-net + by-refdes + CSV next to ODB root)
netlist ODB_ROOT:
    uv run ecad-netlist {{ODB_ROOT}}

# Run the BOM extractor (default: CSV next to ODB root)
bom ODB_ROOT FORMAT="csv":
    uv run ecad-bom {{ODB_ROOT}} --format {{FORMAT}}

# Smoke-test against a local ODB tree (set ODB to point at your job dir)
smoke ODB:
    uv run ecad-netlist {{ODB}}
    uv run ecad-bom {{ODB}} --format csv
    uv run ecad-bom {{ODB}} --format md --out {{ODB}}/../bom.md

# Remove the local venv
clean:
    rm -rf .venv
