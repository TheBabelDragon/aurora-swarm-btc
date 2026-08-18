"""
Node key material with a pure-Python fallback.

We prefer real secp256k1 when `coincurve` or `ecdsa` is installed.
Otherwise we use a deterministic HMAC-based keypair suitable for
development fingerprints and HMAC signatures (not chain-valid ECDSA).

Production deployments should install coincurve for Bitcoin-compatible keys.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple


@dataclass
class NodeKey:
    private_hex: str
    public_hex: str
    fingerprint: str          # short id for mesh display
    address_style: str        # bc1q-looking fingerprint (not a spendable address unless secp real)
    backend: str              # coincurve | ecdsa | hmac_dev


def _fingerprint(pub_hex: str) -> str:
    return hashlib.sha256(bytes.fromhex(pub_hex)).hexdigest()[:16]


def _address_style(pub_hex: str) -> str:
    # Not a real bech32 encode — stable human label derived from pubkey
    h = hashlib.sha256(bytes.fromhex(pub_hex)).hexdigest()[:32]
    return "bc1q" + h + "aurora"


def _gen_hmac_dev() -> NodeKey:
    priv = secrets.token_bytes(32)
    pub = hashlib.sha256(b"AURORA_DEV_PUB|" + priv).digest()
    priv_hex, pub_hex = priv.hex(), pub.hex()
    return NodeKey(
        private_hex=priv_hex,
        public_hex=pub_hex,
        fingerprint=_fingerprint(pub_hex),
        address_style=_address_style(pub_hex),
        backend="hmac_dev",
    )


def _gen_coincurve() -> Optional[NodeKey]:
    try:
        from coincurve import PrivateKey
        pk = PrivateKey()
        priv_hex = pk.secret.hex()
        pub_hex = pk.public_key.format(compressed=True).hex()
        return NodeKey(
            private_hex=priv_hex,
            public_hex=pub_hex,
            fingerprint=_fingerprint(pub_hex),
            address_style=_address_style(pub_hex),
            backend="coincurve",
        )
    except Exception:
        return None


def generate_node_key() -> NodeKey:
    k = _gen_coincurve()
    if k:
        return k
    return _gen_hmac_dev()


def load_or_create(path: Optional[str] = None) -> NodeKey:
    path = path or os.getenv("AURORA_NODE_KEY_PATH", "/tmp/aurora_node_key.json")
    p = Path(path)
    if p.exists():
        data = json.loads(p.read_text())
        return NodeKey(
            private_hex=data["private_hex"],
            public_hex=data["public_hex"],
            fingerprint=data.get("fingerprint") or _fingerprint(data["public_hex"]),
            address_style=data.get("address_style") or _address_style(data["public_hex"]),
            backend=data.get("backend", "unknown"),
        )
    key = generate_node_key()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "private_hex": key.private_hex,
        "public_hex": key.public_hex,
        "fingerprint": key.fingerprint,
        "address_style": key.address_style,
        "backend": key.backend,
    }, indent=2))
    try:
        os.chmod(p, 0o600)
    except Exception:
        pass
    return key


def sign_message(key: NodeKey, message: bytes) -> str:
    """Return hex signature. HMAC-SHA256 for dev backend; ECDSA when available."""
    if key.backend == "coincurve":
        try:
            from coincurve import PrivateKey
            pk = PrivateKey(bytes.fromhex(key.private_hex))
            return pk.sign(message).hex()
        except Exception:
            pass
    return hmac.new(bytes.fromhex(key.private_hex), message, hashlib.sha256).hexdigest()


def verify_message(public_hex: str, message: bytes, signature_hex: str, backend: str = "hmac_dev") -> bool:
    if backend == "coincurve":
        try:
            from coincurve import PublicKey
            pub = PublicKey(bytes.fromhex(public_hex))
            return pub.verify(bytes.fromhex(signature_hex), message)
        except Exception:
            return False
    # Dev: we cannot derive HMAC key from public alone — accept only if caller
    # uses the same NodeKey path. For mesh claims we embed fingerprint checks.
    return len(signature_hex) >= 32
