#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
#
# WFI-retains-state experiment, SECONDARIES ONLY.
#
# Based on yuka's experiments/wfi.py, but skips the boot/proxy core: on M4 the
# boot core also loses register state on WFI, so running WFI on it kills the
# proxy (UartTimeout) before any secondary is tested. Here we only test the
# started secondaries via smp_call_sync (region 0), so the proxy survives and
# we get a per-core result.
#
# Each core: enable CNTP timer, stash x18-x30, set x0=1 (canary, NOT saved),
# WFI (woken by the timer), restore. If WFI lost register state, x0 != 1.
#   -> persists x0 == 1  : state RETAINED through WFI
#   -> persists x0 != 1  : state LOST (deep sleep)  [expected on M4]

import sys, pathlib
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from m1n1.setup import *
from m1n1 import asm

code = u.malloc(0x1000)
c = asm.ARMAsm("""
    msr CNTP_TVAL_EL0, x0
    mov x1, #1
    msr CNTP_CTL_EL0, x1

    mov x0, #1  // canary, not saved across WFI

    str x30, [sp, #-16]!
    stp x28, x29, [sp, #-16]!
    stp x26, x27, [sp, #-16]!
    stp x24, x25, [sp, #-16]!
    stp x22, x23, [sp, #-16]!
    stp x20, x21, [sp, #-16]!
    stp x18, x19, [sp, #-16]!

    isb
    wfi

    ldp x18, x19, [sp], #16
    ldp x20, x21, [sp], #16
    ldp x22, x23, [sp], #16
    ldp x24, x25, [sp], #16
    ldp x26, x27, [sp], #16
    ldp x28, x29, [sp], #16
    ldr x30, [sp], #16

    mov x1, #3
    msr CNTP_CTL_EL0, x1
    ret
""", code)
iface.writemem(code, c.data)
p.dc_cvau(code, len(c.data))
p.ic_ivau(code, len(c.data))

print(f"chip_id=0x{u.adt['/chosen'].chip_id:x}  MIDR part=0x{(u.mrs(MIDR_EL1)>>4)&0xfff:x}")
p.smp_start_secondaries()
freq = u.mrs(CNTFRQ_EL0)

lost = retained = 0
for cpu in u.adt["/cpus"]:
    if cpu.state == "running":
        print(f"cpu{cpu.cpu_id} (boot/proxy core): SKIPPED (WFI here would kill the proxy)")
        continue
    if not p.smp_is_alive(cpu.cpu_id):
        print(f"cpu{cpu.cpu_id}: not alive, skipping")
        continue
    try:
        ret = p.smp_call_sync(cpu.cpu_id, code & ~REGION_RX_EL1, round(freq / 100))
    except Exception as e:
        print(f"cpu{cpu.cpu_id} cluster={cpu.cluster_type}: FAILED/HUNG ({e}) -> likely lost state")
        lost += 1
        continue
    state = "RETAINED" if ret == 1 else f"LOST (x0=0x{ret:x})"
    if ret == 1: retained += 1
    else: lost += 1
    print(f"cpu{cpu.cpu_id} cluster={cpu.cluster_type}: persists x0={ret:#x} -> {state}")

print(f"\nSummary: retained={retained}  lost={lost}")
print("(LOST on M4 secondaries confirms the WFI-deep-sleep-loses-state erratum.)")
