import hashlib
import subprocess
import time

import customtkinter
from tkinter import StringVar, filedialog, messagebox

import semantic_version

import requests
from tempfile import TemporaryDirectory

from serial.serialutil import SerialException

from Device import Device, DeviceViewFrame, ControlIndicator, device_classes
import serial
from serial.tools.list_ports import comports
import logging
import os
from PIL import Image, ImageTk
from tkinter import N, NE, E, SE, S, SW, W, NW, Canvas
from copy import deepcopy
from more_itertools import batched
from itertools import product


class NotSwitchologyDeviceError(TypeError):
    pass


class SwitchologyDeviceViewFrame(DeviceViewFrame):

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.scaling = customtkinter.ScalingTracker.get_widget_scaling(self)
        self.images = dict()
        self.subsample = kwargs.get("subsample", 3.556)
        self.load_images()
        self.offset_x = 0
        self.offset_y = 0
        self.modulesize = 100 * self.scaling
        self.modulegrid = dict()
        self.base_image = None
        self.canvas = None

    def refresh(self, device):
        for child in self.winfo_children():
            child.destroy()
        self.device = device
        self.draw_device(device)

        xpos = 405 * self.scaling
        ypos = 10 * self.scaling
        self.update()
        for i, control in enumerate(self.device.get_controls()):
            ci = ControlIndicator(self, control, width=80)
            if ypos > self.winfo_height():
                ypos = 10 * self.scaling
                xpos += 100 * self.scaling
            self.canvas.create_window(xpos, ypos, window=ci)
            device.add_subscriber(control, ci.update_value)
            ypos += 20 * self.scaling

    def load_images(self):
        imgdir = r"res/modimgs/prototype_v_0_4"
        for filename in os.listdir(imgdir):
            filepath = os.path.join(imgdir, filename)
            if not os.path.isfile(filepath):
                continue
            im = Image.open(filepath)
            im = im.resize((
                int(im.width / self.subsample * self.scaling ),
                int(im.height / self.subsample * self.scaling),
            ))
            self.images[os.path.basename(filepath).lower()] = im

    def draw_device(self, device=None):

        mode = customtkinter.get_appearance_mode()
        self.canvas = Canvas(
            self,
            width=800*self.scaling,
            height=600*self.scaling,
            background=self.cget("fg_color")[mode.lower() == 'dark'],
            bd=0,
            highlightthickness=0
        )
        self.canvas.grid()
        self.canvas.delete("all")
        self.base_image = ImageTk.PhotoImage(self.images.get("base_3x5.png"))
        self.canvas.create_image(0, 0, image=self.base_image, anchor=NW)

        if device is None:
            return

        build_id = device.build_id
        if build_id is None:
            return

        for i, blob in enumerate(batched(build_id, 3)):
            module_id = blob[:2]
            rot = blob[-1]
            ix = int(i / 5)
            iy = i % 5
            self.modulegrid[(ix, iy)] = {"id": "".join(module_id), "rotation": rot}
            logging.debug(f"modulegrid[{ix}][{iy}]={''.join(module_id)}")

        for ix, iy in self.modulegrid.keys():
            x = self.modulesize * (2 - ix) + self.offset_x
            y = self.modulesize * iy + self.offset_y
            module_id = self.modulegrid[(ix, iy)]["id"]
            imgname = module_id.lower() + ".png"
            direction = self.modulegrid[(ix, iy)]["rotation"].lower()

            if direction == N:
                anchor = SW
                rotation = 180
                xm = x
                ym = y + self.modulesize
            elif direction == E:
                anchor = NW
                rotation = 90
                xm = x
                ym = y
            elif direction == S:
                anchor = NE
                rotation = 0
                xm = x + self.modulesize
                ym = y
            elif direction == W:
                anchor = SE
                rotation = 270
                xm = x + self.modulesize
                ym = y + self.modulesize
            else:
                continue

            if imgname in ["xx.png", "--.png"]:
                continue
            if imgname in self.images.keys():
                self.modulegrid[(ix, iy)]["image"] = ImageTk.PhotoImage(
                    self.images.get(imgname).rotate(rotation, expand=1)
                )
                self.canvas.create_image(xm, ym, image=self.modulegrid[(ix, iy)]["image"], anchor=anchor, )
            else:
                logging.error(f"did not find module image \"{imgname}\"!")
            if logging.root.level <= logging.DEBUG:
                self.canvas.create_text(x + self.modulesize / 2, y + self.modulesize / 2,
                                        text=f"({ix, iy}):{module_id}",
                                        fill="magenta")
        if logging.root.level <= logging.DEBUG:
            self.canvas.create_line((0, 0, 100, 0), width=10, fill='red', arrow="last")
            self.canvas.create_line((0, 0, 0, 100), width=10, fill='blue', arrow="last")


