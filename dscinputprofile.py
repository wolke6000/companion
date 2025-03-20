import json
import logging
import psutil
from slpp import SLPP
import lupa.lua51 as lupa
from lupa.lua51 import LuaRuntime
import os
import winreg
import customtkinter
from tkinter import filedialog, messagebox
from pyglet.input.base import Button, AbsoluteAxis

from Device import Device, ControlIndicator
from gui import GUI, appdata_path, PathSelector

pad = 3

lua = LuaRuntime()

dofile = lua.eval("dofile")
loadfile = lua.eval("loadfile")
require = lua.eval("require")

dofile('iCommands.lua')
my_utils = loadfile('my_utils.lua')


def find_dcs_savegames_path():
    path = os.path.join(os.path.expanduser("~"), "Saved Games", "DCS.openbeta")
    logging.debug(f"dcs savegames path located at \"{path}\"")
    return path


def find_dcs_install_path():
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


def load_keydiffs(filepath):
    with open(filepath, "r") as f:
        filecontents = "".join(f.readlines())

    t = filecontents.replace("local diff = {", "diff = {").strip()
    for t_old in ["return diff", "\n", "\t"]:
        t = t.replace(t_old, "")
    slpp = SLPP()
    b = slpp.decode("{" + t + "}")

    return b


luatabletype = type(lupa.LuaRuntime().table())


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
                extra_categories.append(ds[dkey])
            else:
                dso[dkey] = lua_to_py(ds[dkey])
        if len(extra_categories) > 0:
            extra_categories.append(dso["category"])
            dso["category"] = extra_categories
        return dso


def load_device_profile_from_file(filename, device_name, folder, keep_g_untouched, dcspath):
    cwd = os.getcwd()

    os.chdir(dcspath)

    my_utils()

    # load loadDeviceProfileFromFile() from Scripts/Input/Data.lua
    data_lua_content = ""
    with open(os.path.join(dcspath, "Scripts", "Input", "Data.lua"), "r", encoding="utf-8") as f:
        skip = True
        for line in f.readlines():
            if line.startswith("local function loadDeviceProfileFromFile"):
                skip = False
                line = line.replace("local function loadDeviceProfileFromFile", "loadDeviceProfileFromFile = function")
            if not skip:
                data_lua_content += line
                if line.startswith("end"):
                    break

    lua.execute(data_lua_content)
    fun = lua.eval("loadDeviceProfileFromFile")
    result, err = fun(filename, device_name, folder, keep_g_untouched)

    os.chdir(cwd)

    res = lua_to_py(result)

    return res


def parse_entry(filename):
    lua = LuaRuntime()
    with open(filename, "r", encoding='UTF-8') as f:
        file_lines = f.readlines()
    current_mod_path = os.path.dirname(filename).replace('\\', '/')

    # cut of the parts after the declare_plugin()-call
    in_declare_plugin = False
    bracket_depth = 0
    filecontents = ""
    for line in file_lines:
        filecontents += line
        if "declare_plugin" in line:
            in_declare_plugin = True
        if in_declare_plugin:
            bracket_depth += line.count("(") - line.count(")")
            if bracket_depth == 0:
                break

    script = (
        "function()\n"
        "local __DCS_VERSION__ = \"\""
        f"local current_mod_path = \"{current_mod_path}\"\n"
        "_ = function(s) return s end\n"
        "function declare_plugin(id, argtable) return argtable end\n"
        + "".join(filecontents).replace("declare_plugin", "return declare_plugin") +
        "end"
    )
    fun = lua.eval(script)
    result = fun()
    lua_table = lua_to_py(result)
    return lua_table.get('InputProfiles', None)


class Command:
    def __init__(self, **kwargs):
        self.name = kwargs.get('name', None)
        self.category = kwargs.get('category', None)
        self.cockpit_device_id = kwargs.get('cockpit_device_id', 'nil')

    def __repr__(self):
        return f"{self.category}:{self.name}"

    def commandhash(self):
        raise NotImplementedError

    def __hash__(self):
        return hash(self.commandhash())

    def __eq__(self, other):
        return self.__hash__() == other.__hash__()

    def type(self):
        return self.__class__.__name__


