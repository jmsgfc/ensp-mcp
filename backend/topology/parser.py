"""Structured parser for eNSP .topo files."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from backend.topology.models import (
    DeviceTopoInfo,
    InterfaceInfo,
    LinkInfo,
    TopologyData,
)


class TopologyParseError(Exception):
    """Raised when a .topo file cannot be decoded or parsed."""


def _extract_declared_encoding(raw: bytes) -> str | None:
    """Extract the XML declaration encoding from the file header."""

    head = raw[:200]
    for encoding in ("ascii", "utf-8", "utf-16-le", "utf-16-be"):
        try:
            text = head.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
        match = re.search(r'encoding\s*=\s*["\']([^"\']+)["\']', text)
        if match:
            return match.group(1)
    return None


def _candidate_encodings(raw: bytes) -> list[str]:
    """Return encodings in the order they should be decode/parse tested."""

    candidates: list[str] = []
    if raw.startswith(b"\xef\xbb\xbf"):
        candidates.append("utf-8-sig")
    elif raw.startswith(b"\xff\xfe"):
        candidates.append("utf-16-le")
    elif raw.startswith(b"\xfe\xff"):
        candidates.append("utf-16-be")

    declared = _extract_declared_encoding(raw)
    if declared and declared.lower() != "unicode":
        candidates.append(declared)

    candidates.extend(["utf-8", "gb18030", "mbcs", "utf-16-le", "utf-16-be"])

    unique: list[str] = []
    seen: set[str] = set()
    for encoding in candidates:
        key = encoding.lower()
        if key not in seen:
            unique.append(encoding)
            seen.add(key)
    return unique


def _sanitize_encoding_declaration(xml_text: str) -> str:
    """Normalize XML declaration encoding after bytes are already decoded."""

    return re.sub(
        r'(encoding\s*=\s*)["\'][^"\']*["\']',
        r'\1"utf-8"',
        xml_text,
        count=1,
    )


def _decode_and_parse(raw: bytes) -> ET.Element:
    errors: list[str] = []

    for encoding in _candidate_encodings(raw):
        try:
            xml_text = raw.decode(encoding)
            xml_text = _sanitize_encoding_declaration(xml_text)
            return ET.fromstring(xml_text)
        except (LookupError, UnicodeDecodeError, ET.ParseError) as exc:
            errors.append(f"{encoding}: {exc}")

    raise TopologyParseError(
        "拓扑文件解析失败，已尝试编码: " + "; ".join(errors)
    )


def parse_topology(path: str | Path) -> TopologyData:
    """Parse an eNSP .topo file into structured topology data."""

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"拓扑文件不存在: {path}")

    root = _decode_and_parse(path.read_bytes())
    version = root.get("version", "unknown")

    return TopologyData(
        version=version,
        devices=_parse_devices(root),
        links=_parse_links(root),
    )


def _parse_devices(root: ET.Element) -> list[DeviceTopoInfo]:
    devices: list[DeviceTopoInfo] = []
    devices_elem = root.find("devices")
    if devices_elem is None:
        return devices

    for dev_elem in devices_elem.findall("dev"):
        device = _parse_single_device(dev_elem)
        if device:
            devices.append(device)
    return devices


def _parse_single_device(dev_elem: ET.Element) -> DeviceTopoInfo | None:
    dev_id = dev_elem.get("id")
    name = dev_elem.get("name")
    model = dev_elem.get("model")
    if not dev_id or not name or not model:
        return None

    try:
        com_port = int(dev_elem.get("com_port", "0") or "0")
    except (TypeError, ValueError):
        com_port = 0

    try:
        poe = int(dev_elem.get("poe", "0") or "0")
    except (TypeError, ValueError):
        poe = 0

    try:
        bootmode = int(dev_elem.get("bootmode", "0") or "0")
    except (TypeError, ValueError):
        bootmode = 0

    try:
        cx = float(dev_elem.get("cx", "0") or "0")
    except (TypeError, ValueError):
        cx = 0.0

    try:
        cy = float(dev_elem.get("cy", "0") or "0")
    except (TypeError, ValueError):
        cy = 0.0

    return DeviceTopoInfo(
        id=dev_id,
        name=name,
        model=model,
        system_mac=dev_elem.get("system_mac", ""),
        com_port=com_port,
        cx=cx,
        cy=cy,
        poe=poe,
        bootmode=bootmode,
        interfaces=_parse_interfaces(dev_elem),
    )


def _parse_interfaces(dev_elem: ET.Element) -> list[InterfaceInfo]:
    interfaces: list[InterfaceInfo] = []

    for slot_elem in dev_elem.findall("slot"):
        for iface_elem in slot_elem.findall("interface"):
            try:
                count = int(iface_elem.get("count", "0") or "0")
            except (TypeError, ValueError):
                count = 0

            interfaces.append(
                InterfaceInfo(
                    sztype=iface_elem.get("sztype", ""),
                    interfacename=iface_elem.get("interfacename", ""),
                    count=count,
                )
            )
    return interfaces


def _parse_links(root: ET.Element) -> list[LinkInfo]:
    links: list[LinkInfo] = []
    lines_elem = root.find("lines")
    if lines_elem is None:
        return links

    for line_elem in lines_elem.findall("line"):
        link = _parse_single_link(line_elem)
        if link:
            links.append(link)
    return links


def _parse_single_link(line_elem: ET.Element) -> LinkInfo | None:
    src_id = line_elem.get("srcDeviceID")
    dest_id = line_elem.get("destDeviceID")
    if not src_id or not dest_id:
        return None

    iface_pair = line_elem.find("interfacePair")
    if iface_pair is None:
        return None

    try:
        src_index = int(iface_pair.get("srcIndex", "0") or "0")
    except (TypeError, ValueError):
        src_index = 0

    try:
        tar_index = int(iface_pair.get("tarIndex", "0") or "0")
    except (TypeError, ValueError):
        tar_index = 0

    return LinkInfo(
        src_device_id=src_id,
        dest_device_id=dest_id,
        line_name=iface_pair.get("lineName", ""),
        src_index=src_index,
        tar_index=tar_index,
    )