class SwitchologyAlphaDeviceViewRame(SwitchologyDeviceViewFrame):

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.offset_x = 25
        self.offset_y = 25

    def load_images(self):
        imgdir = r"res/modimgs/prototype_v_0_2"
        for filename in os.listdir(imgdir):
            filepath = os.path.join(imgdir, filename)
            if not os.path.isfile(filepath):
                continue
            im = Image.open(filepath)
            im = im.resize((int(im.width / self.subsample), int(im.height / self.subsample)))
            self.images[os.path.basename(filepath).lower()] = im

    def draw_device(self, device=None):
        def try_rot_perm(rp):
            def get_adj_pos(self, position, direction, distance=1) -> (int, int):
                x, y = position
                if direction == N:
                    return x, y - distance
                elif direction == NE:
                    return x - distance, y - distance
                elif direction == E:
                    return x - distance, y
                elif direction == SE:
                    return x - distance, y + distance
                elif direction == S:
                    return x, y + distance
                elif direction == SW:
                    return x + distance, y + distance
                elif direction == W:
                    return x + distance, y
                elif direction == NW:
                    return x + distance, y - distance
                else:
                    raise AttributeError

            rot_perm_list = deepcopy(rp)
            rot_perm_grid = deepcopy(self.modulegrid)
            for ix, iy in rot_perm_grid:
                module_id = rot_perm_grid[(ix, iy)]["id"]
                if module_id.lower() in ["dg", "gl"]:  # 1x2 modules
                    d = rot_perm_list.pop()
                    if rot_perm_grid.get(self.get_adj_pos((ix, iy), d), None) is None:
                        logging.debug(f"modulegrid[{ix}][{iy}]={module_id}, direction={d} hits wall!")
                        return False
                    if rot_perm_grid.get(self.get_adj_pos((ix, iy), d))["id"] != "--":
                        logging.debug(f"modulegrid[{ix}][{iy}]={module_id}, direction={d} hits other module!")
                        return False
                    if rot_perm_grid.get(self.get_adj_pos((ix, iy), d))["id"] == "--":
                        rot_perm_grid.get(self.get_adj_pos((ix, iy), d))["id"] = f"xx({ix},{iy}){module_id}"
                        continue
                elif module_id.lower() in ["gg", "lg"]:  # 1x3 modules
                    d = rot_perm_list.pop()
                    if any(rot_perm_grid.get(self.get_adj_pos((ix, iy), d, distance=distance), None) is None for
                           distance in [1, 2]):
                        logging.debug(f"modulegrid[{ix}][{iy}]={module_id}, direction={d} hits wall!")
                        return False
                    if any(rot_perm_grid.get(self.get_adj_pos((ix, iy), d, distance=distance))["id"] != "--" for
                           distance in [1, 2]):
                        logging.debug(f"modulegrid[{ix}][{iy}]={module_id}, direction={d} hits other module!")
                        return False
                    if all(rot_perm_grid.get(self.get_adj_pos((ix, iy), d, distance=distance))["id"] == "--" for
                           distance in [1, 2]):
                        rot_perm_grid.get(self.get_adj_pos((ix, iy), d, 1))["id"] = f"xx({ix},{iy}){module_id}"
                        rot_perm_grid.get(self.get_adj_pos((ix, iy), d, 2))["id"] = f"xx({ix},{iy}){module_id}"
                        continue
                elif module_id.lower() in ["ga"]:  # 2x2 modules
                    d = rot_perm_list.pop()
                    if d == N:
                        ds = [N, NE, E]
                    elif d == E:
                        ds = [E, SE, S]
                    elif d == S:
                        ds = [S, SW, W]
                    else:  # d == W:
                        ds = [W, NW, N]
                    if any(rot_perm_grid.get(self.get_adj_pos((ix, iy), di), None) is None for di in ds):
                        logging.debug(f"modulegrid[{ix}][{iy}]={module_id}, direction={d} hits wall!")
                        return False
                    if any(rot_perm_grid.get(self.get_adj_pos((ix, iy), di))['id'] != '--' for di in ds):
                        logging.debug(f"modulegrid[{ix}][{iy}]={module_id}, direction={d} hits other module!")
                        return False
                    if all(rot_perm_grid.get(self.get_adj_pos((ix, iy), di))['id'] == '--' for di in ds):
                        for di in ds:
                            rot_perm_grid.get(self.get_adj_pos((ix, iy), di))["id"] = f"xx({ix},{iy}){module_id}:{di}"
                        continue
            return True

        mode = customtkinter.get_appearance_mode()
        self.canvas = Canvas(
            self,
            width=800,
            height=600,
            background=self.cget("fg_color")[mode.lower() == 'dark'],
            bd=0,
            highlightthickness=0
        )
        self.canvas.grid()
        self.canvas.delete("all")
        self.base_image = ImageTk.PhotoImage(self.images.get("base_3x5.png"))
        self.canvas.create_image(0, 0, image=self.base_image, anchor=NW)

        if device is None:
            return

        build_id = device.build_id
        if build_id is None:
            return

        for i, module_id in enumerate(batched(build_id, 2)):
            ix = int(i / 5)
            iy = i % 5
            self.modulegrid[(ix, iy)] = {"id": "".join(module_id), "rotation": 0}
            logging.debug(f"modulegrid[{ix}][{iy}]={''.join(module_id)}")

        rotations = 0
        for ix, iy in self.modulegrid.keys():
            module_id = self.modulegrid[(ix, iy)]["id"]
            if module_id.lower() in ["dg", "gl"]:
                rotations += 1
            elif module_id.lower() in ["gg", "lg"]:
                rotations += 1
            elif module_id.lower() in ["ga"]:
                rotations += 1
        rot_perms = product([N, S, E, W], repeat=rotations)

        for i, rot_perm in enumerate(rot_perms):
            rot_perm_list = list(rot_perm)
            if try_rot_perm(rot_perm_list):
                logging.debug(f"rotation permutation {i}: {rot_perm} is possible!")
                break
            else:
                logging.debug(f"rotation permutation {i}: {rot_perm} is impossible!")

        for ix, iy in self.modulegrid.keys():
            x = self.modulesize * (2 - ix) + self.offset_x
            y = self.modulesize * iy + self.offset_y
            module_id = self.modulegrid[(ix, iy)]["id"]
            imgname = module_id.lower() + ".png"

            direction = N
            if module_id.lower() in ["dg", "gl"]:  # 1x2 modules
                direction = rot_perm_list.pop()
            elif module_id.lower() in ["gg", "lg"]:  # 1x3 modules
                direction = rot_perm_list.pop()
            elif module_id.lower() in ["ga"]:  # 2x2 modules
                direction = rot_perm_list.pop()
            logging.debug(f"modulegrid[{ix}][{iy}]={imgname}, direction={direction}")

            if direction == N:
                anchor = SW
                rotation = 180
                xm = x
                ym = y + self.modulesize
            elif direction == E:
                anchor = NW
                rotation = 90
                xm = x
                ym = y
            elif direction == S:
                anchor = NE
                rotation = 0
                xm = x + self.modulesize
                ym = y
            elif direction == W:
                anchor = SE
                rotation = 270
                xm = x + self.modulesize
                ym = y + self.modulesize
            else:
                rotation = 0

            if imgname in ["xx.png", "--.png"]:
                continue
            if imgname in self.images.keys():
                self.modulegrid[(ix, iy)]["image"] = ImageTk.PhotoImage(
                    self.images.get(imgname).rotate(rotation, expand=1)
                )
                self.canvas.create_image(xm, ym, image=self.modulegrid[(ix, iy)]["image"], anchor=anchor, )
            else:
                logging.error(f"did not find module image \"{imgname}\"!")
            if logging.root.level <= logging.DEBUG:
                self.canvas.create_text(x + self.modulesize / 2, y + self.modulesize / 2,
                                        text=f"({ix, iy}):{module_id}",
                                        fill="magenta")
        if logging.root.level <= logging.DEBUG:
            self.canvas.create_line((0, 0, 100, 0), width=10, fill='red', arrow="last")
            self.canvas.create_line((0, 0, 0, 100), width=10, fill='blue', arrow="last")


