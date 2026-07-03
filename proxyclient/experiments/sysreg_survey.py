#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
#
# Apple impl-def system-register accessibility survey.
#
# Determines, on THIS machine + firmware, which Apple implementation-defined
# registers are readable and writable from EL2 (the proxy core). The write test
# is the interesting one: locked registers trap on write, which is what blocks
# m1n1's HV setup on some M4 firmwares (cf. SYS_IMP_APL_VM_TMR_FIQ_ENA_EL2 on
# M4 Pro). Cross-checks the empirical result against m1n1's own
# cpu_features.apple_sysregs_unlocked (requires P_GET_CPU_FEATURES firmware).
#
# Write tests are SAFE: each writes back the exact value just read (a no-op),
# under the SKIP/SILENT exception guard, and only for registers flagged
# write-safe. Status/action/W1C registers are read-only here.

import sys, pathlib
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from m1n1.setup import *

def log(m):
    print(m, flush=True)

# (name, (op0,op1,CRn,CRm,op2), write_safe)
# write_safe=True only for config/control regs where rewriting the read-back
# value is a definite no-op. Status / W1C / action regs are read-only.
REGS = [
    # The historical "is this core unlocked" reg, + the M4 HV timer blocker
    ("CYC_OVRD",            (3, 5, 15, 5, 0),  True),
    ("VM_TMR_FIQ_ENA_EL2",  (3, 5, 15, 1, 3),  True),
    # SPRR / GXF config (gated on apple_sysregs_unlocked in m1n1)
    ("SPRR_CONFIG_EL1",     (3, 6, 15, 1, 0),  True),
    ("GXF_CONFIG_EL1",      (3, 6, 15, 1, 2),  True),
    ("GXF_STATUS_EL1",      (3, 6, 15, 8, 0),  False),
    ("GXF_ENTER_EL1",       (3, 6, 15, 8, 1),  False),
    ("SPRR_PERM_EL1",       (3, 6, 15, 1, 6),  False),
    # AMX control
    ("AMX_CTL_EL1",         (3, 4, 15, 1, 4),  True),
    ("AMX_CTL_EL2",         (3, 4, 15, 4, 7),  True),
    # Pointer-auth control
    ("APCTL_EL1",           (3, 4, 15, 0, 4),  True),
    # IPI: SR is write-1-to-clear -> read only
    ("IPI_SR_EL1",          (3, 5, 15, 1, 1),  False),
    # Chicken-bit registers: m1n1 only writes these if apple_sysregs_unlocked,
    # so write access here IS the apple_sysregs_unlocked test. Same-value
    # write-back is a no-op.
    ("HID0",                (3, 0, 15, 0, 0),  True),
    ("HID1",                (3, 0, 15, 1, 0),  True),
    ("HID4",                (3, 0, 15, 4, 0),  True),
    ("HID5",                (3, 0, 15, 5, 0),  True),
    ("HID11",               (3, 0, 15, 11, 0), True),
    # Performance monitor control (writable when unlocked)
    ("PMCR0",               (3, 1, 15, 0, 0),  True),
    # Standard arch control reg, as a sanity baseline (should always work)
    ("ACTLR_EL1",           (3, 0, 1, 0, 1),   True),
]

chip_id = u.adt["/chosen"].chip_id
part = (u.mrs(MIDR_EL1) >> 4) & 0xfff
log(f"chip_id={chip_id:#x}  MIDR part={part:#04x}")

cf = getattr(u, "cpu_features", None)
if cf is not None:
    log("m1n1 cpu_features view:")
    for k in ("apple_sysregs_unlocked", "mmu_sprr", "fast_ipi", "nex_powergating"):
        try:
            log(f"    {k} = {getattr(cf, k)}")
        except Exception:
            pass
else:
    log("m1n1 cpu_features: UNAVAILABLE (old firmware without P_GET_CPU_FEATURES?)")

log("")
log(f"{'register':22} {'read':>10}  {'value':>18}  {'write':>10}")
log("-" * 66)

rows = []
for name, enc, wsafe in REGS:
    # read test
    try:
        val = u.mrs(enc, silent=True)
        rd = "OK"
    except Exception:
        val, rd = None, "TRAP"
    # write test (no-op write-back), only if read worked and reg is write-safe
    if rd == "OK" and wsafe:
        try:
            u.msr(enc, val, silent=True)
            wr = "OK"
        except Exception:
            wr = "TRAP"
    elif not wsafe:
        wr = "(skip)"
    else:
        wr = "-"
    valstr = f"{val:#018x}" if val is not None else ""
    log(f"{name:22} {rd:>10}  {valstr:>18}  {wr:>10}")
    rows.append((name, rd, wr, wsafe))

log("")
log("=== Summary ===")
wt = [r for r in rows if r[3]]
locked = [r[0] for r in rows if r[1] == "OK" and r[2] == "TRAP"]
unwrit = [r[0] for r in rows if r[2] == "TRAP"]
log(f"writable (of {len(wt)} write-tested): {[r[0] for r in wt if r[2]=='OK']}")
log(f"write-LOCKED (readable but write traps): {locked or 'none'}")
if cf is not None:
    log(f"m1n1 says apple_sysregs_unlocked = {getattr(cf,'apple_sysregs_unlocked','?')}; "
        f"empirical chicken-bit (HID) writes {'ALL OK' if not any(n.startswith('HID') and w=='TRAP' for n,_,w,_ in rows) else 'SOME TRAPPED'}")
log("[*] done")
