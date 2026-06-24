import json
from typing import Dict, Any, List

class PolicyEngine:
    """Working policy engine that translates sensing context into swarm actions."""

    def __init__(self):
        self.policies = {
            "high_occupancy": self._high_occupancy_policy,
            "anomaly": self._anomaly_policy,
            "empty_hall": self._empty_hall_policy,
        }

    def evaluate(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        actions = []
        data_type = context.get("type", "")

        if data_type == "FULL_CONTEXT_UPDATE":
            tracks = context.get("tracks", [])
            events = context.get("events", [])

            if any("ANOMALY" in str(e) for e in events):
                actions.append(self.policies["anomaly"](context))

            elif len(tracks) >= 3:
                actions.append(self.policies["high_occupancy"](context))

            elif len(tracks) == 0:
                actions.append(self.policies["empty_hall"](context))

        return [a for a in actions if a]

    def _high_occupancy_policy(self, context):
        return {
            "action": "scale_down",
            "factor": 0.6,
            "reason": "high_physical_occupancy",
            "priority": "high",
            "source": "sensing"
        }

    def _anomaly_policy(self, context):
        return {
            "action": "security_mode",
            "reason": "physical_anomaly_detected",
            "duration_minutes": 10,
            "priority": "critical",
            "source": "sensing"
        }

    def _empty_hall_policy(self, context):
        return {
            "action": "scale_up",
            "factor": 1.2,
            "reason": "no_physical_presence",
            "priority": "medium",
            "source": "sensing"
        }

if __name__ == "__main__":
    engine = PolicyEngine()
    sample_context = {
        "type": "FULL_CONTEXT_UPDATE",
        "tracks": [{"id": 1}, {"id": 2}, {"id": 3}],
        "events": []
    }
    print(engine.evaluate(sample_context))