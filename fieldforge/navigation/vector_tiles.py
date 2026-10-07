"""Bounded, dependency-light Mapbox Vector Tile (MVT) preview renderer.

This renders common geometry layers and bounded source-name labels from an
offline PBF MBTiles tile into a plain PNG. It deliberately does not execute a
publisher's MapLibre style, fonts, glyph ranges, sprites, filters, or
expressions. It is a basic offline preview style, not a full cartographic
style engine.
"""

from __future__ import annotations

import gzip
import io
import struct
import zlib

MAX_TILE_BYTES = 2 * 1024**2
MAX_UNCOMPRESSED_BYTES = 8 * 1024**2
MAX_FIELDS = 200_000
MAX_FEATURES = 20_000
MAX_COMMANDS = 250_000
TILE_PIXELS = 256
MAX_LABELS = 96
MAX_LABEL_LENGTH = 48


def _varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(data):
            raise ValueError("Truncated vector tile protobuf integer.")
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if byte < 0x80:
            if shift == 63 and byte > 1:
                raise ValueError("Vector tile protobuf integer overflows 64 bits.")
            return value, offset
    raise ValueError("Vector tile protobuf integer is too long.")


def _fields(data: bytes):
    offset = 0
    count = 0
    while offset < len(data):
        count += 1
        if count > MAX_FIELDS:
            raise ValueError("Vector tile contains too many protobuf fields.")
        tag, offset = _varint(data, offset)
        number, wire = tag >> 3, tag & 7
        if number == 0:
            raise ValueError("Vector tile has an invalid protobuf field number.")
        if wire == 0:
            value, offset = _varint(data, offset)
        elif wire == 1:
            end = offset + 8
            if end > len(data):
                raise ValueError("Truncated fixed64 vector tile field.")
            value, offset = data[offset:end], end
        elif wire == 2:
            length, offset = _varint(data, offset)
            end = offset + length
            if end > len(data):
                raise ValueError("Truncated length-delimited vector tile field.")
            value, offset = data[offset:end], end
        elif wire == 5:
            end = offset + 4
            if end > len(data):
                raise ValueError("Truncated fixed32 vector tile field.")
            value, offset = data[offset:end], end
        else:
            raise ValueError("Unsupported protobuf wire type in vector tile.")
        yield number, wire, value


def _packed(data: bytes) -> list[int]:
    values, offset = [], 0
    while offset < len(data):
        value, offset = _varint(data, offset)
        values.append(value)
        if len(values) > MAX_COMMANDS:
            raise ValueError("Vector tile geometry has too many commands.")
    return values


def _decode_value(data: bytes):
    for number, wire, value in _fields(data):
        if number == 1 and wire == 2:
            try:
                return value.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("Vector tile contains invalid UTF-8 properties.") from exc
        if number == 2 and wire == 5:
            return struct.unpack("<f", value)[0]
        if number == 3 and wire == 1:
            return struct.unpack("<d", value)[0]
        if number == 4 and wire == 0:
            return value
        if number == 5 and wire == 0:
            return value
        if number == 6 and wire == 0:
            return (value >> 1) ^ -(value & 1)
        if number == 7 and wire == 0:
            return bool(value)
    return None


def _feature(data: bytes, keys: list[str], values: list[object]):
    geom_type, tags, commands = 0, [], []
    for number, wire, value in _fields(data):
        if number == 2:
            if wire == 2:
                tags.extend(_packed(value))
            elif wire == 0:
                tags.append(value)
        elif number == 3 and wire == 0:
            geom_type = value
        elif number == 4:
            if wire == 2:
                commands.extend(_packed(value))
            elif wire == 0:
                commands.append(value)
    if len(tags) % 2:
        raise ValueError("Vector tile feature has an incomplete property pair.")
    properties = {}
    for index in range(0, len(tags), 2):
        key, item = tags[index:index + 2]
        if key >= len(keys) or item >= len(values):
            raise ValueError("Vector tile feature references a missing property.")
        properties[keys[key]] = values[item]
    return geom_type, properties, commands


