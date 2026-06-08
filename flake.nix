{
  description = "ecad_parse - ODB++ netlist & BOM extractors";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        ecad-parse = import ./default.nix { inherit pkgs; };
      in {
        # Build outputs: one source of truth (default.nix) for both traditional
        # nix-build and flake consumers.
        packages.default = ecad-parse;
        packages.ecad-parse = ecad-parse;

        # `nix run` shortcuts -- default goes to ecad-query (the most
        # discoverable / AI-friendly entry point).
        apps.default = { type = "app"; program = "${ecad-parse}/bin/ecad-query"; };
        apps.netlist = { type = "app"; program = "${ecad-parse}/bin/ecad-netlist"; };
        apps.bom     = { type = "app"; program = "${ecad-parse}/bin/ecad-bom"; };
        apps.query   = { type = "app"; program = "${ecad-parse}/bin/ecad-query"; };

        # Dev shell still uses uv for iterative work; built package above is
        # for distribution / consumption.
        devShells.default = pkgs.mkShell {
          packages = [
            pkgs.uv
            pkgs.python313
            pkgs.just
          ];
          shellHook = ''
            export UV_PYTHON_DOWNLOADS=never
            export UV_PYTHON=${pkgs.python313}/bin/python
          '';
        };
      });
}
