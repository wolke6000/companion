import json
import logging
import typing

import psutil
from pyglet.input import AbsoluteAxis, Button, Control
from slpp import slpp
import lupa.lua51 as lupa
from lupa.lua51 import LuaRuntime
import os
import winreg
import customtkinter
from tkinter import filedialog, messagebox

from PullDownButton import PullDownButton

import Switchology
from Device import Device, ControlIndicator
from gui import GUI, appdata_path, PathSelector, get_devices
from icon import icon

pad = 3

def dcsify_device_name(device: Device):
    return device.instance_name + " {" + device.instance_guid[:12].upper() + device.instance_guid[12:].lower() + "}"

def find_dcs_savegames_path():
    for dcs_dir in ["DCS", "DCS.openbeta"]:
        path = os.path.join(os.path.expanduser("~"), "Saved Games", dcs_dir)
        if os.path.exists(path):
            break
    logging.debug(f"dcs savegames path located at \"{path}\"")
    return path


def find_dcs_install_path():
    return r"Z:\DCS World OpenBeta"
    hkey = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall")
    index = 0
    installdir = None
    while True:
        try:
            key_name = winreg.EnumKey(hkey, index)
        except OSError as e:
            break
        hsubkey = winreg.OpenKey(hkey, key_name)
        try:
            url = winreg.QueryValueEx(hsubkey, "URLInfoAbout")[0]
            if "www.digitalcombatsimulator.com" in url:
                installdir = winreg.QueryValueEx(hsubkey, "InstallLocation")[0]
        except OSError as e:
            pass
        winreg.CloseKey(hsubkey)
        index += 1
    winreg.CloseKey(hkey)
    logging.debug(f"dcs install path located at \"{installdir}\"")
    return installdir


luatabletype = type(lupa.LuaRuntime().table())

axes = ["X", "Y", "Z", "RX", "RY", "RZ"]

def change_control_names_dcs_to_pyglet(value):
    if not isinstance(value, str):
        return value
    if "JOY_BTN" in value:
        try:
            return "Button " + str(int(value.replace("JOY_BTN", "")) - 1)
        except ValueError:
            return value
    else:
        for axis in axes:
            if value == f"JOY_{axis}":
                value = f"{axis} Axis"
                return value
    return value


def change_control_names_pyglet_to_dcs(value):
    if not isinstance(value, str):
        return value
    if "Button" in value:
        return "JOY_BTN" + str(int(value.replace("Button ", "")) + 1)
    else:
        for axis in axes:
            if value == f"{axis} Axis":
                value = f"JOY_{axis}"
                return value
    return value

def lua_to_py(luatable):
    if not isinstance(luatable, luatabletype):
        return luatable
    ds = dict(luatable)
    if all(isinstance(x, int) for x in ds.keys()):
        ls = list()
        for d in ds.values():
            ls.append(lua_to_py(d))
        return ls
    else:
        dso = dict()
        extra_categories = list()  # workaround for commands with two categories
        for dkey in ds.keys():
            if isinstance(dkey, int):
                extra_categories.append(ds[str(dkey)])
            else:
                dso[dkey] = change_control_names_dcs_to_pyglet(lua_to_py(ds[dkey]))
        if len(extra_categories) > 0:
            extra_categories.append(dso["category"])
            dso["category"] = extra_categories
        return dso


