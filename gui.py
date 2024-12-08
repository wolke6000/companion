import json
import os
import sys
import tkinter.messagebox
from tkinter import filedialog, messagebox
import logging
import argparse
import customtkinter
from Device import Device
from Switchology import SwitchologyDevice, NotSwitchologyDeviceError

import ctypes
from pyglet.libs.win32 import _kernel32
from pyglet.libs.win32 import dinput
from pyglet.input.base import Button, AbsoluteAxis

from updater import check_for_update, update

try:
    from gitrev import gitrev
except ModuleNotFoundError:
    gitrev = "unknown version"

appdata_path = os.path.join(os.getenv('APPDATA'), 'sw_app')


class LogHandler(logging.Handler):
    def __init__(self, textwidget: customtkinter.CTkTextbox):
        super().__init__()
        self.textwidget = textwidget

    def emit(self, record):
        self.textwidget.configure(state="normal")
        self.textwidget.insert("end", self.format(record) + '\n')
        self.textwidget.yview("end")
        self.textwidget.update()
        self.textwidget.configure(state="disabled")


def get_devices():
    def _device_enum(device_instance, arg):
        i_di_device = dinput.IDirectInputDevice8()
        _i_dinput.CreateDevice(device_instance.contents.guidInstance, ctypes.byref(i_di_device), None)
        try:
            devices.append(SwitchologyDevice(i_di_device, device_instance.contents))
            logging.info(f"Found Switchology Device \"{device_instance.contents.tszProductName}\"")
        except NotSwitchologyDeviceError:
            # devices.append(Device(i_di_device, device_instance.contents))
            logging.debug(f"Ingoring Non-Switchology Device \"{device_instance.contents.tszProductName}\"")
        return dinput.DIENUM_CONTINUE

    logging.debug("Enumerating DirectInput Devices...")

    _i_dinput = dinput.IDirectInput8()
    module_handle = _kernel32.GetModuleHandleW(None)
    dinput.DirectInput8Create(
        module_handle,
        dinput.DIRECTINPUT_VERSION,
        dinput.IID_IDirectInput8W,
        ctypes.byref(_i_dinput),
        None
    )
    devices = list()
    _i_dinput.EnumDevices(
        dinput.DI8DEVCLASS_GAMECTRL,
        dinput.LPDIENUMDEVICESCALLBACK(_device_enum),
        None,
        dinput.DIEDFL_ATTACHEDONLY
    )
    logging.debug("Enumeration of DirectInput Devices completed!")
    return devices


class GUI(customtkinter.CTk):
    mode2s = ['A', ] + list(f"B{x}" for x in range(1, 15)) + ['C']

    def change_loglevel(self, *args):  # noqa
        logging.getLogger().setLevel(logging.getLevelNamesMapping().get(self.var_llvl.get(), 'INFO'))

    def change_device_frame(self, device):
        self.device_tabview.destroy()
        self.device_tabview = customtkinter.CTkTabview(self, width=600, height=550)
        for tabname in device.tabs.keys():
            tab = self.device_tabview.add(tabname)
            tabframe = device.tabs[tabname](tab, width=600, height=550)
            tabframe.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)
            try:
                tabframe.refresh(device)
            except:
                continue
        self.device_tabview.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        if not os.path.exists(appdata_path):
            os.makedirs(appdata_path)

        self.devices = get_devices()

        self.device_tabview = customtkinter.CTkTabview(self, width=600, height=550)
        self.device_tabview.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)

        self.device_list_frame = DeviceListFrame(self, self.devices, command=self.change_device_frame, width=200,
                                                 height=550)
        self.device_list_frame.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

        self.bindings_frame = customtkinter.CTkFrame(self, width=300, height=550)  # reset to BindingsFrame when DCS code issue is solved
        self.bindings_frame.grid(row=0, column=2, sticky="nsew", padx=5, pady=5)

        self.txt_logs = customtkinter.CTkTextbox(self, width=1000, height=100)
        self.txt_logs.grid(row=1, column=0, columnspan=3, sticky="nsew", padx=5, pady=5)

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        latest_version = check_for_update()
        if latest_version:
            ans = tkinter.messagebox.askquestion(
                title="Update available!",
                message=f"There is a new version available!\n"
                        f"Your version: \"{gitrev}\", latest version: \"{latest_version}\"\n"
                        f"Do you want to update?"
            )
            if ans == "yes":
                update()
                os.execl(sys.executable, os.path.abspath(__file__), *sys.argv)



