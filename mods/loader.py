"""Simple Mod Loader for Aurora Swarm.

Loads enabled mods and registers their hooks.
"""

import importlib
import json
import os
from pathlib import Path

import logging

logger = logging.getLogger("aurora.mods")


def load_mods(mods_dir: str = "mods") -> dict:
    """Load all enabled mods from the mods directory."""
    loaded_mods = {}
    mods_path = Path(mods_dir)

    if not mods_path.exists():
        logger.warning("Mods directory not found")
        return loaded_mods

    for mod_dir in mods_path.iterdir():
        if not mod_dir.is_dir() or mod_dir.name.startswith("."):
            continue

        manifest_path = mod_dir / "manifest.json"
        if not manifest_path.exists():
            continue

        try:
            with open(manifest_path) as f:
                manifest = json.load(f)

            if not manifest.get("enabled", False):
                continue

            mod_name = manifest["name"]
            entry = manifest.get("entry", "entrypoint.py")

            # Import the entrypoint
            entry_path = mod_dir / entry
            if entry_path.exists():
                spec = importlib.util.spec_from_file_location(mod_name, entry_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                if hasattr(module, "register"):
                    module.register()

                loaded_mods[mod_name] = manifest
                logger.info(f"Loaded mod: {mod_name}")

        except Exception as e:
            logger.error(f"Failed to load mod {mod_dir.name}: {e}")

    return loaded_mods


if __name__ == "__main__":
    load_mods()
