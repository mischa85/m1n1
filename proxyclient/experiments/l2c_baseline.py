#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
#
# Baseline the Apple L2C/error-syndrome registers right after m1n1 boot, with
# NO guest started. Disambiguates whether the L2C ACCESS_FAULT we see at the
# guest's async SError is the guest's runtime fault, or stale from m1n1's own
# boot-time DART/clock init (the L2C_ERR W1C-clear traps on M4, so it latches).
#
#   L2C_ERR_STS already set here (no guest)  -> m1n1-boot fault (stale)
#   L2C_ERR_STS clear here                   -> the guest causes it at runtime

import sys, pathlib
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
from m1n1.setup import *

print(f"chip_id=0x{u.adt['/chosen'].chip_id:x}  MIDR part=0x{(u.mrs(MIDR_EL1)>>4)&0xfff:x}")
print("== L2C / error syndrome BASELINE (no guest booted) ==")

def rd(name, reg):
    try:
        v = u.mrs(reg, silent=True)
        print(f"  {name:14}: {v:#018x}")
        return v
    except Exception:
        print(f"  {name:14}: (trapped)")
        return None

sts = rd("L2C_ERR_STS", L2C_ERR_STS_EL1)
if sts:
    fl = []
    if sts & (1 << 1):  fl.append("RECURSIVE_FAULT")
    if sts & (1 << 7):  fl.append("ACCESS_FAULT")
    if sts & (1 << 56): fl.append("ENABLE_W1C")
    print(f"  -> {' | '.join(fl) if fl else '(no flags)'}")
rd("L2C_ERR_ADR", L2C_ERR_ADR_EL1)
rd("L2C_ERR_INF", L2C_ERR_INF_EL1)
rd("LSU_ERR_STS", LSU_ERR_STS_EL1)
rd("FED_ERR_STS", FED_ERR_STS_EL1)
rd("MMU_ERR_STS", MMU_ERR_STS_EL1)

print()
if sts and (sts & (1 << 7)):
    print("VERDICT: L2C ACCESS_FAULT is ALREADY SET with no guest -> it's m1n1's")
    print("         own boot-time access (stale/latched), NOT the guest's runtime fault.")
elif sts:
    print(f"VERDICT: L2C_ERR_STS set ({sts:#x}) but no ACCESS_FAULT bit.")
else:
    print("VERDICT: L2C_ERR_STS clear here -> the guest causes the access fault at runtime.")
