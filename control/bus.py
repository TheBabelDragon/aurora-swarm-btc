import os
import json
import redis
from typing import Any

class Bus:
    def __init__(self):
        self.r = redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"), 
                               socket_connect_timeout=10, socket_timeout=10)

    def set(self, key: str, value: Any, expire: int = 0):
        full_key = f"aurora:{key}"
        val = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
        self.r.set(full_key, val)
        if expire > 0:
            self.r.expire(full_key, expire)

    def get(self, key: str, default=None):
        val = self.r.get(f"aurora:{key}")
        if val is None:
            return default
        try:
            return json.loads(val)
        except:
            return val

    def increment(self, key: str, amount: int = 1):
        return self.r.incrby(f"aurora:{key}", amount)

    def publish(self, channel: str, message: Any):
        if isinstance(message, (dict, list)):
            message = json.dumps(message)
        self.r.publish(f"aurora:{channel}", message)