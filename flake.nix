{
  description = "tube-scout – YouTube lecture video analytics CLI + admin web UI";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    agenix = {
      url = "github:ryantm/agenix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nixpkgs, flake-utils, agenix, ... }:
    let
      # NixOS module: services.tube-scout-admin-web.{enable,package,...}.
      # Consumers must `imports = [ inputs.tube-scout.nixosModules.default
      # inputs.agenix.nixosModules.default ];` and supply their own
      # `services.tube-scout-admin-web.package` derivation (uv2nix etc.).
      adminWebModule = import ./nix/module.nix;
    in
    {
      nixosModules = {
        default = adminWebModule;
        tube-scout-admin-web = adminWebModule;
      };
    } // flake-utils.lib.eachDefaultSystem (system:
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

            # spec 012: yt-dlp audio download + chromaprint fingerprinting
            yt-dlp
            chromaprint
            ffmpeg
            zlib
            stdenv.cc.cc.lib

            # agenix CLI for editing department/shared *.age files
            agenix.packages.${system}.default
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
            ])}:${pkgs.chromaprint}/lib:${pkgs.zlib}/lib:${pkgs.stdenv.cc.cc.lib}/lib:''${LD_LIBRARY_PATH}"

          '';
        };
      });
}