def _geometry(commands: list[int], extent: int):
    paths, path, x, y, cursor = [], [], 0, 0, 0
    while cursor < len(commands):
        command = commands[cursor]
        cursor += 1
        command_id, count = command & 7, command >> 3
        if count < 1 or command_id not in (1, 2, 7):
            raise ValueError("Vector tile has an invalid geometry command.")
        if command_id == 7:
            if count != 1 or len(path) < 3:
                raise ValueError("Vector tile has an invalid polygon close command.")
            paths.append(path)
            path = []
            continue
        for _ in range(count):
            if cursor + 1 >= len(commands):
                raise ValueError("Vector tile geometry coordinate pair is truncated.")
            dx, dy = commands[cursor], commands[cursor + 1]
            cursor += 2
            x += (dx >> 1) ^ -(dx & 1)
            y += (dy >> 1) ^ -(dy & 1)
            if not -extent <= x <= 2 * extent or not -extent <= y <= 2 * extent:
                raise ValueError("Vector tile geometry coordinate exceeds the tile buffer bounds.")
            point = (round(x * TILE_PIXELS / extent), round(y * TILE_PIXELS / extent))
            if command_id == 1:
                if path:
                    paths.append(path)
                path = [point]
            else:
                if not path:
                    raise ValueError("Vector tile line command appears before a move command.")
                path.append(point)
    if path:
        paths.append(path)
    return paths


def _layer(data: bytes, feature_limit: int):
    name, features, keys, raw_values, extent = "", [], [], [], 4096
    for number, wire, value in _fields(data):
        if number == 1 and wire == 2:
            name = value.decode("utf-8", errors="strict")
        elif number == 2 and wire == 2:
            features.append(value)
            if len(features) > feature_limit:
                raise ValueError("Vector tile layer contains too many features.")
        elif number == 3 and wire == 2:
            keys.append(value.decode("utf-8", errors="strict"))
        elif number == 4 and wire == 2:
            raw_values.append(value)
        elif number == 5 and wire == 0:
            extent = value
        elif number == 15 and wire == 0 and value not in (1, 2):
            raise ValueError("Unsupported vector tile layer version.")
    if not name or not 1 <= extent <= 65536:
        raise ValueError("Vector tile layer has invalid metadata or extent.")
    values = [_decode_value(item) for item in raw_values]
    parsed = [_feature(item, keys, values) for item in features]
    return name.lower(), extent, parsed


def _layers(data: bytes):
    if type(data) is not bytes or not data or len(data) > MAX_TILE_BYTES:
        raise ValueError("Vector tile is empty or exceeds the 2 MiB tile limit.")
    if data.startswith(b"\x1f\x8b"):
        try:
            with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
                data = stream.read(MAX_UNCOMPRESSED_BYTES + 1)
        except (OSError, EOFError, zlib.error) as exc:
            raise ValueError("Vector tile gzip data is unreadable.") from exc
        if len(data) > MAX_UNCOMPRESSED_BYTES:
            raise ValueError("Expanded vector tile exceeds the 8 MiB limit.")
    if len(data) > MAX_UNCOMPRESSED_BYTES:
        raise ValueError("Expanded vector tile exceeds the 8 MiB limit.")
    layers = []
    feature_count = command_count = 0
    for number, wire, value in _fields(data):
        if number == 3 and wire == 2:
            layer = _layer(value, MAX_FEATURES - feature_count)
            feature_count += len(layer[2])
            command_count += sum(len(feature[2]) for feature in layer[2])
            if command_count > MAX_COMMANDS:
                raise ValueError("Vector tile has too many geometry commands.")
            layers.append(layer)
            if len(layers) > 64:
                raise ValueError("Vector tile contains too many layers.")
    if not layers:
        raise ValueError("Vector tile contains no Mapbox Vector Tile layers.")
    return layers


