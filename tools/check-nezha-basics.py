#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Inventory basic Nezha hardware nodes in a FINAL merged DTB, not a DTBO.

Exit 1 when a required node group is missing/disabled, 2 on invalid input.
Exit 0 only means these DT nodes exist. It does not qualify drivers, firmware,
regulator/GPIO values, HAL compatibility, charging protection or device operation.
Run on every bootloader-selected variant; never audit just the overlay source.
"""
import argparse
import hashlib
import json
import runpy
import struct
from pathlib import Path


# This is the current OS4 Nezha hardware profile, not a generic Qualcomm BOM.
# Alternative charger stacks need a reviewed profile change, not a dummy node.
REQUIRED = {
    "charging": {
        "gauge": ("ti,bq27z561", "ti,bq27z561_master"),
        "adsp_transport": ("mca,adsp_glink",),
        "pd": ("mca,adsp_pd_protocol",),
        "charge_pump": ("sc8585_master",),
        "buck_provider": ("mca,qcom_subpmic",),
        "charge_interface": ("mca,charge_interface",),
        "wireless_receiver": ("sc,sc96281-wireless-charger",),
    },
    "touch": {
        "controller": ("synaptics,tcm-spi",),
        "framework": ("xiaomi-touch",),
    },
    "camera": {
        "request_manager": ("qcom,cam-req-mgr",),
        "cci": ("qcom,cci",),
        "csi": ("qcom,csiphy",),
        "sensor": ("qcom,cam-sensor", "qcom,cam-i2c-sensor"),
    },
    "modem": {
        "remoteproc": ("qcom,canoe-modem-pas", "qcom,whale-modem-pas"),
    },
    "wifi": {"peach": ("qcom,cnss-peach",)},
    "bluetooth": {"power": ("qcom,peach-bt",)},
}


def strings(value):
    return value.rstrip(b"\0").decode("ascii").split("\0") if value else []


def enabled(nodes, path):
    while True:
        status = nodes[path].get("status")
        if status is not None and strings(status) not in (["ok"], ["okay"]):
            return False
        if path == "/":
            return True
        path = path.rpartition("/")[0] or "/"


def inventory(nodes):
    if any(p.startswith("/fragment@") or p == "/__fixups__" for p in nodes):
        raise ValueError("Expected a final merged DTB, not an overlay")
    index = {}
    for path, props in nodes.items():
        for compat in strings(props.get("compatible", b"")):
            index.setdefault(compat, []).append(path)
    result = {}
    for feature, groups in REQUIRED.items():
        result[feature] = {}
        for name, compatibles in groups.items():
            paths = sorted({p for c in compatibles for p in index.get(c, [])})
            active = [p for p in paths if enabled(nodes, p)]
            result[feature][name] = {
                "state": "present" if active else "missing_or_disabled",
                "enabled_paths": active,
                "disabled_paths": [p for p in paths if p not in active],
            }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dtb", type=Path, nargs="+")
    args = parser.parse_args()
    read_nodes = runpy.run_path(str(Path(__file__).with_name(
        "prepare-nezha-display.py")))["read_nodes"]
    reports, missing = [], False
    for path in args.dtb:
        try:
            blob = path.read_bytes()
            features = inventory(read_nodes(blob))
        except (OSError, ValueError, IndexError, KeyError, struct.error) as exc:
            parser.error(f"{path}: {exc}")
        missing |= any(g["state"] != "present" for groups in features.values()
                       for g in groups.values())
        reports.append({"file": str(path), "sha256": hashlib.sha256(blob).hexdigest(),
                        "features": features})
    print(json.dumps({"scope": "DT node presence only; no hardware qualification",
                      "reports": reports}, indent=2))
    return int(missing)


if __name__ == "__main__":
    raise SystemExit(main())
