import hashlib
import subprocess
import time
import tkinter.messagebox

from settings import settings

import customtkinter
from tkinter import StringVar, BooleanVar, filedialog, messagebox
import re
import semantic_version

import requests
from tempfile import TemporaryDirectory

from serial.serialutil import SerialException

from Device import Device, DeviceViewFrame, device_classes, DfuDevice
import serial
from serial.tools.list_ports import comports
import logging
import os
from PIL import Image, ImageTk
from tkinter import N, NE, E, SE, S, SW, W, NW, Canvas
from copy import deepcopy
from more_itertools import batched
from itertools import product
import swinput


class NotSwitchologyDeviceError(TypeError):
    pass

class NoSerialNumberError(Exception):
    pass


path_to_dfuutil = os.path.join("dfu-util", "dfu-util.exe")

UPDATE_SERVER_URL = (
    "https://us-central1-switchology-a3b47.cloudfunctions.net/"
    "download_latest_firmware"
)

DFU_VIDPIDS = (
    "0483:a4f5",
    "1209:db42",
)


def dfu_util_list_devices():
    logging.debug(f"dfutil list devices...")
    result = subprocess.run(
        [path_to_dfuutil, "-l"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=5,
        check=False,
    )
    listout = result.stdout.decode(errors="replace")
    logging.debug(listout)
    for vp in DFU_VIDPIDS:
        if vp in listout:
            yield vp


def dfu_util_update(firmwarepath, vidpid):
    logging.debug(f"dfutil updating {vidpid}...")
    return subprocess.Popen(
        [path_to_dfuutil, "-D", firmwarepath, "-d", vidpid, ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=0,
    )


class SwitchologyDeviceViewFrame(DeviceViewFrame):

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
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
        self.draw_controls()

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
            width=400*self.scaling,
            height=600*self.scaling,
            background=self.cget("fg_color")[mode.lower() == 'dark'],
            bd=0,
            highlightthickness=0
        )
        self.canvas.grid(row=0, column=0)
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
            imgname = "".join([ c if c.isupper() else "_"+c for c in module_id ]).lower() + ".png"
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
    mode2s = dict({x: f"B{x}" for x in range(1, 15)})  # B-Modes
    mode2s[0x00] = 'A'
    mode2s[0x0F] = 'C'
    mode2s[0x20] = 'D'

    def var_mode_update(self, *args):  # noqa
        if any(x == "" for x in [self.var_mode1.get(), self.var_mode2.get()]):
            return
        bmode = 0x00
        for k, v in self.mode2s.items():
            if v == self.var_mode2.get():
                bmode = k
                break
        value = 256 * int(self.var_mode1.get()) + bmode
        self.var_mode.set(f"0x{value:04x}")

    def module_mode_8way_update(self, choice):
        if choice == "as 8+1 buttons":
            self.module_modes = self.module_modes | 0x01
        else:
            self.module_modes = self.module_modes & ~0x01

    def module_mode_toggle_update(self, choice):
        if choice == "Pulse":
            self.module_modes = self.module_modes | 0x02
        else:
            self.module_modes = self.module_modes & ~0x02

    def module_mode_rotabs_update(self, choice):
        self.module_modes = self.module_modes & ~0x0C
        if choice == "Pulse":
            self.module_modes = self.module_modes | 0x04
        elif choice == "Encoder":
            self.module_modes = self.module_modes | 0x08

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
        self.var_jsdz = StringVar(value="")
        self.var_jssa = StringVar(value="")

        self.var_deid = StringVar(value="")

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
            values=list(self.mode2s.values()),
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

        self.lbl_deid = customtkinter.CTkLabel(self, text="Device Id", padx=2, pady=2)
        self.lbl_deid.grid(row=8, column=0, padx=2, sticky="w")
        self.ent_deid = customtkinter.CTkComboBox(
            self,
            values=[str(x) for x in range(1,9)],
            variable=self.var_deid
        )
        self.ent_deid.grid(row=8, column=1, padx=2)

        frm_elmo = customtkinter.CTkFrame(self)
        frm_elmo.columnconfigure(0, weight=1)
        frm_elmo.columnconfigure(1, weight=3)
        lbl_elmo = customtkinter.CTkLabel(frm_elmo, text="Module settings")
        lbl_elmo.grid(row=0, column=0, columnspan=2, sticky="ew")

        self.lbl_8wmd = customtkinter.CTkLabel(frm_elmo, text="8-Way Switch Mode", padx=2, pady=2)
        self.lbl_8wmd.grid(row=1, column=0, padx=2, sticky="w")
        self.cbx_8wmd = customtkinter.CTkComboBox(
            master=frm_elmo,
            values=["as 4+1 buttons", "as 8+1 buttons"],
            command=self.module_mode_8way_update,
            state="readonly",
        )
        self.cbx_8wmd.grid(row=1, column=1, padx=2, sticky="e")

        self.lbl_tgmd = customtkinter.CTkLabel(frm_elmo, text="Toggle Mode", padx=2, pady=2)
        self.lbl_tgmd.grid(row=2, column=0, padx=2, sticky="w")
        self.cbx_tgmd = customtkinter.CTkComboBox(
            master=frm_elmo,
            values=["Continuous", "Pulse"],
            command=self.module_mode_toggle_update,
            state="readonly",
        )
        self.cbx_tgmd.grid(row=2, column=1, padx=2, sticky="e")

        self.lbl_rsmd = customtkinter.CTkLabel(frm_elmo, text="Rotary Selector Mode", padx=2, pady=2)
        self.lbl_rsmd.grid(row=3, column=0, padx=2, sticky="w")
        self.cbx_rsmd = customtkinter.CTkComboBox(
            master=frm_elmo,
            values=["Continuous", "Pulse", "Encoder"],
            command=self.module_mode_rotabs_update,
            state="readonly",
        )
        self.cbx_rsmd.grid(row=3, column=1, padx=2, sticky="e")

        self.lbl_jsdz = customtkinter.CTkLabel(frm_elmo, text="Joystick Deadzone", padx=2, pady=2)
        self.lbl_jsdz.grid(row=4, column=0, padx=2, sticky="w")
        self.ent_jsdz = customtkinter.CTkEntry(frm_elmo, textvariable=self.var_jsdz)
        self.ent_jsdz.grid(row=4, column=1, padx=2, sticky="e")

        self.lbl_jsdz = customtkinter.CTkLabel(frm_elmo, text="Joystick Saturation", padx=2, pady=2)
        self.lbl_jsdz.grid(row=5, column=0, padx=2, sticky="w")
        self.ent_jsdz = customtkinter.CTkEntry(frm_elmo, textvariable=self.var_jssa)
        self.ent_jsdz.grid(row=5, column=1, padx=2, sticky="e")

        frm_elmo.grid(row=9, column=0, columnspan=2, sticky="ew")

        self.btn_write = customtkinter.CTkButton(self, text="Write and Restart", command=self.write_all)
        self.btn_write.grid(row=10, column=0)
        self.btn_reset = customtkinter.CTkButton(self, text="Factory Reset and Restart", command=self.factory_reset, fg_color="red", text_color="white")
        self.btn_reset.grid(row=10, column=1)

    def refresh(self, device):
        self.device = device
        self.var_buid.set(device.build_id)
        self.var_hwve.set(device.hwver)
        self.var_fwve.set(device.fwver)
        self.var_mode.set(device.base_mode)
        self.var_udpe.set(device.update_period)
        self.var_blfc.set(device.backlight_factor)
        self.var_jsdz.set(device.joystick_deadzone)
        self.var_jssa.set(device.joystick_saturation)
        self.var_deid.set(device.id+1)

        self.module_modes = device.module_mode
        if self.module_modes & 0x01:
            self.cbx_8wmd.set("as 8+1 buttons")
        else:
            self.cbx_8wmd.set("as 4+1 buttons")
        if self.module_modes & 0x02:
            self.cbx_tgmd.set("Pulse")
        else:
            self.cbx_tgmd.set("Continuous")
        if self.module_modes & 0x04:
            self.cbx_rsmd.set("Pulse")
        else:
            self.cbx_rsmd.set("Continuous")


        mode = int(self.var_mode.get(), 16)
        mode1 = int(mode / 256)
        mode2 = int(mode % 256)
        self.var_mode1.set(str(mode1))
        self.var_mode2.set(self.mode2s[mode2])

    def write_all(self):
        commands = [
            f'sbm {self.var_mode.get()}',
            f'sup {hex(int(self.var_udpe.get()))}',
            f'sbf {hex(int(self.var_blfc.get()))}',
            f'sem {hex(self.module_modes)}',
            f'sjs {hex(int(self.var_jsdz.get())<<8 | int(self.var_jssa.get()))}',
            f'sid {hex(int(self.var_deid.get())-1)}'
        ]
        for command in commands:
            ans = self.device.send_command(command)
            if "ok" in ans.lower():
                logging.info(f"Successful write to device ({command})")
            else:
                logging.error(f"Failed to write to device ({command})!")
        self.device.send_command('rst')

    def factory_reset(self):
        if not tkinter.messagebox.askokcancel(
            title="Factory Reset",
            message="This will reset all the configuration to default values!\nDo you wish to proceed?"
        ):
            return
        ans = self.device.send_command('fmt')
        if "ok" in ans.lower():
            logging.info(f"Successful write to device (fmt)")
            self.device.send_command('rst')
        else:
            logging.error(f"Failed to write to device (fmt)!")


def verify_firmware(filepath):
    data = None
    with open(filepath, "rb") as f:
        data = f.read(-1)

    # check meta data
    meta = data[-16:]
    meta_mag = meta[:4]
    meta_len = int.from_bytes(meta[4:8], byteorder="little")
    meta_crc = int.from_bytes(meta[8:12], byteorder="little")
    meta_ver = int.from_bytes(meta[12:16], byteorder="little")
    if meta_mag != b'SWCP':  # check magic value
        return False
    if meta_ver != 1:  # check meta version
        return False
    if meta_len & 0x3 != 0:  # check length
        return False

    # check file crc
    crc = 0xFFFFFFFF
    for i in range(0, meta_len, 4):
        word = int.from_bytes(data[i:i+4], byteorder="little")
        crc ^= word
        for _ in range(32):
            if crc & 0x80000000:
                crc = ((crc << 1) & 0xFFFFFFFF) ^ 0x04C11DB7
            else:
                crc = (crc << 1) & 0xFFFFFFFF
    crc &= 0xFFFFFFFF

    return crc == meta_crc


class SwitchologyDeviceUpdateFrame(DeviceViewFrame):

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.firmwarepath = StringVar(value="")
        self.var_prer = BooleanVar(value=settings.get("include_prereleases", False))
        self._firmware_tempdir = None
        self.btn_upol = customtkinter.CTkButton(self, text="Update from server", command=self.update_from_server)
        self.btn_upol.grid(column=0, row=0, padx=5, pady=5)
        self.swi_prer = customtkinter.CTkSwitch(self, text="include Prerelases", variable=self.var_prer, command=self._prerelease_setting_changed)
        self.swi_prer.grid(column=1, row=0, padx=5, pady=5, sticky="w")
        self.btn_slfw = customtkinter.CTkButton(self, text="Update from file", command=self.update_from_file)
        self.btn_slfw.grid(column=2, row=0, padx=5, pady=5)
        self.lbl_info = customtkinter.CTkLabel(self, text="")
        self.lbl_info.grid(column=0, row=1, columnspan=3, padx=5, pady=5)
        self.pro_upfw = customtkinter.CTkProgressBar(self, orientation="horizontal", mode='determinate', width=600, height=15)
        self.pro_upfw.grid(column=0, row=2, columnspan=3, padx=5, pady=5)
        self.pro_upfw.set(0)
        self.txt_lice = customtkinter.CTkTextbox(self, width=600, height=400)
        self.txt_lice.grid(column=0, row=3, columnspan=3, padx=5, pady=5)
        self.txt_lice.insert("end",
                             f"This software uses dfu-util, an open-source utility licensed under the GNU General Public License v2 (GPL-2.0).\n"
                             f"\n"
                             f"dfu-util is Copyright © its respective authors.\n"
                             f"\n"
                             f"The complete corresponding source code for dfu-util is available at:\n"
                             f"https://dfu-util.sourceforge.net/\n"
                             f"\n"
                             f"A copy of the GNU GPL v2 license is included with this software.\n"
                             f"\n\n"
                             )
        with open(r"dfu-util/gpl-2.0.txt") as f:
            self.txt_lice.insert("end", "".join(f.readlines()))
        self.txt_lice.configure(state="disabled")

    def refresh(self, device):
        self.device = device
        self.update_from_server()

    def _prerelease_setting_changed(self):
        settings.set("include_prereleases", self.var_prer.get())

    @staticmethod
    def _request_firmware_info():
        logging.info("requesting firmware information from server...")
        url = UPDATE_SERVER_URL
        if settings.get("include_prereleases", False):
            url += "?prerelease=true"
        response = requests.get(url,timeout=(5, 15),)
        response.raise_for_status()
        try:
            firmware_info = response.json()
        except ValueError as exc:
            raise ValueError("Firmware server returned invalid JSON.") from exc
        if not isinstance(firmware_info, dict):
            raise ValueError("Firmware server returned an invalid response.")
        for field in ("tag", "hash", "url"):
            value = firmware_info.get(field)
            if not isinstance(value, str) or not value:
                raise ValueError(f"Firmware server response is missing {field!r}.")
        return firmware_info

    def _cleanup_firmware_tempdir(self):
        if self._firmware_tempdir is not None:
            self._firmware_tempdir.cleanup()
            self._firmware_tempdir = None

    def _set_update_controls_enabled(self, enabled):
        state = "normal" if enabled else "disabled"
        self.btn_upol.configure(state=state)
        self.btn_slfw.configure(state=state)

    def _finish_update(self):
        self._cleanup_firmware_tempdir()
        self._set_update_controls_enabled(True)

    def update_from_server(self):
        try:
            firmware_info = self._request_firmware_info()
        except (requests.RequestException, ValueError) as exc:
            logging.error(f"Firmware update check failed: {exc}")
            self.lbl_info.configure(text="Could not check for firmware updates.")
            messagebox.showerror(
                title="Firmware update check failed!",
                message=f"Could not check for firmware updates.\n\n{exc}",
            )
            return
        server_tag = firmware_info["tag"]
        if self.device.fwver == server_tag:
            logging.info("firmware is up to date")
            self.lbl_info.configure(
                text="Firmware is up to date."
            )
            return
        ans = messagebox.askquestion(
            title="Firmware update available!",
            message=(
                "A different recommended firmware version "
                "is available.\n\n"
                f"Current version: {self.device.fwver}\n"
                f"Recommended version: {server_tag}\n"
                f"Published at: "
                f"{firmware_info.get('published_at', 'unknown')}\n\n"
                "Do you want to update?"
            ),
        )
        if ans == "yes":
            self._set_update_controls_enabled(False)
            self.master.master.set("Update")
            self.after(100, self._download_server_firmware,server_tag)

    def _download_server_firmware(self, expected_tag):
        try:
            # Request metadata again to get a fresh signed URL.
            firmware_info = self._request_firmware_info()
            if firmware_info["tag"] != expected_tag:
                logging.info(
                    "Firmware changed while waiting for "
                    "confirmation: "
                    f"{expected_tag} -> "
                    f"{firmware_info['tag']}"
                )
                self.lbl_info.configure(text="Available firmware changed.\nPlease retry.")
                messagebox.showinfo(
                    title="Firmware version changed",
                    message=(
                        "The recommended firmware version changed "
                        "while the update was waiting to start.\n\n"
                        "Please start the update again."
                    ),
                )
                self._finish_update()
                return
            self._cleanup_firmware_tempdir()
            self._firmware_tempdir = TemporaryDirectory()
            tempdir = self._firmware_tempdir.name
            logging.info("firmware file downloading to PC...")
            logging.debug(f'temporary directory created: "{tempdir}"')
            self.lbl_info.configure(text="Downloading to PC...")
            with requests.get(firmware_info["url"], stream=True, timeout=(5, 30),) as file_response:
                file_response.raise_for_status()
                firmware_file_path = os.path.join(tempdir, f"{firmware_info['tag']}.bin")
                hash_calculator = hashlib.sha256()
                with open(firmware_file_path, "wb") as firmware_file:
                    for chunk in file_response.iter_content(chunk_size=8192):
                        if not chunk:
                            continue
                        firmware_file.write(chunk)
                        hash_calculator.update(chunk)
            firmware_hash = hash_calculator.hexdigest()
            expected_hash = firmware_info["hash"].lower()
            if firmware_hash.lower() != expected_hash:
                logging.error("firmware file download hash \nverification failed")
                self.lbl_info.configure(text="Downloading to PC not successful!")
                messagebox.showerror(
                    title="Downloading to PC not successful!",
                    message=(
                        "The downloaded firmware failed "
                        "SHA-256 verification."
                    ),
                )
                self._finish_update()
                return
            logging.info("firmware file downloaded to PC")
            self.lbl_info.configure(text="Downloading to PC successful")
            self.firmwarepath.set(firmware_file_path)
            self.update_firmware()

        except (requests.RequestException, OSError, ValueError) as exc:
            logging.error(f"Firmware download failed: {exc}")
            self.lbl_info.configure(text="Downloading to PC not successful!")
            messagebox.showerror(
                title="Downloading to PC not successful!",
                message=(
                    "The new firmware could not be downloaded "
                    "to your PC.\n\n"
                    f"{exc}"
                ),
            )
            self._finish_update()

    def update_firmware(self):
        firmware_path = self.firmwarepath.get()
        logging.info("Verifying firmware file integrity...")
        self.lbl_info.configure(text="Verifying firmware file integrity...")
        try:
            firmware_valid = verify_firmware(firmware_path)
        except OSError as exc:
            logging.error(f"Could not read firmware file: {exc}")
            firmware_valid = False
        if not firmware_valid:
            logging.error("Firmware file integrity compromised!")
            self.lbl_info.configure(text="Firmware file integrity compromised!")
            messagebox.showerror(
                title="Firmware update failed!",
                message=(
                    "The integrity of the firmware file "
                    "could not be verified.\n"
                    "Please retry!"
                ),
            )
            self._finish_update()
            return
        logging.info("Firmware file integrity intact")
        logging.info("updating firmware on device...")
        self.pro_upfw.set(0)
        if isinstance(self.device, SwitchologyDevice):
            device_hash = self.device.hash
            try:
                self.device.send_command("btl")
            except Exception as exc:
                self._show_update_error("Could not switch the device to bootloader mode.",exc)
                self._cleanup_firmware_tempdir()
                return
            # Allow the bootloader command to reach the device
            # without blocking the Tkinter event loop.
            self.after(100, self._reset_into_bootloader, device_hash,)
            return
        if isinstance(self.device, DfuDevice):
            self._flash_firmware(self.device.vidpid,None)
            return
        self._finish_update()
        raise TypeError("Unexpected Device Type!")

    def _reset_into_bootloader(self, device_hash):
        try:
            self.device.reset(wait=False)
        except Exception as exc:
            self._show_update_error("Could not reset the device into bootloader mode.", exc)
            self._cleanup_firmware_tempdir()
            return
        deadline = time.monotonic() + 5.0
        self.lbl_info.configure(text="Waiting for DFU device...")
        self.after(200, self._poll_for_dfu_device, deadline, device_hash)

    def _poll_for_dfu_device(self, deadline, device_hash):
        try:
            devices = list(dfu_util_list_devices())
        except (OSError, subprocess.SubprocessError) as exc:
            self._show_update_error("Could not enumerate DFU devices.", exc)
            self._cleanup_firmware_tempdir()
            return
        if devices:
            self._flash_firmware(devices[0], device_hash)
            return
        if time.monotonic() >= deadline:
            logging.error("did not find any matching DFU device")
            self.lbl_info.configure(text="Failed!")
            messagebox.showerror(
                title="Firmware update failed!",
                message=(
                    "The firmware update failed!\n\n"
                    "No matching DFU device was found.\n"
                    "Your device should still be on the "
                    "old version.\n"
                    "Please disconnect and reconnect "
                    "the device."
                ),
            )
            self._finish_update()
            return

        self.after(200, self._poll_for_dfu_device, deadline, device_hash)

    def _flash_firmware(self, vidpid, device_hash):
        logging.debug("running dfutil...")
        try:
            updateproc = dfu_util_update(self.firmwarepath.get(), vidpid)
        except OSError as exc:
            self._show_update_error("Could not start dfu-util.", exc)
            self._cleanup_firmware_tempdir()
            return
        line = ""
        output = ""
        while True:
            c = updateproc.stdout.read(1)
            if not c:
                break
            text = c.decode(errors="replace")
            output += text
            if text == "\n":
                if line:
                    logging.debug(line)
                line = ""
            else:
                line += text
            match = re.search(r"(\d{1,3})%$",output[-16:],)
            if match is not None:
                percent = min(int(match.group(1)), 100)
                self.pro_upfw.set(percent / 100)
                self.lbl_info.configure(text=f"Updating... {percent}%")
                self.update_idletasks()
        if line:
            logging.debug(line)
        returncode = updateproc.wait()
        manifest_complete = "Download done." in output and "DFU state(7) = dfuMANIFEST, status(0) = No error condition is present" in output
        expected_disconnect = "unable to read DFU status after completion (LIBUSB_ERROR_IO)" in output
        flash_successful = returncode == 0 or (manifest_complete and expected_disconnect)
        if flash_successful:
            if returncode != 0:
                logging.info(f"dfu-util lost the device after successful manifestation; ignoring exit code {returncode}")
            logging.info("Firmware update complete!")
            self.pro_upfw.set(1)
            self.lbl_info.configure(text="Complete")
            messagebox.showinfo(
                title="Firmware update complete!",
                message="Your device is now on the new version!",
            )
            device_list_frame = self._find_device_list_frame()
            if device_list_frame is not None:
                device_list_frame.selected_device_hash = None
                self._wait_for_reconnect(5, device_list_frame, device_hash)
            else:
                self._finish_update()
        else:
            logging.error(f"Firmware update failed! dfu-util exit code: {returncode}")
            logging.error(output)
            self.lbl_info.configure(text="Failed!")
            messagebox.showerror(
                title="Firmware update failed!",
                message=(
                    "The firmware update failed!\n\n"
                    f"dfu-util exited with code {returncode}.\n"
                    "Your device may still be in DFU mode.\n"
                    "Please disconnect and reconnect the device."
                ),
            )
            device_list_frame = self._find_device_list_frame()
            if device_list_frame is not None:
                self.after(1000, device_list_frame.refresh)
            self._finish_update()

    def _find_device_list_frame(self):
        widget = self
        while True:
            master = getattr(widget, "master", None)
            if master is None:
                return None
            if hasattr(master, "device_list_frame"):
                return master.device_list_frame
            widget = master

    def _wait_for_reconnect(self, numsec, device_list_frame, device_hash):
        if numsec > 0:
            self.lbl_info.configure(text=f"Complete. Waiting for device to restart {numsec}s...")
            self.after(1000, self._wait_for_reconnect, numsec - 1, device_list_frame, device_hash)
            return
        # The refresh may destroy this update frame, so clean up
        # everything belonging to it before refreshing the device list.
        self._cleanup_firmware_tempdir()
        device_list_frame.refresh()
        if device_hash is not None and device_hash in device_list_frame.devices:
            device_list_frame.select(device_hash)

    def _show_update_error(self, message, exc=None):
        if exc is not None:
            logging.error(f"{message} {exc}")
        else:
            logging.error(message)
        self.lbl_info.configure(text="Failed!")
        details = ""
        if exc is not None:
            details = f"\n\n{exc}"
        messagebox.showerror(
            title="Firmware update failed!",
            message=message + details,
        )
        self._finish_update()

    def update_from_file(self):
        self.pro_upfw.set(0)
        self._cleanup_firmware_tempdir()
        filetypes = (
            ('firmware files', '*.bin'),
            ('All files', '*.*')
        )
        filename = filedialog.askopenfilename(title="Open a file", initialdir="/", filetypes=filetypes,)
        if not os.path.isfile(filename):
            return
        self.firmwarepath.set(filename)
        logging.debug(f"firmware update file \"{filename}\" selected.")
        self._set_update_controls_enabled(False)
        self.update_firmware()


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
        self._joystick_settings = None
        self.serial_itf = None
        self.port = None
        self._id = None

    def __del__(self):
        super().__del__()
        self.close_comport()

    def open_comport(self):
        logging.debug(f"retrieving comport via swinput...")
        try:
            self.port = swinput.get_com_port(self._hash)
            logging.debug(f"found device at \"{self.port}\"")
        except RuntimeError:
            logging.debug(f"looking for device \"{self.serial_number}\"")
            timout_at = time.thread_time_ns() + 1e9
            while self.port is None:
                if time.thread_time_ns() > timout_at:
                    raise TimeoutError
                logging.debug("enumerating comports...")
                for comport in comports():
                    logging.debug(f"...{comport.serial_number} at {comport.name}")
                    if comport.serial_number == self.serial_number:
                        logging.debug(f"found device {comport.serial_number} at {comport.name}!")
                        self.port = comport.device
                        break

        timout_at = time.thread_time_ns() + 1e9
        while self.serial_itf is None:
            if time.thread_time_ns() > timout_at:
                raise TimeoutError
            try:
                self.serial_itf = serial.Serial(
                    port=self.port,
                    baudrate=9600,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    xonxoff=False,
                    rtscts=False,
                    dsrdtr=False,
                    timeout=1,
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

    @property
    def serial_number(self):
        if self._serial_number in ["", None]:
            raise NoSerialNumberError
        return self._serial_number


    def send_command(self, command):

        # basic check if firmware supports the command
        if command != "gfw":
            cmd_ver = {
                "gfw": semantic_version.Version("0.2.0"),
                "ghw": semantic_version.Version("0.2.0"),
                "gbi": semantic_version.Version("0.2.0"),
                "sbm": semantic_version.Version("0.2.0"),
                "gbm": semantic_version.Version("0.2.0"),
                "rst": semantic_version.Version("0.2.0"),
                "fmt": semantic_version.Version("0.2.0"),
                "btl": semantic_version.Version("0.3.0"),
                "gup": semantic_version.Version("0.3.1"),
                "sup": semantic_version.Version("0.3.1"),
                "sbf": semantic_version.Version("0.4.0"),
                "gbf": semantic_version.Version("0.4.0"),
                "sem": semantic_version.Version("0.4.4"),
                "gem": semantic_version.Version("0.4.4"),
                "sdl": semantic_version.Version("0.5.0"),
                "gdl": semantic_version.Version("0.5.0"),
                "eol": semantic_version.Version("1.0.0"),
                "gjs": semantic_version.Version("1.2.0"),
                "sjs": semantic_version.Version("1.2.0"),
                "gid": semantic_version.Version("1.3.0"),
                "sid": semantic_version.Version("1.3.0"),
            }
            ver = cmd_ver.get(command.split(" ")[0])
            if ver is not None:
                if ver > semantic_version.Version(self.fwver.replace("v", "").replace("-","+",1)):
                    logging.debug(f"Command \"{command}\" is not supported by firmware {self.fwver}")
                    return

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

    def reset(self, wait=True):
        self._build_id = None
        self._fw_ver = None
        self._hw_ver = None
        self._base_mode = None
        self._update_period = None
        self._backlight_factor = None
        self.send_command("rst")
        if wait:
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
            for retry in range(3):
                _fw_ver = self.send_command('gfw')
                m = re.match("v\d+\.\d+\.\d+(\S*)?", _fw_ver)
                if m is None:
                    logging.warning(f"device provided invalid answer to \"gfw\", retry {retry+1} of 3")
                    time.sleep(1)
                    continue
                self._fw_ver = _fw_ver
                self._sem_fw_ver = semantic_version.Version(self._fw_ver.replace("v", ""))
                break
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

    @property
    def joystick_deadzone(self):
        if not self._joystick_settings:
            self._joystick_settings = int(self.send_command("gjs"), 16)
        return self._joystick_settings >> 8

    @property
    def joystick_saturation(self):
        if not self._joystick_settings:
            self._joystick_settings = int(self.send_command("gjs"), 16)
        return self._joystick_settings & 0x00FF

    @property
    def id(self):
        if not self._id:
            self._id = int(self.send_command("gid"), 16)
        return self._id

device_classes[(0x0483, 0xA4F5)] = SwitchologyDevice  # VID & PID assigned to Switchology MCP (starting with firmware v0.4.0)
device_classes[(0x0483, 0xD431)] = SwitchologyDevice  # compatibility with arbitrary VID and PID for older firmware prior v0.4.0
