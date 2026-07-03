#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
#
# T6041 (M4 Max) NVMe probe: is Apple's SPTM resident at gl2 in our m1n1 boot?
#
# Background: SPTM writes the NVMe admin-queue BAR with a PLAIN store to a VA it
# mapped in gl2; there is no per-store hardware gl/el check (chaos_princess). Our
# m1n1 EL2 store to bar+0x24 faulted at the FABRIC (L2C async), so the question is
# whether the gl2-owned mappings/physical-protection are held by a RESIDENT Apple
# SPTM (=> m1n1@EL2 can't override, need the gl2/SPTM path) or not (=> m1n1 may be
# able to map + store directly).
#
# This probe is STRICTLY READ-ONLY:
#   - it never writes SPRR/GXF config (enabling SPRR crashed m1n1 before), and
#   - it never touches the NVMe BAR (that store faults ASYNC -> reboot).
# Synchronous faulting reads are caught via GUARD.SKIP (u.mrs raises ProxyError),
# so a locked/inaccessible reg is reported, not fatal.

import sys, pathlib
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from m1n1.setup import *

SPRR_PERM_EL1  = (3, 6, 15, 1, 6)
GL_CTX_SCRATCH = (3, 6, 15, 11, 1)   # s3_6_c15_c11_1: SPTM per-cpu guarded ctx ptr

def read(reg):
    try:
        return u.mrs(reg, silent=True), None
    except Exception as e:
        return None, e

def show(name, reg, decode=None):
    v, err = read(reg)
    if err is not None:
        print("  %-26s = <faulted / inaccessible from EL2>" % name)
        return None
    s = "  %-26s = 0x%016x" % (name, v)
    if decode:
        s += "   " + decode(v)
    print(s)
    return v

print("== CurrentEL ==")
print("  CurrentEL = 0x%x  (0x8 = EL2h expected under m1n1 HV)" % u.mrs(CurrentEL))

print("\n== GXF / SPRR / guarded-mode state ==")
aidr = show("AIDR_EL1", AIDR_EL1,
            lambda v: "GXF-capable" if (v & (1 << 16)) else "no GXF capability bit")
sprr  = show("SPRR_CONFIG_EL1",  SPRR_CONFIG_EL1,
             lambda v: "EN=%d LOCK_CFG=%d LOCK_PERM=%d" % (v & 1, (v >> 1) & 1, (v >> 4) & 1))
sprr12= show("SPRR_CONFIG_EL12", SPRR_CONFIG_EL12,
             lambda v: "EN=%d LOCK_CFG=%d LOCK_PERM=%d" % (v & 1, (v >> 1) & 1, (v >> 4) & 1))
gxfc  = show("GXF_CONFIG_EL1",   GXF_CONFIG_EL1,   lambda v: "EN=%d" % (v & 1))
gxfc12= show("GXF_CONFIG_EL12",  GXF_CONFIG_EL12,  lambda v: "EN=%d" % (v & 1))
gxfs  = show("GXF_STATUS_EL1",   GXF_STATUS_EL1,   lambda v: "GUARDED=%d" % (v & 1))
ctx   = show("s3_6_c15_c11_1 (gl ctx)", GL_CTX_SCRATCH,
             lambda v: "NONZERO => SPTM per-cpu ctx set" if v else "zero")
show("SPRR_PERM_EL1", SPRR_PERM_EL1,
     lambda v: "programmed (perm remap active)" if v not in (0, None) else "zero")

def _set(x, bit):  # None-safe bit test
    return x is not None and (x & bit)

print("\n== interpretation ==")
active = False
if _set(sprr, 1) or _set(sprr12, 1):
    print("  * SPRR_CONFIG_EN set at boot -> guarded machinery ENABLED by the boot chain")
    active = True
if _set(gxfc, 1) or _set(gxfc12, 1):
    print("  * GXF_CONFIG_EN set -> GXF active")
    active = True
if _set(sprr, 0b10010) or _set(sprr12, 0b10010):
    print("  * SPRR LOCK bit(s) set -> a monitor locked the config (SPTM ran)")
    active = True
if ctx:
    print("  * guarded ctx scratch nonzero -> SPTM set up a per-cpu guarded context")
    active = True

if active:
    print("  => Apple SPTM appears RESIDENT at gl2. The NVMe BAR mappings/physical")
    print("     protection are gl2-owned; m1n1@EL2 cannot override them, so NVMe")
    print("     needs the gl2/SPTM-emulation path (not a plain-EL2 map+store).")
else:
    print("  => No active gl2/GXF state detected at EL2. If so, the NVMe fabric")
    print("     protection was set pre-handoff (iBoot/SPTM) and may or may not")
    print("     persist. Next: an explicit device-attr mapping of the BAR in m1n1's")
    print("     own EL2 tables + store (separate test; store faults async, so do it")
    print("     under the HV where we can catch/inspect it).")

print("\n(read-only probe complete; no config written, BAR untouched)")
