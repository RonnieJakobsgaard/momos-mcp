import subprocess


def _validate_ref(ref: str) -> str | None:
    """Return None if ref is valid, or an error string if not."""
    result = subprocess.run(
        ["git", "rev-parse", "--verify", ref],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return f"invalid ref: {ref}"
    return None
