import json
import os
import sys
from tkinter import filedialog, messagebox
import logging
import argparse
import customtkinter
from Device import Device, device_classes
from Switchology import SwitchologyDevice, NotSwitchologyDeviceError

import ctypes
from pyglet.libs.win32 import _kernel32
from pyglet.libs.win32 import dinput
from pyglet.input.base import Button, AbsoluteAxis

from dscinputprofile import *
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
        product_guid = device_instance.contents.guidProduct
        pid = (product_guid.Data1 >> 16) & 0xFFFF
        vid = product_guid.Data1 & 0xFFFF
        logging.debug(f"found device with VID: {hex(vid)}, PID: {hex(pid)}")
        temp_device_class = device_classes.get((vid, pid), Device)
        devices.append(temp_device_class(i_di_device, device_instance.contents))
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
            except Exception as e:
                logging.error(e)
                continue
        self.device_tabview.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)
        if self.bindings_frame.selected_device:
            self.bindings_frame.selected_device.unsubscribe_all()
        self.bindings_frame.selected_device = device

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

        self.bindings_frame = BindingsFrame(self, width=300, height=550)
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


class BindingsFrame(customtkinter.CTkFrame):
    filetypes = [("DCS profile", ".diff.lua")]

    def __init__(self, master: GUI, **kwargs):
        pad = 3
        super().__init__(master, **kwargs)

        self.dpm = DCSProfileManager()
        profiles_found = self.dpm.load_profiles(appdata_path)

        self.blub = customtkinter.CTkLabel(self, text="DCS Input Profiles")
        self.blub.grid(row=0, column=0, columnspan=2, padx=pad, pady=pad)

        self.dcs_path_selector = PathSelector(self, path=self.dpm.dcs_path, title="DCS path")
        self.dcs_path_selector.grid(row=1, column=0, columnspan=2, sticky="ew", padx=pad, pady=pad)

        self.dcs_savegames_path_selector = PathSelector(self, path=self.dpm.dcs_savegames_path,
                                                        title="DCS Saved Games path")
        self.dcs_savegames_path_selector.grid(row=2, column=0, columnspan=2, sticky="ew", padx=pad, pady=pad)

        self.load_profiles_button = customtkinter.CTkButton(self, text="Reload data from DCS", command=self.load_profiles)
        self.load_profiles_button.grid(row=3, column=0, columnspan=2, padx=pad, pady=pad)

        self.aircraft_label = customtkinter.CTkLabel(self, text="Aircraft")
        self.aircraft_label.grid(row=4, column=0, sticky="w", padx=pad, pady=pad)
        self.aircraft_combobox = customtkinter.CTkComboBox(
            self,
            values=[],
            state="disabled",
            command=self.switch_aircraft,
        )
        self.aircraft_combobox.grid(row=4, column=1, sticky="ew", padx=pad, pady=pad)
        self.last_aircraft_choice = None

        self.category_label = customtkinter.CTkLabel(self, text="Category")
        self.category_label.grid(row=5, column=0, sticky="w", padx=pad, pady=pad)
        self.category_combobox = customtkinter.CTkComboBox(
            self,
            values=[],
            state="disabled",
            command=self.switch_category,
        )
        self.category_combobox.grid(row=5, column=1, sticky="ew", padx=pad, pady=pad)

        self.bindings = dict()
        self.bindings_frame = customtkinter.CTkScrollableFrame(self, width=500)
        self.bindings_frame.grid(row=6, column=0, columnspan=2, sticky="ns", padx=pad, pady=pad)

        self.grid_rowconfigure(6, weight=1)

        self.load_from_savegames_button = customtkinter.CTkButton(self, text="Load your DCS control settings\nfor this device and airplane",
                                                                  command=self.import_dcs)
        self.load_from_savegames_button.grid(row=7, column=0, sticky="ew", padx=pad, pady=pad)
        self.load_from_profile_button = customtkinter.CTkButton(self, text="Load a DCS profile file (*.diff.lua)",
                                                                command=self.import_file)
        self.load_from_profile_button.grid(row=8, column=0, sticky="ew", padx=pad, pady=pad)
        self.load_switchology_profile_button = customtkinter.CTkButton(self, text="Load a Switchology profile file (*.swpf)",
                                                                       command=self.import_switchology)
        self.load_switchology_profile_button.grid(row=9, column=0, sticky="ew", padx=pad, pady=pad)
        self.save_to_savegames_button = customtkinter.CTkButton(self, text="Push into DCS control settings",
                                                                command=self.export_dcs)
        self.save_to_savegames_button.grid(row=7, column=1, sticky="ew", padx=pad, pady=pad)
        self.save_to_profile_button = customtkinter.CTkButton(self, text="Save as DCS profile file (*.diff.lua)",
                                                              command=self.export_file)
        self.save_to_profile_button.grid(row=8, column=1, sticky="ew", padx=pad, pady=pad)
        self.save_switchology_button = customtkinter.CTkButton(self, text="Save as Switchology profile file (*.swpf)",
                                                               command=self.export_switchology)
        self.save_switchology_button.grid(row=9, column=1, sticky="ew", padx=pad, pady=pad)

        self.popup = None

        self.selected_device = None

        self.diff = Diff()

        if not profiles_found:
            self.after(100, self.show_path_popup)
        elif self.dpm.dcs_config_version != self.dpm.get_dcs_version():
            self.after(100, self.show_path_popup)
        else:
            self.update_aircraftlist()

    def show_path_popup(self):
        def load():
            self.dcs_path_selector.path.set(dcs_path_selector.path.get())
            self.dcs_savegames_path_selector.path.set(dcs_savegames_path_selector.path.get())
            self.load_profiles()
            self.popup.destroy()

        def back_on_top():
            if self.popup is not None and self.popup.winfo_exists():
                if not dcs_savegames_path_selector.dialog_open and not dcs_path_selector.dialog_open:
                    self.popup.lift()
                self.popup.after(100, back_on_top)

        if self.popup is None or not self.popup.winfo_exists():
            self.popup = customtkinter.CTkToplevel(self)
            self.popup.title(f"Configure DCS Paths")

            label = customtkinter.CTkLabel(self.popup,
                                           text="Your DCS profiles config is not up to date! Please specify paths and reload!")
            label.grid(row=0, column=0, columnspan=2, sticky="ew")

            dcs_path_selector = PathSelector(self.popup, path=find_dcs_install_path(), title="DCS path")
            dcs_path_selector.grid(row=1, column=0, columnspan=2, sticky="ew")

            dcs_savegames_path_selector = PathSelector(self.popup, path=find_dcs_savegames_path(),
                                                       title="DCS Saved Games path")
            dcs_savegames_path_selector.grid(row=2, column=0, columnspan=2, sticky="ew")

            load_profiles_button = customtkinter.CTkButton(self.popup, text="Load data from DCS", command=load)
            load_profiles_button.grid(row=3, column=0, columnspan=2)

            back_on_top()

    def import_file(self):
        path = filedialog.askopenfilename(
            title='Select path',
            filetypes=self.filetypes,
            initialdir=self.dcs_savegames_path_selector.path.get(),
        )
        if self.diff.unsaved_changes:
            ans = messagebox.askokcancel(
                "Warning",
                "Your profile has unsaved changes! If you continue, those will be lost!",
                parent=self
            )
            if not ans:
                return
        self.diff.clear()
        self.diff.load_from_file(path)
        self.switch_category(self.category_combobox.get())

    def export_file(self):
        path = filedialog.asksaveasfilename(
            title='Select path',
            filetypes=self.filetypes,
            initialdir=self.dcs_savegames_path_selector.path.get(),
        )
        if not path.endswith(".diff.lua"):
            path += ".diff.lua"
        self.diff.store_to_file(path)

    def import_dcs(self):
        if self.diff.unsaved_changes:
            ans = messagebox.askokcancel(
                "Warning",
                "Your profile has unsaved changes! If you continue, those will be lost!",
                parent=self
            )
            if not ans:
                return
        aircraftname = self.aircraft_combobox.get()
        path = os.path.join(
            self.dcs_savegames_path_selector.path.get(),
            "Config",
            "Input",
            self.dpm.profiles[aircraftname]["aircraftname"],
            "Joystick"
        )
        logging.debug(f"looking for input profile in {path}")
        for filename in os.listdir(path):
            if self.selected_device.instance_guid.lower() in filename.lower():
                self.diff.clear()
                self.diff.load_from_file(os.path.join(path, filename))
                self.switch_category(self.category_combobox.get())
                return
        logging.warning(f"no input profile found for \"{self.selected_device}\" and \"{aircraftname}\"")

    def export_dcs(self):
        aircraftname = self.aircraft_combobox.get()
        path = os.path.join(
            self.dcs_savegames_path_selector.path.get(),
            "Config",
            "Input",
            self.dpm.profiles[aircraftname]["aircraftname"],
            "Joystick"
        )
        if self.dpm.check_if_dcs_is_running():
            messagebox.showwarning(
                title="DCS appears to be running!",
                message=f"You must restart DCS for changes to take effect!",
            )
        for filename in os.listdir(path):
            if self.selected_device.instance_guid.lower() in filename.lower():
                self.diff.store_to_file(os.path.join(path, filename))
                return
        # if there is no valid file there, create one
        filename = str(self.selected_device)
        self.diff.store_to_file(os.path.join(path, filename))

    def import_switchology(self):
        if not isinstance(self.selected_device, SwitchologyDevice):
            logging.error(f"Selected device \"{self.selected_device}\" is not a Switchology Device!")
            return
        path = filedialog.askopenfilename(
            title='Select path',
            filetypes=[("Switchology profile", ".swpf")],
        )
        with open(path, "r") as f:
            loaddict = json.load(f)
        if loaddict.get("build_id", "") != self.selected_device.build_id:
            logging.error(f"Selected device's build id \"{self.selected_device.build_id}\" does not match the profile's build id \"{loaddict.get('build_id', '')}\"")
            return
        dcsdiff = loaddict.get("DCSdiff", None)
        if dcsdiff is None:
            logging.error(f"The file does not contain a DCS profile!")
            return
        if self.diff.unsaved_changes:
            ans = messagebox.askokcancel(
                "Warning",
                "Your profile has unsaved changes! If you continue, those will be lost!",
                parent=self
            )
            if not ans:
                return
        self.diff.clear()
        self.diff.from_dict(dcsdiff)
        self.switch_category(self.category_combobox.get())
        logging.info(f"Switchology profile loaded from \"{path}\"")

    def export_switchology(self):
        if not isinstance(self.selected_device, SwitchologyDevice):
            logging.error(f"Selected device \"{self.selected_device}\" is not a Switchology Device!")
            return
        path = filedialog.asksaveasfilename(
            title='Select path',
            filetypes=[("Switchology profile", ".swpf")],
        )
        if not path.endswith(".swpf"):
            path += ".swpf"
        storedict = {
            "build_id": self.selected_device.build_id,
            "DCSdiff": self.diff.to_dict()
        }
        with open(path, "w") as f:
            json.dump(storedict, f, indent=4)
        logging.info(f"Switchology profile stored to \"{path}\"")

    def load_profiles(self):
        self.dpm.set_dcs_path(self.dcs_path_selector.path.get())
        self.dpm.set_dcs_savegames_path(self.dcs_savegames_path_selector.path.get())
        self.dpm.scan_for_profiles()
        self.dpm.store_profiles(appdata_path)
        self.update_aircraftlist()

    def update_aircraftlist(self):
        aircraftlist = sorted(list(self.dpm.get_aircrafts()))
        self.aircraft_combobox.configure(
            values=aircraftlist,
            state="readonly"
        )
        self.aircraft_combobox.set(aircraftlist[0])
        self.aircraft_combobox.update()
        self.switch_aircraft(aircraftlist[0])

    def switch_aircraft(self, choice):
        if self.last_aircraft_choice and choice != self.last_aircraft_choice and self.diff.unsaved_changes:
            ans = messagebox.askokcancel(
                "Warning",
                "Your profile has unsaved changes! If you continue, those will be lost!",
                parent=self
            )
            if not ans:
                self.aircraft_combobox.set(self.last_aircraft_choice)
                self.aircraft_combobox.update()
                return
        self.diff.clear(reset_unsaved_changes=True)
        self.last_aircraft_choice = choice
        categorylist = sorted(list(self.dpm.get_categories_for_aircraft(choice)))
        self.category_combobox.configure(
            values=categorylist,
            state="readonly"
        )
        self.category_combobox.set(categorylist[0])
        self.category_combobox.update()
        self.switch_category(categorylist[0])

    def switch_category(self, choice):
        commandlist = self.dpm.get_commands_for_aircraft_and_category(
            aircraft=self.aircraft_combobox.get(),
            category=choice
        )
        for child in self.bindings_frame.winfo_children():
            child.destroy()
        for i, command in enumerate(sorted(commandlist, key=lambda c: c.name)):
            label = customtkinter.CTkLabel(self.bindings_frame, text=command.name, wraplength=360, justify='left')
            label.grid(row=i, column=0, sticky="w")
            typelabel = customtkinter.CTkLabel(self.bindings_frame,text=command.type().replace("Command", ""))
            typelabel.grid(row=i, column=1, sticky="w")
            bindings = customtkinter.CTkLabel(
                self.bindings_frame,
                text="\n".join(self.diff.get_key_for_command(command)),
                width=100
            )
            bindings.grid(row=i, column=2)
            self.bindings_frame.grid_columnconfigure(0, weight=1)
            button = customtkinter.CTkButton(self.bindings_frame, text="Edit", width=20,
                                             command=lambda x=command: self.show_binding_popup(x))
            button.grid(row=i, column=3)

    def show_binding_popup(self, command):

        def clear():
            bindings.clear()
            update_text()

        def close():
            self.selected_device.unsubscribe("all", func)
            self.popup.destroy()

        def done():
            self.diff.clear_command(command)
            for key in bindings:
                self.diff.add_diff(command, key)
            self.switch_category(self.category_combobox.get())
            close()

        def button_pressed(device, control, value):
            if "Key" in command.type() and not isinstance(control, Button):
                return
            if not value:
                return
            if self.popup is None or not self.popup.winfo_exists():
                return
            bindings.add(control.raw_name)
            update_text()

        def update_text():
            text.configure(state="normal")
            text.delete("0.0", "end")
            text.insert("end", f"; ".join(list(bindings)))
            text.update()
            text.configure(state="disabled")

        aircraft = self.aircraft_combobox.get()
        category = self.category_combobox.get()

        if self.popup is None or not self.popup.winfo_exists():
            self.popup = customtkinter.CTkToplevel(self)
            self.popup.title(f"{aircraft} - {category} - {command.name}")
            self.popup.after(100,
                             self.popup.lift)  # Workaround for bug where main window takes focus from https://github.com/kelltom/OS-Bot-COLOR/blob/3c61fbec9ae8fffd15f2ce66158e176cff2be045/src/OSBC.py#L227C41-L228C1

            bindings = set(self.diff.get_key_for_command(command))

            label = customtkinter.CTkLabel(self.popup, text="Push some button to bind")
            label.grid(row=0, column=0, columnspan=3, padx=5, pady=5)

            text = customtkinter.CTkTextbox(self.popup, state="disabled")
            text.grid(row=1, column=0, columnspan=3, sticky="ew", padx=5, pady=5)

            clear_button = customtkinter.CTkButton(self.popup, text="Clear", command=clear)
            clear_button.grid(row=2, column=0, padx=5, pady=5)
            cancel_button = customtkinter.CTkButton(self.popup, text="Cancel", command=close)
            cancel_button.grid(row=2, column=1, padx=5, pady=5)
            done_button = customtkinter.CTkButton(self.popup, text="Done", command=done)
            done_button.grid(row=2, column=2, padx=5, pady=5)

            update_text()
            if self.selected_device:
                func = lambda ctrl, value, device=self.selected_device: button_pressed(device, ctrl, value)
                self.selected_device.add_subscriber("all", func)


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
        for device in gui.devices:
            device.dispatch_events()
        gui.after(100, dispatch_selected_device_events)

    gui.after(100, dispatch_selected_device_events)
    logging.info("Program start")
    gui.mainloop()


if __name__ == "__main__":
    main()
