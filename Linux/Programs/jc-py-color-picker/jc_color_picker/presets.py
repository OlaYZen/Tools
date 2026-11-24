"""Preset colors and user-preset persistence.

* **Retail presets** — the fixed Nintendo retail body/button colors, read from the
  bundled ``retail_colors.xml`` (the same data file shipped with the original
  toolkit).
* **Grip presets** — the retail Pro-Controller grip colors.  These were hard-coded
  in the original WinForms designer (not in the XML), so they are reproduced here.
* **User preset banks** — two banks of editable swatches (a 16-slot "retail user"
  bank and a 32-slot "user" bank) persisted to ``colors.xml`` in the *exact* same
  format the original tool used, so a ``colors.xml`` is interchangeable between
  the two programs.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import List

from .adobe_colors import hex_to_rgb, rgb_to_hex

HERE = os.path.dirname(os.path.abspath(__file__))
RETAIL_XML = os.path.join(HERE, "retail_colors.xml")

# Editable swatch banks (match the original control counts).
RETAIL_USER_SLOTS = 16
USER_SLOTS = 32
# Colour the original tool uses for an empty / cleared slot: RGB(80, 80, 80).
EMPTY_HEX = "505050"

# Retail Pro-Controller grip colors, hard-coded in frmJoyConColorPicker's designer.
RETAIL_GRIPS = [
    {"hex": "464646", "name": "Normal Grips"},
    {"hex": "DD3B64", "name": "Xenoblade Grips"},
    {"hex": "1EDC00", "name": "Splatoon Left Grip"},
    {"hex": "FF3278", "name": "Splatoon Right Grip"},
]


@dataclass
class Swatch:
    """A single preset swatch: a hex color plus an optional tooltip/name."""

    hex: str = EMPTY_HEX
    tooltip: str = ""

    @property
    def empty(self) -> bool:
        return self.hex.upper() == EMPTY_HEX and not self.tooltip

    def to_dict(self) -> dict:
        return {"hex": self.hex.upper(), "tooltip": self.tooltip}


def _normalise_hex(value: str) -> str:
    """Best-effort clean-up of a hex string read from XML/JSON."""
    try:
        return rgb_to_hex(*hex_to_rgb(value))
    except (ValueError, TypeError):
        return EMPTY_HEX


def load_retail_colors(path: str = RETAIL_XML) -> dict:
    """Parse ``retail_colors.xml`` into body / button swatch lists.

    Returns ``{"body": [Swatch, ...], "buttons": [Swatch, ...]}``.
    """
    body: List[Swatch] = []
    buttons: List[Swatch] = []
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, FileNotFoundError):
        return {"body": body, "buttons": buttons}

    def _collect(tag: str, dest: List[Swatch]) -> None:
        node = root.find(tag)
        if node is None:
            return
        for rc in node.findall("RC"):
            dest.append(
                Swatch(
                    hex=_normalise_hex(rc.get("rgb_color", EMPTY_HEX)),
                    tooltip=rc.get("tooltip", ""),
                )
            )

    _collect("RetailColors", body)
    _collect("RetailColorsButtons", buttons)
    return {"body": body, "buttons": buttons}


def default_config_path() -> str:
    """Where user presets are stored (XDG config dir, override with env var)."""
    override = os.environ.get("JC_COLOR_PICKER_CONFIG")
    if override:
        return override
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "jc-color-picker", "colors.xml")


@dataclass
class PresetStore:
    """Loads and saves the two editable preset banks to ``colors.xml``."""

    path: str = field(default_factory=default_config_path)
    retail_user: List[Swatch] = field(default_factory=list)
    user: List[Swatch] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.retail_user:
            self.retail_user = [Swatch() for _ in range(RETAIL_USER_SLOTS)]
        if not self.user:
            self.user = [Swatch() for _ in range(USER_SLOTS)]

    # -- loading -----------------------------------------------------------
    @classmethod
    def load(cls, path: str | None = None) -> "PresetStore":
        store = cls(path=path or default_config_path())
        try:
            root = ET.parse(store.path).getroot()
        except (ET.ParseError, FileNotFoundError, OSError):
            return store  # fresh store with empty banks

        store._read_bank(root, "RetailColors", "RC", store.retail_user)
        store._read_bank(root, "UserColors", "UC", store.user)
        return store

    @staticmethod
    def _read_bank(root, container_tag: str, item_tag: str, dest: List[Swatch]) -> None:
        node = root.find(container_tag)
        if node is None:
            return
        for i, item in enumerate(node.findall(item_tag)):
            if i >= len(dest):
                break
            dest[i] = Swatch(
                hex=_normalise_hex(item.get("rgb_color", EMPTY_HEX)),
                tooltip=item.get("tooltip", ""),
            )

    # -- saving ------------------------------------------------------------
    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)

        root = ET.Element("configuration")
        comment = ET.Comment("Values are in RGB. Written by jc-py-color-picker.")
        root.append(comment)

        self._write_bank(root, "RetailColors", "RC", "retailpreset_", self.retail_user)
        self._write_bank(root, "UserColors", "UC", "userpreset_", self.user)

        tree = ET.ElementTree(root)
        ET.indent(tree, space="  ")
        tree.write(self.path, encoding="utf-8", xml_declaration=True)

    @staticmethod
    def _write_bank(root, container_tag, item_tag, key_prefix, swatches) -> None:
        container = ET.SubElement(root, container_tag)
        for i, sw in enumerate(swatches, start=1):
            el = ET.SubElement(container, item_tag)
            el.set("key", f"{key_prefix}{i:02d}")
            el.set("rgb_color", sw.hex.upper())
            el.set("tooltip", sw.tooltip)

    # -- mutation from the API --------------------------------------------
    def update_from_payload(self, payload: dict) -> None:
        """Replace bank contents from a JSON payload sent by the front-end."""
        if "retail_user" in payload:
            self.retail_user = self._coerce_bank(payload["retail_user"], RETAIL_USER_SLOTS)
        if "user" in payload:
            self.user = self._coerce_bank(payload["user"], USER_SLOTS)

    @staticmethod
    def _coerce_bank(items, count: int) -> List[Swatch]:
        bank = [Swatch() for _ in range(count)]
        for i, item in enumerate(items or []):
            if i >= count:
                break
            bank[i] = Swatch(
                hex=_normalise_hex(item.get("hex", EMPTY_HEX)),
                tooltip=str(item.get("tooltip", "")),
            )
        return bank

    def to_dict(self) -> dict:
        return {
            "retail_user": [s.to_dict() for s in self.retail_user],
            "user": [s.to_dict() for s in self.user],
        }


def all_presets(store: PresetStore | None = None) -> dict:
    """Bundle every preset group into one JSON-friendly dict for the front-end."""
    if store is None:
        store = PresetStore.load()
    retail = load_retail_colors()
    return {
        "retail_body": [s.to_dict() for s in retail["body"]],
        "retail_buttons": [s.to_dict() for s in retail["buttons"]],
        "retail_grips": [dict(hex=g["hex"], tooltip=g["name"]) for g in RETAIL_GRIPS],
        "retail_user": [s.to_dict() for s in store.retail_user],
        "user": [s.to_dict() for s in store.user],
        "config_path": store.path,
    }