class DCSProfileManager:

    def _run_in_dcspath(func):
        def wrapper(self, *args, **kwargs):
            cwd = os.getcwd()
            os.chdir(self.dcspath)
            result = func(self, *args, **kwargs)
            os.chdir(cwd)
            return result
        return wrapper

    def __init__(self, dcs_savegames_path, dcs_path):
        self._lua = LuaRuntime()
        self.dofile = self._lua.eval("dofile")
        self.loadfile = self._lua.eval("loadfile")
        self.require = self._lua.eval("require")
        self.dcspath = dcs_path
        self.dcs_savegames_path = dcs_savegames_path

        my_utils = self.loadfile('my_utils.lua')

        my_utils()

        self._lua.execute(
            "local f, err = loadfile('envTable.lua')\n"
            "envTable = f()"
        )

        self.reload_profiles()

    @_run_in_dcspath
    def reload_profiles(self):
        self._populate_devices()
        self._populate_input_profiles()

        self._lua.execute("lfs = require('lfs')")
        self._lua.execute("InputData = require('Input.Data')")
        self._lua.execute("ProfileDatabase = require('Input.ProfileDatabase')")
        self._lua.execute("DCS = require('DCS')")
        self.unload_profiles()
        user_config_path = str(os.path.join(self.dcs_savegames_path, 'Config', 'Input')).replace("\\", "/")
        self._lua.execute(f"InputData.initialize('{user_config_path}/', './Config/Input/')")

        self._lua.execute(f"profileInfos = ProfileDatabase.createDefaultProfilesSet('./Config/Input/', DCS.getInputProfiles())")
        self._lua.execute(
            "for i, profileInfo in ipairs(profileInfos) do\n"
            "   InputData.createProfile(profileInfo\n)"
            "end"
        )

    def _populate_devices(self):
        # populate devices list in lua
        for device in get_devices():
            device_name = dcsify_device_name(device)
            self._lua.execute(f"table.insert(devices, '{device_name}')")

    def _populate_input_profiles(self):
        profiles = {
            "a-10a": {
                "is_unit": True,
                "path": './Mods/aircraft/A-10A/Input/a-10a'
            }
        }
        for profile_name, profile in profiles.items():
            self._lua.execute(f"_InputProfiles['{profile_name}'] = {slpp.encode(profile)}")

    def _eval_to_py(self, command: str):
        _lua = self._lua.eval(command)
        _py = lua_to_py(_lua)
        return _py

    @_run_in_dcspath
    def unload_profiles(self):
        self._lua.execute(f"InputData.unloadProfiles()")

    @_run_in_dcspath
    def load_device_profile(self, profile_name: str, device_name: str, file_name: str):
        self._lua.execute(f"InputData.loadDeviceProfile('{profile_name}', '{device_name}', '{file_name}')")

    @_run_in_dcspath
    def get_device_profile(self, profile_name: str, device_name: str):
        return self._eval_to_py(f"InputData.getDeviceProfile('{profile_name}', '{device_name}')")

    @_run_in_dcspath
    def command_combos(self, profile_name: str, command_hash: str, device_name: str):
        return self._eval_to_py(f"InputData.commandCombos('{profile_name}', '{command_hash}', '{device_name}')")

    @_run_in_dcspath
    def get_profile_key_commands(self, profile_name: str, category: str | None = None):
        if category:
            return self._eval_to_py(f"InputData.getProfileKeyCommands('{profile_name}', '{category}')")
        else:
            return self._eval_to_py(f"InputData.getProfileKeyCommands('{profile_name}')")

    @_run_in_dcspath
    def get_profile_axis_commands(self, profile_name: str):
        return self._eval_to_py(f"InputData.getProfileAxisCommands('{profile_name}')")

    @_run_in_dcspath
    def get_profile_category_names(self, profile_name: str):
        return self._eval_to_py(f"InputData.getProfileCategoryNames('{profile_name}')")

    @_run_in_dcspath
    def save_device_profile(self, profile_name: str, device_name: str, file_name: str):
        self._lua.execute(f"InputData.saveDeviceProfile('{profile_name}', '{device_name}', '{file_name}')")

    @_run_in_dcspath
    def get_profile_modifiers(self, profile_name: str):
        return self._eval_to_py(f"InputData.getProfileModifiers('{profile_name}')")

    @_run_in_dcspath
    def get_profile_names(self):
        return self._eval_to_py(f"InputData.getProfileNames()")

    @_run_in_dcspath
    def get_profile_name_by_unit_name(self, unit_name: str):
        return self._eval_to_py(f"InputData.getProfileNameByUnitName('{unit_name}')")

    @_run_in_dcspath
    def get_profile_unit_name(self, profile_name: str):
        return self._eval_to_py(f"InputData.getProfileUnitName('{profile_name}')")

    @_run_in_dcspath
    def save_changes(self):
        self._lua.execute(f"InputData.saveChanges()")

    @_run_in_dcspath
    def undo_changes(self):
        self._lua.execute(f"InputData.undoChanges()")

    @_run_in_dcspath
    def clear_profile(self, profile_name: str, device_names: list[str]):
        device_names_lua = slpp.encode(device_names)
        self._lua.execute(f"InputData.clearProfile('{profile_name}', {device_names_lua})")

    @_run_in_dcspath
    def add_combo_to_key_command(self, profile_name: str, command_hash: str, device_name: str, combo):
        self._lua.execute(f"InputData.addComboToKeyCommand('{profile_name}', '{command_hash}', '{device_name}', {combo})")

    @_run_in_dcspath
    def add_combo_to_axis_command(self, profile_name: str, command_hash: str, device_name: str, combo):
        self._lua.execute(f"InputData.addComboToAxisCommand('{profile_name}', '{command_hash}', '{device_name}', {combo})")

    @_run_in_dcspath
    def remove_key_command_combos(self, profile_name: str, command_hash: str, device_name: str):
        self._lua.execute(f"InputData.removeKeyCommandCombos('{profile_name}', '{command_hash}', '{device_name}')")

    @_run_in_dcspath
    def remove_axis_command_combos(self, profile_name: str, command_hash: str, device_name: str):
        self._lua.execute(f"InputData.removeAxisCommandCombos('{profile_name}', '{command_hash}', '{device_name}')")

    def import_swpf(self, device: Device, path):
        pass

    def export_swpf(self, device: Device, path, profile_name=""):
        pass



