# INTENTIONALLY VULNERABLE — FSI-Mythos scanner testbed (defensive corpus).
# CWE-347: improper verification of cryptographic signature (JWT signature disabled).
import jwt  # type: ignore


def verify_session(token: str) -> dict:
    # Disabling signature verification lets an attacker forge any claims.
    return jwt.decode(token, options={"verify_signature": False})  # CWE-347


def is_admin(token: str) -> bool:
    claims = verify_session(token)
    return claims.get("role") == "admin"
