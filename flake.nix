{
  description = "ecad_parse - ODB++ netlist & BOM extractors (uv-locked build)";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";

    # uv2nix + supporting libs: turns uv.lock into a deterministic
    # python package set so the nix-built artifact matches what
    # `uv sync` produces in the dev shell.
    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.uv2nix.follows = "uv2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nixpkgs, flake-utils, pyproject-nix, uv2nix,
              pyproject-build-systems, ... }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        lib = nixpkgs.lib;
        python = pkgs.python313;

        # Load the uv workspace (pyproject.toml + uv.lock).
        workspace = uv2nix.lib.workspace.loadWorkspace {
          workspaceRoot = ./.;
        };

        # Overlay capturing every resolved dependency from uv.lock. Choose
        # "wheel" so binary deps don't recompile from sdist; for pure-python
        # projects this is a wash.
        overlay = workspace.mkPyprojectOverlay {
          sourcePreference = "wheel";
        };

        # Compose nixpkgs' python infra + standard build-system shims +
        # our locked workspace overlay into one cohesive package set.
        pythonSet = (pkgs.callPackage pyproject-nix.build.packages {
          inherit python;
        }).overrideScope (lib.composeManyExtensions [
          pyproject-build-systems.overlays.default
          overlay
        ]);

        # The artifact: a virtualenv containing ecad-parse + (no) runtime
        # deps, exactly as uv would have installed them.
        ecad-parse = pythonSet.mkVirtualEnv "ecad-parse-env"
          workspace.deps.default;
      in {
        # Build outputs
        packages.default = ecad-parse;
        packages.ecad-parse = ecad-parse;

        # `nix run` shortcuts. `apps.default` is the unified `ecad`
        # dispatcher; the per-subcommand apps remain as direct entry
        # points for backwards compatibility.
        apps.default = { type = "app"; program = "${ecad-parse}/bin/ecad"; };
        apps.ecad    = { type = "app"; program = "${ecad-parse}/bin/ecad"; };
        apps.netlist = { type = "app"; program = "${ecad-parse}/bin/ecad-netlist"; };
        apps.bom     = { type = "app"; program = "${ecad-parse}/bin/ecad-bom"; };
        apps.query   = { type = "app"; program = "${ecad-parse}/bin/ecad-query"; };

        # Dev shell: still uv for iterative work.
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
