#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# T6041 (M4 Max) MTP coprocessor test: drive the MTP RTKit coprocessor directly
# from the proxy (EL2, bare m1n1 -- no Linux, no HV). Confirms the coprocessor
# boots (RTKit HELLO/endpoints/power) and tries to bring up the keyboard.
# NOTE: needs a FRESH proxy boot each run -- the coprocessor won't re-HELLO once
# it has been booted (no reset without a machine reboot).
import sys, pathlib, time
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from m1n1.setup import *
from m1n1.fw.asc import StandardASC
from m1n1.hw.dart import DART
from m1n1.hw.dockchannel import DockChannel
from m1n1.fw.smc import SMCClient, SMCError
from m1n1.fw.mtp import *

print("\n>>> ===== MTP coprocessor test (T6041 / M4 Max) =====")

smc = None
try:
    smc_addr = u.adt["arm-io/smc"].get_reg(0)[0]
    smc = SMCClient(u, smc_addr); smc.start(); smc.start_ep(0x20); smc.verbose = 0
    print(">>> SMC started")
except Exception as e:
    print(f">>> SMC start failed: {e!r} (keyboard init needs it; boot test still valid)")

try:
    p.dapf_init("/arm-io/dart-mtp"); print(">>> dapf_init(dart-mtp) OK")
except Exception as e:
    print(f">>> dapf_init(dart-mtp): {e!r}")

dart = DART.from_adt(u, "/arm-io/dart-mtp", iova_range=(0x8000, 0x100000))
dart.dart.regs.TCR[1].set(BYPASS_DAPF=0, BYPASS_DART=0, TRANSLATE_ENABLE=1)

irq_base = u.adt["/arm-io/dockchannel-mtp"].get_reg(1)[0]
fifo_base = u.adt["/arm-io/dockchannel-mtp"].get_reg(2)[0]
dc = DockChannel(u, irq_base, fifo_base, 1)
node = u.adt["/arm-io/dockchannel-mtp/mtp-transport"]
while dc.rx_count:
    dc.read(dc.rx_count)

mtp_addr = u.adt["/arm-io/mtp"].get_reg(0)[0]
print(f">>> MTP ASC base = {mtp_addr:#x}; booting (60s wait)...")
mtp = StandardASC(u, mtp_addr, dart, stream=1)
mtp.verbose = 3
super(StandardASC, mtp).boot()
mtp.mgmt.wait_boot(60)
print("\n>>> !!!!! MTP coprocessor BOOTED -- ALIVE !!!!!\n")
mtp.allow_phys = True

if smc is not None:
    print(">>> bringing up keyboard over MTP...")
    mp = MTPProtocol(u, node, mtp, dc, smc)
    mp.wait_init("keyboard")
    print("\n>>> !!!!! KEYBOARD INITIALIZED OVER MTP -- the M4 Max internal keyboard is ALIVE from m1n1 !!!!!\n")
else:
    print(">>> skipping keyboard init (no SMC)")

print(">>> done (machine left in proxy mode)")
