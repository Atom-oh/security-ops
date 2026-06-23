# INTENTIONALLY VULNERABLE — FSI-Mythos scanner testbed (defensive corpus).
# CWE-327: use of a broken/weak cryptographic algorithm.
import hashlib


def hash_pin(pin: str) -> str:
    # MD5 is broken for password/PIN hashing (fast, collidable, unsalted).
    return hashlib.md5(pin.encode()).hexdigest()  # CWE-327
