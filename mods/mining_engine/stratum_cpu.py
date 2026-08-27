"""CPU stratum miner — process workers (escape the GIL), robust handshake.

Empty extranonce1 is valid (Braiins). Set AURORA_MINE_OFFLINE=1 to hash
dummy work without a pool (proves the hasher; does not earn shares).
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
from multiprocessing import Process, Value
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


def _hash_process(tid: int, step: int, stop_flag, hash_counter, prefix_buf, prefix_ready):
    """Module-level so it pickles into a child process."""
    nonce = tid & 0xFFFFFFFF
    dummy = b"\x00" * 76
    while stop_flag.value == 0:
        if prefix_ready.value == 0:
            header = dummy + struct.pack("<I", nonce)
        else:
            header = bytes(prefix_buf) + struct.pack("<I", nonce)
        _sha256d(header)
        nonce = (nonce + step) & 0xFFFFFFFF
        if (nonce & 0x3FF) == (tid & 0x3FF):
            with hash_counter.get_lock():
                hash_counter.value += 1024


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
        offline = os.getenv("AURORA_MINE_OFFLINE", "0") in ("1", "true", "True")
        self.offline = offline
        # Processes, not threads — 1 per core is the useful default
        default_n = cpus if offline else max(1, cpus)
        self.threads = max(1, threads if threads and threads > 0 else default_n)
        self.lines: queue.Queue = line_queue if line_queue is not None else queue.Queue(maxsize=500)
        self.comms = comms
        self.coin = coin

        self._sock: Optional[socket.socket] = None
        self._stop = threading.Event()
        self._msg_id = 0

        self._job_lock = threading.Lock()
        self._job: Optional[Dict[str, Any]] = None
        self._extranonce1 = ""
        self._en1_ready = False
        self._extranonce2_size = 4
        self._difficulty = 1.0
        self._header_prefix: Optional[bytes] = None
        self._job_id: Optional[str] = None
        self._current_en2 = b"\x00" * 4
        self._target = _diff_to_target(1.0)
        self.job_ready = False
        self.authorized = False

        self._hashrate_hs = 0.0
        self._last_hr_t = time.time()
        self._last_hr_hashes = 0

        self._workers: List[Process] = []
        self._reader: Optional[threading.Thread] = None
        self._hr_thread: Optional[threading.Thread] = None
        self.last_error = ""

        self._stop_flag = Value("i", 0)
        self._hash_counter = Value("Q", 0)
        self._prefix_buf = None
        self._prefix_ready = Value("i", 1 if offline else 0)

    def get_hashrate_hs(self) -> float:
        return float(self._hashrate_hs)

    def _emit(self, line: str):
        try:
            self.lines.put_nowait(line.rstrip() + "\n")
        except queue.Full:
            pass
        logger.info(line)

    def _rpc(self, method: str, params: list) -> int:
        self._msg_id += 1
        mid = self._msg_id
        payload = json.dumps({"id": mid, "method": method, "params": params}) + "\n"
        assert self._sock
        self._sock.sendall(payload.encode())
        return mid

    def _apply_subscribe(self, res: Any) -> bool:
        """Accept common stratum subscribe shapes."""
        en1 = None
        en2 = 4
        if isinstance(res, list) and len(res) >= 3 and isinstance(res[1], str):
            en1, en2 = res[1], res[2]
        elif isinstance(res, dict):
            en1 = res.get("extranonce1") or res.get("extra_nonce1")
            en2 = res.get("extranonce2_size") or res.get("extra_nonce2_size") or 4
        if en1 is None:
            return False
        with self._job_lock:
            self._extranonce1 = en1 if isinstance(en1, str) else ""
            self._en1_ready = True
            try:
                self._extranonce2_size = int(en2)
            except Exception:
                self._extranonce2_size = 4
            self._rebuild_prefix()
        self._emit(f"Subscribed en1_len={len(self._extranonce1)} en2_size={self._extranonce2_size}")
        return True

    def connect(self) -> bool:
        if self.offline:
            self.last_error = ""
            self._emit("OFFLINE hasher — no pool (AURORA_MINE_OFFLINE=1)")
            return True
        host, port = _parse_pool(self.pool_url)
        try:
            self._sock = socket.create_connection((host, port), timeout=12)
            self._sock.settimeout(20)
            self._rpc("mining.subscribe", ["aurora-cpu/0.7"])
            self._rpc("mining.authorize", [self.username, self.password])
            self._emit(f"Connected {host}:{port} as {self.username}")
            self.last_error = ""
            return True
        except socket.timeout:
            self.last_error = f"timeout connecting {host}:{port}"
        except socket.gaierror as e:
            self.last_error = f"DNS {host}: {e}"
        except OSError as e:
            self.last_error = f"socket {host}:{port}: {e}"
        except Exception as e:
            self.last_error = str(e)
        self._emit(f"Connect failed: {self.last_error}")
        logger.error("stratum connect: %s", self.last_error)
        try:
            if self._sock:
                self._sock.close()
        except Exception:
            pass
        self._sock = None
        return False

    def _rebuild_prefix(self):
        job = self._job
        if not job or not self._en1_ready:
            self._header_prefix = None
            self.job_ready = False
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
            prefix = version + prevhash + merkle_le + ntime + nbits
            self._header_prefix = prefix
            self._job_id = job["job_id"]
            self._target = _diff_to_target(self._difficulty)
            self.job_ready = len(prefix) == 76
            if self._prefix_buf is not None and self.job_ready:
                for i, b in enumerate(prefix):
                    self._prefix_buf[i] = b
                self._prefix_ready.value = 1
        except Exception as e:
            logger.warning("rebuild prefix: %s", e)
            self.last_error = f"prefix: {e}"
            self._header_prefix = None
            self.job_ready = False

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
                if self.job_ready:
                    self._emit("Job ready — hashing")
                    self.last_error = ""
        elif method == "mining.set_difficulty":
            try:
                self._difficulty = float((msg.get("params") or [1])[0])
                with self._job_lock:
                    self._rebuild_prefix()
                self._emit(f"Difficulty set to {self._difficulty}")
            except Exception:
                pass
        elif msg.get("id") is not None:
            if msg.get("error"):
                self.last_error = str(msg.get("error"))
                self._emit(f"RPC error: {self.last_error}")
                return
            res = msg.get("result")
            if res is True:
                self.authorized = True
                self._emit("Authorized")
                return
            if res is False:
                self.last_error = "authorize rejected — check MINING_WALLET"
                self._emit(self.last_error)
                return
            self._apply_subscribe(res)

    def _reader_loop(self):
        buf = ""
        if not self._sock:
            return
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

    def _hr_loop(self):
        while not self._stop.is_set():
            time.sleep(1.5)
            now = time.time()
            total = int(self._hash_counter.value)
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

    def _spawn_workers(self):
        from multiprocessing import Array

        self._stop_flag.value = 0
        self._hash_counter.value = 0
        self._prefix_buf = Array("B", 76)
        dummy = b"\x00" * 76
        for i, b in enumerate(dummy):
            self._prefix_buf[i] = b
        if self.offline:
            self._prefix_ready.value = 1
        self._workers = []
        for i in range(self.threads):
            p = Process(
                target=_hash_process,
                args=(
                    i,
                    self.threads,
                    self._stop_flag,
                    self._hash_counter,
                    self._prefix_buf,
                    self._prefix_ready,
                ),
                name=f"cpu-mine-{i}",
                daemon=True,
            )
            p.start()
            self._workers.append(p)
        self._emit(f"CPU hasher processes={self.threads} cores={os.cpu_count()} offline={self.offline}")

    def start(self) -> bool:
        self._stop.clear()
        self._en1_ready = self.offline
        self.job_ready = self.offline
        if not self.connect():
            return False
        self._spawn_workers()
        if not self.offline:
            self._reader = threading.Thread(target=self._reader_loop, name="stratum-reader", daemon=True)
            self._reader.start()
        self._hr_thread = threading.Thread(target=self._hr_loop, name="stratum-hr", daemon=True)
        self._hr_thread.start()
        return True

    def stop(self):
        self._stop.set()
        try:
            self._stop_flag.value = 1
        except Exception:
            pass
        for p in self._workers:
            try:
                p.terminate()
            except Exception:
                pass
        self._workers = []
        try:
            if self._sock:
                self._sock.close()
        except Exception:
            pass
        self._sock = None
        self._hashrate_hs = 0.0
        self.job_ready = False

    def running(self) -> bool:
        if self._stop.is_set():
            return False
        if self.offline:
            return any(p.is_alive() for p in self._workers)
        return self._sock is not None
