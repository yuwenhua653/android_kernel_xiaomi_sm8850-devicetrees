#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compare a final Nezha DTB with the matching merged China OS4.0.7 factory DTB."""
import argparse
import runpy
from pathlib import Path

helpers = runpy.run_path(str(Path(__file__).with_name("prepare-nezha-display.py")))
cells = helpers["cells"]
SPECIFIERS = {
    "dmas": "#dma-cells", "clocks": "#clock-cells", "assigned-clocks": "#clock-cells",
    "resets": "#reset-cells", "gpios": "#gpio-cells", "phys": "#phy-cells",
    "power-domains": "#power-domain-cells", "interconnects": "#interconnect-cells",
    "iommus": "#iommu-cells", "interrupts-extended": "#interrupt-cells",
    "thermal-sensors": "#thermal-sensor-cells", "cooling-device": "#cooling-cells",
    "mboxes": "#mbox-cells", "io-channels": "#io-channel-cells", "msi-parent": "#msi-cells",
}
PHANDLES = {
    "remote-endpoint", "operating-points-v2", "interrupt-parent", "memory-region",
    "nvmem-cells", "nvmem", "msi-parent", "extcon", "qcom,wcd_usbss", "trip",
    "usb-repeater", "qcom,iommu-group", "cpu", "cpus", "cpu-idle-states", "next-level-cache", "shared-ice-cfg",
}
# Optional IP blocks must have the same path set, including their absence.
GROUPS = {
    "UFS": ("qcom,ufshc", "qcom,ufs-phy-qmp-v4-canoe"),
    "PMIC/keys": ("gpio-keys", "qcom,pmk8350-pwrkey", "qcom,pmk8350-resin",
                  "qcom,pmk8350-rtc", "qcom,regulator-ocp-notifier"),
    "USB": ("qcom,ucsi-glink", "usb-c-connector", "qcom,pmic-eusb2-repeater"),
    "GPU": ("qcom,kgsl-3d0", "qcom,kgsl-smmu-v2"),
    "IPA": ("qcom,ipa", "qcom,rmnet-ipa3", "qcom,smem_mailbox"),
    "DSP": ("qcom,fastrpc",),
    "video": ("qcom,canoe-vidc", "qcom,canoe-vidc-v2", "qcom,canoe-vidc-v3", "qcom,msm-cvp", "qcom,msm-mmrm"),
    "idle": ("qcom,lpm-cluster-dev",),
    "thermal": (),
    "IR": ("ir-spi",),
    "ToF": ("st,stmvl53l5",),
}
LABELS = {
    "USB": ("usb0", "wcd_usbss", "eusb2_phy0", "usb_qmp_dp_phy"),
    "thermal": ("pmk8850_vadc", "thermal_zones"),
    "IR": ("qupv3_se0_spi_mosi_active", "qupv3_se0_spi_sleep", "ls_gpio_active", "ls_gpio_sleep"),
    "ToF": ("L1F", "L16B", "L18B", "mi_se14_spi_miso_active", "mi_se14_spi_mosi_active",
            "mi_se14_spi_clk_active", "mi_tof_se14_spi_cs_active", "mi_qupv3_se14_spi_sleep",
            "mi_qupv3_se14_spi_cs_sleep"),
}