class SwitchologyDeviceConfigFrame(DeviceViewFrame):
    mode2s = ['A', ] + list(f"B{x}" for x in range(1, 15)) + ['C']

    def var_mode_update(self, *args):  # noqa
        if any(x == "" for x in [self.var_mode1.get(), self.var_mode2.get()]):
            return
        value = 256 * int(self.var_mode1.get()) + self.mode2s.index(self.var_mode2.get())
        self.var_mode.set(f"0x{value:04x}")

    def module_mode_8way_update(self, choice):
        if choice == "as 8+1 buttons":
            self.module_modes = self.module_modes | 0x01
        else:
            self.module_modes = self.module_modes & ~0x01

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)

        self.module_modes = 0x00

        self.firmware_update_checked = False

        self.var_mode1 = StringVar(value="")
        self.var_mode1.trace_add("write", self.var_mode_update)
        self.var_mode2 = StringVar(value='')
        self.var_mode2.trace_add("write", self.var_mode_update)
        self.var_mode = StringVar(value="")

        self.var_fwve = StringVar(value="")
        self.var_hwve = StringVar(value="")
        self.var_buid = StringVar(value="")
        self.var_conn = StringVar(value='')
        self.var_udpe = StringVar(value="")
        self.var_blfc = StringVar(value="")

        self.lbl_fwve = customtkinter.CTkLabel(self, text='Firmware Version')
        self.lbl_fwve.grid(row=0, column=0, sticky="w")
        self.ent_fwve = customtkinter.CTkEntry(self, state='disabled', textvariable=self.var_fwve)
        self.ent_fwve.grid(row=0, column=1)

        self.lbl_hwve = customtkinter.CTkLabel(self, text='Hardware Version')
        self.lbl_hwve.grid(row=1, column=0, sticky="w")
        self.ent_hwve = customtkinter.CTkEntry(self, state='disabled', textvariable=self.var_hwve)
        self.ent_hwve.grid(row=1, column=1)

        self.lbl_buid = customtkinter.CTkLabel(self, text='Build ID')
        self.lbl_buid.grid(column=0, row=2, sticky="w")
        self.ent_buid = customtkinter.CTkEntry(self, state='disabled', textvariable=self.var_buid, width=250)
        self.ent_buid.grid(column=1, row=2)

        self.lbl_mode1 = customtkinter.CTkLabel(self, text='Logical devices')
        self.cbx_mode1 = customtkinter.CTkComboBox(
            self,
            variable=self.var_mode1,
            values=["1", "2", "3", "4", "5"],
            state='readonly',
        )
        self.lbl_mode1.grid(column=0, row=3, sticky="w")
        self.cbx_mode1.grid(column=1, row=3)

        self.lbl_mode2 = customtkinter.CTkLabel(self, text='Buttonmode')
        self.cbx_mode2 = customtkinter.CTkComboBox(
            self,
            variable=self.var_mode2,
            values=self.mode2s,
            state='readonly'
        )
        self.lbl_mode2.grid(column=0, row=4, sticky="w")
        self.cbx_mode2.grid(column=1, row=4)

        self.lbl_mode = customtkinter.CTkLabel(self, text='Mode Variable')
        self.ent_mode = customtkinter.CTkEntry(self, textvariable=self.var_mode, state='disabled')
        self.lbl_mode.grid(column=0, row=5, sticky="w")
        self.ent_mode.grid(column=1, row=5)

        self.lbl_udpe = customtkinter.CTkLabel(self, text='Update Period in ms')
        self.lbl_udpe.grid(row=6, column=0, sticky="w")
        self.ent_udpe = customtkinter.CTkEntry(self, textvariable=self.var_udpe)
        self.ent_udpe.grid(row=6, column=1)

        self.lbl_blfc = customtkinter.CTkLabel(self, text='Backlight Factor')
        self.lbl_blfc.grid(row=7, column=0, sticky="w")
        self.ent_blfc = customtkinter.CTkEntry(self, textvariable=self.var_blfc)
        self.ent_blfc.grid(row=7, column=1)

        frm_elmo = customtkinter.CTkFrame(self)
        lbl_elmo = customtkinter.CTkLabel(frm_elmo, text="Module modes")
        lbl_elmo.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.lbl_8wmd = customtkinter.CTkLabel(frm_elmo, text="8-Way Switch Mode", padx=2, pady=2)
        self.lbl_8wmd.grid(row=1, column=0, padx=2, sticky="w")
        self.cbx_8wmd = customtkinter.CTkComboBox(
            master=frm_elmo,
            values=["as 4+1 buttons", "as 8+1 buttons"],
            command=self.module_mode_8way_update,
            state="readonly",
        )
        self.cbx_8wmd.grid(row=1, column=1, padx=2, sticky="ew")
        frm_elmo.grid(row=8, column=0, columnspan=2, sticky="ew")

        self.btn_write = customtkinter.CTkButton(self, text="Write", command=self.write_all)
        self.btn_write.grid()
        self.btn_reset = customtkinter.CTkButton(self, text="Reset", command=lambda: self.device.reset())
        self.btn_reset.grid()
        self.btn_format = customtkinter.CTkButton(self, text="Format", command=lambda: self.device.send_command('fmt'))
        self.btn_format.grid()

    def refresh(self, device):
        self.device = device
        self.var_buid.set(device.build_id)
        self.var_hwve.set(device.hwver)
        self.var_fwve.set(device.fwver)
        self.var_mode.set(device.base_mode)
        self.var_udpe.set(device.update_period)
        self.var_blfc.set(device.backlight_factor)

        self.module_modes = device.module_mode
        if self.module_modes & 0x01:
            self.cbx_8wmd.set("as 8+1 buttons")
        else:
            self.cbx_8wmd.set("as 4+1 buttons")

        mode = int(self.var_mode.get(), 16)
        mode1 = int(mode / 256)
        mode2 = int(mode % 256)
        self.var_mode1.set(str(mode1))
        self.var_mode2.set(self.mode2s[mode2] if mode2 < len(self.mode2s) else mode2)

    def write_all(self):
        for command in [
            f'sbm {self.var_mode.get()}',
            f'sup {hex(int(self.var_udpe.get()))}',
            f'sbf {hex(int(self.var_blfc.get()))}',
            f'sem {hex(self.module_modes)}'
        ]:
            ans = self.device.send_command(command)
            if "ok" in ans.lower():
                logging.info(f"Successful write to device ({command})")
            else:
                logging.error(f"Failed to write to device ({command})!")


