"""Offline storage for explicitly downloaded maps and saved planned routes.

Files are published under new names only. Attribution is retained alongside map
bytes and in route JSON/GPX. No network or database operations are performed.
"""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from xml.etree import ElementTree as ET

from .models import (
    MAX_JSON_BYTES,
    MAX_MAPS,
    ValidationError,
    decode_json,
    encode_json,
    object_fields,
    validate_asset,
    validate_filename,
    validate_portal_url,
    validate_route,
    validate_timestamp,
)

GPX_NS = "http://www.topografix.com/GPX/1/1"
MAP_MANIFEST_SUFFIX = ".fieldforge.json"
MAX_LOCAL_ROUTES = 5000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def ensure_directory(directory: str | Path) -> Path:
    """Create an explicit local folder, rejecting a symlink leaf or changed path."""
    path = Path(directory).expanduser().absolute()
    if path.is_symlink():
        raise ValidationError("Choose a real local folder, not a symbolic link.")
    path.mkdir(parents=True, exist_ok=True)
    path = path.resolve()
    check_directory(path)
    return path


def check_directory(path: Path) -> None:
    if not stat.S_ISDIR(path.lstat().st_mode) or path.resolve() != path:
        raise ValidationError("The local storage folder changed or is not a real directory.")


def _signature(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def read_local_json(path: Path):
    """Read one bounded regular file without following a replacement symlink."""
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= MAX_JSON_BYTES:
        raise ValidationError("Choose a regular local JSON file of at most 8 MiB.")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(path, flags), "rb") as stream:
        opened = os.fstat(stream.fileno())
        if not stat.S_ISREG(opened.st_mode) or _signature(opened)[:4] != _signature(before)[:4]:
            raise ValidationError("The saved file changed before it could be read.")
        data = stream.read(MAX_JSON_BYTES + 1)
        finished = os.fstat(stream.fileno())
    if _signature(opened) != _signature(finished) or _signature(before) != _signature(path.lstat()):
        raise ValidationError("The saved file changed while it was being read.")
    return decode_json(data)


