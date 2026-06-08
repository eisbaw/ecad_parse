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
      in {
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
