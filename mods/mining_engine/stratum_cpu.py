"""
Pure-Python Bitcoin stratum miner (CPU SHA256d).

No bfgminer / OpenCL required. Hashrate is modest; shares still go to the
pool under wallet.worker when difficulty is met. This is real mining,
not a simulation — just not GPU-class throughput.
"""

from __future__ import annotations

import hashlib
import json
import logging
import queue
import socket
import struct
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

logger = logging.getLogger("aurora.mining.stratum_cpu")


def _sha256d(b: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(b).digest()).digest()


def _parse_pool(url: str) -> Tuple[str, int, bool]:
    u = urlparse(url if "://" in url else "stratum+tcp://" + url)
    host = u.hostname or "stratum.braiins.com"
    port = u.port or 3333
    return host, int(port), False


def _diff_to_target(diff: float) -> int:
    # target = target1 / difficulty  (simplified; target1 = 0x1d00ffff compact range)
    # Use standard float approach used by many CPU miners
    if diff <= 0:
        diff = 1.0
    # 0x00000000FFFF0000... max target for diff 1 (truncated 256-bit as int)
    max_target = 0x00000000FFFF0000000000000000000000000000000000000000000000000000
    return int(max_target / diff)


def _hexrev(h: str) -> bytes:
    b = bytes.fromhex(h)
    return b[::-1]


