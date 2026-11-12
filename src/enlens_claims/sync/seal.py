"""Sealed files for a storage space (0.18.0rc2, roadmap L6): encrypted on this computer before they leave it, signed
by their writer, opened and checked after they are read.

A storage space is somebody else's computer. Everything ENLENS writes there is sealed:

- **encrypted** with the project's key (AES-256-GCM, a fresh 96-bit nonce per file). The key travels only inside an
  invite link, after its `#`, and between the team's copies sealed to each member's own key (`seal_key` / `open_key`,
  X25519 + HKDF-SHA-256 + AES-GCM); the storage never holds it in the clear. When a colleague is removed, a new key
  (a new *epoch*) is made for those who stay; each file says which epoch sealed it.
- **signed** with its writer's own key (Ed25519), over everything before the signature: the format, the header (which
  file this is, which part of the space wrote it, which epoch) and the encrypted bytes. A copy takes a file only when
  its header names the place it was read from and the signature is that part's member's key, as the team's roster
  (signed by the space's keeper) says. A file put in someone else's part is set aside.
- **named without its words** where a name says something: a document's reading and original file are stored under a
  keyed hash of their name (`hidden_name`), so the storage cannot tell which known file is in the corpus.

The library is `cryptography` (pyca), ENLENS's one dependency for this. Nothing here reads or writes a storage.

    blob = MAGIC + len(header) (4 bytes, big-endian) + header (JSON) + ciphertext + signature (64 bytes)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import struct
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

MAGIC = b"ENLENS-SEALED-1\n"
_SIG_CONTEXT = b"ENLENS sealed file signature v1\x00"
_MAX_HEADER = 64 * 1024
SIG_LEN = 64


class SealProblem(ValueError):
    """A file that cannot be opened or trusted; `why` is one of: "format", "place", "writer", "signature", "key",
    "damaged"."""

    def __init__(self, message: str, why: str):
        super().__init__(message)
        self.why = why


def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def unb64(s: str) -> bytes:
    if not isinstance(s, str):
        raise ValueError("not base64")
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def new_key() -> bytes:
    """A new 256-bit key (a project key of one epoch, the key that hides names, a join secret)."""
    return os.urandom(32)


def _derive(key: bytes, info: bytes, n: int = 32) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=n, salt=None, info=info).derive(key)


def hidden_name(names_key: bytes, logical: str) -> str:
    """The name a file is stored under when its own name would say which document it is: 32 hex characters of an HMAC
    with the space's names key. The same in every copy, so each copy finds a file written once for the team."""
    return hmac.new(_derive(names_key, b"ENLENS names v1"), logical.encode("utf-8"), hashlib.sha256).hexdigest()[:32]


# ---------------------------------------------------------------------------------------------
# a member's own keys
# ---------------------------------------------------------------------------------------------
@dataclass
class Identity:
    """One copy's keys in one space: to sign what it writes, and to receive the project's key sealed to it."""
    sign: Ed25519PrivateKey
    box: X25519PrivateKey

    @classmethod
    def new(cls) -> "Identity":
        return cls(Ed25519PrivateKey.generate(), X25519PrivateKey.generate())

    def public(self) -> dict:
        return {"sign": b64(_raw_pub(self.sign.public_key())), "box": b64(_raw_pub(self.box.public_key()))}

    def dump(self) -> str:
        """For the keychain only."""
        return json.dumps({"sign": b64(_raw_priv(self.sign)), "box": b64(_raw_priv(self.box))})

    @classmethod
    def load(cls, text: str) -> "Identity":
        d = json.loads(text)
        return cls(Ed25519PrivateKey.from_private_bytes(unb64(d["sign"])),
                   X25519PrivateKey.from_private_bytes(unb64(d["box"])))


def _raw_pub(k) -> bytes:
    return k.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def _raw_priv(k) -> bytes:
    return k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())


def sign_public(text: str) -> Ed25519PublicKey:
    try:
        return Ed25519PublicKey.from_public_bytes(unb64(text))
    except (ValueError, TypeError) as e:
        raise SealProblem("A member's public key is not one ENLENS can use.", "key") from e


def sign_bytes(ident: Identity, data: bytes) -> str:
    return b64(ident.sign.sign(_SIG_CONTEXT + hashlib.sha256(data).digest()))


