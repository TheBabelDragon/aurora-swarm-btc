"""Simple Mod Loader for Aurora Swarm.

Loads enabled mods and registers their hooks.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger("aurora.mods")


def _exec_entrypoint(mod_dir: Path, entry_path: Path, mod_name: str):
    """Prefer package import so relative imports inside mods work."""
    pkg_name = f"mods.{mod_dir.name}"
    entry_mod = entry_path.stem
    module_name = f"{pkg_name}.{entry_mod}"

    try:
        return importlib.import_module(module_name)
    except Exception as pkg_exc:
        logger.debug("package import failed for %s (%s); falling back to file spec", module_name, pkg_exc)

    spec = importlib.util.spec_from_file_location(f"aurora_mod_{mod_name}", entry_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load spec for {mod_name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_mods(mods_dir: str = "mods") -> dict:
    """Load all enabled mods from the mods directory."""
    loaded_mods = {}
    mods_path = Path(mods_dir)

    if not mods_path.exists():
        logger.warning("Mods directory not found: %s", mods_path)
        return loaded_mods

    repo_root = mods_path.resolve().parent
    root_str = str(repo_root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

    for mod_dir in sorted(mods_path.iterdir()):
        if not mod_dir.is_dir() or mod_dir.name.startswith(".") or mod_dir.name == "__pycache__":
            continue

        manifest_path = mod_dir / "manifest.json"
        if not manifest_path.exists():
            continue

        try:
            with open(manifest_path) as f:
                manifest = json.load(f)

            if not manifest.get("enabled", False):
                logger.debug("Skipping disabled mod: %s", mod_dir.name)
                continue

            mod_name = manifest.get("name") or mod_dir.name
            entry = manifest.get("entry") or manifest.get("entrypoint") or "entrypoint.py"
            entry_path = mod_dir / entry
            if not entry_path.exists():
                logger.error("Missing entry for %s: %s", mod_name, entry_path)
                continue

            # Make `from .hooks...` work even if the mod had no package marker.
            init_py = mod_dir / "__init__.py"
            if not init_py.exists():
                init_py.write_text("")
            hooks_dir = mod_dir / "hooks"
            if hooks_dir.is_dir() and not (hooks_dir / "__init__.py").exists():
                (hooks_dir / "__init__.py").write_text("")

            module = _exec_entrypoint(mod_dir, entry_path, mod_name)

            if hasattr(module, "register"):
                module.register()

            loaded_mods[mod_name] = manifest
            logger.info("Loaded mod: %s", mod_name)

        except Exception as e:
            logger.error("Failed to load mod %s: %s", mod_dir.name, e)

    return loaded_mods


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    loaded = load_mods()
    print(f"loaded={list(loaded)}")
