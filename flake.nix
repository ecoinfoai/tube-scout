{
  description = "tube-scout – YouTube lecture video analytics CLI";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        python = pkgs.python311;
      in
      {
        devShells.default = pkgs.mkShell {
          packages = [
            python
            pkgs.uv
            pkgs.ruff
          ];

          env = {
            UV_PYTHON = "${python}/bin/python";
          };

          shellHook = ''
            if [ ! -d .venv ]; then
              uv venv --python ${python}/bin/python
            fi
            source .venv/bin/activate
            uv sync --all-extras 2>/dev/null
          '';
        };
      }
    );
}
