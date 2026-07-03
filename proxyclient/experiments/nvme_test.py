#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# T6041 NVMe validation from the m1n1 proxy: dump the ANS/SART ADT addresses
# (for the Linux DT) and boot the ANS + NVMe via m1n1's own driver. If this
# works, the hardware is good and the Linux job is just the DT.
import sys, pathlib
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
from m1n1.setup import *

def regs(path):
    try:
        n = u.adt[path]
    except Exception as e:
        return f"(no node: {e})"
    out = []
    for i in range(6):
        try:
            a, s = n.get_reg(i)
            out.append(f"[{i}] {a:#x} (size {s:#x})")
        except Exception:
            break
    return "; ".join(out)

print("\n>>> ===== T6041 NVMe / ANS / SART validation =====")
print(">>> /arm-io/ans       :", regs("/arm-io/ans"))
try: print(">>> ans interrupts    :", u.adt["/arm-io/ans"].interrupts)
except Exception as e: print(">>> ans interrupts    :", e)
print(">>> /arm-io/sart-ans  :", regs("/arm-io/sart-ans"))

print("\n>>> calling p.nvme_init() (boots the ANS coprocessor + NVMe)...")
try:
    r = p.nvme_init()
    print(f">>> p.nvme_init() returned: {r!r}")
    if r:
        print(">>> !!!!! NVMe/ANS came up on M4 Max from m1n1 -- hardware is GOOD !!!!!")
        # read LBA 0 of namespace 1 as proof
        try:
            buf = u.heap.memalign(0x4000, 0x1000)
            ok = p.nvme_read(1, 0, buf)
            data = iface.readmem(buf, 16)
            print(f">>> nvme_read(nsid=1,lba=0) -> {ok!r}; LBA0[:16] = {bytes(data).hex()}")
        except Exception as e:
            print(f">>> block read skipped: {e!r}")
    else:
        print(">>> nvme_init returned falsy -- ANS/NVMe did not come up")
except Exception as e:
    print(f">>> p.nvme_init() raised: {e!r}")
print(">>> done")