class BindingsFrame(customtkinter.CTkFrame):
    selected_device: Device | None

    def __init__(self, master: GUI, **kwargs):
        super().__init__(master, **kwargs)

        self.popup = None
        self.selected_device = None
        self.last_aircraft_choice = None
        self.selected_category = None
        self.command_filter_str = ""
        self.controls = dict()
        self.open_popup_with_control = False
        self.dpm = DCSProfileManager(find_dcs_savegames_path(), find_dcs_install_path())
        self.profile_name_variable = customtkinter.StringVar(value="unnamed profile")
        self.controls_frame = None

        self.activated = False
        filepath = os.path.join(appdata_path, "plugins.json")
        if not os.path.isfile(filepath):
            logging.warning(f"could not find dcs config in \"{filepath}\"")
        else:
            try:
                with open(filepath, "r") as f:
                    config = json.load(f)
                self.activated = config.get("dcs_activated", False)
            except json.decoder.JSONDecodeError:
                logging.warning(f"could not read dcs config in \"{filepath}\"")

        # profilename = 'A-10A'
        # devicename = 'Switchology MCP {C65522F0-8C08-11ef-8003-444553540000}'
        # filename = "C:/Users/wolfg/Saved Games/DCS.openbeta/Config/Input/a-10a/joystick/Switchology MCP {C65522F0-8C08-11ef-8003-444553540000}.diff.lua"
        # self.dpm.load_device_profile(profilename, devicename, filename)

        self.create_widgets()

    def create_widgets(self):
        for child in self.winfo_children():
            child.destroy()
        if not self.activated:
            customtkinter.CTkLabel(
                master=self,
                text=f"DCS plugin is not activated.\nGo to settings to activate!"
            ).grid()
            customtkinter.CTkButton(
                master=self,
                text="",
                command=self.show_settings_popup,
                width=30,
                image=icon("wrench")
            ).grid()
            return

        title_row = customtkinter.CTkFrame(master=self)
        title_row.grid(row=0)
        title_label = customtkinter.CTkLabel(master=title_row, text="DCS Input Profiles")
        title_label.grid(row=0, column=0, padx=pad, pady=pad)
        settings_button = customtkinter.CTkButton(
            master=title_row,
            text="",
            command=self.show_settings_popup,
            width=30,
            image=icon("wrench")
        )
        settings_button.grid(row=0, column=1, padx=pad, pady=pad)

        top_button_row = customtkinter.CTkFrame(master=self)
        top_button_row.grid(row=1, sticky="ew")
        import_button = PullDownButton(
            master=top_button_row,
            text="Load...",
            values={
                "...from *.swpf-file": self.load_from_swpf,
                "...from DCS": self.load_from_dcs,
            },
            image = icon("import"),
        )
        import_button.grid(row=0, column=0, padx=pad, pady=pad)
        clear_button = customtkinter.CTkButton(
            master=top_button_row,
            text="Clear",
            command=self.clear_diffs,
            fg_color=customtkinter.ThemeManager.theme["CTkSegmentedButton"]["unselected_color"],
            image=icon("clear"),
        )
        clear_button.grid(row=0, column=1, padx=pad, pady=pad)
        profile_name_entry = customtkinter.CTkEntry(
            master=top_button_row,
            textvariable=self.profile_name_variable,
            width=300
        )
        profile_name_entry.grid(row=0, column=2, sticky="ew", padx=pad, pady=pad)

        self.controls_frame = customtkinter.CTkScrollableFrame(self)
        self.controls_frame.grid(row=2, sticky="nsew", padx=pad, pady=pad)
        self.controls_frame.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        bottom_button_row = customtkinter.CTkFrame(master=self)
        bottom_button_row.grid_columnconfigure((0, 1), weight=1)
        bottom_button_row.grid(row=3, sticky="ew")
        export_button = PullDownButton(
            master=bottom_button_row,
            text="Share...",
            values={
                "...to *.swpf-file": self.share_to_swpf
            },
            fg_color=customtkinter.ThemeManager.theme["CTkSegmentedButton"]["unselected_color"],
            image=icon("share"),
        )
        export_button.grid(row=0, column=0, padx=pad, pady=pad, sticky="w")
        save_to_savegames_button = customtkinter.CTkButton(
            master=bottom_button_row,
            text="Push to DCS",
            command=self.push_to_dcs,
            image=icon("rocket")
        )
        save_to_savegames_button.grid(row=0, column=1, padx=pad, pady=pad, sticky="e")
        # if not profiles_found:
        #     self.after(100, self.show_settings_popup)
        # elif self.dpm.dcs_config_version != self.dpm.get_dcs_version():
        #     self.load_profiles()
        self.refresh()

    def refresh(self):
        if not self.activated:
            return
        # if not self.dpm.dcs_imported:
        #     self.dpm.import_dcs()
        #     bbs = self.dpm.find_broken_bindings()
        #     if bbs:
        #         self.show_broken_bindings_popup(bbs)
        self.populate_controls_list()

    def show_keybind_popup(self, control):

        def close():
            self.command_filter_str = command_filter_var.get()
            self.last_aircraft_choice = aircraft_selection.get()
            if not issubclass(type(control), AbsoluteAxis):
                self.selected_category = category_selection.get()
            command_filter_var.trace_remove("write", cb_name)
            self.popup.destroy()
            self.popup = None

        def bind(command, key):
            profile_name = aircraft_selection.get()
            command_hash = command["hash"]
            device_name = dcsify_device_name(self.selected_device)
            combo = {"key": change_control_names_pyglet_to_dcs(key)}
            self.dpm.add_combo_to_key_command(profile_name, command_hash, device_name, slpp.encode(combo))
            self.populate_controls_list()
            close()

        def switch_aircraft(choice):
            self.last_aircraft_choice = choice
            if not issubclass(type(control), AbsoluteAxis):
                configlist = sorted(list(self.dpm.get_profile_category_names(choice)))
                category_selection.configure(
                    values=[all_categories_str] + configlist,
                )
                switch_category(all_categories_str)
            else:
                switch_category(axes_category_str)

        def switch_category(choice=None):
            ac = aircraft_selection.get()
            if not choice:
                choice = self.selected_category
            commandlist = list()
            if choice == all_categories_str:
                commandlist += self.dpm.get_profile_key_commands(ac)
                self.selected_category = choice
            elif choice == axes_category_str:
                commandlist = self.dpm.get_profile_axis_commands(ac)
            else:
                commandlist = self.dpm.get_profile_key_commands(ac, choice)
                self.selected_category = choice
            for child in bindings_frame.winfo_children():
                child.destroy()
            i = 0
            for command in sorted(commandlist, key=lambda c: c["name"]):
                if command_filter_var.get().lower() not in command["name"].lower():
                    continue
                btn = customtkinter.CTkButton(
                    master=bindings_frame,
                    text=command["name"],
                    command=lambda cmd=command, key=control.raw_name: bind(cmd, key)
                )
                btn.grid(row=i, column=0, sticky="ew", padx=pad, pady=pad)
                i += 1
            bindings_frame._parent_canvas.yview_moveto(0.0)

        def filter_commands(a, b, c):
            switch_category()

        all_categories_str = "all but axes"
        axes_category_str = "axis commands"
        if self.popup is None or not self.popup.winfo_exists():
            self.popup = customtkinter.CTkToplevel(self)
        self.popup.geometry(f"+{self.winfo_rootx() - 50}+{self.winfo_rooty() + 200}")
        self.popup.title(f"Configure command for {control.raw_name}")
        self.popup.after(100, self.popup.lift)
        self.popup.focus()
        self.popup.grid_columnconfigure(index=(0,1,2), weight=1)
        self.popup.grid_rowconfigure(index=2, weight=1)
        aircraft_label = customtkinter.CTkLabel(
            master=self.popup,
            text="Aircraft"
        )
        aircraft_label.grid(row=0, column=0)
        if self.last_aircraft_choice is None:
            self.last_aircraft_choice = sorted(list(self.dpm.get_profile_names()))[0]
        aircraft_selection = customtkinter.CTkOptionMenu(
            master=self.popup,
            values=sorted(list(self.dpm.get_profile_names())),
            command=switch_aircraft,
        )
        aircraft_selection.grid(row=1, column=0, sticky="ew", padx=pad, pady=pad)
        aircraft_selection.set(self.last_aircraft_choice)
        if self.selected_category is None:
            self.selected_category = all_categories_str
        if not issubclass(type(control), AbsoluteAxis):
            category_label = customtkinter.CTkLabel(
                master=self.popup,
                text="Category"
            )
            category_label.grid(row=0, column=1)
            category_selection = customtkinter.CTkOptionMenu(
                master=self.popup,
                values=[all_categories_str] + sorted(list(self.dpm.get_profile_category_names(self.last_aircraft_choice))),
                command=switch_category,
            )
            category_selection.set(self.selected_category)
            category_selection.grid(row=1, column=1, sticky="ew", padx=pad, pady=pad)
        filter_label = customtkinter.CTkLabel(
            master=self.popup,
            text="Search..."
        )
        filter_label.grid(row=0, column=2)
        command_filter_var = customtkinter.StringVar(value=self.command_filter_str)
        cb_name = command_filter_var.trace_add("write", filter_commands)
        command_filter_entry = customtkinter.CTkEntry(
            master=self.popup,
            textvariable=command_filter_var,
        )
        command_filter_entry.grid(row=1, column=2, sticky="ew", padx=pad, pady=pad)
        bindings_frame = customtkinter.CTkScrollableFrame(self.popup, width=350)
        bindings_frame.columnconfigure(index=0, weight=1)
        bindings_frame.grid(row=2, column=0, columnspan=3, sticky="nsew", padx=pad, pady=pad)
        if issubclass(type(control), AbsoluteAxis):
            switch_category(axes_category_str)
        else:
            switch_category(self.selected_category)

    def show_settings_popup(self):
        def apply():
            self.popup.destroy()
            self.popup = None
            new_dcs_path = dcs_path_selector.path.get()
            new_dcs_savegames_path = dcs_savegames_path_selector.path.get()
            if activated != self.activated:
                filepath = os.path.join(appdata_path, "plugins.json")
                plugins_dict = dict()
                if not os.path.isfile(filepath):
                    logging.warning(f"could not find dcs config in \"{filepath}\"")
                else:
                    try:
                        with open(filepath, "r") as f:
                            plugins_dict = json.load(f)
                    except json.decoder.JSONDecodeError:
                        logging.warning(f"could not read dcs config in \"{filepath}\"")
                plugins_dict["dcs_activated"] = bool(self.activated)
                with open(filepath, "w") as f:
                    json.dump(plugins_dict, f, indent=4)
            # if self.activated:
            #     self.dpm.set_dcs_path(new_dcs_path)
            #     self.dpm.set_dcs_savegames_path(new_dcs_savegames_path)
            #     if old_dcs_path != new_dcs_path or old_dcs_savegames_path != new_dcs_savegames_path or len(self.dpm.profiles) == 0:
            #         self.dpm.load_profiles(appdata_path)
            self.create_widgets()
            # self.dpm.import_dcs()
            self.populate_controls_list()

        def back_on_top():
            if self.popup is not None and self.popup.winfo_exists():
                if not dcs_savegames_path_selector.dialog_open and not dcs_path_selector.dialog_open:
                    self.popup.lift()
                self.popup.after(100, back_on_top)

        def open_with_controls_switch_callback():
            self.open_popup_with_control = open_popup_with_control_switch.get()

        def activate_switch_callback():
            self.activated = activate_switch.get()
            de_activate()

        def de_activate():
            if self.activated:
                open_popup_with_control_switch.configure(state="normal")
                dcs_path_selector.configure(state="normal")
                dcs_savegames_path_selector.configure(state="normal")
            else:
                open_popup_with_control_switch.configure(state="disabled")
                dcs_path_selector.configure(state="disabled")
                dcs_savegames_path_selector.configure(state="disabled")

        if self.popup is None or not self.popup.winfo_exists():

            self.popup = customtkinter.CTkToplevel(self)
            self.popup.title(f"Configure DCS Paths")
            activated = self.activated

            activate_switch = customtkinter.CTkSwitch(
                master=self.popup,
                text="Activate DCS profile plugin",
                command=activate_switch_callback,

            )
            if self.activated:
                activate_switch.select()
            else:
                activate_switch.deselect()
            activate_switch.grid(sticky="w")

            dcs_path_selector = PathSelector(self.popup, path=find_dcs_install_path(), title="DCS path")
            old_dcs_path = dcs_path_selector.path.get()
            dcs_path_selector.grid(sticky="ew")

            dcs_savegames_path_selector = PathSelector(self.popup, path=find_dcs_savegames_path(),
                                                       title="DCS Saved Games path")
            old_dcs_savegames_path = dcs_savegames_path_selector.path.get()
            dcs_savegames_path_selector.grid(sticky="ew")

            open_popup_with_control_switch = customtkinter.CTkSwitch(
                master=self.popup,
                text="Open bindings popup when pressing device buttons",
                command=open_with_controls_switch_callback,
            )
            if self.open_popup_with_control:
                open_popup_with_control_switch.select()
            else:
                open_popup_with_control_switch.deselect()
            open_popup_with_control_switch.grid(sticky="w")

            save_settings_button = customtkinter.CTkButton(self.popup, text="Save settings", command=apply)
            save_settings_button.grid()

            de_activate()

            back_on_top()

    def populate_controls_list(self):
        def destroy_children(widget):
            for child in widget.winfo_children():
                if issubclass(type(child), ControlIndicator):
                    self.selected_device.unsubscribe(fun=child.update_value)
                destroy_children(child)
                child.destroy()

        if not self.activated:
            return
        destroy_children(self.controls_frame)
        if self.selected_device is None:
            return

        for i, control in enumerate(self.selected_device.controls):
            self.controls[control] = None
            command_name_list = list()
            for profile_name in self.dpm.get_profile_names():
                # device_profile = self.dpm.get_device_profile(profile_name, dcsify_device_name(self.selected_device))
                if issubclass(type(control), AbsoluteAxis):
                    commands = self.dpm.get_profile_axis_commands(profile_name)
                else:
                    commands = self.dpm.get_profile_key_commands(profile_name)
                for command in commands:
                    for device_name, combo in command["combos"].items():
                        if device_name.lower() != dcsify_device_name(self.selected_device).lower():
                            continue
                        if len(combo) == 0:
                            continue
                        for c in combo:
                            if c["key"] == control.raw_name:
                                command_name_list.append((profile_name, command))

            controls_line_frame = customtkinter.CTkFrame(master=self.controls_frame)
            controls_line_frame.grid_columnconfigure(1, weight=1)
            controls_line_frame.grid(row=i, column=0, sticky="ew", pady=3)
            indicator = ControlIndicator(controls_line_frame, control, width=100)
            indicator.grid(row=0, column=0, sticky="w", padx=pad, pady=pad)
            self.selected_device.add_subscriber(control, indicator.update_value)
            if self.open_popup_with_control:
                self.selected_device.add_subscriber(control, self.open_popup_on_control)
            button = customtkinter.CTkButton(
                master=controls_line_frame,
                text="",
                command=lambda c=control: self.show_keybind_popup(c),
                width=30,
                image=icon("add", (15, 15))
            )
            button.grid(row=0, column=2, sticky="e", padx=pad, pady=pad)
            for j, (aircraft, command) in enumerate(command_name_list):
                binding = BindingButton(
                    master=controls_line_frame,
                    text=f"{aircraft.strip()}: {command['name'].strip()}",
                    command=lambda a=aircraft, c=command, k=control: self.remove_binding(a, c, k),
                )
                binding.bind('<Enter>', binding.configure, )
                binding.grid(row=j, column=1, sticky="w")

    def remove_binding(self, profile_name, command, control):
        ans = messagebox.askyesnocancel(
            title=f"Remove {command['name']}",
            message=f"Do you want to remove \"{command['name']}\" from \"{control.raw_name}\" for \"{profile_name}\"?"
        )
        if not ans:
            return
        if issubclass(type(control), AbsoluteAxis):
            self.dpm.remove_axis_command_combos(profile_name, command["hash"], dcsify_device_name(self.selected_device))
        else:
            self.dpm.remove_key_command_combos(profile_name, command["hash"], dcsify_device_name(self.selected_device))
        self.populate_controls_list()

    def clear_diffs(self):
        self.profile_name_variable.set("unnamed profile")
        for profile_name in self.dpm.get_profile_names():
            self.dpm.clear_profile(profile_name, [dcsify_device_name(self.selected_device)])
        self.populate_controls_list()

    def push_to_dcs(self):
        self.dpm.save_changes()

    def load_from_dcs(self):
        self.dpm.reload_profiles()
        self.populate_controls_list()

    def load_from_swpf(self):
        return
        # if any(diff.unsaved_changes for diff in self.dpm.get_diffs_for_device(self.selected_device).values()):
        #     ans = messagebox.askokcancel(
        #         "Warning",
        #         "Your profile has unsaved changes! If you continue, those will be lost!",
        #         parent=self
        #     )
        #     if not ans:
        #         return
        # path = filedialog.askopenfilename(
        #     title='Select path',
        #     filetypes=[("Switchology profile", ".swpf")],
        # )
        # if not os.path.isfile(path):
        #     return
        # self.dpm.import_swpf(self.selected_device, path)
        # self.populate_controls_list()

    def share_to_swpf(self):
        return
        # path = filedialog.asksaveasfilename(
        #     title='Select path',
        #     filetypes=[("Switchology profile", ".swpf")],
        # )
        # if not path.endswith(".swpf"):
        #     path += ".swpf"
        # self.dpm.export_swpf(self.selected_device, path)

    def open_popup_on_control(self, value, control):
        if not self.open_popup_with_control:
            return
        if isinstance(control, Button):
            self.show_keybind_popup(control)

    def show_broken_bindings_popup(self, broken_bindings):

        def automatch():
            messagebox.showwarning(title="not implemented!", message="not implemented!")

        def repair():
            for device in selects.keys():
                for aircraft, select in selects[device].items():
                    for diffs in broken_bindings[device.serial_number.lower()][aircraft]:
                        if os.path.basename(diffs.origin_path) in select.get():
                            new_path = os.path.join(os.path.dirname(diffs.origin_path), str(device))
                            if hasattr(device, "build_id"):
                                diffs.embedded_dict["build_id"] = device.build_id
                            diffs.store_to_file(new_path)
            self.popup.destroy()
            self.popup = None
            self.refresh()

        if self.popup is None or not self.popup.winfo_exists():
            self.popup = customtkinter.CTkToplevel(self)
        self.popup.geometry(f"+{self.winfo_rootx() - 50}+{self.winfo_rooty() + 200}")
        self.popup.title(f"Fix Broken Device Bindings")
        self.popup.after(100, self.popup.lift)
        self.popup.focus()
        self.popup.columnconfigure((0, 1), weight=1)

        description = customtkinter.CTkTextbox(
            master=self.popup,
            height=60,
            wrap="word",
        )
        description.insert("0.0", "Some of your DCS input binding files refer to devices that are no longer detected. "
                 "This can happen if GUIDs change. Select the correct device to repair each binding.")
        description.configure(state="disabled")
        description.grid(row=0, column=0, sticky="ew", columnspan=2)
        scrollframe = customtkinter.CTkScrollableFrame(
            master=self.popup,
            width=600,
        )
        scrollframe.grid(row=1, column=0, sticky="nsew", columnspan=2)
        selects = dict()
        for i, device_serial in enumerate(broken_bindings.keys()):
            device = None
            for d in get_devices():
                if d.serial_number.lower() == device_serial.lower():
                    device = d
                    break
            if device is None:
                continue
            device_frame = customtkinter.CTkFrame(
                master=scrollframe
            )
            device_frame.grid(row=i+1, column=0, sticky="ew", padx=pad, pady=pad)
            device_frame.columnconfigure( 1, weight=1)
            device_description = f"{device.product_name}\nSerial: {device_serial}\nCurrent GUID: {device.instance_guid}"
            if issubclass(type(device), Switchology.SwitchologyDevice):
                device_description += f"\nBuild-ID: {device.build_id}"
            device_label = customtkinter.CTkLabel(
                master=device_frame,
                text=device_description,
                anchor="w",
                justify="left",
            )
            device_label.grid(row=0, column=0, columnspan=2, sticky="w")
            selects[device] = dict()
            for j, aircraft in enumerate(broken_bindings[device_serial].keys()):
                aircraft_label = customtkinter.CTkLabel(
                    master=device_frame,
                    text=aircraft,
                    anchor="w",
                    width=80,
                )
                aircraft_label.grid(row=j+1, column=0, sticky="w")
                values = list()
                for diffs in broken_bindings[device_serial][aircraft]:
                    diff_description = os.path.basename(diffs.origin_path)
                    if diffs.build_id is not None:
                        diff_description += "\n Build-ID: " + diffs.build_id
                    values.append(diff_description)
                selects[device][aircraft] = customtkinter.CTkOptionMenu(
                    master=device_frame,
                    values=values,
                    anchor="w",
                )
                selects[device][aircraft].grid(row=j+1, column=1, sticky="ew")
        auto_button = customtkinter.CTkButton(
            master=self.popup,
            text="Match automatically",
            fg_color=customtkinter.ThemeManager.theme["CTkSegmentedButton"]["unselected_color"],
            command=automatch,
        )
        auto_button.grid(row=2, column=0)
        repair_button = customtkinter.CTkButton(
            master=self.popup,
            text="Repair",
            command=repair,
        )
        repair_button.grid(row=2, column=1)


