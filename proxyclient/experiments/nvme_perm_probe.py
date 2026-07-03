#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
#
# T6041 (M4 Max) NVMe DMA-permission probe -- READ ONLY, SAFE.
#
# Purpose: the ANS firmware crashes in its cold-boot FTL rebuild with
#   NVME_PERM_ERR F2H (a storage-lane DMA permission fault). Before guessing
#   what bringup is missing, read what iBoot ALREADY programmed into the
#   SART + NVMMU/CoastGuard allowed-DMA apertures while the ANS is still
#   iBoot-booted (RUN set) and BEFORE Linux ever attaches.
#
# This does NOT call p.nvme_init() and does NOT write anything, so it cannot
# wedge the machine. Run it at a fresh m1n1 proxy:
#   M1N1DEVICE=/dev/ttyACM1 python3 proxyclient/experiments/nvme_perm_probe.py
#
# Then boot Linux (which crashes), p.reboot(), and re-run to compare -- if the
# apertures differ, Linux is clobbering iBoot's DMA-permission setup.
#
# Addresses (CPU-phys, from the ADT /arm-io/ans + /arm-io/sart-ans):
#   NVMe BAR      0x40dcc0000   (admin regs 0x24-0x34, NVMMU 0x281xx, linear_sq 0x2813c)
#   NVMe BAR alias 0x44dcc0000  (= BAR + 0x40000000; the EL2-writable window)
#   SART regs     0x40dc50000
import sys, pathlib
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
from m1n1.setup import *

BAR   = 0x40dcc0000
ALIAS = BAR + 0x40000000
SART  = 0x40dc50000

def rd32(addr, note=""):
    try:
        v = p.read32(addr)
        print(f"    {addr:#013x} = {v:#010x}  {note}")
        return v
    except Exception as e:  # ProxyCommandError etc. -- keep the probe going
        print(f"    {addr:#013x} = <FAULT: {e}>  {note}")
        return None

print("\n>>> ===== T6041 NVMe DMA-permission probe (READ ONLY) =====")

# 1. ADT ground truth
try:
    ans = u.adt["/arm-io/ans"]
    print(">>> /arm-io/ans regs:")
    for i in range(10):
        try:
            a, s = ans.get_reg(i)
            print(f"      reg[{i}] {a:#x} (size {s:#x})")
        except Exception:
            break
except Exception as e:
    print(">>> /arm-io/ans:", e)
try:
    nub = u.adt["/arm-io/ans/iop-ans-nub"]
    print(f">>> iop-ans-nub region-base = {nub.region_base:#x}  region-size = {nub.region_size:#x}")
except Exception as e:
    print(">>> iop-ans-nub:", e)

# SAFETY: only read known-accessible locations, and order SAFEST-FIRST so we
# capture data even if a later read faults. DO NOT read the low NVMe-BAR block
# (0x00-0xfff: admin 0x24/28/30, 0x44, 0x13c8) from the primary BAR -- those are
# EL2-gated and a read there SYNC-faults + wedges m1n1 (learned the hard way).
# The +0x40000000 alias is only 0x10000 wide, so it CANNOT reach 0x28xxx -- the
# NVMMU block at 0x281xx is non-gated and is read via the PRIMARY BAR directly.

# 2. ANS boot status (confirmed safe: 0x1300 returns 0xde71ce55 when booted)
print("\n>>> ANS boot-status:")
rd32(BAR + 0x1300, "boot status (expect 0xde71ce55 = OK)")

# 3. NVMMU / CoastGuard allowed-DMA aperture (base[0x748] = BAR+0x28000), primary
#    BAR (0x281xx is non-gated). enable_coastguard (SPTM op1) writes:
#      +0x100 = enable mask (0x3f when armed)
#      +0x108/+0x10c = allowed-DMA base  (lo/hi)
#      +0x110/+0x114 = allowed-DMA limit (lo/hi)
print("\n>>> NVMMU/CoastGuard aperture (BAR 0x40dcc0000 + 0x28100..):")
rd32(BAR + 0x28100, "num_tcbs / enable")
lo  = rd32(BAR + 0x28108, "allowed-DMA base lo")
hi  = rd32(BAR + 0x2810c, "allowed-DMA base hi")
llo = rd32(BAR + 0x28110, "allowed-DMA limit lo")
lhi = rd32(BAR + 0x28114, "allowed-DMA limit hi")
if None not in (lo, hi, llo, lhi):
    b = (hi << 32) | lo
    l = (lhi << 32) | llo
    print(f"      => allowed-DMA window [{b:#x} .. {l:#x}]  (fw region-base = 0x11fd9ce4000)")

# 4. SART entries (iBoot's allow-list). v3 layout: cfg@0x00+4i, paddr@0x40+4i,
#    size@0x80+4i. Separate peripheral; EL2-read-safety UNCONFIRMED and a SYNC
#    fault here would wedge m1n1 (Python can't catch it). OPT-IN via PROBE_SART=1
#    only after a clean boot-status+NVMMU run, so we never burn a reboot blindly.
import os
if not os.environ.get("PROBE_SART"):
    print("\n>>> SART dump skipped (set PROBE_SART=1 to enable, after a clean run)")
    print("\n>>> done (safe subset). KEY: does the allowed-DMA window cover the fw")
    print(">>>   working region 0x11fd9ce4000 + 600MB?")
    sys.exit(0)
print("\n>>> SART entries (0x40dc50000):")
for i in range(16):
    cfg  = rd32(SART + 0x00 + 4*i)
    if cfg is None:
        print("      (SART read faulted; stopping SART dump)")
        break
    padr = rd32(SART + 0x40 + 4*i)
    size = rd32(SART + 0x80 + 4*i)
    if padr is None or size is None:
        break
    flags = (cfg >> 24) & 0xff
    if flags or padr or size:
        print(f"      [{i:2}] flags={flags:#04x} paddr={padr<<12:#013x} size={size<<12:#x}")

print("\n>>> done. Compare this dump before vs after a Linux attach (p.reboot() between).")
print(">>> KEY QUESTION: does the allowed-DMA window cover the fw working region")
print(">>>   (0x11fd9ce4000 + 600MB), and is it still set after Linux attaches?")
