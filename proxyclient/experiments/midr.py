#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
#
# Print MIDR_EL1 for every CPU, decoding the Apple part ID per cluster.
#
# The proxy runs on one core (read directly). Secondaries are started and read
# via smp_call_sync; since secondaries run with the MMU off, the code buffer
# must be reached at its physical address (region 0), not REGION_RX_EL1.

import sys, pathlib
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from m1n1.setup import *

# Part IDs in MIDR_EL1[15:4] -> name (see src/midr.h, src/chickens.c)
PART_NAMES = {
    0x44: "T6030 Sawtooth (E)",  0x45: "T6030 Everest (P)",
    0x48: "T6031 Sawtooth (E)",  0x49: "T6031 Everest (P)",
    0x52: "T8132 Donan (E)",     0x53: "T8132 Donan (P)",
    0x54: "T6040 Brava Chop (E)",0x55: "T6040 Brava Chop (P)",
    0x58: "T6041 Brava (E)",     0x59: "T6041 Brava (P)",
    0x60: "T8140 Tahiti (E)",    0x61: "T8140 Tahiti (P)",
}

def decode(midr):
    return (midr >> 4) & 0xfff

p.smp_start_secondaries()

results = {}
for node in u.adt["cpus"]:
    cid = node.cpu_id
    ctype = node.cluster_type
    if p.smp_is_alive(cid):
        # region 0: secondaries run MMU-off, so execute the code buffer at its
        # physical address rather than the default REGION_RX_EL1 virtual one.
        call = (lambda addr, *a, _c=cid: p.smp_call_sync(_c, addr, *a), 0)
        try:
            midr = u.mrs(MIDR_EL1, call=call, silent=True)
            mpidr = u.mrs(MPIDR_EL1, call=call, silent=True)
        except Exception as e:
            print(f"cpu {cid:2d} cluster={ctype}: FAILED ({e})")
            continue
    else:
        # Not started as a secondary: this is the core the proxy itself runs on.
        midr, mpidr = u.mrs(MIDR_EL1), u.mrs(MPIDR_EL1)

    part = decode(midr)
    name = PART_NAMES.get(part, "*** UNKNOWN ***")
    results.setdefault((ctype, part), []).append(cid)
    print(f"cpu {cid:2d} cluster={ctype} MPIDR={mpidr:#011x} MIDR={midr:#011x} "
          f"part={part:#04x} -> {name}")

print("\n=== Summary by (cluster, part) ===")
for (ctype, part), ids in sorted(results.items()):
    print(f"cluster {ctype}: part {part:#04x}  {PART_NAMES.get(part, '*** UNKNOWN ***')}  cpus={ids}")
