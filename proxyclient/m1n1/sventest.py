#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
import sys, pathlib
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from m1n1.setup import *
from m1n1.hw.dart import DART
from m1n1.hw.scaler import *
from m1n1.utils import *
from m1n1 import asm

def main():
    print("Reading CNTVCT_EL0...")
    start = u.mrs("CNTVCT_EL0")
    print(f"Start time: {start:#x}")

    delay = 1000000  # tune as needed
    target = start + delay
    print(f"Waiting until CNTVCT_EL0 reaches {target:#x}")

    while True:
        now = u.mrs("CNTVCT_EL0")
        if now >= target:
            break

    print("Reached target time, preparing WFI...")

    code = u.malloc(0x1000)

    magic = 0x1234
    result = asm.ARMAsm("""
        mov x1, {magic}
        wfi
        mov x0, x1
        ret
    """.format(magic=magic), code)

    result_value = int.from_bytes(result.data[:2], byteorder='big')
    
    print(f"x1 value after WFI: {result_value:#x}")

    if result_value == magic:
        print("Register state preserved across WFI!")
    else:
        print("Register state NOT preserved!")

if __name__ == "__main__":
    main()
