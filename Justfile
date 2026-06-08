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

# Smoke-test all three CLIs against a local ODB tree. SEED defaults to
# net:GND (universally present); override for board-specific patterns,
# e.g. `just smoke /path/to/odb ref:U7`.
smoke ODB SEED='net:GND':
    uv run ecad-netlist {{ODB}}
    uv run ecad-bom {{ODB}} --format csv
    uv run ecad-bom {{ODB}} --format md --out {{ODB}}/../bom.md
    uv run ecad-query {{ODB}} '{{SEED}}' --max-show 5
    uv run ecad-query {{ODB}} '{{SEED}}' --hops 1 --internal-only --max-show 10
    uv run ecad-query {{ODB}} '{{SEED}}' --format json --max-show 0 > /tmp/ecad_query_smoke.json
    @echo "  JSON smoke result -> /tmp/ecad_query_smoke.json"

# Build the nix flake (uv2nix; respects uv.lock for deterministic deps).
nix-build:
    nix build --print-out-paths

# Remove the local venv
clean:
    rm -rf .venv
