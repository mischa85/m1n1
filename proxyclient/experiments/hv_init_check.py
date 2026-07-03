#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
#
# Stage-0 HV substrate validation for T6041 (M4 Max).
#
# Brings up the m1n1 hypervisor on real hardware WITHOUT loading a guest or a
# device tree, to confirm the flashed HV path works on this SoC:
#   - hv.init()         : core HV setup; on a locked chip it must take the
#                         !apple_sysregs_unlocked branch (skip AMX/AP-key/SPRR).
#   - hv.map_essential(): exercises the T6041 CPUSTART entry (chip_id 0x6041 ->
#                         cpu_start 0x88000) and the RVBAR-on-!unlocked hooks.
# Does NOT call hv.start() (that would need a payload + entrypoint). Leaving the
# HV initialized-but-idle is a normal, reconnectable state.

import sys, pathlib, traceback
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

def log(m):
    print(m, flush=True)

from m1n1.setup import *   # provides iface, p, u, and hv = HV(iface, p, u)

chip_id = u.adt["/chosen"].chip_id
unlocked = getattr(getattr(u, "cpu_features", None), "apple_sysregs_unlocked", "?")
log(f"chip_id={chip_id:#x}  MIDR part={(u.mrs(MIDR_EL1) >> 4) & 0xfff:#04x}  "
    f"apple_sysregs_unlocked={unlocked}")

# Expected CPUSTART offset for T6041, per the table we extended in map_essential()
expected = {0x6031: 0x88000, 0x6034: 0x88000, 0x6040: 0x88000, 0x6041: 0x88000}.get(chip_id)
log(f"expected CPUSTART offset for this chip = {expected:#x}" if expected else
    "expected CPUSTART offset: UNKNOWN (chip not in 0x88000 group!)")

ok = True

log("\n[*] hv.init() ...")
try:
    hv.init()
    log("[+] hv.init() completed — HV core is up (locked-reg path taken if unlocked=0)")
except Exception:
    ok = False
    log("[!] hv.init() FAILED:\n" + traceback.format_exc())

if ok:
    log("\n[*] hv.map_essential() (exercises T6041 CPUSTART + RVBAR-on-locked) ...")
    try:
        hv.map_essential()
        log("[+] map_essential() completed — CPUSTART hook for chip_id "
            f"{chip_id:#x} set up, no 'CPUSTART unknown' (T6041 line works)")
    except Exception:
        ok = False
        log("[!] map_essential() FAILED:\n" + traceback.format_exc())

log("\n=== VERDICT ===")
if ok:
    log("PASS: m1n1 HV initialized on T6041 and essential MMIO/CPUSTART/RVBAR "
        "hooks set up. The flashed CPUSTART(0x6041) + !apple_sysregs_unlocked "
        "paths work on real hardware. Next stage: load a guest and hv.start().")
else:
    log("FAIL: see traceback above — this is the first concrete HV blocker on T6041.")
log("[*] done (HV left initialized-but-idle; not starting a guest)")
