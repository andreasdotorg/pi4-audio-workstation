{
  description = "Pi 4B audio workstation — development environment and NixOS deployment";

  nixConfig = {
    extra-substituters = [ "https://mugge.cachix.org" ];
    extra-trusted-public-keys = [ "mugge.cachix.org-1:5p6UsgwD9LPWgJJaTGrRp5qahNcaq86Ew7Oro9HTevc=" ];
  };

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.11";
    # US-128: PipeWire 1.6.2 source — nixos-25.11 ships 1.4.9.
    # Only PW is imported from this input; everything else stays on nixos-25.11.
    nixpkgs-pw.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    flake-utils.url = "github:numtide/flake-utils/11707dc2f618dd54ca8739b309ec4fc024de578b";
    nixos-hardware.url = "github:NixOS/nixos-hardware";
    nixgl = {
      url = "github:nix-community/nixGL";
      inputs.nixpkgs.follows = "nixpkgs";       # prevent GLIBC version mismatch
      inputs.flake-utils.follows = "flake-utils"; # deduplicate
    };
    disko = {
      url = "github:nix-community/disko";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nixpkgs, nixpkgs-pw, flake-utils, nixos-hardware, nixgl, disko }:
    (flake-utils.lib.eachSystem [
      "x86_64-darwin"   # macOS Intel dev
      "aarch64-darwin"  # macOS Apple Silicon dev
      "aarch64-linux"   # Pi 4B deployment target
      "x86_64-linux"    # GitHub Actions CI runners
    ] (system:
      let
        pkgs = import nixpkgs {
          inherit system;
          overlays = nixpkgs.lib.optionals (builtins.match ".*-linux" system != null) [
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

        # Python with test dependencies — shared by checks and unit-test apps.
        testPython = python.withPackages (ps: [
          ps.mido
          ps.python-rtmidi
          ps.fastapi
          ps.uvicorn
          ps.scipy
          ps.numpy
          ps.soundfile
          ps.websockets
          ps.pyyaml
          # US-110: Passkey auth dependencies
          ps.webauthn    # py-webauthn (WebAuthn registration/authentication)
          ps.aiosqlite   # async SQLite for credential + session storage
          ps.qrcode      # QR code generation for invite links
          # Testing
          ps.pytest
          ps.httpx
          pycamilladsp
        ]);

        # Python with browser-test dependencies — adds playwright on top of testPython's deps.
        # Used by test-integration-browser app and devShell.
        e2ePython = python.withPackages (ps: [
          ps.mido
          ps.python-rtmidi
          ps.fastapi
          ps.uvicorn
          ps.scipy
          ps.numpy
          ps.soundfile
          ps.websockets
          ps.pyyaml
          # US-110: Passkey auth dependencies
          ps.webauthn
          ps.aiosqlite
          ps.qrcode
          # Testing
          ps.pytest
          ps.httpx
          pycamilladsp
          # Browser integration testing
          ps.playwright
          ps.pytest-playwright
        ]);

        # CamillaDSP binary for integration testing (TK-189).
        # Built with websocket + file backend — no JACK/PulseAudio needed.
        # The File capture/playback type is always compiled in (not a feature).
        # Used by room-correction integration tests to replace MockCamillaClient.
        camilladsp-test = pkgs.rustPlatform.buildRustPackage {
          pname = "camilladsp";
          version = "3.0.1";
          src = pkgs.fetchFromGitHub {
            owner = "HEnquist";
            repo = "camilladsp";
            rev = "v3.0.1";
            hash = "sha256-IJ1sYprBh8ys1Og3T3newIDlBlR0PoQiblbJmzLbsfs=";
          };
          cargoLock.lockFile = ./src/camilladsp-test/Cargo.lock;
          # Upstream doesn't ship a Cargo.lock — copy ours into the source.
          postPatch = ''
            cp ${./src/camilladsp-test/Cargo.lock} Cargo.lock
          '';
          # Default features = ["websocket"] — includes tungstenite WS server.
          # No extra features needed: File I/O backend is always compiled in.
          buildNoDefaultFeatures = false;
          nativeBuildInputs = [ pkgs.pkg-config ];
          buildInputs =
            pkgs.lib.optionals pkgs.stdenv.hostPlatform.isLinux [ pkgs.alsa-lib ]
            ++ pkgs.lib.optionals pkgs.stdenv.hostPlatform.isDarwin [
              pkgs.apple-sdk  # Provides AudioUnit, CoreAudio, CoreServices frameworks
            ];
          doCheck = false;  # CamillaDSP tests require audio hardware
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
            HOST_LIB="/usr/lib/${system}-gnu"
            if [ -d "$HOST_LIB/pipewire-0.3/jack" ]; then
              export LD_LIBRARY_PATH="$HOST_LIB/pipewire-0.3/jack''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
            fi

            exec nixGLIntel mixxx "$@"
          '';
        };

        # Workspace source for level-bridge + pcm-bridge + signal-gen + audio-common.
        # Cleaned to include only the workspace root and member crates.
        rustWorkspaceSrc = pkgs.lib.cleanSourceWith {
          src = ./src;
          filter = path: type:
            let baseName = builtins.baseNameOf path; in
            # Include workspace root files
            baseName == "Cargo.toml" || baseName == "Cargo.lock"
            # Include workspace member directories
            || pkgs.lib.hasPrefix (toString ./src/audio-common) (toString path)
            || pkgs.lib.hasPrefix (toString ./src/level-bridge) (toString path)
            || pkgs.lib.hasPrefix (toString ./src/pcm-bridge) (toString path)
            || pkgs.lib.hasPrefix (toString ./src/signal-gen) (toString path);
        };

        # US-128: PipeWire 1.6.2 from nixpkgs-unstable with US-112 reload patch.
        # nixos-25.11 ships PW 1.4.9; we upgrade source + nixpkgs patches from
        # nixpkgs-unstable while keeping all build deps from nixos-25.11.
        # The convolver-reload patch (1.6.2 version) uses the clean API:
        # plugin_builtin.c, spa_loop_locked, control_changed callback.
        pwUnstable = ((import nixpkgs-pw { inherit system; }).pipewire.override {
          # Disable Bluetooth codecs — build deps from nixos-25.11 may lack
          # ldacbt-dec and other BT libraries present in nixpkgs-unstable.
          bluezSupport = false;
        });
        pipewire-patched = pkgs.pipewire.overrideAttrs (oldAttrs: {
          version = pwUnstable.version;
          src = pwUnstable.src;
          # Replace mesonFlags entirely — nixos-25.11 passes -Dsystemd=enabled
          # which doesn't exist in PW 1.6.2 (renamed to -Dlibsystemd=enabled).
          mesonFlags = pwUnstable.mesonFlags;
          patches = pwUnstable.patches ++ [
            ./nix/patches/pipewire-convolver-reload.patch
          ];
        });

        # Shared PipeWire build args for Rust crates.
        rustPwBuildArgs = {
          nativeBuildInputs = [ pkgs.pkg-config pkgs.llvmPackages.libclang ];
          buildInputs = [ pkgs.pipewire ];
          LIBCLANG_PATH = "${pkgs.llvmPackages.libclang.lib}/lib";
          BINDGEN_EXTRA_CLANG_ARGS = builtins.toString [
            "-isystem ${pkgs.llvmPackages.libclang.lib}/lib/clang/${pkgs.llvmPackages.libclang.version}/include"
            "-isystem ${pkgs.glibc.dev}/include"
          ];
        };

        # Rust PipeWire tools (Linux-only, need libpipewire).
        # Built from the Cargo workspace (audio-common + level-bridge + pcm-bridge + signal-gen).
        level-bridge = pkgs.rustPlatform.buildRustPackage (rustPwBuildArgs // {
          pname = "level-bridge";
          version = "0.1.0";
          src = rustWorkspaceSrc;
          cargoLock.lockFile = ./src/Cargo.lock;
          buildAndTestSubdir = "level-bridge";
        });

        pcm-bridge = pkgs.rustPlatform.buildRustPackage (rustPwBuildArgs // {
          pname = "pcm-bridge";
          version = "0.1.0";
          src = rustWorkspaceSrc;
          cargoLock.lockFile = ./src/Cargo.lock;
          buildAndTestSubdir = "pcm-bridge";
        });

        signal-gen = pkgs.rustPlatform.buildRustPackage (rustPwBuildArgs // {
          pname = "pi4audio-signal-gen";
          version = "0.1.0";
          src = rustWorkspaceSrc;
          cargoLock.lockFile = ./src/Cargo.lock;
          buildAndTestSubdir = "signal-gen";
        });

        graph-manager = pkgs.rustPlatform.buildRustPackage {
          pname = "pi4audio-graph-manager";
          version = "0.1.0";
          src = ./src/graph-manager;
          cargoLock.lockFile = ./src/graph-manager/Cargo.lock;
          nativeBuildInputs = [ pkgs.pkg-config pkgs.llvmPackages.libclang ];
          buildInputs = [ pkgs.pipewire ];
          LIBCLANG_PATH = "${pkgs.llvmPackages.libclang.lib}/lib";
          BINDGEN_EXTRA_CLANG_ARGS = builtins.toString [
            "-isystem ${pkgs.llvmPackages.libclang.lib}/lib/clang/${pkgs.llvmPackages.libclang.version}/include"
            "-isystem ${pkgs.glibc.dev}/include"
          ];
        };
      in
      {
        packages = {
          # CamillaDSP with file backend for integration testing (all platforms).
          inherit camilladsp-test;
        } // pkgs.lib.optionalAttrs pkgs.stdenv.hostPlatform.isLinux {
          # US-112: PipeWire with convolver reload patch (for local-demo/tests).
          inherit pipewire-patched;

          # Unwrapped Mixxx (for NixOS or debugging)
          mixxx = pkgs.mixxx;

          # Wrapped Mixxx with nixGL + host PipeWire/JACK (for non-NixOS)
          mixxx-gl = mixxx-wrapped;

          # Always-on PipeWire level metering bridge for web UI (D-049).
          inherit level-bridge;

          # Passive PipeWire monitor-port PCM bridge for web UI.
          inherit pcm-bridge;

          # RT signal generator for measurement and test tooling (D-037).
          inherit signal-gen;

          # PipeWire graph manager — session manager for link topology (GM-7).
          inherit graph-manager;

          # Default package for `nix run .#` on Linux
          default = mixxx-wrapped;
        };

        devShells.default = pkgs.mkShell {
          packages = [
            e2ePython
            pkgs.playwright-driver
            pkgs.playwright-mcp        # US-109: MCP server for agent-driven browser testing
            camilladsp-test  # Real CamillaDSP for integration tests (TK-189)
            # Rust toolchain — same version as buildRustPackage uses.
            pkgs.cargo
            pkgs.rustc
            pkgs.clippy
            pkgs.rust-analyzer
          ];

          buildInputs = [
            pkgs.libsndfile
          ] ++ pkgs.lib.optionals pkgs.stdenv.hostPlatform.isLinux [
            pkgs.alsa-lib
            # PipeWire dev deps for cargo build of PW crates
            pkgs.pipewire
            pkgs.pkg-config
            pkgs.llvmPackages.libclang
          ];

          shellHook = ''
            export PLAYWRIGHT_BROWSERS_PATH="${pkgs.playwright-driver.browsers}"
            export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
          '' + pkgs.lib.optionalString pkgs.stdenv.hostPlatform.isLinux ''
            export LIBCLANG_PATH="${pkgs.llvmPackages.libclang.lib}/lib"
            export BINDGEN_EXTRA_CLANG_ARGS="-isystem ${pkgs.llvmPackages.libclang.lib}/lib/clang/${pkgs.llvmPackages.libclang.version}/include -isystem ${pkgs.glibc.dev}/include"
          '' + ''

            echo "Pi 4B audio workstation dev shell"
            echo "Python: $(python3 --version)"
            echo "Rust:   $(rustc --version 2>/dev/null || echo 'not available')"
            echo "Cargo:  $(cargo --version 2>/dev/null || echo 'not available')"
            echo ""
            echo "Packages from nixpkgs: mido, python-rtmidi, fastapi,"
            echo "  uvicorn, scipy, numpy, soundfile, websockets,"
            echo "  pytest, playwright, pytest-playwright"
            echo ""

            echo "pycamilladsp: $(python3 -c 'from camilladsp.versions import VERSION; print(VERSION)' 2>/dev/null || echo 'not available')"
          '';
        };

        # -----------------------------------------------------------------
        # Checks — sandboxed test derivations for `nix flake check`
        # -----------------------------------------------------------------
        checks = {
          test-web-ui = pkgs.runCommand "test-web-ui" {
            nativeBuildInputs = [ testPython ];
            PI_AUDIO_MOCK = "1";
          } ''
            cp -r ${./src/web-ui} web-ui
            cp -r ${./src/room-correction} room-correction
            chmod -R u+w web-ui room-correction
            cd web-ui
            python -m pytest tests/ -v --ignore=tests/integration/ --ignore=tests/e2e/ --tb=short
            touch $out
          '';

          test-room-correction = pkgs.runCommand "test-room-correction" {
            nativeBuildInputs = [ testPython camilladsp-test ];
            PI_AUDIO_MOCK = "1";
          } ''
            cp -r ${./src/room-correction} room-correction
            cp ${./src/camilladsp-test/test_config.yml} room-correction/test_camilladsp.yml
            chmod -R u+w room-correction
            cd room-correction
            python -m pytest tests/ -v --tb=short
            touch $out
          '';

          test-midi = pkgs.runCommand "test-midi" {
            nativeBuildInputs = [ testPython ];
            PI_AUDIO_MOCK = "1";
          } ''
            cp -r ${./src/midi} midi
            cp -r ${./configs} configs
            chmod -R u+w midi configs
            cd midi
            python -m pytest tests/ -v --tb=short
            touch $out
          '';

          test-drivers = pkgs.runCommand "test-drivers" {
            nativeBuildInputs = [ testPython ];
            PI_AUDIO_MOCK = "1";
          } ''
            cp -r ${./scripts/drivers} drivers
            mkdir -p scripts
            ln -s "$PWD/drivers" scripts/drivers
            chmod -R u+w drivers
            cd drivers
            python -m pytest tests/ -v --tb=short
            touch $out
          '';
        } // pkgs.lib.optionalAttrs pkgs.stdenv.hostPlatform.isLinux {
          # Rust QA gate (Tier 2): hermetic buildRustPackage tests.
          # US-075 AC 7: consolidated from fragile runCommand + buildRustPackage
          # variants into a single hermetic build per crate.
          test-graph-manager = graph-manager;
          test-level-bridge = level-bridge;
          test-pcm-bridge = pcm-bridge;
          test-signal-gen = signal-gen;
        };

        # -----------------------------------------------------------------
        # Apps — runnable test / dev commands via `nix run .#<name>`
        # -----------------------------------------------------------------
        apps = {
          test-unit = {
            type = "app";
            program = "${pkgs.writeShellScript "test-unit" ''
              export PI_AUDIO_MOCK=1
              cd ${toString ./.}/src/web-ui
              exec ${testPython}/bin/python -m pytest tests/unit/ -v "$@"
            ''}";
          };

          test-integration-browser = {
            type = "app";
            program = "${pkgs.writeShellScript "test-integration-browser" ''
              export PI_AUDIO_MOCK=1
              export PLAYWRIGHT_BROWSERS_PATH="${pkgs.playwright-driver.browsers}"
              export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
              cd ${toString ./.}/src/web-ui
              exec ${e2ePython}/bin/python -m pytest tests/integration/ -v "$@"
            ''}";
          };

          # Full user journey integration test — speaker setup through verified room
          # correction.  Runs real DSP code with MockSoundDevice + Playwright
          # headless browser.  Slower than the regular integration-browser suite (~30-60s).
          test-journey = {
            type = "app";
            program = "${pkgs.writeShellScript "test-journey" ''
              export PI_AUDIO_MOCK=1
              export PLAYWRIGHT_BROWSERS_PATH="${pkgs.playwright-driver.browsers}"
              export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
              cd ${toString ./.}/src/web-ui
              exec ${e2ePython}/bin/python -m pytest tests/integration/test_full_user_journey.py -v "$@"
            ''}";
          };

          test-room-correction = {
            type = "app";
            program = "${pkgs.writeShellScript "test-room-correction" ''
              export PI_AUDIO_MOCK=1
              cd ${toString ./.}/src/room-correction
              exec ${testPython}/bin/python -m pytest tests/ -v "$@"
            ''}";
          };

          # Room simulation E2E tests (T-067-6, US-067).
          # Runs sim config generator, correction roundtrip, and mock E2E tests
          # in isolated temp XDG directories. Pure Python — no PipeWire needed.
          # PW headless tests (T-067-5) extend this with a real PW instance.
          test-room-sim-e2e = {
            type = "app";
            program = "${pkgs.writeShellScript "test-room-sim-e2e" ''
              set -euo pipefail
              REPO_DIR="${toString ./.}"
              TMPBASE="''${TMPDIR:-/tmp}/room-sim-e2e-$$"
              mkdir -p "$TMPBASE"
              export XDG_RUNTIME_DIR="$TMPBASE/runtime"
              export XDG_CONFIG_HOME="$TMPBASE/config"
              export XDG_DATA_HOME="$TMPBASE/data"
              export XDG_CACHE_HOME="$TMPBASE/cache"
              export ROOM_SIM_OUTPUT_DIR="$TMPBASE/sim-output"
              mkdir -p "$XDG_RUNTIME_DIR" "$XDG_CONFIG_HOME" "$XDG_DATA_HOME" \
                       "$XDG_CACHE_HOME" "$ROOM_SIM_OUTPUT_DIR"
              chmod 700 "$XDG_RUNTIME_DIR"
              cleanup() {
                if [ "''${ROOM_SIM_KEEP_TMPDIR:-0}" = "1" ]; then
                  echo "Keeping temp dir: $TMPBASE"
                else
                  rm -rf "$TMPBASE"
                fi
              }
              trap cleanup EXIT
              export PI_AUDIO_MOCK=1
              export PYTHONDONTWRITEBYTECODE=1
              echo "=== Room Simulation E2E Tests ==="
              echo "Repo:    $REPO_DIR"
              echo "Tmp dir: $TMPBASE"
              echo "Output:  $ROOM_SIM_OUTPUT_DIR"
              echo ""
              cd "$REPO_DIR/src/room-correction"
              exec ${testPython}/bin/python -m pytest tests/ -v --tb=short \
                -k "test_sim_ or test_correction_roundtrip or test_mock_e2e" \
                "$@"
            ''}";
          };

          test-all = {
            type = "app";
            program = "${pkgs.writeShellScript "test-all" ''
              export PI_AUDIO_MOCK=1
              set -e
              echo "=== web-ui unit tests ==="
              cd ${toString ./.}/src/web-ui
              ${testPython}/bin/python -m pytest tests/ -v --ignore=tests/integration/ --ignore=tests/e2e/ --tb=short
              echo ""
              echo "=== room-correction tests ==="
              cd ${toString ./.}/src/room-correction
              ${testPython}/bin/python -m pytest tests/ -v --tb=short
              echo ""
              echo "=== midi tests ==="
              cd ${toString ./.}/src/midi
              ${testPython}/bin/python -m pytest tests/ -v --tb=short
              echo ""
              echo "=== drivers tests ==="
              cd ${toString ./.}/scripts/drivers
              ${testPython}/bin/python -m pytest tests/ -v --tb=short
              echo ""
              echo "=== audio-common tests ==="
              cd ${toString ./.}/src
              HOME="''${HOME:-/tmp}" CARGO_TARGET_DIR="''${HOME:-/tmp}/.cargo-target/pi4audio-ws" PATH="${pkgs.cargo}/bin:${pkgs.rustc}/bin:${pkgs.stdenv.cc}/bin:$PATH" cargo test --locked -p audio-common 2>&1
              echo ""
              echo "=== graph-manager tests ==="
              cd ${toString ./.}/src/graph-manager
              HOME="''${HOME:-/tmp}" CARGO_TARGET_DIR="''${HOME:-/tmp}/.cargo-target/pi4audio-gm" PATH="${pkgs.cargo}/bin:${pkgs.rustc}/bin:${pkgs.stdenv.cc}/bin:$PATH" cargo test --locked --no-default-features --release 2>&1
              echo ""
              echo "All test suites passed."
              echo "(pcm-bridge and signal-gen: run nix run .#test-pcm-bridge / .#test-signal-gen on Linux)"
            ''}";
          };

          # Tier 1 — Dev loop (fast, non-hermetic cargo test wrappers).
          # NOT QA gates — use for quick iteration during development.
          test-audio-common = {
            type = "app";
            program = "${pkgs.writeShellScript "test-audio-common" ''
              export HOME="''${HOME:-/tmp}"
              export CARGO_TARGET_DIR="''${HOME}/.cargo-target/pi4audio-ws"
              export PATH="${pkgs.cargo}/bin:${pkgs.rustc}/bin:${pkgs.stdenv.cc}/bin:$PATH"
              cd ${toString ./.}/src
              exec cargo test --locked -p audio-common "$@"
            ''}";
          };

          test-graph-manager = {
            type = "app";
            program = "${pkgs.writeShellScript "test-graph-manager" ''
              export HOME="''${HOME:-/tmp}"
              export CARGO_TARGET_DIR="''${HOME}/.cargo-target/pi4audio-gm"
              export PATH="${pkgs.cargo}/bin:${pkgs.rustc}/bin:${pkgs.stdenv.cc}/bin:$PATH"
              cd ${toString ./.}/src/graph-manager
              exec cargo test --locked --no-default-features "$@"
            ''}";
          };

          test-everything = {
            type = "app";
            program = "${pkgs.writeShellScript "test-everything" ''
              set -e
              echo "========== test-all (unit + integration) =========="
              export PI_AUDIO_MOCK=1
              cd ${toString ./.}/src/web-ui
              ${testPython}/bin/python -m pytest tests/ -v --ignore=tests/integration/ --ignore=tests/e2e/ --tb=short
              echo ""
              echo "=== room-correction tests ==="
              cd ${toString ./.}/src/room-correction
              ${testPython}/bin/python -m pytest tests/ -v --tb=short
              echo ""
              echo "=== midi tests ==="
              cd ${toString ./.}/src/midi
              ${testPython}/bin/python -m pytest tests/ -v --tb=short
              echo ""
              echo "=== drivers tests ==="
              cd ${toString ./.}/scripts/drivers
              ${testPython}/bin/python -m pytest tests/ -v --tb=short
              echo ""
              echo "=== audio-common tests ==="
              cd ${toString ./.}/src
              HOME="''${HOME:-/tmp}" CARGO_TARGET_DIR="''${HOME:-/tmp}/.cargo-target/pi4audio-ws" PATH="${pkgs.cargo}/bin:${pkgs.rustc}/bin:${pkgs.stdenv.cc}/bin:$PATH" cargo test --locked -p audio-common 2>&1
              echo ""
              echo "=== graph-manager tests ==="
              cd ${toString ./.}/src/graph-manager
              HOME="''${HOME:-/tmp}" CARGO_TARGET_DIR="''${HOME:-/tmp}/.cargo-target/pi4audio-gm" PATH="${pkgs.cargo}/bin:${pkgs.rustc}/bin:${pkgs.stdenv.cc}/bin:$PATH" cargo test --locked --no-default-features --release 2>&1
              echo ""
              echo "========== test-integration-browser (browser tests) =========="
              export PLAYWRIGHT_BROWSERS_PATH="${pkgs.playwright-driver.browsers}"
              export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
              cd ${toString ./.}/src/web-ui
              ${e2ePython}/bin/python -m pytest tests/integration/ -v --tb=short
              echo ""
              echo "All test suites passed (unit + integration + integration-browser)."
            ''}";
          };

        } // pkgs.lib.optionalAttrs pkgs.stdenv.hostPlatform.isLinux {
          # PipeWire Rust tools — require libpipewire (Linux only).
          test-level-bridge = {
            type = "app";
            program = "${pkgs.writeShellScript "test-level-bridge" ''
              export HOME="''${HOME:-/tmp}"
              export CARGO_TARGET_DIR="''${HOME}/.cargo-target/pi4audio-ws"
              export PATH="${pkgs.cargo}/bin:${pkgs.rustc}/bin:${pkgs.pkg-config}/bin:${pkgs.stdenv.cc}/bin:$PATH"
              export PKG_CONFIG_PATH="${pkgs.pipewire.dev}/lib/pkgconfig''${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
              export LIBCLANG_PATH="${pkgs.llvmPackages.libclang.lib}/lib"
              export BINDGEN_EXTRA_CLANG_ARGS="-isystem ${pkgs.llvmPackages.libclang.lib}/lib/clang/${pkgs.llvmPackages.libclang.version}/include -isystem ${pkgs.glibc.dev}/include"
              cd ${toString ./.}/src
              exec cargo test --locked -p level-bridge "$@"
            ''}";
          };

          test-pcm-bridge = {
            type = "app";
            program = "${pkgs.writeShellScript "test-pcm-bridge" ''
              export HOME="''${HOME:-/tmp}"
              export CARGO_TARGET_DIR="''${HOME}/.cargo-target/pi4audio-ws"
              export PATH="${pkgs.cargo}/bin:${pkgs.rustc}/bin:${pkgs.pkg-config}/bin:${pkgs.stdenv.cc}/bin:$PATH"
              export PKG_CONFIG_PATH="${pkgs.pipewire.dev}/lib/pkgconfig''${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
              export LIBCLANG_PATH="${pkgs.llvmPackages.libclang.lib}/lib"
              export BINDGEN_EXTRA_CLANG_ARGS="-isystem ${pkgs.llvmPackages.libclang.lib}/lib/clang/${pkgs.llvmPackages.libclang.version}/include -isystem ${pkgs.glibc.dev}/include"
              cd ${toString ./.}/src
              exec cargo test --locked -p pcm-bridge "$@"
            ''}";
          };

          test-signal-gen = {
            type = "app";
            program = "${pkgs.writeShellScript "test-signal-gen" ''
              export HOME="''${HOME:-/tmp}"
              export CARGO_TARGET_DIR="''${HOME}/.cargo-target/pi4audio-ws"
              export PATH="${pkgs.cargo}/bin:${pkgs.rustc}/bin:${pkgs.pkg-config}/bin:${pkgs.stdenv.cc}/bin:$PATH"
              export PKG_CONFIG_PATH="${pkgs.pipewire.dev}/lib/pkgconfig''${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
              export LIBCLANG_PATH="${pkgs.llvmPackages.libclang.lib}/lib"
              export BINDGEN_EXTRA_CLANG_ARGS="-isystem ${pkgs.llvmPackages.libclang.lib}/lib/clang/${pkgs.llvmPackages.libclang.version}/include -isystem ${pkgs.glibc.dev}/include"
              cd ${toString ./.}/src
              exec cargo test --locked -p pi4audio-signal-gen "$@"
            ''}";
          };

          # Local demo stack: PipeWire test env + GM + signal-gen + pcm-bridge + web-ui.
          local-demo = {
            type = "app";
            program = "${pkgs.writeShellScript "local-demo" ''
              export LOCAL_DEMO_GM_BIN="${graph-manager}/bin/pi4audio-graph-manager"
              export LOCAL_DEMO_SG_BIN="${signal-gen}/bin/pi4audio-signal-gen"
              export LOCAL_DEMO_LB_BIN="${level-bridge}/bin/level-bridge"
              export LOCAL_DEMO_PCM_BIN="${pcm-bridge}/bin/pcm-bridge"
              export LOCAL_DEMO_PYTHON="${testPython}/bin/python"
              export LOCAL_DEMO_PW_JACK="${pipewire-patched.jack}/bin/pw-jack"
              export LOCAL_DEMO_REPO_DIR="${toString ./.}"
              export PW_STORE="${pipewire-patched}"
              export PATH="${pkgs.ffmpeg-headless}/bin:${testPython}/bin:$PATH"
              exec ${pkgs.bash}/bin/bash ${./scripts/local-demo.sh} "$@"
            ''}";
          };

          # US-075 AC 4/5: PipeWire integration test — end-to-end verification.
          # Starts headless PW + GM + signal-gen + level-bridge + pcm-bridge,
          # verifies audio flow, link topology, and graph metadata, then tears down.
          test-integration = {
            type = "app";
            program = "${pkgs.writeShellScript "test-integration" ''
              export LOCAL_DEMO_GM_BIN="${graph-manager}/bin/pi4audio-graph-manager"
              export LOCAL_DEMO_SG_BIN="${signal-gen}/bin/pi4audio-signal-gen"
              export LOCAL_DEMO_LB_BIN="${level-bridge}/bin/level-bridge"
              export LOCAL_DEMO_PCM_BIN="${pcm-bridge}/bin/pcm-bridge"
              export LOCAL_DEMO_PYTHON="${testPython}/bin/python"
              export LOCAL_DEMO_REPO_DIR="${toString ./.}"
              export PW_STORE="${pipewire-patched}"
              export PATH="${testPython}/bin:$PATH"
              exec ${pkgs.bash}/bin/bash ${./scripts/test-integration.sh} "$@"
            ''}";
          };

          # Real E2E tests — full stack (PipeWire + GM + services + web UI).
          # Starts local-demo, waits for health, runs pytest against live server.
          # Only physical audio hardware is absent. Linux-only.
          test-e2e = {
            type = "app";
            program = "${pkgs.writeShellScript "test-e2e" ''
              export LOCAL_DEMO_GM_BIN="${graph-manager}/bin/pi4audio-graph-manager"
              export LOCAL_DEMO_SG_BIN="${signal-gen}/bin/pi4audio-signal-gen"
              export LOCAL_DEMO_LB_BIN="${level-bridge}/bin/level-bridge"
              export LOCAL_DEMO_PCM_BIN="${pcm-bridge}/bin/pcm-bridge"
              export LOCAL_DEMO_PYTHON="${testPython}/bin/python"
              export LOCAL_DEMO_E2E_PYTHON="${e2ePython}/bin/python"
              export LOCAL_DEMO_PW_JACK="${pipewire-patched.jack}/bin/pw-jack"
              export LOCAL_DEMO_REPO_DIR="${toString ./.}"
              export LOCAL_DEMO_SH="${./scripts/local-demo.sh}"
              export LOCAL_DEMO_BASH="${pkgs.bash}/bin/bash"
              export PW_STORE="${pipewire-patched}"
              export PLAYWRIGHT_BROWSERS_PATH="${pkgs.playwright-driver.browsers}"
              export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
              export PATH="${pkgs.curl}/bin:${pkgs.ffmpeg-headless}/bin:${e2ePython}/bin:${testPython}/bin:$PATH"
              exec ${pkgs.bash}/bin/bash ${./scripts/test-e2e.sh} "$@"
            ''}";
          };

          # Pi-loopback tests — real USB audio with patch cables, no speakers.
          # Runs E2E tests excluding acoustic tests. Requires --loopback-confirmed.
          test-pi-loopback = {
            type = "app";
            program = "${pkgs.writeShellScript "test-pi-loopback" ''
              export PI_AUDIO_BACKEND=pi-loopback
              cd ${toString ./.}/src/web-ui
              exec ${e2ePython}/bin/python -m pytest tests/e2e/ -v -m "not needs_acoustic" --loopback-confirmed "$@"
            ''}";
          };

          # Pi-full tests — everything, owner present, speakers connected.
          test-pi-full = {
            type = "app";
            program = "${pkgs.writeShellScript "test-pi-full" ''
              export PI_AUDIO_BACKEND=pi-full
              cd ${toString ./.}/src/web-ui
              exec ${e2ePython}/bin/python -m pytest tests/e2e/ -v --owner-confirmed --destructive "$@"
            ''}";
          };

          # US-077 DoD #2: Capture headless browser screenshots of dashboard
          # with steady-state 1 kHz sine. Starts full local-demo stack, plays
          # sine, uses Playwright to screenshot meters/spectrum, then tears down.
          capture-screenshot = {
            type = "app";
            program = "${pkgs.writeShellScript "capture-screenshot" ''
              export LOCAL_DEMO_GM_BIN="${graph-manager}/bin/pi4audio-graph-manager"
              export LOCAL_DEMO_SG_BIN="${signal-gen}/bin/pi4audio-signal-gen"
              export LOCAL_DEMO_LB_BIN="${level-bridge}/bin/level-bridge"
              export LOCAL_DEMO_PCM_BIN="${pcm-bridge}/bin/pcm-bridge"
              export LOCAL_DEMO_PYTHON="${testPython}/bin/python"
              export LOCAL_DEMO_E2E_PYTHON="${e2ePython}/bin/python"
              export LOCAL_DEMO_REPO_DIR="${toString ./.}"
              export PW_STORE="${pipewire-patched}"
              export PLAYWRIGHT_BROWSERS_PATH="${pkgs.playwright-driver.browsers}"
              export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
              export PATH="${e2ePython}/bin:${testPython}/bin:$PATH"
              exec ${pkgs.bash}/bin/bash ${./scripts/screenshot-local-demo.sh} "$@"
            ''}";
          };
        };
      }
    ))
    // {
      nixosConfigurations =
        let
          system = "aarch64-linux";
          pkgs = import nixpkgs {
            inherit system;
            overlays = [ nixgl.overlay ];
          };
          # Build our custom Rust packages for the Pi target.
          # These are passed to NixOS modules via specialArgs so service
          # units can reference Nix store paths instead of ~/bin.
          rustPwArgs = {
            nativeBuildInputs = [ pkgs.pkg-config pkgs.llvmPackages.libclang ];
            buildInputs = [ pkgs.pipewire ];
            LIBCLANG_PATH = "${pkgs.llvmPackages.libclang.lib}/lib";
            BINDGEN_EXTRA_CLANG_ARGS = builtins.toString [
              "-isystem ${pkgs.llvmPackages.libclang.lib}/lib/clang/${pkgs.llvmPackages.libclang.version}/include"
              "-isystem ${pkgs.glibc.dev}/include"
            ];
          };

          # Workspace source for level-bridge + pcm-bridge + signal-gen + audio-common.
          workspaceSrc = pkgs.lib.cleanSourceWith {
            src = ./src;
            filter = path: type:
              let baseName = builtins.baseNameOf path; in
              baseName == "Cargo.toml" || baseName == "Cargo.lock"
              || pkgs.lib.hasPrefix (toString ./src/audio-common) (toString path)
              || pkgs.lib.hasPrefix (toString ./src/level-bridge) (toString path)
              || pkgs.lib.hasPrefix (toString ./src/pcm-bridge) (toString path)
              || pkgs.lib.hasPrefix (toString ./src/signal-gen) (toString path);
          };

          # US-128: PipeWire 1.6.2 from nixpkgs-unstable for NixOS overlay.
          # Apply bluezSupport=false here so mesonFlags already have bluez
          # disabled — the NixOS overlay inherits these flags directly.
          pwUnstablePkg = ((import nixpkgs-pw { inherit system; }).pipewire.override {
            bluezSupport = false;
          });

          # Shared specialArgs for both NixOS configurations.
          sharedSpecialArgs = {
            inherit pwUnstablePkg;
            pi4audio-packages = {
              graph-manager = pkgs.rustPlatform.buildRustPackage (rustPwArgs // {
                pname = "pi4audio-graph-manager";
                version = "0.1.0";
                src = ./src/graph-manager;
                cargoLock.lockFile = ./src/graph-manager/Cargo.lock;
              });
              level-bridge = pkgs.rustPlatform.buildRustPackage (rustPwArgs // {
                pname = "level-bridge";
                version = "0.1.0";
                src = workspaceSrc;
                cargoLock.lockFile = ./src/Cargo.lock;
                buildAndTestSubdir = "level-bridge";
              });
              pcm-bridge = pkgs.rustPlatform.buildRustPackage (rustPwArgs // {
                pname = "pcm-bridge";
                version = "0.1.0";
                src = workspaceSrc;
                cargoLock.lockFile = ./src/Cargo.lock;
                buildAndTestSubdir = "pcm-bridge";
              });
              signal-gen = pkgs.rustPlatform.buildRustPackage (rustPwArgs // {
                pname = "pi4audio-signal-gen";
                version = "0.1.0";
                src = workspaceSrc;
                cargoLock.lockFile = ./src/Cargo.lock;
                buildAndTestSubdir = "signal-gen";
              });
            };
          };

          # Shared modules for both configurations.
          sharedModules = [
            nixos-hardware.nixosModules.raspberry-pi-4
            ./nix/nixos/configuration.nix
          ];
        in
        {
          # SD card image configuration (T-072-17).
          # Usage: nix build .#images.sd-card
          mugge = nixpkgs.lib.nixosSystem {
            inherit system;
            specialArgs = sharedSpecialArgs;
            modules = sharedModules ++ [
              ./nix/nixos/sd-image.nix
            ];
          };

          # nixos-anywhere deployment configuration (T-072-18).
          # Usage: nixos-anywhere --flake .#mugge-deploy root@192.168.178.35
          # Also supports incremental upgrades (T-072-19):
          #   nixos-rebuild switch --flake .#mugge-deploy --target-host root@192.168.178.35
          mugge-deploy = nixpkgs.lib.nixosSystem {
            inherit system;
            specialArgs = sharedSpecialArgs;
            modules = sharedModules ++ [
              disko.nixosModules.disko
              ./nix/nixos/disko.nix
            ];
          };
        };

      # T-072-17: SD card image output.
      # Usage: nix build .#images.sd-card
      # Produces a compressed .img.zst flashable onto an SD card for Pi 4B.
      images.sd-card = self.nixosConfigurations.mugge.config.system.build.sdImage;
    };
}