class DeviceListFrame(customtkinter.CTkFrame):
    _sb_selected_color = customtkinter.ThemeManager.theme["CTkSegmentedButton"]["selected_color"]
    _sb_selected_hover_color = customtkinter.ThemeManager.theme["CTkSegmentedButton"]["selected_hover_color"]
    _sb_unselected_color = customtkinter.ThemeManager.theme["CTkSegmentedButton"]["unselected_color"]
    _sb_unselected_hover_color = customtkinter.ThemeManager.theme["CTkSegmentedButton"]["unselected_hover_color"]

    def __init__(self, master: GUI, devices, command=None, **kwargs):
        super().__init__(master, **kwargs)
        self.device_buttons = list()
        self.devices = list(devices)
        self.refresh()
        self.selected_device_index = None
        self._command = command

    def select(self, device_index):
        if len(self.device_buttons) == 0:
            return
        if self.selected_device_index is not None:
            self.device_buttons[self.selected_device_index].configure(
                fg_color=self._sb_unselected_color,
                hover_color=self._sb_unselected_hover_color
            )
            self.devices[self.selected_device_index].close()
        self.selected_device_index = device_index
        self.device_buttons[self.selected_device_index].configure(
            fg_color=self._sb_selected_color,
            hover_color=self._sb_selected_hover_color
        )
        self.devices[self.selected_device_index].open()
        if self._command:
            self._command(self.devices[self.selected_device_index])

    def refresh(self):
        for i, device in enumerate(self.devices):
            button = customtkinter.CTkButton(
                self,
                text="\n".join([device.instance_name, device.serial_number, device.instance_guid]),
                command=lambda x=i: self.select(x),
                fg_color=self._sb_unselected_color,
                hover_color=self._sb_unselected_hover_color
            )
            button.grid(pady=5, padx=5)
            self.device_buttons.append(button)


class PathSelector(customtkinter.CTkFrame):
    def __init__(self, master, title="", path="", **kwargs):
        super().__init__(master, **kwargs)
        self.path = customtkinter.StringVar(value=path)
        self.label = customtkinter.CTkLabel(self, text=title)
        self.label.grid(row=0, column=0, sticky="e")
        self.entry = customtkinter.CTkEntry(self, textvariable=self.path)
        self.entry.xview_moveto(1)
        self.entry.grid(row=0, column=1, sticky="ew")
        self.button = customtkinter.CTkButton(self, text="Change path", command=self.change_path_clicked)
        self.button.grid(row=0, column=2)
        self.grid_columnconfigure(1, weight=1)
        self.dialog_open = False

    def change_path_clicked(self):
        self.dialog_open = True
        path = filedialog.askdirectory(
            initialdir=self.path.get(),
            title='Select path'
        )
        self.dialog_open = False
        if os.path.isdir(path):
            self.path.set(path)
            self.entry.xview_moveto(1)


def main():
    parser = argparse.ArgumentParser(
        prog=f"Switchology Companion App {gitrev}",
        description='Configuration of Switchology Devices',
    )
    parser.add_argument('-d', '--debug', action='store_true', help='set loglevel to DEBUG')
    parser.add_argument('--logfile')

    args = parser.parse_args()

    if args.debug:
        loglevel = logging.DEBUG
    else:
        loglevel = logging.INFO

    logging.basicConfig(
        level=loglevel,
        format='%(asctime)s - %(levelname)s - %(message)s',
    )

    if args.logfile:
        fh = logging.FileHandler(args.logfile)
        logging.getLogger().addHandler(fh)

    gui = GUI()
    gui.title(f"Switchology Companion App {gitrev}")
    # gui.geometry("1000x600")
    lh = LogHandler(gui.txt_logs)
    logging.getLogger().addHandler(lh)

    def dispatch_selected_device_events():
        # if gui.bindings_frame.selected_device:
        #     gui.bindings_frame.selected_device.dispatch_events()
        gui.after(100, dispatch_selected_device_events)

    gui.after(100, dispatch_selected_device_events)
    logging.info("Program start")
    gui.mainloop()


if __name__ == "__main__":
    main()
