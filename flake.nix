{
  description = "Pi 4B audio workstation — development environment and NixOS deployment";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils/11707dc2f618dd54ca8739b309ec4fc024de578b";
    nixos-hardware.url = "github:NixOS/nixos-hardware";
    nixgl = {
      url = "github:nix-community/nixGL";
      inputs.nixpkgs.follows = "nixpkgs";       # prevent GLIBC version mismatch
      inputs.flake-utils.follows = "flake-utils"; # deduplicate
    };
  };

  outputs = { self, nixpkgs, flake-utils, nixos-hardware, nixgl }:
    (flake-utils.lib.eachSystem [
      "x86_64-darwin"   # macOS Intel dev
      "aarch64-darwin"  # macOS Apple Silicon dev
      "aarch64-linux"   # Pi 4B deployment target
    ] (system:
      let
        pkgs = import nixpkgs {
          inherit system;
          overlays = nixpkgs.lib.optionals (system == "aarch64-linux") [
            nixgl.overlay
          ];
        };
        python = pkgs.python313;
        pycamilladsp = python.pkgs.buildPythonPackage rec {
          pname = "camilladsp";
          version = "3.0.0";
          pyproject = true;
          src = pkgs.fetchFromGitHub {
            owner = "HEnquist";
            repo = "pycamilladsp";
            rev = "v${version}";
            hash = "sha256-WyyeYAEi2s46WSSuSl/s04+yW4rXWMPUx+oT1bVP3HM=";
          };
          build-system = with python.pkgs; [ setuptools ];
          dependencies = with python.pkgs; [
            pyyaml
            websocket-client
          ];
          doCheck = false;  # tests need a running CamillaDSP instance
        };

        # nixGL wrapper for Mixxx on non-NixOS (Debian Trixie).
        # nixGLIntel is the Mesa wrapper — works for all Mesa drivers
        # including V3D on the Pi 4. Despite the "Intel" name, it sets
        # LIBGL_DRIVERS_PATH, GBM_BACKENDS_PATH, and LD_LIBRARY_PATH
        # to point at Nix's Mesa, which contains the V3D DRI driver.
        #
        # We also prepend host PipeWire/JACK library paths so that
        # pw-jack compatibility works (Mixxx uses JACK via PipeWire).
        # On non-NixOS, PipeWire's pw-jack libraries live under the
        # host's /usr/lib, which Nix isolates away.
        mixxx-wrapped = let
          nixGLMesa = pkgs.nixgl.nixGLIntel;
        in pkgs.writeShellApplication {
          name = "mixxx";
          runtimeInputs = [ nixGLMesa pkgs.mixxx ];
          text = ''
            # Host PipeWire/JACK paths for non-NixOS Debian Trixie.
            # pw-jack provides libjack.so that routes JACK calls through
            # PipeWire. Mixxx links against JACK, so it needs to find
            # the host's pw-jack library.
            HOST_LIB="/usr/lib/aarch64-linux-gnu"
            if [ -d "$HOST_LIB/pipewire-0.3/jack" ]; then
              export LD_LIBRARY_PATH="$HOST_LIB/pipewire-0.3/jack''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
            fi

            exec nixGLIntel mixxx "$@"
          '';
        };
      in
      {
        packages = { } // pkgs.lib.optionalAttrs pkgs.stdenv.hostPlatform.isLinux {
          # Unwrapped Mixxx (for NixOS or debugging)
          mixxx = pkgs.mixxx;

          # Wrapped Mixxx with nixGL + host PipeWire/JACK (for non-NixOS)
          mixxx-gl = mixxx-wrapped;

          # Default package for `nix run .#` on Linux
          default = mixxx-wrapped;
        };

        devShells.default = pkgs.mkShell {
          packages = [
            (python.withPackages (ps: [
              ps.mido
              ps.python-rtmidi
              ps.fastapi
              ps.uvicorn
              ps.scipy
              ps.numpy
              ps.soundfile
              ps.websockets
              ps.pyyaml
              # Testing
              ps.pytest
              ps.httpx
              ps.playwright
              ps.pytest-playwright
              pycamilladsp
            ]))
            pkgs.playwright-driver
          ];

          buildInputs = [
            pkgs.libsndfile
          ] ++ pkgs.lib.optionals pkgs.stdenv.hostPlatform.isLinux [
            pkgs.alsa-lib
            pkgs.libjack2
          ];

          shellHook = ''
            export PLAYWRIGHT_BROWSERS_PATH="${pkgs.playwright-driver.browsers}"
            export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

            echo "Pi 4B audio workstation dev shell"
            echo "Python: $(python3 --version)"
            echo ""
            echo "Packages from nixpkgs: mido, python-rtmidi, fastapi,"
            echo "  uvicorn, scipy, numpy, soundfile, websockets,"
            echo "  pytest, playwright, pytest-playwright"
            echo ""

            echo "pycamilladsp: $(python3 -c 'from camilladsp.versions import VERSION; print(VERSION)' 2>/dev/null || echo 'not available')"
          '';
        };
      }
    ))
    // {
      nixosConfigurations.mugge = nixpkgs.lib.nixosSystem {
        system = "aarch64-linux";
        modules = [
          nixos-hardware.nixosModules.raspberry-pi-4
          ./nix/nixos/configuration.nix
        ];
      };
    };
}
