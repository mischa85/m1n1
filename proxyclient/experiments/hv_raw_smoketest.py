#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
#
# Stage-1 HV guest smoke test for T6041.
#
# Boots a 16-byte raw guest under the m1n1 hypervisor that does:
#       mov  x0, #1            ; hvcall id 1
#       movz x1, #0xc0de       ; magic, to prove our code ran
#       brk  #0x4242           ; -> handle_brk -> our add_hvcall(1) handler
#   loop: b loop               ; spin after the hypercall
#
# If the handler fires with x1 == 0xc0de and ELR == entry+8, the full
# start -> guest-exec -> trap -> observe cycle works on T6041. The guest is
# then left spinning (harmless); this script records the proof and is killed
# externally (reboot to reclaim the proxy, as with other invasive HV runs).

import sys, pathlib
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from m1n1.setup import *       # iface, p, u, hv
from m1n1.asm import ARMAsm

def log(m):
    print(m, flush=True)

MAGIC = 0xc0de
code = ARMAsm("""
    mov  x0, #1
    movz x1, #0xc0de
    brk  #0x4242
loop:
    b loop
""", 0)
image = code.data
log(f"guest payload: {len(image)} bytes: {image.hex()}")

def guest_hvcall(ctx):
    x0 = ctx.regs[0]
    x1 = ctx.regs[1]
    elr = ctx.elr
    expect_elr = hv.entry + 8          # brk is the 3rd insn (offset 8)
    ok = (x1 == MAGIC) and (elr == expect_elr)
    log("")
    log("*** GUEST HYPERCALL RECEIVED ***")
    log(f"  callid (x0) = {x0:#x}")
    log(f"  magic  (x1) = {x1:#x}   (expected {MAGIC:#x})")
    log(f"  ELR         = {elr:#x}  (expected entry+8 = {expect_elr:#x})")
    log("")
    log("=== VERDICT ===")
    if ok:
        log("PASS: guest started at our entry, executed our code, and trapped "
            "back into the HV via brk hypercall. Full start->exec->trap cycle "
            "works on T6041. (Guest now spinning; safe to kill + reboot.)")
    else:
        log("PARTIAL: hypercall fired but values unexpected — see above.")
    log("[*] proof recorded")
    return True                        # resume guest (it spins at 'loop')

log("[*] hv.init() ...")
hv.init()
hv.add_hvcall(1, guest_hvcall)
log("[*] hv.load_raw() ...")
hv.load_raw(image, entryoffset=0)
log(f"[*] guest entry = {hv.entry:#x}; starting guest (blocks; handler writes proof) ...")
hv.start()
log("[*] hv.start() returned")
