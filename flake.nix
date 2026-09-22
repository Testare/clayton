{
  description = "Clayton: HGSS Safari Zone RNG manipulation toolkit";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs { inherit system; };
        py = pkgs.python3Packages;

        # The Clayton desktop app: claytonlib (pure-stdlib core) + app/ (pywebview
        # shell) built into a `clayton` executable. pywebview's GTK backend needs a
        # system webview (webkitgtk) and the GObject typelibs, wired up by
        # wrapGAppsHook3 + gobject-introspection.
        clayton = py.buildPythonApplication {
          pname = "clayton";
          version = "0.1.0";
          pyproject = true;
          src = ./.;

          build-system = [ py.setuptools ];

          nativeBuildInputs = [
            pkgs.wrapGAppsHook3
            pkgs.gobject-introspection
          ];

          buildInputs = [
            pkgs.gtk3
            pkgs.webkitgtk_4_1
          ];

          dependencies = [
            py.pywebview
            py.pygobject3
          ];

          # buildPythonApplication wraps the console script itself; let it, but fold in
          # the GApps wrapper args (GI_TYPELIB_PATH, GDK/GSettings, …) so the GTK webview
          # is found at runtime. This is the documented pattern for Python GTK apps.
          dontWrapGApps = true;
          preFixup = ''
            makeWrapperArgs+=("''${gappsWrapperArgs[@]}")
          '';

          # Desktop integration: without a .desktop entry and themed icons the app shows
          # up as a nameless window with a generic icon, however good the icon file is.
          # The entry's StartupWMClass matches the WM_CLASS that app/main.py pins via
          # GLib.set_prgname, which is what lets the taskbar merge window and launcher.
          postInstall = ''
            install -Dm644 packaging/clayton.desktop \
              $out/share/applications/clayton.desktop
            for size in 16 24 32 48 64 128 256 512; do
              install -Dm644 "packaging/icons/''${size}x''${size}/clayton.png" \
                "$out/share/icons/hicolor/''${size}x''${size}/apps/clayton.png"
            done
          '';

          # The unittest suite reads dev-only data files; skip it in the sandbox and
          # just confirm the packages import.
          doCheck = false;
          pythonImportsCheck = [ "claytonlib" "app" ];

          meta = with pkgs.lib; {
            description = "HGSS Safari Zone RNG manipulation toolkit (desktop app)";
            mainProgram = "clayton";
            desktopFile = "clayton.desktop";
            platforms = platforms.linux;
          };
        };
      in
      {
        packages.default = clayton;
        packages.clayton = clayton;

        # `nix run .#clayton` (or `nix run .`) launches the window.
        apps.default = {
          type = "app";
          program = "${clayton}/bin/clayton";
        };
        apps.clayton = self.apps.${system}.default;

        devShells.default = pkgs.mkShell {
          buildInputs = with pkgs; [
            # ARM Embedded Toolchain (includes arm-none-eabi-gdb)
            gcc-arm-embedded

            # Python environment with common dev tools
            (python3.withPackages (ps: with ps; [
              ruff
              ipython
              jupyter
              notebook
              # Desktop-app deps, so `python -m app.main` runs inside `nix develop`.
              pywebview
              pygobject3
            ]))

            # System webview + typelibs for pywebview's GTK backend
            gtk3
            webkitgtk_4_1
            gobject-introspection

            ruff
            git
          ];

          shellHook = ''
            echo "--- Clayton Development Environment ---"
            echo "arm-none-eabi-gdb: $(arm-none-eabi-gdb --version | head -n 1)"
            echo "Python:            $(python --version)"
            echo "Run the app:       python -m app.main   (or: nix run .#clayton)"
            echo "---------------------------------------"
          '';
        };
      });
}
