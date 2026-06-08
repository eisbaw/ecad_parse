# default.nix
# -----------
# Standalone build of ecad_parse. Works two ways:
#
#   1) Traditional nix:    nix-build           # -> ./result/bin/ecad-{netlist,bom,query}
#                          nix-shell -p '(import ./. {})'
#
#   2) Imported into a flake (sibling flake.nix already does this internally):
#
#        outputs = { self, nixpkgs, ecad-parse, ... }: let
#          pkgs = nixpkgs.legacyPackages.x86_64-linux;
#          tool = import "${ecad-parse}/default.nix" { inherit pkgs; };
#        in {
#          packages.x86_64-linux.default = tool;
#        };
#
# Pure stdlib at runtime; no Python dependencies, just the interpreter.
{ pkgs ? import <nixpkgs> { } }:

let
  py = pkgs.python3Packages;
in
py.buildPythonApplication {
  pname = "ecad-parse";
  version = "0.1.0";

  # Filter out build/venv detritus so cache keys stay stable across iterations.
  src = pkgs.lib.cleanSourceWith {
    src = ./.;
    filter = path: type:
      let name = baseNameOf path; in
      !(builtins.elem name [
        ".venv" ".git" "result" "dist" "__pycache__" ".uv-cache"
      ]) && (pkgs.lib.cleanSourceFilter path type);
  };

  pyproject = true;
  build-system = [ py.hatchling ];

  # No runtime deps. Smoke test that the entry points import.
  doCheck = true;
  checkPhase = ''
    runHook preCheck
    $out/bin/ecad-netlist --help >/dev/null
    $out/bin/ecad-bom     --help >/dev/null
    $out/bin/ecad-query   --help >/dev/null
    runHook postCheck
  '';

  meta = with pkgs.lib; {
    description = "ODB++ netlist / BOM / graph-query extractors";
    homepage = "https://github.com/eisbaw/ecad_parse";
    license = licenses.mit;
    mainProgram = "ecad-query";
    platforms = platforms.all;
  };
}