class SwitchologyDeviceUpdateFrame(DeviceViewFrame):

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.firmwarepath = StringVar(value="")
        self.var_fwve = StringVar(value="")

        self.btn_upol = customtkinter.CTkButton(self, text="Update from server", command=self.update_from_server)
        self.btn_upol.grid(column=1, row=0, columnspan=2, padx=5, pady=5)
        self.btn_slfw = customtkinter.CTkButton(self, text="Select file", command=self.select_file)
        self.btn_slfw.grid(column=1, row=1, padx=5, pady=5)
        self.btn_upfw = customtkinter.CTkButton(self, text="Update from file", command=self.update_firmware, state='disabled')
        self.btn_upfw.grid(column=2, row=1, padx=5, pady=5)
        self.ent_fwpt = customtkinter.CTkEntry(self, textvariable=self.firmwarepath, state='disabled')
        self.ent_fwpt.grid(column=1, row=2, columnspan=2, padx=5, pady=5)
        self.pro_upfw = customtkinter.CTkProgressBar(self, orientation="horizontal", mode='determinate')
        self.pro_upfw.grid(column=1, row=3, columnspan=2, padx=5, pady=5)
        self.pro_upfw.set(0)

    def refresh(self, device):
        self.device = device
        self.var_fwve.set(device.fwver)
        self.update_from_server()

    def update_from_server(self):
        update_server_url = "https://us-central1-switchology-a3b47.cloudfunctions.net/download_latest_firmware"
        logging.info("reqeuesting firmware information from server...")
        response = requests.get(update_server_url)
        response_json = response.json()
        if self.device.fwver == response_json.get('tag'):
            logging.info("firmware is up to date")
            return
        ans = messagebox.askquestion(
                title="Firmware update available!",
                message=f"There is a new version available! Do you want to update?\n"
                        f"current version: \"{self.device.fwver}\", new version: \"{response_json.get('tag')}\"\n"
                        f"published at: {response_json.get('published_at')}\n"
        )
        if ans == 'yes':
            with TemporaryDirectory() as tempdir:
                logging.debug(f"temporary directory created: \"{tempdir}\"")
                file_response = requests.get(response_json.get("url"))
                hash_calculator = hashlib.sha256()
                firmware_file_path = os.path.join(tempdir, f"{response_json.get('tag')}.bin")
                with open(firmware_file_path, "w+b") as firmware_file:
                    for chunk in file_response.iter_content(chunk_size=8192):
                        firmware_file.write(chunk)
                        hash_calculator.update(chunk)

                    # firmware_file.seek(0)
                firmware_hash = hash_calculator.hexdigest()

                if firmware_hash != response_json.get('hash'):
                    logging.error(f"firmware download was not successfull!")
                    return

                logging.info("firmware download successfull")
                self.firmwarepath.set(firmware_file.name)
                self.update_firmware()

    def update_firmware(self):
        logging.info("updating firmware...")
        self.device.send_command("btl")  # switch to bootloader
        time.sleep(0.1)
        self.device.send_command("rst")  # reset
        time.sleep(1)

        path_to_dfuutil = os.path.join("dfu-util", "dfu-util.exe")

        logging.debug(f"running dfutil...")
        self.updateproc = subprocess.Popen(
            [path_to_dfuutil, "-D", self.firmwarepath.get()],
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE
        )
        s = ""
        line = ""
        for c in iter(lambda: self.updateproc.stdout.read(1), b""):
            if c.decode() == "\n":
                logging.debug(line)
                line=""
            else:
                line += c.decode()
            if c == b'%':
                v = int(s[-3:]) / 100
                self.pro_upfw.set(v)
                self.pro_upfw.update()
            else:
                s += c.decode()
        if "DFU state(7) = dfuMANIFEST, status(0) = No error condition is present" in s:
            logging.info("Firmware update complete!")
        else:
            logging.error(f"Firmware update failed!")
            logging.error(s)
        time.sleep(1)
        self.device._fw_ver = None
        self.refresh(self.device)

    def select_file(self):
        self.pro_upfw['value'] = 0
        filetypes = (
            ('firmware files', '*.bin'),
            ('All files', '*.*')
        )

        filename = filedialog.askopenfilename(
            title='Open a file',
            initialdir='/',
            filetypes=filetypes)

        if os.path.isfile(filename):
            self.firmwarepath.set(filename)
            self.btn_upfw.configure(state="normal")
            self.ent_fwpt.xview_moveto(1)
            logging.debug(f"firmware update file \"{filename}\" selected.")


