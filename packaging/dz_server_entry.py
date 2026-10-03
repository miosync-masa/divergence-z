"""PyInstaller entry point for the Divergence-Z sidecar (python -m divergence_z.server)."""
import sys

from divergence_z.server.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
