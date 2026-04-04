{
  description = "tube-scout – YouTube lecture video analytics CLI";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
      in
      {
        devShells.default = pkgs.mkShell {
          buildInputs = with pkgs; [
            # Python
            python311

            # WeasyPrint system dependencies
            pango
            cairo
            gdk-pixbuf
            glib
            harfbuzz
            fontconfig
            freetype

            # Build tools
            pkg-config
          ];

          shellHook = ''
            export LD_LIBRARY_PATH="${pkgs.lib.makeLibraryPath (with pkgs; [
              pango
              cairo
              gdk-pixbuf
              glib
              harfbuzz
              fontconfig
              freetype
            ])}:''${LD_LIBRARY_PATH:-}"

          '';
        };
      });
}
