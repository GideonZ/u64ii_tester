#!/usr/bin/python3

import tkinter as tk
import logging
import git
import time
#import cv2
from tkinter import ttk, messagebox
import tkinter.scrolledtext as tkscrolled
from PIL import ImageTk, Image
from pprint import pprint
from tests import Ultimate64IITests, TestFail, TestFailCritical, JtagClientException
from datetime import datetime
from db import Database
from decimal import *
from pyftdi.usbtools import UsbToolsError
from jtag_xilinx import JtagClient

# sudo apt install python3-pil python3-pil.imagetk

class TextboxLogHandler(logging.StreamHandler):
    def __init__(self, widget):
        logging.StreamHandler.__init__(self)
        self.widget = widget

    def emit(self, record):
        # Record has: name, msg, args, levelname, levelno, pathname, filename, module,
        # exc_info, exc_text,stack_info, lineno, funcName, created, msecs, relativeCreated,
        # thread, threadName, processName, process, message, asctime
        if self.formatter:
            text = self.formatter.format(record)
        else:
            text = record.message
        self.widget.insert(tk.END, text + '\n')
        self.widget.see(tk.END)
        self.widget.update()

class InfoField:
    def __init__(self, parent, name, col, row, label_width, info_width):
        self.frame = tk.Frame(parent)
        self.label = tk.Label(self.frame, text = name, padx = 10, pady = 2, width = label_width)
        self.label.grid(column = 0, row = 0, sticky=tk.W)
        self.entry = tk.Label(self.frame, borderwidth=2, relief="groove", width = info_width, anchor = 'w')
        self.entry.grid(column = 1, row = 0, pady = 2)
        self.frame.grid(column = col, row = row)
        self._info = ""

    @property
    def info(self):
        return self._info

    @info.setter
    def info(self, data):
        self._info = data
        self.entry.configure(text = data)
        self.frame.update()

class InfoFields:
    def __init__(self, parent, fields, col, row, label_width, info_width):
        #self.field_names = fields
        self.fields = { }
        self.frame = tk.Frame(parent, borderwidth=2, relief="ridge")
        for idx, field in enumerate(fields):
            self.fields[field] = InfoField(self.frame, field, 0, idx, label_width, info_width)
        self.frame.grid(column = col, row = row, padx = 8, pady = 8)

    def set(self, name, value):
        self.fields[name].info = value

    def clear(self):
        for stat in self.fields:
            self.fields[stat].info = ""

