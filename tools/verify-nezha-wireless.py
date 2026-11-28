#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compare final Nezha charging nodes with the matching factory DTBO entry."""
import argparse
import hashlib
import runpy
import struct
from pathlib import Path

HERE = Path(__file__).resolve().parent
fdt = runpy.run_path(str(HERE / "prepare-nezha-display.py"))
enabled = runpy.run_path(str(HERE / "check-nezha-basics.py"))["enabled"]
read_nodes, cells = fdt["read_nodes"], fdt["cells"]


def one(nodes, compatible):
    matches = [path for path, props in nodes.items()
               if compatible.encode() in props.get("compatible", b"").split(b"\0")]
    if len(matches) != 1:
        raise ValueError(f"{compatible} has {len(matches)} matching nodes")
    return matches[0]


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def verify(final, factory):
    require("/__fixups__" not in final, "expected a merged DTB")
    handles = {props["phandle"]: path for path, props in final.items() if "phandle" in props}
    rx, fod, cls, glink = (one(final, name) for name in (
        "sc,sc96281-wireless-charger", "mca_sc96281_fod_data",
        "mca,platform_wireless", "mca,adsp_glink"))
    for path in (rx, fod, cls, glink):
        require(enabled(final, path), f"disabled {path}")
    require(handles.get(final[rx].get("mca,fod-data")) == fod, "receiver calibration phandle")
    require(not enabled(final, glink.rsplit("/", 1)[0] + "/battery-charger"), "GLINK owner collision")
    stock_fod = factory[one(factory, "mca_sc96281_fod_data")]
    require({k: v for k, v in final[fod].items() if k != "phandle"} ==
            {k: v for k, v in stock_fod.items() if k != "phandle"}, "FOD property mismatch")
    stock_cls = factory[one(factory, "mca,platform_wireless")]
    for key in ("wireless-num", "wireless-dir-list"):
        require(final[cls].get(key) == stock_cls[key], key)
    stock_rx = factory[one(factory, "sc,sc96281-wireless-charger")]
    for key, expected in stock_rx.items():
        value = final[rx].get(key)
        if key in ("phandle", "pinctrl-0"):
            continue
        if key in ("rx-int", "pwr-det-int", "sleep-rx-gpio", "hall-s-int", "hall-n-int"):
            require(value is not None and value[4:] == expected[4:], key)
            controller = handles.get(value[:4])
            require(controller and final[controller].get("gpio-controller") == b"", key)
            require(final["/__symbols__"]["tlmm"].rstrip(b"\0").decode() == controller, key)
        else:
            require(value == expected, key)
    pins = final[rx]["pinctrl-0"]
    require(len(pins) == 12, "pinctrl-0 size")
    for offset in range(0, len(pins), 4):
        path = handles[pins[offset:offset + 4]]
        name = path.rsplit("/", 1)[1]
        stock = next(p for p in factory if p.endswith("/" + name) and "__overlay__" in p
                     and not p.startswith("/__local_fixups__/"))
        for child in ("mux", "config"):
            node = path + "/" + child
            require(final[node] == factory[stock + "/" + child], node)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dtbo_image", type=Path)
    parser.add_argument("final", nargs="+", type=Path)
    args = parser.parse_args()
    image = args.dtbo_image.read_bytes()
    require(hashlib.sha256(image).hexdigest() == fdt["IMAGE_SHA256"], "stock OS4.0.7 dtbo.img SHA-256")
    _, _, _, stride, count, offset, _, _ = struct.unpack_from(">8I", image)
    entries = {}
    for index in range(count):
        size, start = struct.unpack_from(">II", image, offset + index * stride)
        nodes = read_nodes(image[start:start + size])
        values = cells(nodes["/"]["qcom,msm-id"])
        for soc in zip(values[::2], values[1::2]):
            require(soc not in entries, "ambiguous factory SoC ID")
            entries[soc] = nodes
    for path in args.final:
        final = read_nodes(path.read_bytes())
        soc = tuple(cells(final["/"]["qcom,msm-id"]))
        require(soc in entries, f"{path.name} has no matching factory entry")
        verify(final, entries[soc])
        print(f"PASS {path.name} receiver, Hall, FOD, wireless class and GLINK owner")


if __name__ == "__main__":
    main()
