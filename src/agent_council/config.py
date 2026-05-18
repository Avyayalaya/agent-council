"""council.yaml loader with validation.

Tries ``pyyaml`` first; falls back to a small built-in YAML-subset parser so
the package has zero hard install dependencies for v0.1.

Supported subset (covers everything ``council.yaml.example`` needs):
    - scalar key: value pairs (strings, ints, floats, bool, null)
    - lists with ``-`` items, including dict items
    - nested mappings via indentation
    - block strings via single-line values
    - comments (lines starting with ``#``) ignored
    - blank lines ignored

Anything fancier (anchors, multiline strings, flow style) requires pyyaml.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_config(path: str | Path) -> dict[str, Any]:
    """Load a council.yaml from disk, returning a plain dict.

    Args:
        path: filesystem path to a YAML file.

    Returns:
        Parsed config as nested Python dicts/lists/scalars.

    Raises:
        FileNotFoundError: if ``path`` doesn't exist.
        ValueError: if the file cannot be parsed.
    """
    p = Path(path).expanduser()
    if not p.exists():
        raise FileNotFoundError(f"Council config not found: {p}")
    text = p.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text) or {}
    except ImportError:
        return _parse_mini_yaml(text)


def validate_config(config: dict[str, Any]) -> list[str]:
    """Return a list of human-readable validation errors (empty = valid).

    Checks structural shape — required keys, types — not semantics.
    """
    errors: list[str] = []

    if not isinstance(config, dict):
        return [f"Top-level config must be a mapping, got {type(config).__name__}."]

    rt = config.get("runtime")
    if not isinstance(rt, dict):
        errors.append("`runtime` section missing or not a mapping.")
    else:
        if not rt.get("type"):
            errors.append("`runtime.type` is required (e.g. claude_cli, mock_cli).")
        ts = rt.get("timeout_seconds")
        if ts is not None and not isinstance(ts, (int, float)):
            errors.append("`runtime.timeout_seconds` must be a number.")

    delibs = config.get("deliberators")
    if not isinstance(delibs, list) or not delibs:
        errors.append("`deliberators` must be a non-empty list.")
    else:
        seen_ids: set[str] = set()
        for i, d in enumerate(delibs):
            if not isinstance(d, dict):
                errors.append(f"`deliberators[{i}]` must be a mapping.")
                continue
            did = d.get("id")
            if not did:
                errors.append(f"`deliberators[{i}].id` is required.")
            elif did in seen_ids:
                errors.append(f"Duplicate deliberator id: {did!r}.")
            else:
                seen_ids.add(did)
            if not d.get("prompt"):
                errors.append(f"`deliberators[{i}].prompt` is required (path to prompt file).")

    adj = config.get("adjudicator")
    if not isinstance(adj, dict):
        errors.append("`adjudicator` section missing or not a mapping.")
    elif not adj.get("prompt"):
        errors.append("`adjudicator.prompt` is required.")

    proto = config.get("protocol") or {}
    if proto:
        rounds = proto.get("rounds")
        if rounds is not None and rounds not in (1, 2):
            errors.append("`protocol.rounds` must be 1 or 2 in v0.1.")

    return errors


# ---------------------------------------------------------------------------
# Mini YAML parser — handles a documented subset for offline operation.
# ---------------------------------------------------------------------------

def _parse_mini_yaml(text: str) -> dict[str, Any]:
    """Parse a YAML-subset document into nested dicts/lists/scalars."""
    # Strip comments and blank lines, but preserve indentation.
    lines: list[str] = []
    for raw in text.splitlines():
        # Strip trailing comments (but not values that contain '#' inside quotes).
        stripped = _strip_comment(raw)
        if stripped.strip() == "":
            continue
        lines.append(stripped.rstrip())

    pos = [0]  # mutable index for recursion

    def cur_indent() -> int:
        if pos[0] >= len(lines):
            return -1
        line = lines[pos[0]]
        return len(line) - len(line.lstrip(" "))

    def parse_block(indent: int) -> Any:
        """Parse a block starting at the given indent level."""
        # Detect if block is a list (starts with '-') or a mapping.
        if pos[0] >= len(lines):
            return {}
        first = lines[pos[0]]
        first_content = first.lstrip(" ")
        if first_content.startswith("- "):
            return parse_list(indent)
        return parse_mapping(indent)

    def parse_mapping(indent: int) -> dict[str, Any]:
        result: dict[str, Any] = {}
        while pos[0] < len(lines):
            line = lines[pos[0]]
            this_indent = len(line) - len(line.lstrip(" "))
            if this_indent < indent:
                break
            if this_indent > indent:
                # Should have been consumed by recursive call.
                pos[0] += 1
                continue
            content = line.strip()
            if content.startswith("- "):
                # End of mapping at this level — caller handles list.
                break
            if ":" not in content:
                pos[0] += 1
                continue
            key, _, value = content.partition(":")
            key = key.strip().strip('"').strip("'")
            value = value.strip()
            pos[0] += 1
            if value == "" or value is None:
                # Nested block follows.
                if pos[0] < len(lines):
                    next_indent = len(lines[pos[0]]) - len(lines[pos[0]].lstrip(" "))
                    if next_indent > indent:
                        result[key] = parse_block(next_indent)
                        continue
                result[key] = None
            else:
                result[key] = _parse_scalar(value)
        return result

    def parse_list(indent: int) -> list[Any]:
        result: list[Any] = []
        while pos[0] < len(lines):
            line = lines[pos[0]]
            this_indent = len(line) - len(line.lstrip(" "))
            if this_indent < indent:
                break
            content = line.strip()
            if not content.startswith("- "):
                break
            after_dash = content[2:].strip()
            pos[0] += 1
            if ":" in after_dash and not after_dash.startswith('"'):
                # List item is a mapping. Re-feed line so parse_mapping picks it up.
                key, _, value = after_dash.partition(":")
                item: dict[str, Any] = {}
                key = key.strip()
                value = value.strip()
                if value:
                    item[key] = _parse_scalar(value)
                else:
                    if pos[0] < len(lines):
                        next_indent = len(lines[pos[0]]) - len(lines[pos[0]].lstrip(" "))
                        if next_indent > indent:
                            item[key] = parse_block(next_indent)
                # Continue gathering siblings at indent+2.
                sib_indent = indent + 2
                while pos[0] < len(lines):
                    sib_line = lines[pos[0]]
                    sib_this_indent = len(sib_line) - len(sib_line.lstrip(" "))
                    if sib_this_indent < sib_indent:
                        break
                    if sib_this_indent > sib_indent:
                        # Belongs to a child of the current key — let parse_mapping handle.
                        pos[0] += 1
                        continue
                    sib_content = sib_line.strip()
                    if sib_content.startswith("- "):
                        # New list item begins.
                        break
                    sk, _, sv = sib_content.partition(":")
                    sk = sk.strip()
                    sv = sv.strip()
                    pos[0] += 1
                    if sv == "":
                        # Nested block.
                        if pos[0] < len(lines):
                            child_indent = len(lines[pos[0]]) - len(lines[pos[0]].lstrip(" "))
                            if child_indent > sib_indent:
                                item[sk] = parse_block(child_indent)
                                continue
                        item[sk] = None
                    else:
                        item[sk] = _parse_scalar(sv)
                result.append(item)
            else:
                result.append(_parse_scalar(after_dash))
        return result

    return parse_block(0)


def _strip_comment(line: str) -> str:
    """Strip an inline comment from a YAML line, respecting quotes."""
    in_single = False
    in_double = False
    out_chars: list[str] = []
    for ch in line:
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            break
        out_chars.append(ch)
    return "".join(out_chars)


def _parse_scalar(value: str) -> Any:
    """Convert a YAML scalar string to a Python value."""
    value = value.strip()
    if value == "":
        return None
    if value in ("null", "~", "Null", "NULL"):
        return None
    if value in ("true", "True", "TRUE"):
        return True
    if value in ("false", "False", "FALSE"):
        return False
    # Strip quotes.
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    # Inline list: [a, b, c]
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(p.strip()) for p in inner.split(",")]
    # Numeric?
    try:
        if "." in value or "e" in value or "E" in value:
            return float(value)
        return int(value)
    except ValueError:
        return value
