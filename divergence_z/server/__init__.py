"""Divergence-Z sidecar API for the desktop app (Electron / Tauri).

    python -m divergence_z.server            # prints {"event":"ready","port":...,"token":...}
"""

from .app import create_app

__all__ = ["create_app"]
