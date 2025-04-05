#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
import sys, pathlib
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))

from m1n1.setup import *
from m1n1.hw.dart import DART
from m1n1.hw.scaler import *
from m1n1.utils import *

import struct
import time

MAGIC_VALUE = 0x12345678

# Timer MMIO base for CPU (you'll need to check this for M4)
TIMER_BASE = 0x302580000  # Example: adjust to M4 timer base
TIMER_OFFSETS = {
    "cntcr": 0x000,
    "cntcv_lo": 0x008,
    "cntcv_hi": 0x00C,
    "cntfrq": 0x010,
    "cnthp_cval_lo": 0x028,
    "cnthp_cval_hi": 0x02C,
    "cnthp_ctl": 0x020,
    "cnthp_tval": 0x024,
}

# Prepare timer: fires in X microseconds
def setup_timer(microseconds):
	cntfrq = p.read32(TIMER_BASE + TIMER_OFFSETS["cntfrq"])
	current_count = p.read64(TIMER_BASE + TIMER_OFFSETS["cntcv_lo"])

	# Calculate target count
	target_count = current_count + int(cntfrq * (microseconds / 1_000_000.0))

	# Set compare value
	p.write32(TIMER_BASE + TIMER_OFFSETS["cnthp_cval_lo"], target_count & 0xFFFFFFFF)
	p.write32(TIMER_BASE + TIMER_OFFSETS["cnthp_cval_hi"], target_count >> 32)

	# Enable the timer (bit 0 = enable, bit 1 = interrupt enable)
	p.write32(TIMER_BASE + TIMER_OFFSETS["cnthp_ctl"], 0b11)

	print(f"[+] Timer set for {microseconds} us")

def main():
	# Set up timer to fire after 1ms
	setup_timer(microseconds=1000)

	lo = p.read32(TIMER_MMIO_BASE + 0x08)  # CNTCV_LO
	hi = p.read32(TIMER_MMIO_BASE + 0x0C)  # CNTCV_HI
	val = (hi << 32) | lo
	print(f"Current counter value: {val:#x}")

if __name__ == "__main__":
	main()
