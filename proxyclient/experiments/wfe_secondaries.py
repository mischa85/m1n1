#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
#
# WFE-retains-state experiment, SECONDARIES ONLY.
#
# Companion to wfi_secondaries.py, to test (sven's well-founded doubt) whether
# M4 loses register state on WFE like it does on WFI.
#
# IMPORTANT wake difference: WFI wakes on a pending interrupt even when masked
# (PSTATE.I=1), which is how wfi_secondaries.py wakes via the CNTP timer. WFE
# does NOT wake on a masked interrupt -- it wakes on an event. So here we enable
# the generic-timer EVENT STREAM (CNTKCTL_EL1.EVNTEN, longest period EVNTI=15)
# as the wake source, and loop `wfe` for ~10ms of wall-clock (comparable dwell
# to the 10ms WFI test) so the core actually enters the wait repeatedly. The
# canary in x0 is set once and never re-written; if any WFE in the loop lost
# register state, x0 != 1 on return.
#   persists x0 == 1  : state RETAINED through ~10ms of WFE  (WFE does NOT lose state)
#   persists x0 != 1  : state LOST                            (WFE also loses state)

import sys, pathlib
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from m1n1.setup import *
from m1n1 import asm

code = u.malloc(0x1000)
c = asm.ARMAsm("""
    // enable the timer event stream (the WFE wake source), longest period
    mrs x2, CNTKCTL_EL1
    orr x2, x2, #(15 << 4)   // EVNTI = 15 (event ~ every 2^16 vcounter ticks)
    orr x2, x2, #(1 << 2)    // EVNTEN
    msr CNTKCTL_EL1, x2
    isb

    // deadline = CNTVCT + x0 ticks (x0 = freq/100 = ~10ms)
    mrs x4, CNTVCT_EL0
    add x4, x4, x0

    mov x0, #1   // canary, never saved/rewritten

    str x30, [sp, #-16]!
    stp x28, x29, [sp, #-16]!
    stp x26, x27, [sp, #-16]!
    stp x24, x25, [sp, #-16]!
    stp x22, x23, [sp, #-16]!
    stp x20, x21, [sp, #-16]!
    stp x18, x19, [sp, #-16]!

1:
    isb
    wfe                      // waits for the next event-stream tick
    mrs x5, CNTVCT_EL0
    cmp x5, x4
    b.lo 1b                  // keep waiting until ~10ms elapsed

    ldp x18, x19, [sp], #16
    ldp x20, x21, [sp], #16
    ldp x22, x23, [sp], #16
    ldp x24, x25, [sp], #16
    ldp x26, x27, [sp], #16
    ldp x28, x29, [sp], #16
    ldr x30, [sp], #16

    ret
""", code)
iface.writemem(code, c.data)
p.dc_cvau(code, len(c.data))
p.ic_ivau(code, len(c.data))

print(f"chip_id=0x{u.adt['/chosen'].chip_id:x}  MIDR part=0x{(u.mrs(MIDR_EL1)>>4)&0xfff:x}")
p.smp_start_secondaries()
freq = u.mrs(CNTFRQ_EL0)

lost = retained = hung = 0
for cpu in u.adt["/cpus"]:
    if cpu.state == "running":
        print(f"cpu{cpu.cpu_id} (boot/proxy core): SKIPPED")
        continue
    if not p.smp_is_alive(cpu.cpu_id):
        print(f"cpu{cpu.cpu_id}: not alive, skipping")
        continue
    try:
        ret = p.smp_call_sync(cpu.cpu_id, code & ~REGION_RX_EL1, round(freq / 100))
    except Exception as e:
        print(f"cpu{cpu.cpu_id} cluster={cpu.cluster_type}: HUNG ({e}) -- WFE never woke?")
        hung += 1
        break  # proxy is desynced after a timeout; stop
    state = "RETAINED" if ret == 1 else f"LOST (x0=0x{ret:x})"
    if ret == 1: retained += 1
    else: lost += 1
    print(f"cpu{cpu.cpu_id} cluster={cpu.cluster_type}: persists x0={ret:#x} -> {state}")

print(f"\nSummary: retained={retained}  lost={lost}  hung={hung}")
print("RETAINED on all -> WFE does NOT lose state (sven right; WFE claim retracted).")
print("LOST -> WFE also loses state (reproduced in m1n1).  HUNG -> event-stream wake failed, inconclusive.")
