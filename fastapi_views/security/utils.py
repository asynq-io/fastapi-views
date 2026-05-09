import secrets


def safe_compare(a: str, b: str) -> bool:
    """Safely compare 2 strings"""
    return secrets.compare_digest(a, b)
