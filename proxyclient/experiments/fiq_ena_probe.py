#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
#
# Probe whether SYS_IMP_APL_VM_TMR_FIQ_ENA_EL2 is accessible (read + write) on
# this machine + firmware. This is the reg whose *write* is disallowed on M4 Pro
# under some macOS versions and blocks booting Linux under the m1n1 HV.
#
#   SYS_IMP_APL_VM_TMR_FIQ_ENA_EL2 = sys_reg(3, 5, 15, 1, 3)
#   ENA_V = bit0 (virtual timer), ENA_P = bit1 (physical timer)

import sys, pathlib
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from m1n1.setup import *

REG = (3, 5, 15, 1, 3)

chip_id = u.adt["/chosen"].chip_id
try:
    board = u.adt["/chosen"].target_type
except Exception:
    board = "?"
print(f"chip_id=0x{chip_id:x} board={board!r}")
print(f"MIDR part=0x{(u.mrs(MIDR_EL1) >> 4) & 0xfff:x}")

# --- read test ---
try:
    val = u.mrs(REG, silent=True)
    read_ok = True
    print(f"READ  SYS_IMP_APL_VM_TMR_FIQ_ENA_EL2 = 0x{val:x}  (read ALLOWED)")
except ProxyError:
    read_ok, val = False, None
    print("READ  trapped (read DISALLOWED)")

# --- write test (no-op: write back the same value, or 0 if unreadable) ---
wval = val if read_ok else 0
try:
    u.msr(REG, wval, silent=True)
    print(f"WRITE 0x{wval:x} -> ALLOWED")
    write_ok = True
except ProxyError:
    print(f"WRITE 0x{wval:x} -> trapped (write DISALLOWED)")
    write_ok = False

print()
print("=== VERDICT ===")
if write_ok:
    print("SYS_IMP_APL_VM_TMR_FIQ_ENA_EL2 is WRITABLE here -> the M4 Pro blocker")
    print("does NOT apply; Linux-in-HV timer setup should get past this point.")
else:
    print("Write is DISALLOWED here -> same blocker flokli hit on M4 Pro.")
