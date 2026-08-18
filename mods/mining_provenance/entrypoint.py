"""Register mining_provenance capability."""

from __future__ import annotations

import logging

logger = logging.getLogger("aurora.mining_provenance.entry")


def register(comms, **kwargs):
    try:
        if hasattr(comms, "register_node"):
            comms.register_node(
                node_type="worker",
                capabilities=["mining_provenance"],
                metadata={"mod": "mining_provenance", "version": "0.1.0"},
            )
        logger.info("mining_provenance registered")
    except Exception as e:
        logger.debug(f"register: {e}")
    return True
