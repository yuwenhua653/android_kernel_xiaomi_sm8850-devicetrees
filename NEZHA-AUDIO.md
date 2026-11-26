# Nezha OS4.0.7 audio/haptic board wiring

`qcom/nezha-canoe-board-overlay.dtso` includes the new
`qcom/nezha-canoe-audio.dtsi` through the existing build entry and overlay order.
There is no extra extraction step during a normal source build.

Source: China OS4.0.7.0.XPACNXM dtbo entry 1, audio fragments 220–258 (even),
receiver GPIO fragment 261 and BT SoundWire fragment 274, plus the referenced
PMK8850 SDAM and PMIH010x haptic nodes. DTBO image SHA-256:
`1b78a4cc5fe5ee46fcf1ea3af0ee5a1287c0b4a2ef78a30f4b62f745d31505ac`.
Phandle references resolve to source labels; numeric factory phandles are not
used as fabricated providers. Original binaries are not committed.

Validated on canoe, canoe-v2, canoe-tp, canoe-tp-v2, canoep and canoep-v2:
1294 audio/haptic properties and references per final merged DTB, alongside
649 camera checks (including one GPIO descriptor conversion) and 194
connectivity checks. Normal Kbuild overlay compilation succeeds; DTC still
reports existing overlay-context/style warnings.

```sh
python3 tools/verify-nezha-audio.py stock-overlay-1.dtbo final.dtb
python3 tools/check-nezha-basics.py final.dtb
```

The first command accepts multiple final DTBs and compares properties after
resolving phandles. Later stock fragments take precedence. It rejects an
unmerged overlay as a final DTB. The second checks enabled nodes and ancestors;
it still reports missing charge-interface and wireless-receiver groups.

Audio/haptic nodes are not a runtime qualification. TAS25xx driver is still
absent from this port; the reviewed MiCode audio songyuan release
`922ff4070f803d8f7d1122b268fe0b2cd5d262c4` does not supply it. Kernel Nezha
haptic custom/calibration voltages and F0 fallback are separately integrated;
other OEM controls remain outside this change. Speakers, microphones, call
routing, BT audio, haptic HAL and suspend require device acceptance tests.