class KeyCommand(Command):
    def __init__(self, **kwargs):
        if all(x in kwargs.keys() for x in ["hash", "name"]):
            kwargs["down"] = kwargs["hash"].split('d', maxsplit=1)[-1].split("p")[0]
            kwargs["pressed"] = kwargs["hash"].split('p', maxsplit=1)[-1].split("u")[0]
            kwargs["up"] = kwargs["hash"].split('u', maxsplit=1)[-1].split("cd")[0]
            kwargs["cockpit_device_id"] = kwargs["hash"].split('cd', maxsplit=1)[-1].split("vd")[0]
            kwargs["value_down"] = kwargs["hash"].split('vd', maxsplit=1)[-1].split("vp")[0]
            kwargs["value_pressed"] = kwargs["hash"].split('vp', maxsplit=1)[-1].split("vu")[0]
            kwargs["value_up"] = kwargs["hash"].split('vu', maxsplit=1)[-1]

        super().__init__(**kwargs)
        self.down = kwargs.get('down', 'nil')
        self.value_down = kwargs.get('value_down', 'nil')
        self.up = kwargs.get('up', 'nil')
        self.value_up = kwargs.get('value_up', 'nil')
        self.pressed = kwargs.get('pressed', 'nil')
        self.value_pressed = kwargs.get('value_pressed', 'nil')

    def commandhash(self):
        return (f"d{self.down}p{self.pressed}u{self.up}"
                f"cd{self.cockpit_device_id}"
                f"vd{self.value_down}vp{self.value_pressed}vu{self.value_up}")


class AxisCommand(Command):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.action = kwargs.get('action', None)

    def commandhash(self):
        return f"a{self.action}cd{self.cockpit_device_id}"


class Diff:
    def __init__(self):
        self.axis_diffs = dict()
        self.key_diffs = dict()
        self.unsaved_changes = False

    def clear(self, reset_unsaved_changes=False):
        if reset_unsaved_changes:
            self.unsaved_changes = False
        self.axis_diffs.clear()
        self.key_diffs.clear()

    def add_diff(self, command: Command, key):
        self.unsaved_changes = True
        if isinstance(command, KeyCommand):
            diffs = self.key_diffs
        elif isinstance(command, AxisCommand):
            diffs = self.axis_diffs
        else:
            return
        if command not in diffs.keys():
            diffs[command] = list()
        diffs[command].append(key)

    def clear_command(self, command: Command):
        self.unsaved_changes = True
        if isinstance(command, KeyCommand):
            diffs = self.key_diffs
        elif isinstance(command, AxisCommand):
            diffs = self.axis_diffs
        else:
            return
        diffs[command] = list()

    def get_key_for_command(self, command: Command):
        if isinstance(command, KeyCommand):
            diffs = self.key_diffs
        elif isinstance(command, AxisCommand):
            diffs = self.axis_diffs
        else:
            return
        return diffs.get(command, [])

    def to_lua_table(self):
        return SLPP().encode(self.to_dict())

    def from_lua_table(self, luatable):
        pytable = SLPP().decode(luatable)
        self.from_dict(pytable)

    def store_to_file(self, filepath):
        with open(filepath, "w") as f:
            f.write("local diff = " + self.to_lua_table() + "\nreturn diff")
        self.unsaved_changes = False
        logging.info(f"input profile stored to \"{filepath}\"")

    def load_from_file(self, filepath):
        with open(filepath, "r") as f:
            filecontent = "".join(f.readlines())
        self.from_lua_table(filecontent.replace("local diff = ", "").replace("\nreturn diff", ""))
        logging.info(f"input profile loaded from \"{filepath}\"")

    def to_dict(self):
        def rename_keys(key):
            return "JOY_BTN" + str(int(key.replace("Button ", ""))+1)
        return {
                "axisDiffs": {
                    command.commandhash(): {
                        "added": {
                            i + 1: {"key": keybind} for i, keybind in enumerate(self.axis_diffs[command])
                        },
                        "name": command.name,
                    } for command in self.axis_diffs.keys()
                },
                "keyDiffs": {
                    command.commandhash(): {
                        "added": {
                            i + 1: {"key": rename_keys(keybind)} for i, keybind in enumerate(self.key_diffs[command])
                        },
                        "name": command.name,
                    } for command in self.key_diffs.keys()
                },
            }

    def from_dict(self, origin_dict):
        def rename_keys(key):
            if "JOY_BTN" in key:
                return "Button " + str(int(key.replace("JOY_BTN", ""))-1)

        if "keyDiffs" in origin_dict.keys():
            for keydiff in origin_dict["keyDiffs"].keys():
                name = origin_dict["keyDiffs"][keydiff]["name"]
                if 'added' in origin_dict["keyDiffs"][keydiff].keys():
                    for added in origin_dict["keyDiffs"][keydiff]['added'].keys():
                        key = rename_keys(origin_dict["keyDiffs"][keydiff]['added'][added]["key"])
                        self.add_diff(KeyCommand(hash=keydiff, name=name), key)


