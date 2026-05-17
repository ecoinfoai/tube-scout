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

        # Note (pyproject extras ↔ devShell parity, audit v3 G-3.a 2026-05-17):
        # Whenever a new heavyweight runtime dependency lands in
        # pyproject.toml [project.optional-dependencies].asr / .pdf / .ml-*,
        # check if it dlopens a system library (CUDA, cairo, etc.). If so,
        # add the matching nixpkgs package to commonBuildInputs (CPU-safe)
        # or to devShells.gpu.buildInputs (GPU-only / unfree), and mirror
        # the path under shellHook LD_LIBRARY_PATH. See CLAUDE.md
        # "Consistency Invariants".
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

          # Chromaprint fingerprinting + ffmpeg audio decode
          # (spec 013 services/audio_fingerprint.py + audio_extract.py)
          chromaprint
          ffmpeg
          zlib
          stdenv.cc.cc.lib

          # sqlite CLI for ad-hoc inspection of content_reuse.db.
          # Also required for runtime: faster-whisper / worker_pool atomic
          # claim relies on SQLite >= 3.35 (RETURNING). audit v3 F-1 G-1.b.
          sqlite

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

        # CTranslate2 4.7.x GPU runtime dlopen requirements (audit v3 G-4,
        # 2026-05-17, binary analysis on nixpkgs rev 8110df5 / CUDA 12.9).
        # faster-whisper -> CTranslate2 -> dlopen the following at first
        # GPU model load. Each MUST resolve via LD_LIBRARY_PATH or the
        # process raises a generic RuntimeError that is hard to attribute
        # (asr.py F-3a now classifies these explicitly).
        #
        # dlopen targets (confirmed by binary analysis, cuRAND NOT used):
        #   - libcudnn.so.9          (cudaPackages.cudnn)
        #   - libcudnn_ops.so.9      (cudaPackages.cudnn)
        #   - libnvrtc.so.12         (cudaPackages.cuda_nvrtc)
        #   - libcublas.so.12        (cudaPackages.libcublas)
        #   - libcublasLt.so.12      (cudaPackages.libcublas)
        #   - libcudart.so.12        (cudaPackages.cuda_cudart)
        #   - libcuda.so.1           (kernel-provided, host driver)
        #
        # gpuLibPath centralizes the path list so additions stay in one
        # place. Adding/removing CUDA components requires updating both
        # buildInputs and gpuLibPath (CLAUDE.md Consistency Invariants).
        #
        # F-1 follow-up (2026-05-17): cudaPackages.{cudnn, cuda_nvrtc,
        # libcublas} are multi-output derivations whose default ``out``
        # contains only LICENSE + nix-support; the actual shared
        # libraries live in the ``.lib`` output. cuda_cudart keeps its
        # default ``out`` shape (lib/ + include/). Use ``.lib or .``
        # so we always pick the output that holds libcublas.so.12 etc.
        gpuLibPath = with pkgsUnfree; [
          (cudaPackages.cudnn.lib or cudaPackages.cudnn)
          (cudaPackages.cuda_nvrtc.lib or cudaPackages.cuda_nvrtc)
          (cudaPackages.libcublas.lib or cudaPackages.libcublas)
          (cudaPackages.cuda_cudart.lib or cudaPackages.cuda_cudart)
        ];

        gpuLibPathString = pkgs.lib.concatMapStringsSep ":"
          (p: "${p}/lib") gpuLibPath;
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

        # GPU shell: adds CUDA cuDNN + NVRTC + cuBLAS + cudart for
        # faster-whisper GPU inference. cuDNN is distributed under NVIDIA's
        # cuDNN EULA (unfree); pkgsUnfree opts in to that license. Enter
        # explicitly:
        #   nix develop .#gpu
        # or in direnv:
        #   echo 'use flake .#gpu' > .envrc.local && direnv allow
        devShells.gpu = pkgsUnfree.mkShell {
          buildInputs = commonBuildInputs ++ gpuLibPath;

          shellHook = ''
            ${commonShellHookPrefix}
            export LD_LIBRARY_PATH="$LD_LIBRARY_PATH_BASE:${gpuLibPathString}:''${LD_LIBRARY_PATH}"
          '';
        };
      });
}