def _style(layer: str, properties: dict):
    subtype = str(properties.get("class", properties.get("subclass", ""))).lower()
    if any(word in layer for word in ("water", "ocean", "lake", "river")):
        return "line" if any(word in layer for word in ("way", "line")) else "water"
    if "park" in layer or "landcover" in layer or "landuse" in layer or "land" == layer:
        return "green"
    if "building" in layer:
        return "building"
    if "transportation" in layer or "road" in layer or "highway" in layer:
        return "road-major" if subtype in {"motorway", "trunk", "primary"} else "road"
    if "boundary" in layer or "admin" in layer:
        return "boundary"
    if "rail" in layer:
        return "rail"
    if "place" in layer or "poi" in layer or "label" in layer:
        return "point"
    return "minor"


def _label(layer: str, properties: dict):
    """Return a bounded source label and stable priority for named features."""
    if not any(token in layer for token in (
            "place", "poi", "name", "peak", "label", "transportation",
            "road", "water", "waterway", "boundary", "park")):
        return None
    value = next((properties.get(key) for key in (
        "name:en", "name_en", "name:latin", "name:local", "name")
                  if isinstance(properties.get(key), str) and properties[key].strip()), None)
    if value is None:
        return None
    value = " ".join("".join(char for char in value if char.isprintable()).split())[:MAX_LABEL_LENGTH]
    if not value:
        return None
    kind = str(properties.get("class", "")).lower()
    tier = 0 if layer == "place" and kind in {"continent", "country", "state", "province"} else 1
    tier += 0 if properties.get("capital") in (True, 1, "yes") else 1
    if any(token in layer for token in ("transportation", "road")):
        tier += 0 if kind in {"motorway", "trunk", "primary"} else 2
    elif any(token in layer for token in ("water", "waterway")):
        tier += 1
    try:
        rank = float(properties.get("rank", 99))
    except (TypeError, ValueError):
        rank = 99
    return tier, rank, value


def _line_anchor(paths):
    """Return the halfway point of the longest line, avoiding route-wide averages."""
    choices = []
    for path in paths:
        if len(path) < 2:
            continue
        lengths = [((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
                   for a, b in zip(path, path[1:])]
        total = sum(lengths)
        if total:
            choices.append((total, path, lengths))
    if not choices:
        return None
    _, path, lengths = max(choices, key=lambda item: item[0])
    remaining = sum(lengths) / 2
    for a, b, length in zip(path, path[1:], lengths):
        if remaining <= length:
            fraction = remaining / length
            return (round(a[0] + (b[0] - a[0]) * fraction),
                    round(a[1] + (b[1] - a[1]) * fraction))
        remaining -= length
    return path[-1]


def _ring_centroid(ring):
    """Compute a polygon ring's area centroid, or None for a degenerate ring."""
    area2 = sum(x1 * y2 - x2 * y1
                for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]))
    if not area2:
        return None
    x = sum((x1 + x2) * (x1 * y2 - x2 * y1)
            for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1])) / (3 * area2)
    y = sum((y1 + y2) * (x1 * y2 - x2 * y1)
            for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1])) / (3 * area2)
    return round(x), round(y)


def _inside_ring(point, ring):
    x, y = point
    inside = False
    previous = ring[-1]
    for current in ring:
        x1, y1 = previous
        x2, y2 = current
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
        previous = current
    return inside


def _polygon_anchor(paths):
    """Place a label inside the largest ring; skip concave/outside centroids."""
    rings = [path for path in paths if len(path) >= 3]
    if not rings:
        return None
    outer = max(rings, key=lambda ring: abs(_ring_area(ring)))
    point = _ring_centroid(outer)
    if point is not None and _inside_ring(point, outer):
        return point
    return None


def _label_anchor(geom_type, paths):
    if geom_type == 1:
        return paths[0][0] if paths and paths[0] else None
    if geom_type == 2:
        return _line_anchor(paths)
    if geom_type == 3:
        return _polygon_anchor(paths)
    return None


