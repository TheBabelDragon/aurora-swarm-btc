"""
Example policies showing how aurora-swarm-btc can react to physical sensing data.

These can be expanded into real scheduler logic.
"""

def handle_occupancy(data):
    count = data.get("count", 0)
    if count > 3:
        return {"action": "reduce_power", "factor": 0.6, "reason": "high_occupancy"}
    elif count == 0:
        return {"action": "increase_power", "factor": 1.1, "reason": "empty_hall"}
    return {"action": "maintain", "reason": "normal_occupancy"}

def handle_anomaly(data):
    return {
        "action": "security_alert",
        "reason": data.get("type", "unknown_anomaly"),
        "duration_minutes": 10
    }

# Example usage
if __name__ == "__main__":
    event = {"type": "OCCUPANCY_DETECTED", "count": 4}
    print(handle_occupancy(event))