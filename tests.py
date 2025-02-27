
from jtag_xilinx import JtagClientException, JtagClient
import time
import struct
import numpy as np
import logging
from tkinter import ttk, messagebox

class TestFail(Exception):
    pass

class TestFailCritical(TestFail):
    pass

# create logger
logger = logging.getLogger('Tests')
logger.setLevel(logging.DEBUG)

dut_fpga  = '/home/gideon/proj/ult64/target/u64ii_loader/u64ii_loader.runs/impl_1/u64_mk2_loader.bit'
dut_appl  = '/home/gideon/proj/ult64/ultimate/target/u64ii/riscv/factorytest/result/factorytest.bin'
final_fpga = '/home/gideon/proj/ult64/target/u64_artix/u64_artix.runs/impl_1/u64_mk2_artix.bit'
final_appl = '/home/gideon/proj/ult64/ultimate/target/u64ii/riscv/ultimate/result/ultimate.app'
final_fat = 'binaries/fat.bin'
esp32_bootloader      = '/home/gideon/proj/ult64/ultimate/software/u64ctrl/build/bootloader/bootloader.bin'
esp32_partition_table = '/home/gideon/proj/ult64/ultimate/software/u64ctrl/build/partition_table/partition-table.bin'
esp32_application     = '/home/gideon/proj/ult64/ultimate/software/u64ctrl/build/u64ctrl.bin'

TEST_KEYBOARD = 1
TEST_IEC = 2
TEST_USERPORT = 3
TEST_CARTRIDGE = 4
TEST_CASSETTE = 5
TEST_JOYSTICK = 6
TEST_PADDLE = 7
TEST_SID_SOCKETS = 8
TEST_AUDIO_CODEC_SILENCE = 9
TEST_AUDIO_CODEC_PURITY = 10
TEST_SPEAKER = 11
TEST_WIFI_COMM = 12
TEST_VOLTAGES = 13
TEST_USB_HUB = 14
TEST_USB_INIT = 15
TEST_ETHERNET = 16
TEST_OFF = 17
TEST_REBOOT = 18
TEST_WIFI_DOWNLOAD = 51
TEST_WIFI_FLASH = 52

TEST_ALL = 101


