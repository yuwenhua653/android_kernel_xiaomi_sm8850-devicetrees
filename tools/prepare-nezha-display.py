#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Prepare the Canoe board display include from a local Nezha OS4.0.7 DTBO image."""
import argparse
import hashlib
import json
import struct
import tempfile
from collections import defaultdict
from pathlib import Path

IMAGE_SHA256 = "1b78a4cc5fe5ee46fcf1ea3af0ee5a1287c0b4a2ef78a30f4b62f745d31505ac"
# Fragment numbers refer to entry 1 of this exact DT table. Entry 0 is SG/Whale.
# The last connector list (179) supersedes the earlier list at fragment 155.
DISPLAY_FRAGMENTS = (81, 147, 149, 151, 153, *range(157, 184, 2))
OUTPUT = Path(__file__).resolve().parents[1] / "qcom/nezha-os4-display.generated.dtsi"


def cells(data):
    return [v for v, in struct.iter_unpack(">I", data)]


def read_nodes(blob):
    magic, total, pos, strings, *_ = struct.unpack_from(">10I", blob)
    if magic != 0xd00dfeed or total != len(blob):
        raise ValueError("Invalid flattened device tree")
    nodes, stack = {}, []
    while pos < total:
        token, = struct.unpack_from(">I", blob, pos)
        pos += 4
        if token == 1:
            end = blob.index(0, pos)
            stack.append(blob[pos:end].decode())
            nodes["/".join(stack) or "/"] = {}
            pos = (end + 4) & ~3
        elif token == 2:
            stack.pop()
        elif token == 3:
            length, name = struct.unpack_from(">II", blob, pos)
            start = strings + name
            key = blob[start:blob.index(0, start)].decode()
            pos += 8
            nodes["/".join(stack) or "/"][key] = blob[pos:pos + length]
            pos = (pos + length + 3) & ~3
        elif token == 9:
            return nodes
        elif token != 4:
            raise ValueError(f"Invalid FDT token {token}")
    raise ValueError("Incomplete device tree")


class BoardOverlay:
    def __init__(self, blob):
        self.nodes = read_nodes(blob)
        self.labels = {v[:-1].decode(): k for k, v in self.nodes["/__symbols__"].items()}
        self.children = defaultdict(list)
        handles = {}
        for path, props in self.nodes.items():
            self.children[path.rpartition("/")[0]].append(path)
            if "phandle" in props:
                handles[props["phandle"]] = path

        self.refs = {}
        self.pin_nodes = set()
        for label, encoded in self.nodes["/__fixups__"].items():
            for item in encoded[:-1].decode().split("\0"):
                path, name, offset = item.rsplit(":", 2)
                self.refs[path, name, int(offset)] = label

        for fixup, props in self.nodes.items():
            if not fixup.startswith("/__local_fixups__/"):
                continue
            path = fixup[len("/__local_fixups__"):]
            for name, offsets in props.items():
                for offset in cells(offsets):
                    dest = handles[self.nodes[path][name][offset:offset + 4]]
                    self.refs[path, name, offset] = self.labels[dest]
                    if path.startswith(("/fragment@149/", "/fragment@151/")) and dest.startswith(("/fragment@0/", "/fragment@1/")):
                        while dest.count("/") >= 2:
                            self.pin_nodes.add(dest)
                            dest = dest.rpartition("/")[0]

    def property(self, path, name, data, indent):
        prefix = indent + name
        if not data:
            return prefix + ";"
        pieces = data[:-1].split(b"\0")
        if data[-1] == 0 and all(pieces) and all(all(32 <= c < 127 for c in s) for s in pieces):
            return prefix + " = " + ", ".join(json.dumps(s.decode()) for s in pieces) + ";"
        if len(data) % 4 or ("command" in name and len(data) >= 7 and data[0] and "update" not in name):
            rows = [data[i:i + 16].hex(" ") for i in range(0, len(data), 16)]
            return prefix + " = [\n" + "\n".join(indent + "\t" + row for row in rows) + "\n" + indent + "];"
        rows, row = [], []
        for idx, value in enumerate(cells(data)):
            label = self.refs.get((path, name, idx * 4))
            if row and (label or len(row) == 8):
                rows.append(" ".join(row))
                row = []
            row.append("&" + label if label else str(value) if value < 100000000 else hex(value))
        rows.append(" ".join(row))
        return prefix + " = <" + (">,\n" + indent + "\t<").join(rows) + ">;"

    def contents(self, path, indent, pins_only):
        for name, value in self.nodes[path].items():
            if name != "phandle":
                yield self.property(path, name, value, indent)
        for child in self.children[path]:
            if pins_only and child not in self.pin_nodes:
                continue
            label = self.labels.get(child)
            prefix = label + ": " if label else ""
            yield indent + prefix + child.rsplit("/", 1)[-1] + " {"
            yield from self.contents(child, indent + "\t", pins_only)
            yield indent + "};"

    def source(self):
        yield "/* Generated from the local OS4.0.7.0.XPACNXM image. */"
        for number in (0, 1, *DISPLAY_FRAGMENTS):
            fragment = f"/fragment@{number}"
            yield "\n&" + self.refs[fragment, "target", 0] + " {"
            yield from self.contents(fragment + "/__overlay__", "\t", number in (0, 1))
            yield "};"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dtbo", type=Path, help="dtbo.img extracted from the full China OTA")
    args = parser.parse_args()
    data = args.dtbo.read_bytes()
    if hashlib.sha256(data).hexdigest() != IMAGE_SHA256:
        parser.error("Expected the complete OS4.0.7.0.XPACNXM dtbo partition image")
    _, _, _, stride, _, entries, _, _ = struct.unpack_from(">8I", data)
    length, offset = struct.unpack_from(">II", data, entries + stride)
    overlay = BoardOverlay(data[offset:offset + length])
    source = "\n".join(overlay.source()) + "\n"
    if OUTPUT.exists() and OUTPUT.read_text() == source:
        print(f"Already prepared {OUTPUT}")
        return
    with tempfile.NamedTemporaryFile(mode="w", dir=OUTPUT.parent, delete=False) as tmp:
        tmp.write(source)
    Path(tmp.name).replace(OUTPUT)
    print(f"Prepared {OUTPUT}")


if __name__ == "__main__":
    main()
