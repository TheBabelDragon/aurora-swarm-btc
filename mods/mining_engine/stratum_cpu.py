"""
Pure-Python Bitcoin stratum miner — multiprocess CPU SHA256d.

Uses processes (not threads) so hashlib isn't stuck on the GIL.
Default workers = all logical CPUs.
"""

from __future__ import annotations

import hashlib
import json
import logging
import multiprocessing as mp
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


def _parse_pool(url: str) -> Tuple[str, int, bool]:
    u = urlparse(url if "://" in url else "stratum+tcp://" + url)
    host = u.hostname or "stratum.braiins.com"
    port = u.port or 3333
    return host, int(port), False


def _diff_to_target(diff: float) -> int:
    if diff <= 0:
        diff = 1.0
    max_target = 0x00000000FFFF0000000000000000000000000000000000000000000000000000
    return int(max_target / diff)


def _hexrev(h: str) -> bytes:
    return bytes.fromhex(h)[::-1]


def _build_header(job: Dict[str, Any], extranonce1: str, extranonce2: bytes, nonce: int) -> bytes:
    coinbase = (
        bytes.fromhex(job["coinb1"])
        + bytes.fromhex(extranonce1)
        + extranonce2
        + bytes.fromhex(job["coinb2"])
    )
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


def _worker_process(
    tid: int,
    nworkers: int,
    job_box: Any,
    stop_event: Any,
    hash_counter: Any,
    share_queue: Any,
):
    """Run in a child process — full core utilization."""
    while not stop_event.is_set():
        try:
            snap = dict(job_box)
        except Exception:
            time.sleep(0.05)
            continue
        job = snap.get("job")
        en1 = snap.get("extranonce1") or ""
        en2_size = int(snap.get("extranonce2_size") or 4)
        diff = float(snap.get("difficulty") or 1.0)
        if not job or not en1:
            time.sleep(0.05)
            continue
        target = _diff_to_target(diff)
        # unique extranonce2 per process + time
        base = (int(time.time()) ^ (os.getpid() << 8) ^ tid) & 0xFFFFFFFF
        extranonce2 = struct.pack(">I", base)[:en2_size].ljust(en2_size, b"\x00")
        # stride nonces across workers
        nonce = tid
        batch = 0
        try:
            while not stop_event.is_set() and batch < 250_000:
                # re-check job id occasionally
                if batch and batch % 50_000 == 0:
                    try:
                        if dict(job_box).get("job", {}).get("job_id") != job.get("job_id"):
                            break
                    except Exception:
                        break
                header = _build_header(job, en1, extranonce2, nonce)
                h = _sha256d(header)
                with hash_counter.get_lock():
                    hash_counter.value += 1
                val = int.from_bytes(h[::-1], "big")
                if val <= target:
                    share_queue.put(
                        {
                            "job_id": job["job_id"],
                            "extranonce2": extranonce2.hex(),
                            "ntime": job["ntime"],
                            "nonce": f"{nonce:08x}",
                        }
                    )
                nonce = (nonce + nworkers) & 0xFFFFFFFF
                batch += 1
        except Exception:
            time.sleep(0.01)


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
        if threads and threads > 0:
            self.threads = max(1, min(int(threads), cpus * 2))
        else:
            self.threads = cpus  # all cores by default
        self.lines: queue.Queue = line_queue if line_queue is not None else queue.Queue(maxsize=500)
        self.comms = comms
        self.coin = coin
        self._sock: Optional[socket.socket] = None
        self._stop = threading.Event()
        self._msg_id = 0
        self._reader: Optional[threading.Thread] = None
        self._hr_thread: Optional[threading.Thread] = None
        self._share_thread: Optional[threading.Thread] = None
        self._procs: List[mp.Process] = []
        self._mp_stop = None
        self._job_box = None
        self._hash_counter = None
        self._share_q = None
        self._last_hr_t = time.time()
        self._last_hashes = 0

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
            self._rpc("mining.subscribe", ["aurora-cpu-mp/0.3"])
            self._rpc("mining.authorize", [self.username, self.password])
            self._emit(f"Connected {host}:{port} as {self.username}")
            return True
        except Exception as e:
            self._emit(f"Connect failed: {e}")
            logger.error(f"stratum connect: {e}")
            return False

    def _set_job_box(self, **kwargs):
        if self._job_box is None:
            return
        for k, v in kwargs.items():
            self._job_box[k] = v

    def _handle_line(self, raw: str):
        try:
            msg = json.loads(raw)
        except Exception:
            return
        method = msg.get("method")
        if method == "mining.notify":
            params = msg.get("params") or []
            if len(params) >= 8:
                job = {
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
                self._set_job_box(job=job)
                if self.comms is not None:
                    try:
                        from .job_ledger import JobLedger

                        host, _, _ = _parse_pool(self.pool_url)
                        entry = JobLedger(self.comms).record(params, coin=self.coin, pool_host=host)
                        self._emit(f"Job score={entry.get('score')} id={str(entry.get('job_id'))[:12]}")
                    except Exception as e:
                        logger.debug(f"job ledger: {e}")
        elif method == "mining.set_difficulty":
            try:
                d = float((msg.get("params") or [1])[0])
                self._set_job_box(difficulty=d)
                self._emit(f"Difficulty set to {d}")
            except Exception:
                pass
        elif msg.get("id") is not None and "result" in msg:
            res = msg.get("result")
            if isinstance(res, list) and len(res) >= 3 and isinstance(res[1], str):
                en1 = res[1]
                try:
                    en2s = int(res[2])
                except Exception:
                    en2s = 4
                self._set_job_box(extranonce1=en1, extranonce2_size=en2s)
            if msg.get("result") is True:
                self._emit("Authorized")

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

    def _share_loop(self):
        while not self._stop.is_set():
            try:
                if self._share_q is None:
                    time.sleep(0.2)
                    continue
                try:
                    share = self._share_q.get(timeout=0.5)
                except Exception:
                    continue
                if not share:
                    continue
                params = [
                    self.username,
                    share["job_id"],
                    share["extranonce2"],
                    share["ntime"],
                    share["nonce"],
                ]
                try:
                    self._rpc("mining.submit", params)
                    self._emit(f"Share submitted nonce={share['nonce']} job={share['job_id']}")
                except Exception as e:
                    self._emit(f"Submit failed: {e}")
            except Exception:
                time.sleep(0.2)

    def _hr_loop(self):
        while not self._stop.is_set():
            time.sleep(3)
            if self._hash_counter is None:
                continue
            now = time.time()
            total = int(self._hash_counter.value)
            delta = total - self._last_hashes
            self._last_hashes = total
            dt = max(0.001, now - self._last_hr_t)
            self._last_hr_t = now
            rate = delta / dt
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

        # Prefer fork on Linux for speed; spawn is safer cross-platform
        try:
            ctx = mp.get_context("fork")
        except Exception:
            ctx = mp.get_context("spawn")

        self._mp_stop = ctx.Event()
        self._job_box = ctx.Manager().dict()
        self._job_box["job"] = None
        self._job_box["extranonce1"] = ""
        self._job_box["extranonce2_size"] = 4
        self._job_box["difficulty"] = 1.0
        self._hash_counter = ctx.Value("Q", 0)
        self._share_q = ctx.Queue()

        self._reader = threading.Thread(target=self._reader_loop, name="stratum-reader", daemon=True)
        self._reader.start()
        self._share_thread = threading.Thread(target=self._share_loop, name="stratum-share", daemon=True)
        self._share_thread.start()
        self._hr_thread = threading.Thread(target=self._hr_loop, name="stratum-hr", daemon=True)
        self._hr_thread.start()

        self._procs = []
        for i in range(self.threads):
            p = ctx.Process(
                target=_worker_process,
                args=(
                    i,
                    self.threads,
                    self._job_box,
                    self._mp_stop,
                    self._hash_counter,
                    self._share_q,
                ),
                name=f"cpu-hash-{i}",
                daemon=True,
            )
            p.start()
            self._procs.append(p)

        self._emit(f"CPU stratum FULL POWER workers={self.threads} cores={os.cpu_count()} coin={self.coin}")
        return True

    def stop(self):
        self._stop.set()
        if self._mp_stop is not None:
            self._mp_stop.set()
        for p in self._procs:
            try:
                p.terminate()
            except Exception:
                pass
            try:
                p.join(timeout=1.0)
            except Exception:
                pass
        self._procs = []
        try:
            if self._sock:
                self._sock.close()
        except Exception:
            pass
        self._sock = None

    def running(self) -> bool:
        return not self._stop.is_set() and self._sock is not None
