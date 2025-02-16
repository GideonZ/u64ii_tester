from jtag_xilinx import JtagClient
from jtag_xilinx import ch
from jtag_xilinx import logger
import time

logger.addHandler(ch)
j = JtagClient()
j.xilinx_read_id()
j.user_run_bare('/home/gideon/proj/ult64/ultimate/target/u64ii/riscv/test/result/u64ii_test.bin')
#j.user_run_bare('/home/gideon/proj/ult64/ultimate/target/u64ii/riscv/ultimate/result/ultimate.bin')
time.sleep(2)
data = j.user_read_console(do_print = True)
print(data)

