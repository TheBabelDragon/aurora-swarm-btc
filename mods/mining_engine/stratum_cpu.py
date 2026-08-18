"""
Reliable pure-Python stratum CPU miner.

Critical: extranonce1 may be empty string (Braiins). Empty is valid.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
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


def _parse_pool(url: str) -> Tuple[str, int]:
    u = urlparse(url if "://" in url else "stratum+tcp://" + url)
    return u.hostname or "stratum.braiins.com", int(u.port or 3333)


def _diff_to_target(diff: float) -> int:
    if diff <= 0:
        diff = 1.0
    max_target = 0x00000000FFFF0000000000000000000000000000000000000000000000000000
    return int(max_target / diff)


class StratumCpuMiner:
    def __init__(
        self,
        pool_url: str,
        username: str,
        password: str = "x",
        threads: int = 0,
        line_queue: Optional[queue.Queue] = None,
        comms: Any = None,
        coin: str = "BTC",
    ):
        self.pool_url = pool_url
        self.username = username
        self.password = password
        cpus = os.cpu_count() or 2
        self.threads = max(1, min(threads if threads and threads > 0 else cpus, cpus * 2))
        self.lines: queue.Queue = line_queue if line_queue is not None else queue.Queue(maxsize=500)
        self.comms = comms
        self.coin = coin

        self._sock: Optional[socket.socket] = None
        self._stop = threading.Event()
        self._msg_id = 0

        self._job_lock = threading.Lock()
        self._job: Optional[Dict[str, Any]] = None
        self._extranonce1 = ""  # may legitimately stay empty (Braiins)
        self._en1_ready = False  # set True after subscribe result
        self._extranonce2_size = 4
        self._difficulty = 1.0
        self._header_prefix: Optional[bytes] = None
        self._job_id: Optional[str] = None
        self._current_en2 = b"\x00" * 4
        self._target = _diff_to_target(1.0)

        self._hashes = 0
        self._hashes_lock = threading.Lock()
        self._hashrate_hs = 0.0
        self._last_hr_t = time.time()
        self._last_hr_hashes = 0

        self._workers: List[threading.Thread] = []
        self._reader: Optional[threading.Thread] = None
        self._hr_thread: Optional[threading.Thread] = None
        self.last_error = ""

    def get_hashrate_hs(self) -> float:
        return float(self._hashrate_hs)

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
        host, port = _parse_pool(self.pool_url)
        try:
            self._sock = socket.create_connection((host, port), timeout=20)
            self._sock.settimeout(30)
            self._rpc("mining.subscribe", ["aurora-cpu/0.5"])
            self._rpc("mining.authorize", [self.username, self.password])
            self._emit(f"Connected {host}:{port} as {self.username}")
            self.last_error = ""
            return True
        except Exception as e:
            self.last_error = str(e)
            self._emit(f"Connect failed: {e}")
            logger.error(f"stratum connect: {e}")
            return False

    def _rebuild_prefix(self):
        job = self._job
        if not job or not self._en1_ready:
            self._header_prefix = None
            return
        try:
            en2_size = max(1, int(self._extranonce2_size))
            en2 = struct.pack(">Q", int(time.time() * 1000) & 0xFFFFFFFFFFFFFFFF)[-en2_size:]
            en2 = en2.ljust(en2_size, b"\x00")
            self._current_en2 = en2
            coinbase = (
                bytes.fromhex(job["coinb1"])
                + bytes.fromhex(self._extranonce1 or "")
                + en2
                + bytes.fromhex(job["coinb2"])
            )
            merkle = _sha256d(coinbase)
            for branch in job["merkle"]:
                merkle = _sha256d(merkle + bytes.fromhex(branch))
            version = struct.pack("<I", int(job["version"], 16))
            prevhash = bytes.fromhex(job["prevhash"])[::-1]
            merkle_le = merkle[::-1]
            ntime = struct.pack("<I", int(job["ntime"], 16))
            nbits = struct.pack("<I", int(job["nbits"], 16))
            self._header_prefix = version + prevhash + merkle_le + ntime + nbits
            self._job_id = job["job_id"]
            self._target = _diff_to_target(self._difficulty)
        except Exception as e:
            logger.warning(f"rebuild prefix: {e}")
            self.last_error = f"prefix: {e}"
            self._header_prefix = None

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
                    }
                    self._rebuild_prefix()
                if self.comms is not None:
                    try:
                        from .job_ledger import JobLedger

                        host, _ = _parse_pool(self.pool_url)
                        entry = JobLedger(self.comms).record(params, coin=self.coin, pool_host=host)
                        self._emit(f"Job score={entry.get('score')} id={str(entry.get('job_id'))[:12]}")
                    except Exception:
                        pass
                if self._header_prefix:
                    self._emit("Job ready — hashing")
        elif method == "mining.set_difficulty":
            try:
                self._difficulty = float((msg.get("params") or [1])[0])
                with self._job_lock:
                    self._rebuild_prefix()
                self._emit(f"Difficulty set to {self._difficulty}")
            except Exception:
                pass
        elif msg.get("id") is not None and "result" in msg:
            res = msg.get("result")
            # subscribe: [ [subs], extranonce1, extranonce2_size ] — en1 may be ""
            if isinstance(res, list) and len(res) >= 3:
                en1 = res[1]
                if isinstance(en1, str):
                    with self._job_lock:
                        self._extranonce1 = en1  # empty string is valid
                        self._en1_ready = True
                        try:
                            self._extranonce2_size = int(res[2])
                        except Exception:
                            self._extranonce2_size = 4
                        self._rebuild_prefix()
                    self._emit(f"Subscribed en1_len={len(en1)} en2_size={self._extranonce2_size}")
            if msg.get("result") is True:
                self._emit("Authorized")
            if msg.get("error"):
                self._emit(f"RPC error {msg.get('error')}")

    def _reader_loop(self):
        buf = ""
        assert self._sock
        while not self._stop.is_set():
            try:
                chunk = self._sock.recv(8192)
                if not chunk:
                    self._emit("Pool connection closed")
                    self.last_error = "pool closed"
                    break
                buf += chunk.decode(errors="ignore")
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    if line.strip():
                        self._handle_line(line.strip())
            except socket.timeout:
                continue
            except Exception as e:
                self.last_error = str(e)
                self._emit(f"Reader error: {e}")
                break

    def _mine_loop(self, tid: int):
        nonce = tid
        step = max(1, self.threads)
        while not self._stop.is_set():
            with self._job_lock:
                prefix = self._header_prefix
                target = self._target
                job_id = self._job_id
                en2 = self._current_en2
                ntime = self._job["ntime"] if self._job else None
            if not prefix:
                time.sleep(0.05)
                continue
            local = 0
            for _ in range(25_000):
                if self._stop.is_set():
                    break
                header = prefix + struct.pack("<I", nonce & 0xFFFFFFFF)
                h = _sha256d(header)
                local += 1
                if int.from_bytes(h[::-1], "big") <= target:
                    self._submit(job_id, en2.hex(), ntime, nonce)
                nonce = (nonce + step) & 0xFFFFFFFF
            with self._hashes_lock:
                self._hashes += local

    def _submit(self, job_id, en2_hex, ntime, nonce):
        try:
            self._rpc(
                "mining.submit",
                [self.username, job_id, en2_hex, ntime, f"{nonce:08x}"],
            )
            self._emit(f"Share submitted nonce={nonce:08x} job={job_id}")
        except Exception as e:
            self._emit(f"Submit failed: {e}")

    def _hr_loop(self):
        while not self._stop.is_set():
            time.sleep(2.0)
            now = time.time()
            with self._hashes_lock:
                total = self._hashes
            delta = total - self._last_hr_hashes
            self._last_hr_hashes = total
            dt = max(0.001, now - self._last_hr_t)
            self._last_hr_t = now
            rate = delta / dt
            self._hashrate_hs = rate
            if rate >= 1e6:
                self._emit(f"{rate/1e6:.2f} MH/s")
            elif rate >= 1e3:
                self._emit(f"{rate/1e3:.2f} KH/s")
            else:
                self._emit(f"{rate:.0f} H/s")

    def start(self) -> bool:
        self._stop.clear()
        self._en1_ready = False
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
        self._emit(f"CPU miner workers={self.threads} cores={os.cpu_count()}")
        return True

    def stop(self):
        self._stop.set()
        try:
            if self._sock:
                self._sock.close()
        except Exception:
            pass
        self._sock = None
        self._hashrate_hs = 0.0

    def running(self) -> bool:
        return not self._stop.is_set() and self._sock is not None