class SwitchologyDevice(Device):
    tabs = {
        "View": SwitchologyDeviceViewFrame,
        "Config": SwitchologyDeviceConfigFrame,
        "Update": SwitchologyDeviceUpdateFrame
    }

    def __init__(self, *args):
        super().__init__(*args)
        self._build_id = None
        self._fw_ver = None
        self._sem_fw_ver = None
        self._hw_ver = None
        self._base_mode = None
        self._update_period = None
        self._backlight_factor = None
        self._module_mode = None
        self.serial_itf = None
        self.port = None
        if not (self.vid, self.pid) in [
            (0x0483, 0xA4F5),  # VID & PID assigned to Switchology MCP (starting with firmare v0.4.0)
            (0x0483, 54321),  # compatibility with arbitrary VID and PID for older firmware prior v0.4.0
        ]:
            raise NotSwitchologyDeviceError

    def __del__(self):
        super().__del__()
        self.close_comport()

    def open_comport(self):
        timout_at = time.thread_time_ns() + 1e9
        while self.port is None:
            if time.thread_time_ns() > timout_at:
                raise TimeoutError
            logging.debug("enumerating comports...")
            for comport in comports():
                logging.debug(f"...{comport.serial_number} at {comport.name}")
                if comport.serial_number == self.serial_number:
                    self.port = comport
                    break

        timout_at = time.thread_time_ns() + 1e9
        while self.serial_itf is None:
            if time.thread_time_ns() > timout_at:
                raise TimeoutError
            try:
                self.serial_itf = serial.Serial(
                    port=self.port.device,
                    baudrate=9600,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    xonxoff=False,
                    rtscts=False,
                    dsrdtr=False,
                )
                break
            except Exception as e:
                logging.debug(e)

        timout_at = time.thread_time_ns() + 1e9
        while not self.serial_itf.is_open:
            if time.thread_time_ns() > timout_at:
                raise TimeoutError
            try:
                self.serial_itf.open()
                self.serial_itf.flush()
            except Exception as e:
                logging.debug(e)
                self.serial_itf.close()
        return self.serial_itf.is_open

    def close_comport(self):
        if self.serial_itf:
            self.serial_itf.close()

    def send_command(self, command):
        self.open_comport()
        logging.debug(f"sending command \"{command}\"")
        self.serial_itf.write(f"{command}\r\n".encode('ascii'))
        if command == 'rst':
            self.serial_itf.close()
            logging.debug(f"interface closed")
            return f"{self.serial_itf.portstr} closed"
        self.serial_itf.read_until()  # read the command echo
        ans = self.serial_itf.read_until().decode('ascii').strip()
        logging.debug(f"device answered \"{ans}\"")
        self.close_comport()
        return ans

    def reset(self):
        self._build_id = None
        self._fw_ver = None
        self._hw_ver = None
        self._base_mode = None
        self._update_period = None
        self._backlight_factor = None
        self.send_command("rst")
        time.sleep(5)

    @property
    def build_id(self):
        if not self._build_id:
            if self.fwver == "v0.4.0":
                logging.error(f"Will not request build id from firmware v0.4.0 devices!")
                return ""
            self._build_id = self.send_command('gbi')
        return self._build_id

    @property
    def hwver(self):
        if not self._hw_ver:
            self._hw_ver = self.send_command('ghw')
        return self._hw_ver

    @property
    def fwver(self):
        if not self._fw_ver:
            self._fw_ver = self.send_command('gfw')
            self._sem_fw_ver = semantic_version.Version(self._fw_ver.replace("v", ""))
        return self._fw_ver

    @property
    def update_period(self):
        if not self._update_period:
            self._update_period = int(self.send_command("gup"), 16)
        return self._update_period

    @property
    def base_mode(self):
        if not self._base_mode:
            self._base_mode = self.send_command('gbm')
        return self._base_mode

    @property
    def backlight_factor(self):
        if not self._backlight_factor:
            self._backlight_factor = int(self.send_command('gbf'), 16)
        return self._backlight_factor

    @property
    def module_mode(self):
        if self._sem_fw_ver < semantic_version.Version("0.4.4"):
            return None
        if not self._module_mode:
            self._module_mode = int(self.send_command('gem'), 16)
        return self._module_mode


device_classes[(0x0483, 0xA4F5)] = SwitchologyDevice  # VID & PID assigned to Switchology MCP (starting with firmware v0.4.0)
device_classes[(0x0483, 0xD431)] = SwitchologyDevice  # compatibility with arbitrary VID and PID for older firmware prior v0.4.0