class Ultimate64IITests:
    def __init__(self):
        pass

    def startup(self):
        self.dut = JtagClient()    
        self.reset_variables()

    def reset_variables(self):
        self.proto = False
        self.flashid = 0
        self.unique = 0
        self.voltages = [ 'N/A', 'N/A', 'N/A', 'N/A', 'N/A', 'N/A', 'N/A', 'N/A' ]
        self.revision = 0
        self.off = False
    
    def read_voltages(self):
        rb = self.dut.user_read_memory(0x00A0, 16)
        (vbus, vaux, v50, v33, v18, v10, vusb) = struct.unpack("<HHHHHHH", rb[0:14])
        self.voltages = [ f'{vbus/1000.0:.2f} V', f'{vaux/1000.0:.2f} V', f'{v50/1000.0:.2f} V', f'{v33/1000.0:.2f} V',
                          f'{v18/1000.0:.2f} V', f'{v10/1000.0:.2f} V', f'{vusb/1000.0:.2f} V' ]

    def test_001_unique_id(self):
        """Unique ID"""
        if self.dut.xilinx_read_id() != 0x0362C093:
            raise TestFailCritical("FPGA on DUT not recognized")
        self.unique = self.dut.xilinx_read_dna()

    def test_002_test_fpga(self):
        """FPGA Detection & Load"""
        id = self.dut.xilinx_read_id()
        if id != 0x0362C093:
            logger.error(f"IDCODE does not match: {id:08x}")
            raise TestFailCritical("FPGA on DUT not recognized")
        
        self.dut.xilinx_load_fpga(dut_fpga)

        if self.dut.user_read_id() != 0xdead1541:
            raise TestFailCritical("DUT: User JTAG not working. (bad ID)")

        self.dut.user_set_outputs(0x80) # Unreset

    def test_003_board_revision(self):
        """Board Revision"""
        self.revision = int(self.dut.user_read_io(0x10000c, 1)[0]) >> 3
        self.dut.user_write_io(0x60208, b'\x03')
        self.dut.user_write_io(0x60200, b'\xFF')
        self.dut.user_write_io(0x60208, b'\x01')
        self.dut.user_write_io(0x60200, b'\x4B')
        self.dut.user_write_io(0x60200, b'\x00\x00\x00\x00')
        idbytes = self.dut.user_read_io(0x60200, 4)
        idbytes += self.dut.user_read_io(0x60200, 4)
        self.dut.user_write_io(0x60208, b'\x03')
        logger.info(f"FlashID = {idbytes.hex()}")
        self.flashid = struct.unpack(">Q", idbytes)[0]

    def test_004_ddr2_memory(self):
        """DDR2 Memory Test"""
        # bootloader should have run by now
        time.sleep(0.5)
        text = self.dut.user_read_console(True)
        if "RAM OK!!" not in text:
            raise TestFailCritical("Memory calibration failed.")

        random = {} # Map of random byte blocks
        for i in range(6,26):
            random[i] = np.random.bytes(64)

        for i in range(6,26):
            addr = 1 << i
            logger.debug(f"Writing Addr: {addr:x}")
            self.dut.user_write_memory(addr, random[i])

        for i in range(6,26):
            addr = 1 << i
            logger.debug(f"Reading Addr: {addr:x}")
            rb = self.dut.user_read_memory(addr, 64)
            if rb != random[i]:
                logger.debug(random[i].hex())
                logger.debug(rb.hex())
                raise TestFailCritical('Verify error on DDR2 memory')

    def test_005_start_app(self):
        """Run Application on DUT"""
        self.dut.user_upload(dut_appl, 0x30000)
        self.dut.user_run_app(0x30000)
        time.sleep(0.5)
        text = self.dut.user_read_console(True)
        #logger.info(f"Console Output:\n{text}")
        if "DUT Main" not in text:
            raise TestFailCritical('Running test application failed')

    def test_006_program_esp32(self):
        """Program ESP32"""
        (result, _) = self.dut.perform_test(TEST_WIFI_DOWNLOAD)
        if result != 0:
            raise TestFail(f"Err = {result}")
        self.dut.flash_callback = self.esp_callback
        self.dut.xilinx_prog_esp32(esp32_bootloader, 0x00000, 842)
        self.dut.xilinx_prog_esp32(esp32_partition_table, 0x08000, 842)
        self.dut.xilinx_prog_esp32(esp32_application, 0x10000, 842)

    def test_007_all(self):
        """Run All Tests"""
        (result, _) = self.dut.perform_test(TEST_ALL, 50, True, 0xFFFB)
        if result != 0:
            raise TestFail(f"Err = {result}")

    def test_008_get_voltages(self):
        """Get Voltages"""
        self.read_voltages()
        logger.info(f"Voltages: {self.voltages}")

    def _test_008_ethernet(self):
        """Ethernet"""
        (result, console) = self.dut.perform_test(TEST_ETHERNET)
        logger.debug(f"Console Output:\n{console}")
        if result != 0:
            raise TestFail(f"Ethernet Test failed Err = {result}")

    def _test_009_usb_hub(self):
        """USB HUB Detection"""
        (result, console) = self.dut.perform_test(TEST_USB_INIT)
        logger.debug(f"Console Output:\n{console}")
        (result, console) = self.dut.perform_test(TEST_USB_HUB)
        logger.debug(f"Console Output:\n{console}")
        if result != 0:
            raise TestFail(f"Couldn't find USB HUB (USB2513) Err = {result}")

    def _test_021_iec(self):
        """IEC (Serial DIN)"""
        (result, console) = self.dut.perform_test(TEST_IEC)
        logger.debug(f"Console Output:\n{console}")
        if result != 0:
            raise TestFail(f"IEC Serial Fault. Err = {result}")

    def _test_024_cassette_pins(self):
        """Cassette Pins"""
        (result, console) = self.dut.perform_test(TEST_CASSETTE)
        logger.debug(f"Console Output:\n{console}")
        if result != 0:
            raise TestFail(f"Cassette I/O fault. Err = {result}")

    def program_flash(self, cb = [None, None, None]):
        """Program Flash!"""
        # Program the flash in three steps: 1) FPGA, 2) Application, 3) FAT Filesystem
        # Depricated, but let's do it like this now
        #self.dut.download_flash_images(final_fpga, final_appl, final_fat)
        self.dut.flash_callback = cb[0]
        self.dut.xilinx_prog_flash(final_fpga, 0x000000)
        self.dut.flash_callback = cb[1]
        self.dut.xilinx_prog_flash(final_appl, 0x220000)
        self.dut.flash_callback = cb[2]
        self.dut.xilinx_prog_flash(final_fat, 0x400000)

    def late_099_boot(self):
        """Boot Test"""
        logger.info("Rebooting DUT")
        console = self.dut.reboot(TEST_REBOOT)
        logger.debug(f"Console Output:\n{console}")
        return True

    def dut_off(self):
        if not self.dut_off:
            logger.info("Turning off DUT, if possible")
            (result, _) = self.dut.perform_test(TEST_OFF, 10, True)
            if result != 0:
                raise TestFail(f"Couldn't turn off DUT. Err = {result}")
            self.dut_off = True

    def run_all(self):
        self.startup()
        all = self.get_all_tests()

        for test in all:
            try:
                test()
            except TestFail as e:
                logger.error(f"Test failed: {e}")
            except JtagClientException as e:
                logger.critical(f"JTAG Communication error: {e}")
                return

    def get_all_tests(self):
        di = self.__class__.__dict__
        funcs = {}
        for k in di.keys():
            if k.startswith("test"):
                funcs[k] = di[k]
            if k.startswith("late"):
                funcs[k] = di[k]
        return funcs

    @staticmethod
    def add_log_handler(ch):
        global logger
        logger.addHandler(ch)


if __name__ == '__main__':
    tests = Ultimate64IITests()
    tests.startup()
    tests.run_all()