def _place_label(draw, image, font, point, value, occupied):
    x, y = point
    box = draw.textbbox((x + 4, y + 2), value, font=font, stroke_width=2)
    width, height = box[2] - box[0], box[3] - box[1]
    left = min(max(2, box[0]), TILE_PIXELS - width - 2)
    top = min(max(2, box[1]), TILE_PIXELS - height - 2)
    rect = (left - 2, top - 1, left + width + 2, top + height + 1)
    if any(rect[0] < other[2] and rect[2] > other[0]
           and rect[1] < other[3] and rect[3] > other[1] for other in occupied):
        return False
    draw.text((left, top), value, font=font, fill="#26392f", stroke_width=2,
              stroke_fill="#f4f3ec")
    occupied.append(rect)
    return True


def render_vector_tile(data: bytes) -> bytes:
    """Render common MVT geometry into a 256 px RGBA PNG preview tile."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise ValueError('Vector preview needs Pillow; install FieldForge with the "maps" extra.') from exc

    # Draw opaque geographic areas first, then linework and point markers.
    image = Image.new("RGBA", (TILE_PIXELS, TILE_PIXELS), "#e9e6dc")
    try:
        parsed = []
        labels = []
        for layer, extent, features in _layers(data):
            for geom_type, properties, commands in features:
                paths = _geometry(commands, extent) if geom_type in (1, 2, 3) else []
                style = _style(layer, properties)
                parsed.append((style, geom_type, paths))
                label = _label(layer, properties)
                anchor = _label_anchor(geom_type, paths)
                if label and anchor is not None:
                    labels.append((label, anchor))
        draw = ImageDraw.Draw(image)
        fills = {"water": "#a8cfe0", "green": "#c7d9b4", "building": "#d4c8bd"}
        strokes = {"road": ("#ffffff", "#d1a871", 3, 1),
                   "road-major": ("#fffdf7", "#dc9954", 5, 2),
                   "boundary": ("#aa819b", "#aa819b", 1, 0),
                   "rail": ("#8b8380", "#f7f3ec", 2, 1),
                   "water": ("#89bcd1", "#89bcd1", 2, 0),
                   "line": ("#89bcd1", "#89bcd1", 2, 0),
                   "minor": ("#b4afa4", "#b4afa4", 1, 0)}
        for kind, geom_type, paths in parsed:
            if geom_type != 3 or kind not in fills:
                continue
            mask = Image.new("L", image.size, 0)
            mask_draw = ImageDraw.Draw(mask)
            rings = [path for path in paths if len(path) >= 3]
            for ring in rings:
                mask_draw.polygon(ring, fill=255 if _ring_area(ring) >= 0 else 0)
            color = Image.new("RGBA", image.size, fills[kind])
            image.alpha_composite(Image.composite(color, image, mask))
            mask.close()
            color.close()
        draw = ImageDraw.Draw(image)
        for kind, geom_type, paths in parsed:
            if geom_type == 2:
                # Layer names do not constrain geometry: area/label layers can
                # contain lines too, even without a dedicated line style.
                casing, color, casing_width, width = strokes.get(kind, strokes["minor"])
                for path in paths:
                    if len(path) >= 2:
                        if casing_width:
                            draw.line(path, fill=casing, width=casing_width, joint="curve")
                        draw.line(path, fill=color, width=width or 1, joint="curve")
            elif geom_type == 1 and paths:
                color = "#566f47" if kind == "point" else "#715f53"
                for x, y in (point for path in paths for point in path):
                    draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=color)
        font = ImageFont.load_default(size=10)
        occupied = []
        for (_, _, value), point in sorted(labels, key=lambda item: (item[0][0], item[0][1], item[0][2])):
            if len(occupied) >= MAX_LABELS:
                break
            _place_label(draw, image, font, point, value, occupied)
        result = io.BytesIO()
        image.save(result, format="PNG", optimize=False)
        return result.getvalue()
    finally:
        image.close()


def _ring_area(points):
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]))
