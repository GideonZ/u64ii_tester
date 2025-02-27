from pyftdi.jtag import *
from pyftdi.ftdi import *
import time
import logging
import struct
import os
import math

# create logger
logger = logging.getLogger('JTAG')
logger.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
ch.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

PROG_BUFFER     = 0x1000000
TESTER_PARAM    = 0x0084
PROG_PROGRESS   = 0x0088
PROG_LENGTH     = 0x008C
PROG_LOCATION   = 0x0090
DUT_TO_TESTER   = 0x0094
TESTER_TO_DUT	= 0x0098
TEST_STATUS		= 0x009C

XILINX_USER1    = 0x02
XILINX_USER2    = 0x03
XILINX_USER3    = 0x22
XILINX_USER4    = 0x23
XILINX_IDCODE   = 0x09
XILINX_USERCODE = 0x08
XILINX_PROGRAM  = 0x0B
XILINX_START    = 0x0C
XILINX_SHUTDOWN = 0x0D
XILINX_EXTEST   = 0x26
XILINX_CFG_IN   = 0x05
XILINX_CFG_OUT  = 0x04
XILINX_FUSE_DNA = 0x32
XILINX_FUSE_DNA2 = 0x17

class JtagClientException(Exception):
    pass

class JtagClient:
    def __init__(self, url = 'ftdi://ftdi:232h/0'):
        self.url = url
        self.jtag = JtagEngine(trst=False, frequency=3e6)
        self.tool = JtagTool(self.jtag)
        self.jtag.configure(url)
        self.jtag.reset()
        self._reverse = None

    @staticmethod
    def add_log_handler(ch):
        global logger
        logger.addHandler(ch)

    def jtag_clocks(self, clocks):
        cmd = bytearray(3)
        cnt = (clocks // 8) - 1
        if cnt:
            cmd[0] = 0x8F
            cmd[1] = cnt & 0xFF
            cmd[2] = cnt >> 8
            self.jtag._ctrl._stack_cmd(cmd)
        cnt = clocks % 8
        if cnt:
            cmd[0] = 0x8E
            cmd[1] = cnt
            self.jtag._ctrl._stack_cmd(cmd[0:2])
        
    def xilinx_read_id(self):
        self.jtag.reset()
        idcode = self.jtag.read_dr(32)
        self.jtag.go_idle()
        logger.info(f"IDCODE (reset): {int(idcode):08x}")
        return int(idcode)

    def xilinx_read_dna(self):
        self.jtag.reset()
        self.jtag.go_idle()
        self.jtag.write_ir(BitSequence(XILINX_FUSE_DNA, False, 6))
        dna = self.jtag.read_dr(64)
        self.jtag.go_idle()
        logger.info(f"DNA CODE (0x32): {int(dna):16x}")
        return int(dna)

    def bitreverse(self, bytes):
        result = bytearray(len(bytes))
        if not self._reverse:
            self._reverse = bytearray(256)
            for i in range(256):
                byte = i
                reversed_byte = 0
                for b in range(8):
                    reversed_byte <<= 1  # Left shift to make room for the next bit
                    reversed_byte |= byte & 1  # Add the least significant bit of the original byte
                    byte >>= 1  # Right shift to process the next bit
                self._reverse[i] = reversed_byte
        for i in range(len(bytes)):
            result[i] = self._reverse[bytes[i]]
        return result

    def xilinx_load_fpga(self, filename):
	    # Reset
        logger.info("reset..")
        self.jtag.reset()

        self.jtag.write_ir(BitSequence(XILINX_PROGRAM, False, 6))
        self.jtag.reset()
        self.jtag.go_idle()
        self.jtag_clocks(10000)

        # Program
        logger.info("programming..");
        self.jtag.write_ir(BitSequence(XILINX_CFG_IN, False, 6))
        with open(filename, "rb") as f:
            self.jtag.change_state('shift_dr')
            while(True):
                buffer = f.read(16384)
                if len(buffer) <= 0:
                    break

                olen = len(buffer)-1
                cmd = bytearray((Ftdi.WRITE_BYTES_NVE_MSB, olen & 0xff,
                          (olen >> 8) & 0xff))
                cmd.extend(buffer)
                self.jtag._ctrl._stack_cmd(cmd)

        self.jtag.change_state('update_dr')
        self.jtag.go_idle()
        self.jtag.write_ir(BitSequence(XILINX_START, False, 6))
        self.jtag_clocks(32)

    def reverse_file(self, infile, outfile):
        with open(infile, "rb") as fi:
            with open(outfile, "wb") as fo:
                buffer = fi.read()
                fo.write(self.bitreverse(buffer))

    def set_user_ir(self, ir):
        self.jtag.write_ir(BitSequence(XILINX_USER4, False, 6))
        
        self.jtag.write_dr(BitSequence(ir << 1 | 1, False, 5))

        self.jtag.write_ir(BitSequence(XILINX_USER4, False, 6))
        self.jtag.change_state('shift_dr')
        # Writing the first zero selects the data registers (a '1' selects the IR register)
        self.jtag.shift_register(BitSequence(0, length = 1))
        #logger.info(ir, rb)

    def rw_user_data(self, data, update=False) -> BitSequence:
        data = self.jtag.shift_register(data)
        if update:
            self.jtag.go_idle()
        return data
    
    def read_user_data(self, bits) -> BitSequence:
        inp = BitSequence(0, length = bits)
        return self.jtag.shift_register(inp)

    def user_read_id(self):
        self.set_user_ir(0)
        user_id = int(self.read_user_data(32))
        self.jtag.go_idle()
        logger.info(f"UserID: {user_id:08x}")
        return user_id

    def user_get_inputs(self):
        self.set_user_ir(1)
        inputs = int(self.read_user_data(16))
        self.jtag.go_idle()
        logger.info(f"Inputs: {inputs:04x}")
        return inputs

    def user_set_outputs(self, value):
        self.set_user_ir(2)
        self.jtag.shift_and_update_register(BitSequence(value, False, 8))
        self.jtag.go_idle()

    def read_fifo(self, expected, cmd = 4, stopOnEmpty = False, readAll = False):
        available = 0
        readback = b''
        while expected > 0:
            self.set_user_ir(cmd)
            available = int(self.read_user_data(8))
            # logger.info(f"Number of bytes available in FIFO: {available}, need: {expected}")
            if readAll:
                available = expected # !!!!
            elif available > expected:
                available = expected
            if available == 0:
                if stopOnEmpty:
                    break
                else:
                    logger.info("No more bytes in fifo?!")
                    self.jtag.go_idle()
                    raise JtagClientException("No read data.")

            outbytes = bytearray(available)
            outbytes[-1] = 0xF0 # no read on last

            olen = len(outbytes)-1
            #jtagcmd = bytearray((Ftdi.RW_BYTES_PVE_NVE_LSB, olen & 0xff, (olen >> 8) & 0xff))
            jtagcmd = bytearray((0x3d, olen & 0xff, (olen >> 8) & 0xff))
            jtagcmd.extend(outbytes)
            self.jtag._ctrl._stack_cmd(jtagcmd)
            self.jtag._ctrl.sync()
            read_now = self.jtag._ctrl._ftdi.read_data_bytes(olen+1, 4)
            #print(len(read_now), read_now)

            #read_now = self.jtag.shift_register(BitSequence(bytes_ = outbytes)).tobytes(msby = True)
            expected -= len(read_now)
            readback += read_now

        self.jtag.go_idle()
        return readback

    def user_read_debug(self):
        self.set_user_ir(3)
        rb = self.jtag.shift_and_update_register(BitSequence(0, False, 32))
        logger.info(f"Debug register = {rb}")
        self.jtag.go_idle()
        return int(rb)
    
    def user_read_console(self, do_print = False):
        raw = self.read_fifo(expected = 1000, cmd = 10, stopOnEmpty = True)
        text = bytearray(len(raw))
        for i in range(len(text)):
            text[i] = raw[i] & 0x7F
        text = text.decode("utf-8")
        if do_print:
            lines = text.split("\n")
            for line in lines[:-1]:
                logger.info(line.strip())
        return text
    
    def user_read_console2(self, do_print = False):
        raw = self.read_fifo(expected = 1000, cmd = 11, stopOnEmpty = True)
        text = bytearray(len(raw))
        for i in range(len(text)):
            if raw[i] < 0x20 and raw[i] != 0x0a:
                text[i] = 0x3f
            text[i] = raw[i] & 0x7F
        text = text.decode("utf-8")
        if do_print:
            logger.info(text)
        return text
    
    def user_upload(self, name, addr):
        bytes_read = 0
        with open(name, "rb") as fi:
            logger.info(f"Uploading {name} to address {addr:08x}")
            while(True):
                buffer = fi.read(16384)
                if len(buffer) <= 0:
                    break
                bytes_read += len(buffer)
                self.user_write_memory(addr, buffer + b'\x00\x00\x00\x00\x00\x00\x00\x00')
                addr += 16384
            logger.info(f"Uploaded {bytes_read:06x} bytes.")

        if bytes_read == 0:
            logger.error(f"Reading file {name} failed -> Can't upload to board.")
            raise JtagClientException("Failed to upload applictation")

        return bytes_read

    def user_run_bare(self, name):
        """Uploads the application to the board, assuming that there is no bootloader present, and the CPU starts from address 0x0."""
        self.user_set_outputs(0x00) # Reset
        _size = self.user_upload(name, 0x0)
        self.user_set_outputs(0x80) # Unreset
        time.sleep(3)
        self.user_read_id()
        #with open(name+"rb", "wb") as fo:
        #    fo.write(self.user_read_memory(0x00, size))

    def user_run_app(self, addr, reset = True):
        """Uploads the application to the board and runs it, assuming that there is a bootloader present."""
        magic = struct.pack("<LL", addr, 0x1571babe)
        if reset:
            self.user_set_outputs(0x00) # Reset
        self.user_write_memory(0xFFFFF0, b'\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00') # Clear magic for flashing
        self.user_write_memory(0xFFF8, magic)
        print(f"{self.user_read_int32(0xFFF8):08x}")
        print(f"{self.user_read_int32(0xFFFC):08x}")
        if reset:
            self.user_set_outputs(0x80) # Unreset
    
    def user_write_memory(self, addr, buffer):
        addrbytes = struct.pack("<L", addr)
        command = bytearray([ addrbytes[0], 4, addrbytes[1], 5, addrbytes[2], 6, addrbytes[3], 7, 0x80, 0x01])
        self.set_user_ir(5)
        self.jtag.shift_and_update_register(BitSequence(bytes_ = command))
        self.set_user_ir(6)
        olen = len(buffer)-1
        cmd = bytearray((Ftdi.WRITE_BYTES_NVE_LSB, olen & 0xff,
                    (olen >> 8) & 0xff))
        cmd.extend(buffer)
        self.jtag._ctrl._stack_cmd(cmd)
        self.jtag.go_idle()
    
    def user_read_memory(self, addr, len):
        result = b''
        #logger.info(f"Reading {len} bytes from address {addr:08x}...")
        len //= 4
        #start_time = time.perf_counter()

        cmds = 0
        words = len
        while(len > 0):
            now = len if len < 256 else 256
            addrbytes = struct.pack("<L", addr)
            command = bytearray([ addrbytes[0], 4, addrbytes[1], 5, addrbytes[2], 6, addrbytes[3], 7, now - 1, 0x03])
            cmds += 1
            self.set_user_ir(5)
            self.jtag.shift_and_update_register(BitSequence(bytes_ = command))
            result += self.read_fifo(now * 4, readAll = True) # Assuming reading from memory is always faster than JTAG; we can just continue reading the fifo!
            len -= now
            addr += 4*now

        # print(f"Words per iteration: {words/cmds} ({cmds} iterations)")

        #end_time = time.perf_counter()
        #execution_time = end_time - start_time
        #logger.info(f"Execution time: {execution_time:.3f} seconds")

        return result

    def user_write_int32(self, addr, value):
        self.user_write_memory(addr, struct.pack("<L", value))
    
    def user_read_int32(self, addr):
        valbytes = self.user_read_memory(addr, 4)
        return struct.unpack("<L", valbytes)[0]

    def user_write_io(self, addr, bytes):
        addrbytes = struct.pack("<L", addr)
        command = struct.pack("<BBBBBB", addrbytes[0], 4, addrbytes[1], 5, addrbytes[2], 6)
        for b in bytes:
            command += struct.pack("BB", b, 0x0f)
        self.set_user_ir(5)
        self.jtag.shift_and_update_register(BitSequence(bytes_ = command))
        self.jtag.go_idle()

    def user_read_io(self, addr, len):
        addrbytes = struct.pack("<L", addr)
        command = struct.pack("<BBBBBB", addrbytes[0], 4, addrbytes[1], 5, addrbytes[2], 6)
        for i in range(len):
            command += b'\x00\x0d'
        self.set_user_ir(5)
        self.jtag.shift_and_update_register(BitSequence(bytes_ = command))
        return self.read_fifo(len)

    def download_flash_images(self, fpga, app, fat):
        size3 = self.user_upload(fat, 0x1800000)
        self.user_write_int32(0xFFFFF8, size3)
        size2 = self.user_upload(app, 0x1400000)
        self.user_write_int32(0xFFFFF4, size2)
        size1 = self.user_upload(fpga, 0x1000000)
        self.user_write_int32(0xFFFFF0, size1)
        self.user_read_id()

    def xilinx_prog_esp32(self, name, addr, total_pages):
        max_time = 5*120 # 2 minutes
        file_size = os.stat(name)
        logger.info(f"Size of file: {file_size.st_size} bytes")
        self.user_upload(name, PROG_BUFFER)
        self.user_write_int32(PROG_LENGTH, int(file_size.st_size))
        self.user_write_int32(PROG_LOCATION, addr)
        self.user_write_int32(TESTER_TO_DUT, 52)
        while self.user_read_int32(TESTER_TO_DUT) == 52 and max_time > 0:
            time.sleep(.1)
            if self.flash_callback:
                progress = 100 * self.user_read_int32(PROG_PROGRESS)
                self.flash_callback(progress/total_pages)
            max_time -= 1

        if self.user_read_int32(TESTER_TO_DUT) == 52:
            raise JtagClientException("Test did not complete in time.")

        text = self.user_read_console(True)
        result = self.user_read_int32(TEST_STATUS)
        return (result, text)

    def xilinx_prog_flash(self, name, addr):
        max_time = 5*120 # 2 minutes
        file_size = os.stat(name)
        logger.info(f"Size of file: {file_size.st_size} bytes")
        pages = (file_size.st_size + 255) // 256 #Callback for every page
        self.user_upload(name, PROG_BUFFER)
        self.user_write_int32(PROG_LENGTH, int(file_size.st_size))
        self.user_write_int32(PROG_LOCATION, addr)

        self.user_write_int32(TESTER_TO_DUT, 50)
        while self.user_read_int32(TESTER_TO_DUT) == 50 and max_time > 0:
            time.sleep(.1)
            if self.flash_callback:
                progress = 100 * self.user_read_int32(PROG_PROGRESS)
                self.flash_callback(progress/pages)
            max_time -= 1

        if self.user_read_int32(TESTER_TO_DUT) == 50:
            raise JtagClientException("Test did not complete in time.")

        text = self.user_read_console(True)
        result = self.user_read_int32(TEST_STATUS)
        return (result, text)

    def start_test(self, test_id):
        self.user_write_int32(TESTER_TO_DUT, test_id)

    def complete_test(self):
        if self.user_read_int32(TESTER_TO_DUT) != 0:
            raise JtagClientException("Test did not complete in time.")
        result = self.user_read_int32(TEST_STATUS)
        return result
    
    def perform_test(self, test_id, max_time = 10, log = False, param = None):
        if param != None:
            self.user_write_int32(TESTER_PARAM, param)
        self.user_write_int32(TESTER_TO_DUT, test_id)
        text = self.user_read_console(log)
        while self.user_read_int32(TESTER_TO_DUT) == test_id and max_time > 0:
            time.sleep(.2)
            text += self.user_read_console(log)
            max_time -= 1
        if self.user_read_int32(TESTER_TO_DUT) == test_id:
            raise JtagClientException("Test did not complete in time.")
        result = self.user_read_int32(TEST_STATUS)
        return (result, text)

    def reboot(self, test_id):
        self.user_write_int32(TESTER_TO_DUT, test_id)
        text = ""
        for i in range(15): # 3 seconds
            time.sleep(.2)
            text += self.user_read_console(True)
        return text

# pip3 install opencv-python-headless
