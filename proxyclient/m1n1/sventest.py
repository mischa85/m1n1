import logging
from m1n1.setup import *
from m1n1.utils import *
from m1n1 import asm

# Constants
CODE_BUFFER_SIZE = 0x1000
RESULT_BUFFER_SIZE = 0x100
MAGIC_VALUE = 0x1234

def main():
    code = u.malloc(CODE_BUFFER_SIZE)
    result_buf = u.malloc(RESULT_BUFFER_SIZE)

    result = asm.ARMAsm(f"""
        mov x1, {MAGIC_VALUE}     // set magic value
        wfi                       // wait for interrupt
        str x1, [x0]              // store x1 to result buffer at x0
        ret
    """, code, x0=result_buf)
    result_value = u.read64(result_buf)

    logging.info(f"x1 value after WFI (from memory): {result_value:#x}")

    if result_value == MAGIC_VALUE:
        logging.info("✅ Register state preserved across WFI!")
    else:
        logging.error("❌ Register state NOT preserved!")

if __name__ == "__main__":
    main()