class MyGui:
    def __init__(self):
        self.CollectTests()
        self.db = Database()
        repo = git.Repo(search_parent_directories=True)
        self.gitsha = repo.head.object.hexsha

    def CollectTests(self):
        self.testsuite = Ultimate64IITests()
        self.after = { }
        functions = self.testsuite.get_all_tests()
        self.functions = { }
        for (name, func) in functions.items():
            if func.__doc__:
                self.functions[name] = (func, func.__doc__)
            else:
                self.functions[name] = (func, name[9:])

        self.after['test_008_get_voltages'] = self.UpdateVoltages
        self.after['test_001_unique_id'] = self.UpdateUniqueId
        self.after['test_003_board_revision'] = self.UpdateBoardRevision
        self.testsuite.esp_callback = self.FlashUpdateESP32

    def FlashUpdateESP32(self, val):
        self.progress[0]['value'] = val
        self.progress[0].update()

    def FlashUpdateFPGA(self, val):
        self.progress[1]['value'] = val
        self.progress[1].update()

    def FlashUpdateAppl(self, val):
        self.progress[2]['value'] = val
        self.progress[2].update()

    def FlashUpdateFAT(self, val):
        self.progress[3]['value'] = val
        self.progress[3].update()

    def StartButtonClick(self, param):
        self.window.after(10, self.ExecuteTests)

    def RunOneTest(self, name):
        (func, doc) = self.functions[name]
        self.textbox.insert(tk.END, f"Running test '{doc}'\n{'-' * (14 + len(doc))}\n")
        self.textbox.see(tk.END)
        self.window.update()
        critical = False
        try:
            func(self.testsuite)
            self.test_icon_canvases[name].itemconfig(self.test_icon_images[name], image = self.img_pass)
            self.textbox.insert(tk.END, "-> Result: OK!\n\n")
        except TestFailCritical as e:
            self.test_icon_canvases[name].itemconfig(self.test_icon_images[name], image = self.img_fail)
            self.textbox.insert(tk.END, "-> Result: CRITICAL FAILURE!\n")
            self.textbox.insert(tk.END, f"Reason: {e}\n\n")
            critical = True
            self.errors += 1
            self.critical = True
        except TestFail as e:
            self.test_icon_canvases[name].itemconfig(self.test_icon_images[name], image = self.img_fail)
            self.textbox.insert(tk.END, "-> Result: FAIL!\n")
            self.textbox.insert(tk.END, f"Reason: {e}\n\n")
            self.failed_tests.append(name[5:8]) # Add number to list
            self.errors += 1
        except JtagClientException as e:
            messagebox.showerror("Failure!", f"Communication Error!\n{e}\nRestart Tester Application!")
            exit()
        except Exception as e:
            self.textbox.insert(tk.END, "-> Result: ERROR!\n")
            self.textbox.insert(tk.END, f"Reason: {e}\n\n")
            self.critical = True
            self.errors += 1

        if name in self.after:
            try:
                self.after[name]()
            except TestFailCritical as e:
                self.test_icon_canvases[name].itemconfig(self.test_icon_images[name], image = self.img_fail)
                self.textbox.insert(tk.END, "-> Result: CRITICAL FAILURE!\n")
                self.textbox.insert(tk.END, f"Reason: {e}\n\n")
                critical = True
                self.errors += 1
                self.critical = True

        self.textbox.see(tk.END)
        self.window.update()
        return critical

    def ExecuteTests(self):
        self.start_time = time.time()
        self.start_button.configure(state = 'disabled')
        self.progress[0]['value'] = 0
        self.progress[1]['value'] = 0
        self.progress[2]['value'] = 0
        self.progress[3]['value'] = 0
        self.textbox.delete(1.0, tk.END)
        self.window.update()

        self.serial = self.serial_entry.get()
        if len(self.serial) == 0:
            messagebox.showerror("Serial #", "No serial number given!")
            self.start_button.configure(state = 'normal')
            return

        if not hasattr(self.testsuite, 'dut'):
            try:
                self.testsuite.startup()
            except UsbToolsError as e:
                messagebox.showerror("Failure!", f"Could not find JTAG cable.\n{e}")
                self.start_button.configure(state = 'normal')
                return
            except JtagClientException as e:
                messagebox.showerror("Failure!", f"Could not communicate with board.\n{e}\nCheck if it is powered.\nCheck the USB connection.")
                self.start_button.configure(state = 'normal')
                return

        self.errors = 0
        self.flashed = "No"
        self.boot_ok = False
        self.critical = False
        self.failed_tests = [ ]
        self.testsuite.reset_variables()
        self.testsuite.serial = self.serial

        for name, _ in self.functions.items():
            self.test_icon_canvases[name].itemconfig(self.test_icon_images[name], image = self.img_err)

        self.stats.clear()
        self.stats.set('Serial #', self.serial)
        self.serial_entry.delete(0, tk.END)
        self.window.update()

        for name in self.functions:
            if "test" in name:
                if True: #not self.test_skip[name].get():
                    if self.RunOneTest(name): # Returns 'true' when a critical error occurred (could also have re-raised)
                        break

        #try:
        #    _res,frame = self.capture.read()
        #    cv2.imwrite(f"images/{self.serial}.png", frame)
        #except Exception as e:
        #    self.textbox.insert(tk.END, str(e))

        # If all tests are successful, the board can be flashed
        if self.errors == 0: ## zero!
            self.testsuite.program_flash([self.FlashUpdateFPGA, self.FlashUpdateAppl, self.FlashUpdateFAT])
            self.flashed = "Yes"

            self.boot_ok = self.testsuite.late_099_boot()
            self.testsuite.dut_off()            
            if not self.boot_ok:
                self.test_icon_canvases[name].itemconfig(self.test_icon_images[name], image = self.img_fail)
                self.textbox.insert(tk.END, "\n!!! BOARD DOESN'T BOOT !!!\n\n")
                messagebox.showerror("Reject", "Board doesn't boot correctly after Flashing.")
            else:
                self.test_icon_canvases[name].itemconfig(self.test_icon_images[name], image = self.img_pass)
                self.textbox.insert(tk.END, "\n*** BOARD SUCCESSFULLY TESTED AND PROGRAMMED! ***\n\n")
        else:
            self.testsuite.dut_off()            
            messagebox.showerror("Reject", "Board has not been programmed due to errors.")

        self.testsuite.dut_off()            
        self.end_time = time.time()
        self.textbox.insert(tk.END, f"\nElapsed time: {self.end_time - self.start_time:.1f} sec.\n")
        self.textbox.see(tk.END)
        self.window.update()

        try:
            self.write_test_to_db()
        except Exception as e:
            messagebox.showerror("Database Error", str(e))
            
        self.start_button.configure(state = 'normal')

    def setup(self):
        self.window=tk.Tk()
        self.window.title('Ultimate-64-II Factory Tester')
        self.img_logo = ImageTk.PhotoImage(Image.open("logo.jpg"))
        self.img_pass = ImageTk.PhotoImage(Image.open("pass.png"))
        self.img_fail = ImageTk.PhotoImage(Image.open("fail.png"))
        self.img_err  = ImageTk.PhotoImage(Image.open("err.png"))
        self.window.wm_iconphoto(False, self.img_pass)

        self.window.columnconfigure(0, weight = 2)
        self.window.columnconfigure(1, weight = 1)
        self.window.columnconfigure(2, weight = 1)
        self.window.columnconfigure(3, weight = 1)
        self.logo_canvas = tk.Canvas(self.window, width = self.img_logo.width(), height = self.img_logo.height())
        self.logo_canvas.create_image(self.img_logo.width() // 2, self.img_logo.height() // 2, image = self.img_logo)
        self.logo_canvas.grid(column = 0, row = 0, columnspan=4)

        self.test_frames = [ tk.Frame(self.window, padx = 5, pady = 5), tk.Frame(self.window, padx = 5, pady = 5) ]
        num_tests = len(self.functions)
        per_frame = (num_tests + 1) // 2
        self.test_icon_canvases = { }
        self.test_icon_images = { }
        self.test_skip = { }
        for idx, name in enumerate(self.functions):
            (_func, doc) = self.functions[name]
            test_frame = self.test_frames[idx // per_frame]
            #tk.Label(test_frame, text = doc, font=("Liberation Serif", 15)).grid(column = 0, row = len(self.test_icon_canvases), sticky=tk.W)
            canvas = tk.Canvas(test_frame, width = 48, height = 48)
            canvas.grid(column = 1, row = len(self.test_icon_canvases))
            #self.test_skip[name] = tk.IntVar()
            #tk.Checkbutton(test_frame, text = doc, var = self.test_skip[name], font=("Liberation Serif", 15)).grid(
            #    column = 0, row = len(self.test_icon_canvases), sticky=tk.W)
            tk.Label(test_frame, text = doc, font=("Liberation Serif", 15)).grid(
                column = 0, row = len(self.test_icon_canvases), sticky=tk.W)
            self.test_icon_canvases[name] = canvas
            self.test_icon_images[name] = canvas.create_image(24, 24)

        self.test_frames[0].grid(column = 2, row = 1)
        self.test_frames[1].grid(column = 3, row = 1)

        #pprint(self.test_skip)
        self.serial_frame = tk.Frame(self.window)
        tk.Label(self.serial_frame, text = "Serial #:").grid(column = 0, row = 0)
        self.serial_entry = tk.Entry(self.serial_frame)
        self.serial_entry.grid(column = 1, row = 0)
        self.serial_frame.grid(column = 1, row = 3)

        self.start_button = tk.Button(self.window, text="Start!", font=("Liberation Serif", 16))
        self.start_button.grid(columnspan = 2, column = 2, row = 3, sticky = tk.EW, padx = 15, pady = 15)
        self.start_button.bind('<Button-1>', self.StartButtonClick)
        self.serial_entry.bind('<Return>', self.StartButtonClick)

        self.textbox = tkscrolled.ScrolledText(self.window, width = 80, height = 20, wrap='word')
        self.textbox.grid(column = 0, row = 1, padx = 8, pady = 8, sticky="nsew", rowspan = 4)

        self.progress_frame = tk.Frame(self.window)
        self.progress = []
        self.progress.append(ttk.Progressbar(self.progress_frame, orient = 'horizontal', mode = 'determinate', length = 500))
        self.progress.append(ttk.Progressbar(self.progress_frame, orient = 'horizontal', mode = 'determinate', length = 500))
        self.progress.append(ttk.Progressbar(self.progress_frame, orient = 'horizontal', mode = 'determinate', length = 500))
        self.progress.append(ttk.Progressbar(self.progress_frame, orient = 'horizontal', mode = 'determinate', length = 500))
        self.progress[0].grid(column = 1, row = 0, pady = 4)
        self.progress[1].grid(column = 1, row = 1, pady = 4)
        self.progress[2].grid(column = 1, row = 2, pady = 4)
        self.progress[3].grid(column = 1, row = 3, pady = 4)
        self.flash_tester = tk.IntVar()
        tk.Label(self.progress_frame, text = "Flashing ESP32", anchor = 'w').grid(column = 0, row = 0, sticky = tk.W, padx = 10)
        tk.Label(self.progress_frame, text = "Flashing FPGA Bitfile", anchor = 'w').grid(column = 0, row = 1, sticky = tk.W, padx = 10)
        tk.Label(self.progress_frame, text = "Flashing Application", anchor = 'w').grid(column = 0, row = 2, sticky = tk.W, padx = 10)
        tk.Label(self.progress_frame, text = "Flashing FAT FileSystem", anchor = 'w').grid(column = 0, row = 3, sticky = tk.W, padx = 10)
        self.progress_frame.grid(columnspan = 3, column = 1, row = 2, padx = 10, pady = 5)

        self.stats = InfoFields(self.window, ["Serial #", "FPGA ID", "Flash ID", "Board Revision", "Supply", "+5.0V", "+3.3V", "+1.8V",
                                              "+1.0V", "Vaux", "Vusb" ], 1, 1, 14, 20)

        ch = TextboxLogHandler(self.textbox)
        ch.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(message)s'))
        Ultimate64IITests.add_log_handler(ch)
        JtagClient.add_log_handler(ch)

        welcome_msg = "Welcome to the U64-II Tester.\n1) Attach test harness to board set\n2) Turn on the board\n3) Scan Serial Number\n4) Click 'start!'\n"
        messagebox.showinfo("Welcome!", welcome_msg)

        self.textbox.insert(tk.END, welcome_msg)
        self.textbox.see(tk.END)
        self.serial_entry.focus()
        self.window.update()
        #self.textbox.insert(tk.END, "Opening Video capture device\n")
        #self.window.update()
        #self.capture = cv2.VideoCapture(0)
        #self.textbox.insert(tk.END, "Video capture opened\n")
        #self.window.update()

    def run(self):
        self.window.mainloop()

    def UpdateVoltages(self):
        self.stats.set('Supply', self.testsuite.voltages[0])
        self.stats.set('Vaux', self.testsuite.voltages[1])
        self.stats.set('+5.0V', self.testsuite.voltages[2])
        self.stats.set('+3.3V', self.testsuite.voltages[3])
        self.stats.set('+1.8V', self.testsuite.voltages[4])
        self.stats.set('+1.0V', self.testsuite.voltages[5])
        self.stats.set('Vusb', self.testsuite.voltages[6])

    def UpdateUniqueId(self):
        fpga_id_string = f'{self.testsuite.unique:016X}'
        self.stats.set('FPGA ID', fpga_id_string)
        return # TODO
        serial_from_id = self.db.get_serial(fpga_id_string)
        if serial_from_id:
            if serial_from_id != self.serial:
                msg = f"FPGA ID {fpga_id_string} was previously associated with Serial Number {serial_from_id}!"
                messagebox.showerror("Wrong FPGA ID", msg)
                raise TestFailCritical(msg)

        board = self.db.get_board(self.serial)
        if board:
            if 'fpga_id' in board:
                if board['fpga_id'] != fpga_id_string:
                    msg = f"Serial Number {self.serial} has already been used for a board with FPGA ID {board['fpga_id']}!"
                    messagebox.showerror("Wrong Serial #", msg)
                    raise TestFailCritical(msg)

    def UpdateBoardRevision(self):
        self.stats.set('Board Revision', f'{self.testsuite.revision}')
        self.stats.set('Flash ID', f'{self.testsuite.flashid:016X}')
        if self.testsuite.revision == 16:
            self.testsuite.proto = True
            self.errors -= 1
            # Rerun test!
            self.RunOneTest('test_001_regulators')

    def write_test_to_db(self):
        # Write board to board table
        if self.testsuite.unique != 0 and self.testsuite.flashid != 0:
            self.db.add_board({
                'serial': self.serial,
                'fpga_id': f'{self.testsuite.unique:016X}',
                'flash_id': f'{self.testsuite.flashid:016X}',
                'board_rev': self.testsuite.revision,
            })

        time = datetime.now().strftime("%Y-%m-%d, %H:%M:%S")

        # Write statistiscs to stats table
        self.db.add_test_results({
            'serial': self.serial,
            'flash_id': f'{self.testsuite.flashid:016X}',
            'fpga_id': f'{self.testsuite.unique:016X}',
            'date': time,
            'vbus': self.testsuite.voltages[0][:-2],
            'vaux': self.testsuite.voltages[1][:-2],
            'vusb': self.testsuite.voltages[6][:-2],
            'v50': self.testsuite.voltages[2][:-2],
            'v33': self.testsuite.voltages[3][:-2],
            'v18': self.testsuite.voltages[4][:-2],
            'v10': self.testsuite.voltages[5][:-2],
            'git': self.gitsha,
            'flashed': self.flashed,
            'booted' : self.boot_ok,
            'critical': self.critical,
            'failed': ','.join(self.failed_tests),
        })

        self.db.add_log({'serial' : self.serial,
                         'date': time,
                         'log': self.textbox.get("1.0", tk.END) })

if __name__ == '__main__':
    gui = MyGui()
    gui.setup()
    gui.run()