class DCSProfileManager:

    def __init__(self):
        self.dcs_path = None
        self.dcs_savegames_path = None
        self.dcs_config_version = None
        self.profiles = dict()

    def set_dcs_path(self, path):
        if not os.path.isdir(path):
            raise NotADirectoryError
        self.dcs_path = path

    def set_dcs_savegames_path(self, path):
        if not os.path.isdir(path):
            raise NotADirectoryError
        self.dcs_savegames_path = path

    def check_if_dcs_is_running(self):
        for p in psutil.process_iter():
            try:
                if self.dcs_path in p.exe() and "DCS" in p.name():
                    return True
            except psutil.AccessDenied:
                continue
        return False

    def get_dcs_version(self):
        with open(os.path.join(self.dcs_path, "autoupdate.cfg"), 'r') as f:
            config = json.load(f)
        version = config.get("version", None)
        if version is None:
            logging.warning("Could not get DCS version")
        logging.info(f"Detected DCS version \"{version}\"")
        return version

    def store_profiles(self, path):
        filepath = os.path.join(path, "dcs_config.json")
        with open(filepath, "w") as f:
            json.dump(
                {
                    "dcs_version": self.get_dcs_version(),
                    "dcs_install_path": self.dcs_path,
                    "dcs_savegames_path": self.dcs_savegames_path,
                    "commands": self.profiles,
                },
                f,
                indent=4
            )

    def load_profiles(self, path):
        filepath = os.path.join(path, "dcs_config.json")
        if not os.path.isfile(filepath):
            logging.warning(f"could not find dcs config in \"{filepath}\"")
            return False
        try:
            with open(filepath, "r") as f:
                config = json.load(f)
        except json.decoder.JSONDecodeError:
            return False
        self.profiles = config.get("commands", dict())
        self.dcs_path = config.get("dcs_install_path", None)
        self.dcs_savegames_path = config.get("dcs_savegames_path", None)
        self.dcs_config_version = config.get("dcs_version", None)
        logging.info(f"dcs config loaded from  \"{filepath}\"")
        return True

    def scan_for_profiles(self):
        def scandir(path):
            if not os.path.isdir(path):
                raise NotADirectoryError
            for p in os.listdir(path):
                subpath = os.path.join(path, p)
                if os.path.isdir(subpath):
                    scandir(subpath)
                elif os.path.isfile(subpath):
                    if os.path.basename(subpath) == 'entry.lua':
                        foundpath = os.path.dirname(subpath)
                        try:
                            inputprofiles = parse_entry(subpath)
                            for aircraftname in inputprofiles.keys():
                                foundpath = inputprofiles[aircraftname]
                                with open(os.path.join(foundpath, 'name.lua'), "r") as f:
                                    aircraftname_pretty = f.readline().split("'")[1].strip()
                                logging.debug(f"found aircraft controls for \"{aircraftname}\" in \"{foundpath}\"")
                                result = load_device_profile_from_file(
                                    os.path.join(foundpath, 'joystick', 'default.lua'),
                                    None,
                                    os.path.join(foundpath, r'joystick\\'),
                                    None,
                                    self.dcs_path
                                )
                                if isinstance(result, str):
                                    logging.error(f"could not load aircraft controls: {result}")
                                else:
                                    result["aircraftname"] = aircraftname
                                    self.profiles[aircraftname_pretty] = result
                        except Exception as e:
                            logging.debug(f"Exception when loading from {foundpath}: {e}")

        scandir(os.path.join(self.dcs_path, 'Mods', 'aircraft'))

    def get_aircrafts(self):
        return self.profiles.keys()

    def get_categories_for_aircraft(self, aircraft):
        categories = set()
        if aircraft not in self.profiles.keys():
            return KeyError
        for mylist in [self.profiles[aircraft]["axisCommands"], self.profiles[aircraft]["keyCommands"]]:
            for command in mylist:
                if "category" in command.keys():
                    category = command["category"]
                    if isinstance(category, list):
                        for cat in category:
                            categories.add(cat)
                    else:
                        categories.add(category)
        return categories

    def get_commands_for_aircraft_and_category(self, aircraft, category):
        if aircraft not in self.profiles.keys():
            return KeyError
        if category not in self.get_categories_for_aircraft(aircraft):
            return KeyError
        for mylist, commandclass in [
            (self.profiles[aircraft]["axisCommands"], AxisCommand),
            (self.profiles[aircraft]["keyCommands"], KeyCommand),
        ]:
            for command in mylist:
                if "category" in command.keys():
                    cat = command["category"]
                    if isinstance(cat, list):
                        if category in cat:
                            yield commandclass(**command)
                    else:
                        if cat == category:
                            yield commandclass(**command)


