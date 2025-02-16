
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
TEST_OFF = 16
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
        self.lot = 0
        self.wafer = 0
        self.x_pos = 0
        self.y_pos = 0
        self.extra = 0
        self.supply = 0
        self.current = 0
        self.refclk = 0
        self.osc = 0
        self.voltages = [ 'N/A', 'N/A', 'N/A', 'N/A', 'N/A', 'N/A', 'N/A' ]
        self.revision = 0
        self.time_since_battery = 0


    def _test_001_regulators(self):
        """Voltage Regulators"""
        v50 = self.tester.read_adc_channel('+5.0V', 5)
        v43 = self.tester.read_adc_channel('+4.3V', 5)
        v33 = self.tester.read_adc_channel('+3.3V', 5)
        v25 = self.tester.read_adc_channel('+2.5V', 5)
        v18 = self.tester.read_adc_channel('+1.8V', 5)
        v11 = self.tester.read_adc_channel('+1.1V', 5)
        v09 = self.tester.read_adc_channel('+0.9V', 5)

        ok = True
        if not (0.855 <= v09 <= 0.945) and not self.proto:
            logger.error("v09 out of range")
            ok = False
        if not (1.04 <= v11 <= 1.16):
            logger.error("v11 out of range")
            ok = False
        if not (1.71 <= v18 <= 1.89):
            logger.error("v18 out of range")
            ok = False
        if not (2.375 <= v25 <= 2.625):
            logger.error("v25 out of range")
            ok = False
        if not (3.135 <= v33 <= 3.465) and not self.proto:
            logger.error("v33 out of range")
            ok = False
        if not (4.085 <= v43 <= 4.515):
            logger.error("v43 out of range")
            ok = False
        if not (4.5 <= v50 <= self.supply) and not self.proto:
            logger.error("v50 out of range")
            ok = False

        if self.proto:
            self.voltages = [ 'N/A', f'{v43:.2f} V', 'N/A', f'{v25:.2f} V', f'{v18:.2f} V', f'{v11:.2f} V', 'N/A' ]
        else:
            self.voltages = [ f'{v50:.2f} V', f'{v43:.2f} V', f'{v33:.2f} V', f'{v25:.2f} V', f'{v18:.2f} V', f'{v11:.2f} V', f'{v09:.2f} V' ]

        if not ok:
            self.tester.report_adcs()
            raise TestFailCritical('One or more regulator voltages out of range')

    def test_019_unique_id(self):
        """Unique ID"""
        if self.dut.xilinx_read_id() != 0x0362C093:
            raise TestFailCritical("FPGA on DUT not recognized")
        self.unique = self.dut.xilinx_read_dna()

    def test_003_test_fpga(self):
        """FPGA Detection & Load"""
        id = self.dut.xilinx_read_id()
        if id != 0x0362C093:
            logger.error(f"IDCODE does not match: {id:08x}")
            raise TestFailCritical("FPGA on DUT not recognized")
        
        self.dut.xilinx_load_fpga(dut_fpga)

        if self.dut.user_read_id() != 0xdead1541:
            raise TestFailCritical("DUT: User JTAG not working. (bad ID)")

        self.dut.user_set_outputs(0x80) # Unreset

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

    def test_020_board_revision(self):
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

    def test_005_start_app(self):
        """Run Application on DUT"""
        self.dut.user_upload(dut_appl, 0x30000)
        self.dut.user_run_app(0x30000)
        time.sleep(0.5)
        text = self.dut.user_read_console()
        logger.info(f"Console Output:\n{text}")
        if "DUT Main" not in text:
            raise TestFailCritical('Running test application failed')

    def _test_007_ethernet(self):
        """Ethernet"""
        (result, console) = self.dut.perform_test(TEST_SEND_ETH)
        logger.debug(f"Console Output:\n{console}")
        if result != 0:
            raise TestFail(f"Couldn't send Ethernet Packet. Err = {result}")
        (result, console) = self.dut.perform_test(TEST_RECV_ETH)
        logger.debug(f"Console Output:\n{console}")
        if result != 0:
            raise TestFail(f"Didn't receive Ethernet Packet. Err = {result}")

    def test_008_all(self):
        """Run All Tests"""
        (result, console) = self.dut.perform_test(TEST_ALL, 30)
        logger.debug(f"Console Output:\n{console}")
        if result != 0:
            raise TestFail(f"Err = {result}")

    def _test_009_usb_hub(self):
        """USB HUB Detection"""
        (result, console) = self.dut.perform_test(TEST_USB_INIT)
        logger.debug(f"Console Output:\n{console}")
        (result, console) = self.dut.perform_test(TEST_USB_HUB)
        logger.debug(f"Console Output:\n{console}")
        if result != 0:
            raise TestFail(f"Couldn't find USB HUB (USB2513) Err = {result}")

    def _test_010_usb_sticks(self):
        """USB Sticks Detection"""
        time.sleep(4)
        (result, console) = self.dut.perform_test(TEST_USB_PORTS)
        logger.debug(f"Console Output:\n{console}")
        if result != 0:
            raise TestFail(f"Couldn't find (all) USB sticks Err = {result}")
        (_result, console) = self.dut.perform_test(TEST_USB_SHOW)
        logger.debug(f"Console Output:\n{console}")

    def _test_012_audio(self):
        """Audio Test"""
        pass

    def test_021_iec(self):
        """IEC (Serial DIN)"""
        (result, console) = self.dut.perform_test(TEST_IEC)
        logger.debug(f"Console Output:\n{console}")
        if result != 0:
            raise TestFail(f"IEC Serial Fault. Err = {result}")

    def test_024_cassette_pins(self):
        """Cassette Pins"""
        (result, console) = self.dut.perform_test(TEST_CASSETTE)
        logger.debug(f"Console Output:\n{console}")
        if result != 0:
            raise TestFail(f"Cassette I/O fault. Err = {result}")

    def test_016_speaker(self):
        """Speaker Amplifier"""
        pass

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
        pass
    
    def dut_off(self):
        logger.info("Turning off DUT, if possible")
        (result, console) = self.dut.perform_test(TEST_OFF)
        logger.debug(f"Console Output:\n{console}")

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