class StratumCpuMiner:
    """Minimal stratum client + multi-thread CPU hasher."""

    def __init__(
        self,
        pool_url: str,
        username: str,
        password: str = "x",
        threads: int = 2,
        line_queue: Optional[queue.Queue] = None,
    ):
        self.pool_url = pool_url
        self.username = username
        self.password = password
        self.threads = max(1, min(threads, 32))
        self.lines: queue.Queue = line_queue if line_queue is not None else queue.Queue(maxsize=500)
        self._sock: Optional[socket.socket] = None
        self._stop = threading.Event()
        self._job_lock = threading.Lock()
        self._job: Optional[Dict[str, Any]] = None
        self._extranonce1 = ""
        self._extranonce2_size = 4
        self._difficulty = 1.0
        self._msg_id = 0
        self._hashes = 0
        self._last_hr_t = time.time()
        self._workers: List[threading.Thread] = []
        self._reader: Optional[threading.Thread] = None
        self._hr_thread: Optional[threading.Thread] = None

    def _emit(self, line: str):
        try:
            self.lines.put_nowait(line.rstrip() + "\n")
        except queue.Full:
            pass

    def _rpc(self, method: str, params: list) -> int:
        self._msg_id += 1
        mid = self._msg_id
        payload = json.dumps({"id": mid, "method": method, "params": params}) + "\n"
        assert self._sock
        self._sock.sendall(payload.encode())
        return mid

    def connect(self) -> bool:
        host, port, _ = _parse_pool(self.pool_url)
        try:
            self._sock = socket.create_connection((host, port), timeout=20)
            self._sock.settimeout(30)
            self._rpc("mining.subscribe", ["aurora-cpu/0.1"])
            self._rpc("mining.authorize", [self.username, self.password])
            self._emit(f"Connected {host}:{port} as {self.username}")
            return True
        except Exception as e:
            self._emit(f"Connect failed: {e}")
            logger.error(f"stratum connect: {e}")
            return False

    def _handle_line(self, raw: str):
        try:
            msg = json.loads(raw)
        except Exception:
            return
        method = msg.get("method")
        if method == "mining.notify":
            params = msg.get("params") or []
            if len(params) >= 8:
                with self._job_lock:
                    self._job = {
                        "job_id": params[0],
                        "prevhash": params[1],
                        "coinb1": params[2],
                        "coinb2": params[3],
                        "merkle": params[4] or [],
                        "version": params[5],
                        "nbits": params[6],
                        "ntime": params[7],
                        "clean": params[8] if len(params) > 8 else True,
                    }
        elif method == "mining.set_difficulty":
            try:
                self._difficulty = float((msg.get("params") or [1])[0])
                self._emit(f"Difficulty set to {self._difficulty}")
            except Exception:
                pass
        elif msg.get("id") is not None and "result" in msg:
            # subscribe result: [ [subs], extranonce1, extranonce2_size ]
            res = msg.get("result")
            if isinstance(res, list) and len(res) >= 3 and isinstance(res[1], str):
                self._extranonce1 = res[1]
                try:
                    self._extranonce2_size = int(res[2])
                except Exception:
                    self._extranonce2_size = 4
            if msg.get("result") is True:
                self._emit("Authorized")
            if msg.get("error"):
                self._emit(f"RPC error {msg.get('error')}")

    def _reader_loop(self):
        buf = ""
        assert self._sock
        while not self._stop.is_set():
            try:
                chunk = self._sock.recv(4096)
                if not chunk:
                    self._emit("Pool connection closed")
                    break
                buf += chunk.decode(errors="ignore")
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    if line.strip():
                        self._handle_line(line.strip())
            except socket.timeout:
                continue
            except Exception as e:
                self._emit(f"Reader error: {e}")
                break

    def _build_header(self, job: Dict[str, Any], extranonce2: bytes, nonce: int) -> bytes:
        coinbase = bytes.fromhex(job["coinb1"]) + bytes.fromhex(self._extranonce1) + extranonce2 + bytes.fromhex(job["coinb2"])
        merkle = _sha256d(coinbase)
        for branch in job["merkle"]:
            merkle = _sha256d(merkle + bytes.fromhex(branch))
        version = struct.pack("<I", int(job["version"], 16))
        prevhash = _hexrev(job["prevhash"])
        merkle_le = merkle[::-1]
        ntime = struct.pack("<I", int(job["ntime"], 16))
        nbits = struct.pack("<I", int(job["nbits"], 16))
        nonce_b = struct.pack("<I", nonce & 0xFFFFFFFF)
        return version + prevhash + merkle_le + ntime + nbits + nonce_b

    def _mine_loop(self, tid: int):
        nonce_base = tid * 0x10000000
        while not self._stop.is_set():
            with self._job_lock:
                job = dict(self._job) if self._job else None
                diff = self._difficulty
                en2_size = self._extranonce2_size
            if not job or not self._extranonce1:
                time.sleep(0.2)
                continue
            target = _diff_to_target(diff)
            extranonce2 = struct.pack(">I", int(time.time() * 1000 + tid) & 0xFFFFFFFF)[:en2_size]
            if len(extranonce2) < en2_size:
                extranonce2 = extranonce2.ljust(en2_size, b"\x00")
            for i in range(0x10000):
                if self._stop.is_set():
                    break
                nonce = (nonce_base + i) & 0xFFFFFFFF
                try:
                    header = self._build_header(job, extranonce2, nonce)
                except Exception:
                    break
                h = _sha256d(header)
                self._hashes += 1
                # hash as little-endian uint256
                val = int.from_bytes(h[::-1], "big")
                if val <= target:
                    en2_hex = extranonce2.hex()
                    self._submit(job, en2_hex, nonce)
                    self._emit(f"Accepted share? nonce={nonce} job={job['job_id']}")

    def _submit(self, job: Dict[str, Any], extranonce2_hex: str, nonce: int):
        try:
            params = [
                self.username,
                job["job_id"],
                extranonce2_hex,
                job["ntime"],
                f"{nonce:08x}",
            ]
            self._rpc("mining.submit", params)
            self._emit("Share submitted (accepted pending pool)")
        except Exception as e:
            self._emit(f"Submit failed: {e}")

    def _hr_loop(self):
        while not self._stop.is_set():
            time.sleep(5)
            now = time.time()
            dt = max(0.001, now - self._last_hr_t)
            hs = self._hashes
            self._hashes = 0
            self._last_hr_t = now
            rate = hs / dt
            if rate >= 1e9:
                self._emit(f"{rate/1e9:.3f} GH/s")
            elif rate >= 1e6:
                self._emit(f"{rate/1e6:.2f} MH/s")
            elif rate >= 1e3:
                self._emit(f"{rate/1e3:.2f} KH/s")
            else:
                self._emit(f"{rate:.0f} H/s")

    def start(self) -> bool:
        self._stop.clear()
        if not self.connect():
            return False
        self._reader = threading.Thread(target=self._reader_loop, name="stratum-reader", daemon=True)
        self._reader.start()
        self._hr_thread = threading.Thread(target=self._hr_loop, name="stratum-hr", daemon=True)
        self._hr_thread.start()
        self._workers = []
        for i in range(self.threads):
            t = threading.Thread(target=self._mine_loop, args=(i,), name=f"cpu-mine-{i}", daemon=True)
            t.start()
            self._workers.append(t)
        self._emit(f"CPU stratum miner started threads={self.threads}")
        return True

    def stop(self):
        self._stop.set()
        try:
            if self._sock:
                self._sock.close()
        except Exception:
            pass
        self._sock = None

    def running(self) -> bool:
        return not self._stop.is_set() and self._sock is not None
