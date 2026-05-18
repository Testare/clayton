{
  description = "Clayton: HGSS Safari Zone RNG manipulation toolkit";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
        };
      in
      {
        devShells.default = pkgs.mkShell {
          buildInputs = with pkgs; [
            # ARM Embedded Toolchain (includes arm-none-eabi-gdb)
            gcc-arm-embedded
            
            # Python environment with common dev tools
            (python310.withPackages (ps: with ps; [
              ruff
              ipython
              jupyter
              notebook
              # Add other packages if needed, but project aims for stdlib
            ]))

            # Additional utilities
            ruff
            git
          ];

          shellHook = ''
            echo "--- Clayton Development Environment ---"
            echo "arm-none-eabi-gdb: $(arm-none-eabi-gdb --version | head -n 1)"
            echo "Python:            $(python --version)"
            echo "---------------------------------------"
          '';
        };
      });
}
