# INTENTIONALLY VULNERABLE — FSI-Mythos scanner testbed (defensive corpus).
# CWE-502: deserialization of untrusted data.
import pickle


def load_session(blob: bytes):
    # Unpickling attacker-controlled bytes yields arbitrary code execution.
    return pickle.loads(blob)  # CWE-502
