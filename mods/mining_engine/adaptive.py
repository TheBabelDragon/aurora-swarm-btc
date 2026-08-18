"""
Adaptive intensity — trend-aware, thermal-aware when sensors exist.

Does not claim optimal hashrate physics; nudges intensity from observed
efficiency and optional thermal_aware_scheduler hints.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import Deque, Optional, Tuple

logger = logging.getLogger("aurora.mining.adaptive")


class AdaptiveIntensity:
    def __init__(
        self,
        *,
        min_i: int = 14,
        max_i: int = 20,
        window: int = 12,
    ):
        self.min_i = min_i
        self.max_i = max_i
        self.samples: Deque[Tuple[float, float]] = deque(maxlen=window)  # (ts, ghs)
        self.current = 19

    def observe(self, hashrate_ghs: float):
        self.samples.append((time.time(), float(hashrate_ghs)))

    def suggest(
        self,
        current_intensity: int,
        *,
        thermal_scale: Optional[float] = None,
    ) -> int:
        self.current = int(current_intensity)
        if len(self.samples) < 4:
            base = self.current
        else:
            rates = [g for _, g in self.samples]
            avg = sum(rates) / len(rates)
            recent = sum(rates[-3:]) / 3.0
            # Rising → can push intensity; collapsing → ease off
            if recent > avg * 1.05 and self.current < self.max_i:
                base = self.current + 1
            elif recent < avg * 0.85 and self.current > self.min_i:
                base = self.current - 1
            else:
                base = self.current

        if thermal_scale is not None:
            # thermal_scale 1.0 = cool, 0.5 = hot → bias down
            if thermal_scale < 0.7 and base > self.min_i:
                base -= 1
            elif thermal_scale > 0.95 and base < self.max_i:
                base = min(self.max_i, base + 0)  # hold; don't auto-spike on cool

        return max(self.min_i, min(self.max_i, int(base)))

    def thermal_hint_from_comms(self, comms) -> Optional[float]:
        try:
            raw = comms.get_state("thermal:scale") or comms.get_state("sensing:thermal_scale")
            if raw is None:
                return None
            if isinstance(raw, dict):
                return float(raw.get("scale", 1.0))
            return float(raw)
        except Exception:
            return None