class BindingsFrame(customtkinter.CTkFrame):
    filetypes = [("DCS profile", ".diff.lua")]
    selected_device: Device | None

    def __init__(self, master: GUI, **kwargs):
        super().__init__(master, **kwargs)

        self.dpm = DCSProfileManager()
        profiles_found = self.dpm.load_profiles(appdata_path)

        self.blub = customtkinter.CTkLabel(self, text="DCS Input Profiles")
        self.blub.grid(row=0, column=0, columnspan=2, padx=pad, pady=pad)

        self.load_profiles_button = customtkinter.CTkButton(
            master=self,
            text="\u21bb",
            command=self.load_profiles,
            width=30,
        )
        self.load_profiles_button.grid(row=1, column=0, padx=pad, pady=pad)

        self.settings_button = customtkinter.CTkButton(
            master=self,
            text="\u26ed",
            command=self.show_settings_popup,
            width=30,
        )
        self.settings_button.grid(row=1, column=1, padx=pad, pady=pad)

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

        self.controls_frame = customtkinter.CTkScrollableFrame(self, width=500)
        self.controls_frame.grid(row=6, column=0, columnspan=2, sticky="ns", padx=pad, pady=pad)

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

        self.selected_category = None

        self.controls = dict()

        self.diff = Diff()

        if not profiles_found:
            self.after(100, self.show_settings_popup)
        elif self.dpm.dcs_config_version != self.dpm.get_dcs_version():
            self.after(100, self.show_path_popup)
        else:
            self.update_aircraftlist()

    def show_keybind_popup(self, control):

        def close():
            self.popup.destroy()

        def bind(command, key):
            self.diff.add_diff(command, key)
            self.populate_controls_list()
            close()

        def switch_category(choice=None):
            if not choice:
                choice = self.selected_category
            commandlist = self.dpm.get_commands_for_aircraft_and_category(
                aircraft=self.aircraft_combobox.get(),
                category=choice
            )
            for child in bindings_frame.winfo_children():
                child.destroy()
            for i, command in enumerate(sorted(commandlist, key=lambda c: c.name)):
                btn = customtkinter.CTkButton(
                    master=bindings_frame,
                    text=command.name,
                    command=lambda cmd=command, key=control.raw_name: bind(cmd, key)
                )
                btn.grid(row=i, column=0, sticky="ew", padx=pad, pady=pad)
            self.selected_category = choice

        if self.popup is None or not self.popup.winfo_exists():
            self.popup = customtkinter.CTkToplevel(self)
        self.popup.geometry(f"+{self.winfo_rootx() - 50}+{self.winfo_rooty() + 200}")
        self.popup.title(f"Configure command for {control.raw_name}")
        self.popup.after(100,
                         self.popup.lift)
        self.popup.focus()

        category_label = customtkinter.CTkLabel(self.popup, text="Category", width=30)
        category_label.grid(row=0, column=0, sticky="w", padx=pad, pady=pad)
        category_combobox = customtkinter.CTkComboBox(
            self.popup,
            values=sorted(list(self.dpm.get_categories_for_aircraft(self.aircraft_combobox.get()))),
            command=switch_category,
        )
        category_combobox.grid(row=0, column=1, sticky="ew", padx=pad, pady=pad)

        bindings_frame = customtkinter.CTkScrollableFrame(self.popup, width=250)
        bindings_frame.grid(row=1, column=0, columnspan=2, sticky="ns", padx=pad, pady=pad)

        # done_btn = customtkinter.CTkButton(
        #     master=self.popup,
        #     text="Done",
        #     command=done,
        # )
        # done_btn.grid(row=2, column=0, columnspan=2)

        switch_category()

    def show_settings_popup(self):
        def load():
            self.dpm.set_dcs_path(dcs_path_selector.path.get())
            self.dpm.set_dcs_savegames_path(dcs_savegames_path_selector.path.get())
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
                                           text="Please specify DCS paths")
            label.grid(row=0, column=0, columnspan=2, sticky="ew")

            dcs_path_selector = PathSelector(self.popup, path=find_dcs_install_path(), title="DCS path")
            dcs_path_selector.grid(row=1, column=0, columnspan=2, sticky="ew")

            dcs_savegames_path_selector = PathSelector(self.popup, path=find_dcs_savegames_path(),
                                                       title="DCS Saved Games path")
            dcs_savegames_path_selector.grid(row=2, column=0, columnspan=2, sticky="ew")

            load_profiles_button = customtkinter.CTkButton(self.popup, text="Save settings", command=load)
            load_profiles_button.grid(row=3, column=0, columnspan=2)

            back_on_top()

    def import_file(self):
        path = filedialog.askopenfilename(
            title='Select path',
            filetypes=self.filetypes,
            initialdir=self.dpm.dcs_savegames_path,
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

    def export_file(self):
        path = filedialog.asksaveasfilename(
            title='Select path',
            filetypes=self.filetypes,
            initialdir=self.dpm.dcs_savegames_path,
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
            self.dpm.dcs_savegames_path,
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
            self.dpm.dcs_savegames_path,
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
        path = filedialog.asksaveasfilename(
            title='Select path',
            filetypes=[("Switchology profile", ".swpf")],
        )
        if not path.endswith(".swpf"):
            path += ".swpf"
        storedict = self.selected_device.get_settings_dict()
        storedict["DCSdiff"] = self.diff.to_dict()
        with open(path, "w") as f:
            json.dump(storedict, f, indent=4)
        logging.info(f"Switchology profile stored to \"{path}\"")

    def load_profiles(self):
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
        self.selected_category = list(self.dpm.get_categories_for_aircraft(self.aircraft_combobox.get()))[0]
        self.controls.clear()
        self.populate_controls_list()

    def populate_controls_list(self):
        for child in self.controls_frame.winfo_children():
            if issubclass(type(child), ControlIndicator):
                self.selected_device.unsubscribe(fun=child.update_value)
            child.destroy()
        if self.selected_device is None:
            return
        for i, control in enumerate(self.selected_device.controls):
            self.controls[control] = None
            for command, keys in self.diff.key_diffs.items():
                if control.raw_name in keys:
                    self.controls[control] = command
                    break
            indicator = ControlIndicator(self.controls_frame, control)
            self.selected_device.add_subscriber(control, indicator.update_value)
            indicator.grid(row=i, column=0, sticky="w", padx=pad, pady=pad)

            button = customtkinter.CTkButton(
                master=self.controls_frame,
                text="\u21c4",
                command=lambda c=control: self.show_keybind_popup(c),
                width=30
            )
            button.grid(row=i, column=1, sticky="w", padx=pad, pady=pad)

            binding = customtkinter.CTkLabel(
                master=self.controls_frame,
                text=self.controls[control],
                justify="left",
                wraplength=360,
            )
            binding.grid(row=i, column=2, sticky="w", padx=pad, pady=pad)



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
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(message)s',
    )

    dpm = DCSProfileManager()
    dpm.set_dcs_path(find_dcs_install_path())
    dpm.set_dcs_savegames_path(find_dcs_savegames_path())
    dpm.scan_for_profiles()

    for aircraft in dpm.get_aircrafts():
        print(f"{aircraft}")
        for category in dpm.get_categories_for_aircraft(aircraft):
            print(f"\t{category}")

    diff = Diff()


if __name__ == "__main__":
    main()
