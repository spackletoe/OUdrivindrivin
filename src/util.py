"""Format helpers shared across modules."""


def fmt_laptime(seconds: float) -> str:
    """Format seconds as M:SS.ss"""
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return str(seconds)
    minutes = int(seconds // 60)
    secs = seconds % 60
    return f"{minutes}:{secs:05.2f}"