class Tree:
    def __init__(self, path):
        self.nodes = helpers["read_nodes"](path.read_bytes())
        if "/__fixups__" in self.nodes or "/__symbols__" not in self.nodes:
            raise ValueError(f"{path}: a merged DTB with symbols is required")
        self.handles = {cells(props["phandle"])[0]: key for key, props in self.nodes.items()
                        if "phandle" in props}
        self.labels = {key: value[:-1].decode() for key, value in self.nodes["/__symbols__"].items()}
        self.compat = {}
        for key, props in self.nodes.items():
            for name in props.get("compatible", b"").rstrip(b"\0").split(b"\0"):
                self.compat.setdefault(name.decode(), set()).add(key)

    def enabled(self, path):
        while path:
            if self.nodes[path].get("status", b"ok\0") not in (b"ok\0", b"okay\0"):
                return False
            path = path.rpartition("/")[0]
        return True

    def value(self, path, key, value):
        if key == "status":
            return value.replace(b"okay\0", b"ok\0")
        kind = SPECIFIERS.get(key)
        if key.endswith("-gpios"):
            kind = "#gpio-cells"
        if not (kind or key == "iommu-addresses" or key in PHANDLES or key.endswith("-supply") or
                (key.startswith("pinctrl-") and key[8:].isdigit())):
            return value
        data = cells(value)
        result = []
        i = 0
        while i < len(data):
            # OF phandle arrays can have an empty entry (e.g. the last GPU clock).
            if data[i] == 0 and key == "clocks":
                result.append(None)
                i += 1
                continue
            target = self.handles.get(data[i])
            if target is None:
                raise ValueError(f"{path}:{key} has an unresolved phandle at cell {i}")
            count = cells(self.nodes[target][kind])[0] if kind else 0
            if key == "iommu-addresses":
                count = sum(self.bus_cells(target, prop) for prop in ("#address-cells", "#size-cells"))
            if i + 1 + count > len(data):
                raise ValueError(f"{path}:{key} has a truncated {target} specifier")
            result.append((target, tuple(data[i + 1:i + 1 + count])))
            i += 1 + count
        return tuple(result)

    def bus_cells(self, path, prop):
        while path != "/":
            path = path.rpartition("/")[0] or "/"
            if prop in self.nodes[path]:
                return cells(self.nodes[path][prop])[0]
        raise ValueError(f"missing {prop} for IOMMU address specifier")

    # SE14 also has a separate factory satellite device at CS1. Compare the bus
    # wiring and its SPI/I2C/I3C mux without making CS1 part of ToF validation.
    def selected(self, group):
        roots = {path for compatible in GROUPS[group] for path in self.compat.get(compatible, ())}
        roots.update(self.labels[name] for name in LABELS.get(group, ()))
        paths = {path for root in roots for path in self.nodes if path == root or path.startswith(root + "/")}
        if group == "ToF":
            paths.update(self.labels[name] for name in ("qupv3_se14_spi", "qupv3_se14_i2c", "i3c3"))
        if group == "IR":
            paths.add(self.labels["qupv3_se0_spi"])
        return paths


def compare(ref, actual):
    for key in ("qcom,msm-id", "qcom,board-id"):
        if ref.nodes["/"].get(key) != actual.nodes["/"].get(key):
            raise ValueError(f"root {key} mismatch")
    checked = {}
    for group in GROUPS:
        paths = ref.selected(group)
        other = actual.selected(group)
        if paths != other:
            raise ValueError(f"{group}: node set differs: {sorted(paths ^ other)[:8]}")
        if not paths and group != "IPA":
            raise ValueError(f"{group}: no reference hardware")
        properties = 0
        for path in sorted(paths):
            if ref.enabled(path) != actual.enabled(path):
                raise ValueError(f"{group}: effective status at {path}")
            left, right = ref.nodes[path], actual.nodes[path]
            for key in sorted(left.keys() | right.keys()):
                if key in ("phandle", "linux,phandle"):
                    continue
                if key not in left or key not in right:
                    raise ValueError(f"{group}: missing property at {path}:{key}")
                expected = ref.value(path, key, left[key])
                if group == "ToF" and path == ref.labels["qupv3_se14_spi"] and key == "pinctrl-0":
                    satellite_cs = ref.labels.get("bd_qupv3_se14_spi_cs_active")
                    expected = tuple(entry for entry in expected if entry[0] != satellite_cs)
                if (group == "ToF" and key == "pins" and
                    path.rpartition("/")[0] == ref.labels["mi_qupv3_se14_spi_cs_sleep"]):
                    expected = b"\0".join(pin for pin in expected.split(b"\0") if pin != b"gpio13")
                if expected != actual.value(path, key, right[key]):
                    raise ValueError(f"{group}: property differs at {path}:{key}")
                properties += 1
        checked[group] = properties
    return checked


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stock", type=Path)
    parser.add_argument("final", type=Path, nargs="+")
    args = parser.parse_args()
    ref = Tree(args.stock)
    for path in args.final:
        stats = compare(ref, Tree(path))
        print(f"PASS {path.name}: " + ", ".join(f"{name}={count}" for name, count in stats.items()))


if __name__ == "__main__":
    main()
