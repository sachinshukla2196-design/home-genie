"""Shared input validators."""
from typing import List


def safe_image_refs(urls: List[str], max_items: int = 8) -> List[str]:
    """Images are references the shop renders in <img src>: allow only same-site paths (uploads, /brand) or https URLs.
    Rejects javascript:, data:, plain http, protocol-relative (//host), path traversal, quotes/angle brackets/whitespace."""
    if len(urls) > max_items:
        raise ValueError(f"At most {max_items} images.")
    out = []
    for u in urls:
        u = (u or "").strip()
        local = u.startswith("/") and not u.startswith("//") and ".." not in u
        if not u or len(u) > 500 or not (local or u.startswith("https://")) or any(ch in u for ch in " \t\r\n<>\"'"):
            raise ValueError("Image must be an uploaded file path or an https:// link.")
        out.append(u)
    return out