def write_new_bytes(target: Path, data: bytes) -> Path:
    """Atomic publication without overwriting, including an existing symlink.

    Uses a hard link from a completed temporary file on POSIX, or Windows'
    non-overwriting rename. Unsupported filesystems keep existing files intact.
    """
    check_directory(target.parent)
    fd, temporary = tempfile.mkstemp(prefix=".fieldforge-online-", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        check_directory(target.parent)
        _publish_new_path(Path(temporary), target)
        return target
    finally:
        Path(temporary).unlink(missing_ok=True)


def _publish_new_path(temporary: Path, target: Path) -> None:
    if os.name == "nt":
        # Windows rename is atomic and fails when the target already exists;
        # unlike POSIX rename, it is safe on filesystems without hard links.
        os.rename(temporary, target)
    else:
        os.link(temporary, target)


def publish_map(temporary: Path, target: Path, asset: dict, portal: str, guard, *, legacy_note=None) -> Path:
    """Publish checked map bytes plus provenance; caller holds its connection lock.

    The manifest is the availability marker. Any cancellation or failure before
    this function completes removes only files this operation actually created.
    """
    asset = validate_asset(asset)
    portal = validate_portal_url(portal)
    if validate_filename(target.name, asset["format"]) != target.name or target.parent != temporary.parent:
        raise ValidationError("Map publication must stay in its chosen download folder.")
    manifest_path = target.with_name(target.name + MAP_MANIFEST_SUFFIX)
    payload = encode_json({
        "schema_version": 1, "kind": "downloaded-map", "saved_at": _now(),
        "portal": portal, "local_filename": target.name, "asset": asset,
    })
    source_path = target.with_name(target.name + ".source.json")
    source_payload = encode_json(legacy_note) if legacy_note is not None else None
    published_map = published_manifest = published_source = False
    map_identity = manifest_identity = source_identity = None
    try:
        check_directory(target.parent)
        guard()
        _publish_new_path(temporary, target)
        published_map = True
        map_identity = target.lstat()
        guard()
        write_new_bytes(manifest_path, payload)
        published_manifest = True
        manifest_identity = manifest_path.lstat()
        guard()
        if source_payload is not None:
            write_new_bytes(source_path, source_payload)
            published_source = True
            source_identity = source_path.lstat()
            guard()
        return target
    except BaseException:
        for published, path, identity in (
            (published_source, source_path, source_identity),
            (published_manifest, manifest_path, manifest_identity),
            (published_map, target, map_identity),
        ):
            if published and identity is not None:
                try:
                    current = path.lstat()
                    if (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
                        path.unlink()
                except FileNotFoundError:
                    pass
        raise


def _route_document(value) -> dict:
    """Validate a portal route envelope; its contents never select local paths."""
    value = object_fields(value, {"schema_version", "kind", "saved_at", "route"}, "Saved route")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValidationError("Unsupported saved-route schema; the file was preserved.")
    if value["kind"] != "planned-route":
        raise ValidationError("This file is not a saved planned route.")
    validate_timestamp(value["saved_at"], "Save timestamp")
    return validate_route(value["route"])


class PortalLibrary:
    def __init__(self, root: str | Path):
        self.root = ensure_directory(root)
        self.maps_directory = ensure_directory(self.root / "maps")
        self.routes_directory = ensure_directory(self.root / "routes")

    def _directory(self, name: str) -> Path:
        check_directory(self.root)
        directory = self.root / name
        check_directory(directory)
        return directory

    def _route_path(self, path: str | Path) -> Path:
        directory = self._directory("routes")
        path = Path(path).expanduser().absolute()
        if path.parent != directory or path.suffix != ".json" or path.resolve() != path:
            raise ValidationError("Load a saved route file from this workspace's routes folder.")
        return path

    def save_route(self, route: dict) -> Path:
        route = validate_route(route)
        fingerprint = hashlib.sha256(encode_json(route)).hexdigest()
        target = self._directory("routes") / f"{route['id']}-{fingerprint[:20]}.route.json"
        if target.exists() or target.is_symlink():
            if self.load_route(target) == route:
                return target
            raise FileExistsError("An existing route file was preserved; choose another route.")
        payload = encode_json({
            "schema_version": 1, "kind": "planned-route", "saved_at": _now(), "route": route,
        })
        try:
            write_new_bytes(target, payload)
        except FileExistsError:
            if self.load_route(target) != route:
                raise
        return target

    def load_route(self, path: str | Path) -> dict:
        return _route_document(read_local_json(self._route_path(path)))

    def import_route(self, source: str | Path) -> Path:
        """Copy an explicitly selected portal route JSON into this workspace.

        Browser downloads may live outside the workspace. Their complete envelope
        and route are validated before the local immutable copy is published. The
        source stays unchanged; no links or paths inside its JSON are followed.
        """
        source = Path(source).expanduser().absolute()
        route = _route_document(read_local_json(source))
        return self.save_route(route)

    def routes(self) -> tuple[Path, ...]:
        paths = []
        for path in self._directory("routes").glob("*.route.json"):
            if len(paths) >= MAX_LOCAL_ROUTES:
                raise ValidationError("Too many locally saved routes; no partial list was loaded.")
            self.load_route(path)
            paths.append(path)
        return tuple(sorted(paths, key=lambda p: p.name.lower()))

    def maps(self) -> tuple[Path, ...]:
        """List completed local downloads, validating their metadata and file size.

        The initial download verifies the full SHA-256. Listing does not rehash
        multi-gigabyte maps; the map viewers still validate the selected file.
        """
        directory = self._directory("maps")
        paths = []
        for manifest_path in directory.glob("*" + MAP_MANIFEST_SUFFIX):
            if manifest_path.name.startswith("."):
                continue
            if len(paths) >= MAX_MAPS:
                raise ValidationError("Too many locally downloaded maps; no partial list was loaded.")
            value = object_fields(
                read_local_json(manifest_path),
                {"schema_version", "kind", "saved_at", "portal", "local_filename", "asset"},
                "Saved map metadata",
            )
            if type(value["schema_version"]) is not int or value["schema_version"] != 1:
                raise ValidationError("Unsupported saved-map metadata version.")
            if value["kind"] != "downloaded-map":
                raise ValidationError("Invalid saved-map metadata type.")
            validate_timestamp(value["saved_at"], "Map save timestamp")
            validate_portal_url(value["portal"])
            asset = validate_asset(value["asset"])
            filename = validate_filename(value["local_filename"], asset["format"])
            if value["local_filename"] != filename or manifest_path.name != filename + MAP_MANIFEST_SUFFIX:
                raise ValidationError("Saved map metadata points outside its expected filename.")
            path = directory / filename
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or path.resolve() != path or info.st_size != asset["bytes"]:
                raise ValidationError("A downloaded map is missing, changed, or incomplete.")
            paths.append(path)
        return tuple(sorted(paths, key=lambda p: p.name.lower()))

    def export_gpx(self, route: dict, destination: str | Path) -> Path:
        route = validate_route(route)
        path = Path(destination).expanduser().absolute()
        if path.suffix.lower() != ".gpx":
            raise ValidationError("Choose a new .gpx filename for this planned route.")
        parent = ensure_directory(path.parent)
        target = parent / path.name
        description = (
            f"Planned driving route generated {route['created_at']}. "
            "This is a saved plan, not a recorded trip or live traffic information. "
            f"Source: {route['source']}. Attribution: {route['attribution']}. "
            f"License: {route['license']}. "
            f"Planned distance: {route['distance_m']:g} m; "
            f"estimated duration: {route['duration_s']:g} s. "
            "Turn instructions remain in the saved FieldForge route JSON."
        )
        root = ET.Element("gpx", {
            "xmlns": GPX_NS, "version": "1.1", "creator": "FieldForge Online Maps 1",
        })
        metadata = ET.SubElement(root, "metadata")
        ET.SubElement(metadata, "name").text = route["title"]
        ET.SubElement(metadata, "desc").text = description
        ET.SubElement(metadata, "time").text = route["created_at"]
        track = ET.SubElement(root, "trk")
        ET.SubElement(track, "name").text = ("PLANNED ROUTE — " + route["title"])[:160]
        ET.SubElement(track, "desc").text = description
        ET.SubElement(track, "src").text = route["source"]
        ET.SubElement(track, "type").text = "planned-route"
        segment = ET.SubElement(track, "trkseg")
        for longitude, latitude in route["geometry"]:
            lon = -180.0 if longitude == 180 else longitude
            ET.SubElement(segment, "trkpt", {
                "lat": format(Decimal(str(latitude)), "f"),
                "lon": format(Decimal(str(lon)), "f"),
            })
        payload = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        if len(payload) > 16 * 1024**2:
            raise ValidationError("The exported track exceeds the GPX reviewer's 16 MiB limit.")
        return write_new_bytes(target, payload)