def verify_bytes(pub: str, data: bytes, sig: str) -> bool:
    try:
        sign_public(pub).verify(unb64(sig), _SIG_CONTEXT + hashlib.sha256(data).digest())
        return True
    except (InvalidSignature, SealProblem, ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------------------------
# signed JSON (the roster, the keys of each epoch: readable without the project's key, never forgeable)
# ---------------------------------------------------------------------------------------------
def canonical(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def signed_json(ident: Identity, obj: dict, by: str) -> bytes:
    body = {k: v for k, v in obj.items() if k not in ("sig", "signed_by")}
    body["signed_by"] = by
    return canonical({**body, "sig": sign_bytes(ident, canonical(body))})


def read_signed_json(data: bytes) -> tuple[dict, str, str]:
    """(the object without its signature, who signed it, the signature): checked by the caller against the key it
    trusts for that signer (`check_signed`)."""
    try:
        obj = json.loads(data)
    except ValueError as e:
        raise SealProblem("A signed file of the space cannot be read.", "damaged") from e
    if not isinstance(obj, dict) or not isinstance(obj.get("sig"), str) or not isinstance(obj.get("signed_by"), str):
        raise SealProblem("A file of the space is not signed.", "signature")
    sig = obj.pop("sig")
    return obj, obj["signed_by"], sig


def check_signed(obj: dict, sig: str, pub: str) -> bool:
    return verify_bytes(pub, canonical(obj), sig)


# ---------------------------------------------------------------------------------------------
# the project's key sealed to one member (X25519 + HKDF + AES-GCM)
# ---------------------------------------------------------------------------------------------
def seal_key(box_pub: str, secret: bytes, context: str) -> str:
    """`secret` (a project key, a set of keys) readable only with the member's box key. `context` (e.g. "space S
    epoch 3 part P") is bound in, so a sealed key cannot be moved to another place."""
    eph = X25519PrivateKey.generate()
    peer = X25519PublicKey.from_public_bytes(unb64(box_pub))
    k = _derive(eph.exchange(peer), b"ENLENS sealed key v1 " + context.encode("utf-8"))
    nonce = os.urandom(12)
    ct = AESGCM(k).encrypt(nonce, secret, context.encode("utf-8"))
    return b64(_raw_pub(eph.public_key()) + nonce + ct)


def open_key(ident: Identity, sealed: str, context: str) -> bytes:
    try:
        raw = unb64(sealed)
        eph, nonce, ct = X25519PublicKey.from_public_bytes(raw[:32]), raw[32:44], raw[44:]
        k = _derive(ident.box.exchange(eph), b"ENLENS sealed key v1 " + context.encode("utf-8"))
        return AESGCM(k).decrypt(nonce, ct, context.encode("utf-8"))
    except (InvalidTag, ValueError, TypeError) as e:
        raise SealProblem("A key sealed for this copy cannot be opened.", "key") from e


# ---------------------------------------------------------------------------------------------
# sealed files
# ---------------------------------------------------------------------------------------------
MAX_SEALED = 1536 * 1024 ** 2   # the most one file holds (AES-GCM in `cryptography` takes less than 2 GB at once)


def seal(data: bytes, *, path: str, by: str, epoch: int, key: bytes, ident: Identity) -> bytes:
    """`data` encrypted with the project's key of `epoch` and signed by `ident`, for the place `path` (the file's
    name in the shared layout, e.g. "p0123456789ab/bundles/000041.zip") in part `by`."""
    if len(data) > MAX_SEALED:
        raise SealProblem(f"{path.rsplit('/', 1)[-1]} is larger than ENLENS sends to a storage space "
                          f"({MAX_SEALED // 1024 ** 2} MB).", "too_large")
    nonce = os.urandom(12)
    header = canonical({"v": 1, "path": path, "by": by, "e": int(epoch), "n": b64(nonce)})
    head = MAGIC + struct.pack(">I", len(header)) + header
    ct = AESGCM(_derive(key, b"ENLENS file key v1")).encrypt(nonce, data, head)
    body = head + ct
    return body + ident.sign.sign(_SIG_CONTEXT + hashlib.sha256(body).digest())


@dataclass
class Header:
    """What a sealed file says it is. It holds no copy of the file: `head_len` is where the encrypted bytes start."""
    path: str
    by: str
    epoch: int
    nonce: bytes
    head_len: int


def header(blob: bytes) -> Header:
    """What a sealed file says it is, before anything is trusted."""
    if not blob.startswith(MAGIC) or len(blob) < len(MAGIC) + 4 + SIG_LEN:
        raise SealProblem("A file in the storage space is not one ENLENS sealed.", "format")
    (n,) = struct.unpack(">I", blob[len(MAGIC):len(MAGIC) + 4])
    if n > _MAX_HEADER or len(MAGIC) + 4 + n + SIG_LEN > len(blob):
        raise SealProblem("A file in the storage space is damaged.", "damaged")
    raw = blob[len(MAGIC) + 4:len(MAGIC) + 4 + n]
    try:
        h = json.loads(raw)
        out = Header(str(h["path"]), str(h["by"]), int(h["e"]), unb64(h["n"]), len(MAGIC) + 4 + n)
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        raise SealProblem("A file in the storage space is damaged.", "damaged") from e
    if not isinstance(h, dict) or h.get("v") != 1 or len(out.nonce) != 12:
        raise SealProblem("A file in the storage space was sealed by a newer ENLENS.", "format")
    return out


def _digest(blob: bytes) -> bytes:
    """What the signature covers: everything before it (read in place, never copied)."""
    return hashlib.sha256(memoryview(blob)[:-SIG_LEN]).digest()


def verify(blob: bytes, sign_pub: str) -> Header:
    """The header of a file whose signature is `sign_pub`'s; SealProblem("signature") otherwise."""
    h = header(blob)
    try:
        sign_public(sign_pub).verify(bytes(memoryview(blob)[-SIG_LEN:]), _SIG_CONTEXT + _digest(blob))
    except InvalidSignature as e:
        raise SealProblem("A file in the storage space is not signed by the colleague whose part it is in.",
                          "signature") from e
    return h


def _decrypt(blob: bytes, h: Header, key: bytes) -> bytes:
    view = memoryview(blob)
    try:
        return AESGCM(_derive(key, b"ENLENS file key v1")).decrypt(h.nonce, view[h.head_len:-SIG_LEN],
                                                                    view[:h.head_len])
    except InvalidTag as e:
        raise SealProblem("A file in the storage space is damaged.", "damaged") from e
    except OverflowError as e:   # (more than 2 GB: never written by ENLENS, `MAX_SEALED`)
        raise SealProblem("A file in the storage space is larger than ENLENS reads.", "damaged") from e


def open_sealed(blob: bytes, *, path: str, by: str, sign_pub: str, keys: dict[int, bytes],
                h: Header | None = None) -> bytes:
    """The data of a sealed file read from the place `path` in part `by`, checked: signed by that part's member
    (`sign_pub`), sealed for that very place, and encrypted with a project key this copy holds. `h`: its header,
    when the caller verified it already."""
    h = h or verify(blob, sign_pub)
    if h.path != path:
        raise SealProblem("A file in the storage space says it belongs elsewhere.", "place")
    if h.by != by:
        raise SealProblem("A file in the storage space was written by someone else than the part's member.", "writer")
    key = keys.get(h.epoch)
    if key is None:
        raise SealProblem("A file in the storage space is sealed with a key this copy does not hold (yet).", "key")
    return _decrypt(blob, h, key)


def open_unverified(blob: bytes, keys: dict[int, bytes]) -> tuple[Header, bytes]:
    """The header and data of a sealed file whose writer is not known yet (a colleague's first file, with their own
    public key inside it): decrypted, so only those who hold the project's key could have made it; the caller checks
    the signature against the key the data names (`verify`)."""
    h = header(blob)
    key = keys.get(h.epoch)
    if key is None:
        raise SealProblem("A file in the storage space is sealed with a key this copy does not hold (yet).", "key")
    return h, _decrypt(blob, h, key)


def join_proof(join_secret: bytes, part: str, person: str, public: dict) -> str:
    """What a colleague's first file carries to show it holds the invite made for that part (an HMAC with the invite's
    one-time secret over the part, the person and their public keys)."""
    msg = canonical({"part": part, "person": person, "sign": public.get("sign"), "box": public.get("box")})
    return hmac.new(join_secret, b"ENLENS join v1\x00" + msg, hashlib.sha256).hexdigest()


def check_join_proof(join_secret: bytes, part: str, person: str, public: dict, proof: str) -> bool:
    return isinstance(proof, str) and hmac.compare_digest(join_proof(join_secret, part, person, public), proof)
