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

        # Separate instantiation that permits unfree packages (NVIDIA cuDNN
        # ships under the cuDNN EULA). Scoped to the optional `gpu` shell so
        # the default shell remains fully free-software.
        pkgsUnfree = import nixpkgs {
          inherit system;
          config.allowUnfree = true;
        };

        commonBuildInputs = with pkgs; [
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

          # spec 012: chromaprint fingerprinting + ffmpeg audio decode
          # NOTE: yt-dlp is installed via uv (PyPI) — pkgs.yt-dlp would leak
          # Python 3.13 site-packages into PYTHONPATH, breaking the Python 3.11
          # venv (cryptography ABI mismatch). Subprocess calls use .venv/bin/yt-dlp.
          chromaprint
          ffmpeg
          zlib
          stdenv.cc.cc.lib

          # agenix CLI for editing department/shared *.age files
          agenix.packages.${system}.default
        ];

        commonLibPath = pkgs.lib.makeLibraryPath (with pkgs; [
          pango
          cairo
          gdk-pixbuf
          glib
          harfbuzz
          fontconfig
          freetype
        ]);

        commonShellHookPrefix = ''
          export LD_LIBRARY_PATH_BASE="${commonLibPath}:${pkgs.chromaprint}/lib:${pkgs.zlib}/lib:${pkgs.stdenv.cc.cc.lib}/lib"
        '';
      in
      {
        # Default shell: CPU-only. faster-whisper still works via the
        # CTranslate2 CPU backend (int8). No unfree dependencies.
        devShells.default = pkgs.mkShell {
          buildInputs = commonBuildInputs;

          shellHook = ''
            ${commonShellHookPrefix}
            export LD_LIBRARY_PATH="$LD_LIBRARY_PATH_BASE:''${LD_LIBRARY_PATH}"
          '';
        };

        # GPU shell: adds CUDA cuDNN + NVRTC for faster-whisper GPU inference.
        # cuDNN is distributed under NVIDIA's cuDNN EULA (unfree); pkgsUnfree
        # opts in to that license. Enter explicitly:
        #   nix develop .#gpu
        # or in direnv:
        #   echo 'use flake .#gpu' > .envrc.local && direnv allow
        devShells.gpu = pkgsUnfree.mkShell {
          buildInputs = commonBuildInputs ++ (with pkgsUnfree; [
            cudaPackages.cudnn
            cudaPackages.cuda_nvrtc
          ]);

          shellHook = ''
            ${commonShellHookPrefix}
            export LD_LIBRARY_PATH="$LD_LIBRARY_PATH_BASE:${pkgsUnfree.cudaPackages.cudnn}/lib:${pkgsUnfree.cudaPackages.cuda_nvrtc}/lib:''${LD_LIBRARY_PATH}"
          '';
        };
      });
}
