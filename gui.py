import json
import os
import sys
from tkinter import filedialog, messagebox
import logging
import argparse
import customtkinter
from Device import Device, device_classes
from Switchology import SwitchologyDevice, NotSwitchologyDeviceError, NoSerialNumberError

import swinput

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
    logging.debug("Enumerating HID Devices...")

    devices = dict()
    device_infos = swinput.enumerate_devices()
    for device_info in device_infos:
        description_string = \
            f"Hash: {device_info.device_hash}\n" \
            f"\tManufacturer: \"{device_info.manufacturer}\"\n" \
            f"\tProductName: \"{device_info.product_name}\"\n" \
            f"\tSerial Number: \"{device_info.serial_number}\"\n" \
            f"\tHID-Path: \"{device_info.hid_path}\"\n" \
            f"\tVID: \"0x{device_info.vid:04X}\"\n" \
            f"\tPID: \"0x{device_info.pid:04X}\"\n" \
            f"\tUsagePage: \"0x{device_info.usage_page:04X}\"\n" \
            f"\tUsage: \"0x{device_info.usage:04X}\"\n"

        try:
            comport = swinput.get_com_port(device_info.device_hash)
            description_string += f"\tCOM-Port: \"{comport}\""
        except RuntimeError as e:
            pass  # no COM port found
        logging.debug(description_string)
        temp_device_class = device_classes.get((device_info.vid, device_info.pid), Device)
        devices[device_info.device_hash] = temp_device_class(device_info)

    logging.debug("Enumeration of HID Devices completed!")
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
            except Exception as e:
                logging.error(e)
                continue
        self.device_tabview.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        if not os.path.exists(appdata_path):
            os.makedirs(appdata_path)

        self.devices = get_devices()
        swinput.start_capture()

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
            ans = messagebox.askquestion(
                title="Update available!",
                message=f"There is a new version available!\n"
                        f"Your version: \"{gitrev}\", latest version: \"{latest_version}\"\n"
                        f"Do you want to update?"
            )
            if ans == "yes":
                update()
                messagebox.showinfo(
                    title="Update complete!",
                    message=f"The update to \"{latest_version}\" is complete. The programm will now restart!"
                )
                os.execl(sys.executable, os.path.abspath(__file__), *sys.argv)

    def __del__(self):
        swinput.stop_capture()

class DeviceListFrame(customtkinter.CTkFrame):

    def __init__(self, master: GUI, devices, command=None, **kwargs):
        self._sb_selected_color = customtkinter.ThemeManager.theme["CTkSegmentedButton"]["selected_color"]
        self._sb_selected_hover_color = customtkinter.ThemeManager.theme["CTkSegmentedButton"]["selected_hover_color"]
        self._sb_unselected_color = customtkinter.ThemeManager.theme["CTkSegmentedButton"]["unselected_color"]
        self._sb_unselected_hover_color = customtkinter.ThemeManager.theme["CTkSegmentedButton"]["unselected_hover_color"]
        super().__init__(master, **kwargs)
        self.device_buttons = dict()
        self.devices = devices
        self.refresh()
        self.selected_device_hash = None
        self._command = command

    def select(self, device_hash):
        if len(self.device_buttons) == 0:
            return
        if self.selected_device_hash is not None:
            self.device_buttons[self.selected_device_hash].configure(
                fg_color=self._sb_unselected_color,
                hover_color=self._sb_unselected_hover_color
            )
            self.devices[self.selected_device_hash].close()
        self.selected_device_hash = device_hash
        self.device_buttons[self.selected_device_hash].configure(
            fg_color=self._sb_selected_color,
            hover_color=self._sb_selected_hover_color
        )
        if self._command:
            self._command(self.devices[self.selected_device_hash])

    def refresh(self):
        for i, (device_hash, device) in enumerate(self.devices.items()):
            try:
                btn_text = "\n".join([device.product_name, device.serial_number, str(device.hash)])
                button = customtkinter.CTkButton(
                    self,
                    text=btn_text,
                    command=lambda x=device.hash: self.select(x),
                    fg_color=self._sb_unselected_color,
                    hover_color=self._sb_unselected_hover_color
                )
                button.grid(pady=5, padx=5)
                self.device_buttons[device.hash] = (button)
            except NoSerialNumberError:
                messagebox.showerror(
                    title=f"Could not retrieve serial number for {device.instance_name}!",
                    message=f"Could not retrieve serial number for\n"
                            f"\"{device.instance_name}\"\n"
                            f"{device.instance_guid}!\n"
                            f"The device may have stalled and will not show up in the device list\n"
                            "Please unplug and replug device and restart companion.\n"
                            "If the problem persists, please reboot the computer"
                )



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

    # customtkinter.set_default_color_theme("sw_yellow.json")
    customtkinter.ThemeManager.load_theme("sw_yellow.json")

    gui = GUI()
    gui.title(f"Switchology Companion App {gitrev}")
    # gui.geometry("1000x600")
    lh = LogHandler(gui.txt_logs)
    logging.getLogger().addHandler(lh)

    def dispatch_device_events():
        for this_report in swinput.read_reports(256):
            if this_report.button_count > 0:
                for i in range(this_report.button_count):
                    this_button = this_report.buttons[int(i / 32)] & (1 << (i % 32))
                    gui.devices[this_report.device_hash].update_button(i, this_button != 0)

            if this_report.axis_present:
                for axis_id in range(9):
                    if this_report.axis_present & (1 << axis_id):
                        gui.devices[this_report.device_hash].update_axis(axis_id, this_report.axis[axis_id])
        gui.after(int(1000/60), dispatch_device_events)

    gui.after(100, dispatch_device_events)
    logging.info("Program start")
    gui.mainloop()


if __name__ == "__main__":
    main()