class BindingButton(customtkinter.CTkFrame):

    def __init__(self, master, **kwargs):
        text = kwargs.pop("text", "")
        command = kwargs.pop("command", None)
        super().__init__(
            master=master,
            bg_color=master._fg_color,  # noqa
            fg_color=master._fg_color,  # noqa
            **kwargs,
        )
        self._label = customtkinter.CTkLabel(
            master=self,
            text=text
        )
        self._label.grid(row=0, column=0, sticky="w")
        button_size = 16
        self._xbut = customtkinter.CTkButton(
            master=self,
            text="",
            bg_color=self._fg_color,
            fg_color=self._fg_color,
            hover_color="red",
            border_color=self._label._text_color,  # noqa
            command=command,
            height=button_size,
            width=button_size,
            # corner_radius=round(button_size/2),
            # border_width=1,
            border_spacing=0,
            font=(customtkinter.CTkFont(), 5),
            image=icon("remove", (12, 12))
        )
        self._xbut.grid(row=0, column=1, sticky="w", padx=3)


def main():
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(message)s',
    )

    dcspath = r"Z:\DCS World OpenBeta"
    dcssavegamespath = r"C:\Users\wolfg\Saved Games"

    profilename = 'A-10A'
    devicename = 'Switchology MCP {C65522F0-8C08-11ef-8003-444553540000}'
    filename = "C:/Users/wolfg/Saved Games/DCS.openbeta/Config/Input/a-10a/joystick/Switchology MCP {C65522F0-8C08-11ef-8003-444553540000}.diff.lua"

    did = DCSProfileManager(
        dcs_savegames_path=dcssavegamespath,
        dcs_path=dcspath,
    )
    did.load_device_profile(profilename, devicename, filename)
    profiles = did.get_device_profile(profilename, devicename)
    categories = did.get_profile_category_names(profilename)
    key_commmands = did.get_profile_key_commands(profilename)
    axis_commands = did.get_profile_axis_commands(profilename)
    # did.clear_profile(profilename, [devicename, devicename])

    did._lua.execute("for i, device in ipairs(Input.getDevices()) do print(device) end")

if __name__ == "__main__":
    main()
