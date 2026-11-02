"""Small parser-independent bounds for JSON accepted from untrusted sources."""

from __future__ import annotations


def json_nesting_within_limit(raw: bytes, maximum_depth: int = 128) -> bool:
    """Return whether braces and brackets stay balanced and within a fixed depth.

    JSON structural bytes are ASCII. Quoted text and escaped quotes are skipped,
    leaving syntax validation and Unicode decoding to the standard parser.
    """
    if maximum_depth < 1:
        raise ValueError("maximum_depth must be positive")
    depth = 0
    in_string = False
    escaped = False
    for byte in raw:
        if in_string:
            if escaped:
                escaped = False
            elif byte == 0x5C:  # backslash
                escaped = True
            elif byte == 0x22:  # quote
                in_string = False
            continue
        if byte == 0x22:
            in_string = True
        elif byte in {0x5B, 0x7B}:  # [ or {
            depth += 1
            if depth > maximum_depth:
                return False
        elif byte in {0x5D, 0x7D}:  # ] or }
            depth -= 1
            if depth < 0:
                return False
    return depth == 0 and not in_string and not escaped
