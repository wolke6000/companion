import json
import logging
import typing

import psutil
from pyglet.input import AbsoluteAxis, Button, Control
from slpp import SLPP
import lupa.lua51 as lupa
from lupa.lua51 import LuaRuntime
import os
import winreg
import customtkinter
from tkinter import filedialog, messagebox

from PullDownButton import PullDownButton

import Switchology
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
    for dcs_dir in ["DCS", "DCS.openbeta"]:
        path = os.path.join(os.path.expanduser("~"), "Saved Games", dcs_dir)
        if os.path.exists(path):
            break
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
                    skip = True
            if line.startswith("local fdef, errfdef = loadfile('./Scripts/Input/DefaultAssignments.lua')"):
                data_lua_content += line
                skip = False

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
        if "hash" in kwargs.keys():
            self.action = kwargs["hash"].split('a', maxsplit=1)[-1].split("cd")[0]
            self.cockpit_device_id = kwargs["hash"].split('cd', maxsplit=1)[-1]
        elif "action" in kwargs.keys():
            self.action = kwargs["action"]

    def commandhash(self):
        return f"a{self.action}cd{self.cockpit_device_id}"


class DiffEntry:
    _controls_added: set[str]
    _controls_removed: set[str]

    def __init__(self, add: str | typing.Iterable[str] | None = None, remove: str | typing.Iterable[str] | None = None):
        self._controls_added = set()
        if isinstance(add, str):
            self._controls_added.add(add)
        elif issubclass(type(add), typing.Iterable):
            for a in add:
                self._controls_added.add(a)
        self._controls_removed = set()
        if isinstance(remove, str):
            self._controls_removed.add(remove)
        elif issubclass(type(remove), typing.Iterable):
            for r in remove:
                self._controls_removed.add(r)


    def __repr__(self):
        repr_str = ""
        if len(self._controls_added) > 0:
            repr_str += ", +:[" + ", ".join([c for c in self._controls_added]) + "]"
        if len(self._controls_removed) > 0:
            repr_str += ", -:[" + ", ".join([c for c in self._controls_removed]) + "]"
        return repr_str

    def add_control(self, control: str):
        if control in self._controls_added:
            return
        elif control in self._controls_removed:
            self._controls_removed.remove(control)  # cancelled
        else:
            self._controls_added.add(control)

    def remove_control(self, control: str):
        if control in self._controls_removed:
            return
        elif control in self._controls_added:
            self._controls_added.remove(control)  # cancelled
        else:
            self._controls_added.add(control)

    @property
    def controls(self):
        return self._controls_added | self._controls_removed

    @property
    def active_controls(self):
        return self._controls_added - self._controls_removed

    def to_dict(self):
        retval = dict()
        if len(self._controls_added) > 0:
            retval["added"] = dict()
            for i, added in enumerate(self._controls_added):
                retval["added"][i+1] = {"key": change_control_names_pyglet_to_dcs(added)}
        if len(self._controls_removed) > 0:
            retval["removed"] = dict()
            for i, removed in enumerate(self._controls_removed):
                retval["removed"][i+1] = {"key": change_control_names_pyglet_to_dcs(removed)}
        return retval


    def __add__(self, other: "DiffEntry"):
        return DiffEntry(
            add=(self._controls_added - other._controls_removed) | (other._controls_added - self._controls_removed),
            remove=(self._controls_removed - other._controls_added) | (other._controls_removed - self._controls_added)
        )

    def __sub__(self, other: "DiffEntry"):
        return self.__add__(other.__neg__())

    def __neg__(self):
        return DiffEntry(
            add=self._controls_removed,
            remove=self._controls_added,
        )


class Diff:
    axis_diffs: dict[Command, DiffEntry]
    key_diffs: dict[Command, DiffEntry]
    def __init__(self):
        self.axis_diffs = dict()
        self.key_diffs = dict()
        self.unsaved_changes = False

    def clear(self, reset_unsaved_changes=False):
        if reset_unsaved_changes:
            self.unsaved_changes = False
        self.axis_diffs.clear()
        self.key_diffs.clear()

    def add_diff(self, command: Command, entry: DiffEntry):
        self.unsaved_changes = True
        if isinstance(command, KeyCommand):
            diffs = self.key_diffs
        elif isinstance(command, AxisCommand):
            diffs = self.axis_diffs
        else:
            return
        if command in diffs.keys():
            diffs[command] += entry
        else:
            diffs[command] = entry

    def remove_diff(self, command: Command, entry: DiffEntry):
        self.unsaved_changes = True
        if isinstance(command, KeyCommand):
            diffs = self.key_diffs
        elif isinstance(command, AxisCommand):
            diffs = self.axis_diffs
        else:
            return
        if command in diffs.keys():
            diffs[command] -= entry
        else:
            diffs[command] = -entry

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
        retval = { "axisDiffs": dict(), "keyDiffs": dict() }
        for diffs, diffs_key in [(self.axis_diffs, "axisDiffs"), (self.key_diffs, "keyDiffs")]:
            for command, diffentry in diffs.items():
                if len(diffentry.controls) > 0:
                    retval[diffs_key][command.commandhash()] = diffentry.to_dict()
                    retval[diffs_key][command.commandhash()]["name"] = command.name
        return retval

    def from_dict(self, origin_dict):
        for diffs_key, command_type in [("axisDiffs", AxisCommand), ("keyDiffs", KeyCommand)]:
            if diffs_key in origin_dict.keys():
                for keydiff in origin_dict[diffs_key].keys():
                    name = origin_dict[diffs_key][keydiff]["name"]
                    for operation, operation_key in [(self.add_diff, "added"), (self.remove_diff, "removed")]:
                        if operation_key in origin_dict[diffs_key][keydiff].keys():
                            for item in origin_dict[diffs_key][keydiff][operation_key].keys():
                                key = origin_dict[diffs_key][keydiff][operation_key][item]["key"]
                                operation(command_type(hash=keydiff, name=name), DiffEntry(change_control_names_dcs_to_pyglet(key)))

    def __add__(self, other: "Diff"):
        result = Diff()
        for diffs_name in ["key_diffs", "axis_diffs"]:
            self_diffs = getattr(self, diffs_name)
            other_diffs = getattr(other, diffs_name)
            result_diffs = getattr(result, diffs_name)
            for command in set(self_diffs.keys()).union(set(other_diffs.keys())):
                entry = DiffEntry()
                if command in self_diffs.keys():
                    entry += self_diffs[command]
                if command in other_diffs.keys():
                    entry += other_diffs[command]
                if len(entry.controls) > 0:
                    result_diffs[command] = entry
        return result

    def __neg__(self):
        result = Diff()
        for diffs_name in ["key_diffs", "axis_diffs"]:
            self_diffs = getattr(self, diffs_name)
            result_diffs = getattr(result, diffs_name)
            for command, entry in self_diffs.items():
                result_diffs[command] = -entry
        return result

    def __sub__(self, other):
        return self.__add__(other.__neg__())


class DCSProfileManager:

    def __init__(self):
        self.dcs_path = None
        self.dcs_savegames_path = None
        self.dcs_config_version = None
        self.profiles = dict()
        self.default_diffs = dict()

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
        for aircraftname in self.profiles.keys():
            self.extract_default_diff_from_profile(aircraftname)
        self.dcs_path = config.get("dcs_install_path", None)
        self.dcs_savegames_path = config.get("dcs_savegames_path", None)
        self.dcs_config_version = config.get("dcs_version", None)
        logging.info(f"dcs config loaded from  \"{filepath}\"")
        return True

    def extract_default_diff_from_profile(self, aircraftname: str):
        diffs = Diff()
        for command_class, command_class_key in [(KeyCommand, "keyCommands"), (AxisCommand, "axisCommands")]:
            if command_class_key not in self.profiles[aircraftname]:
                continue
            for command in self.profiles[aircraftname][command_class_key]:
                if not "combos" in command:
                    continue
                diff_entry = DiffEntry()
                for combo in command["combos"]:
                    diff_entry.add_control(combo["key"])
                diffs.add_diff(command_class(**command), diff_entry)
        self.default_diffs[aircraftname] = diffs

    def scan_for_profiles(self):
        def scan_mods_aircraft_dir(path):
            if not os.path.isdir(path):
                raise NotADirectoryError
            for p in os.listdir(path):
                subpath = os.path.join(path, p)
                if os.path.isdir(subpath):
                    scan_mods_aircraft_dir(subpath)
                elif os.path.isfile(subpath):
                    if os.path.basename(subpath) == 'entry.lua':
                        foundpath = os.path.dirname(subpath)
                        try:
                            inputprofiles = parse_entry(subpath)
                            for aircraftname in inputprofiles.keys():
                                foundpath = inputprofiles[aircraftname]
                                with open(os.path.join(foundpath, 'name.lua'), "r") as f:
                                    aircraftname_pretty = f.readline().split("'")[1].strip()
                                logging.debug(f"found aircraft controls for \"{aircraftname_pretty}\" in \"{foundpath}\"")
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
                                    self.extract_default_diff_from_profile(aircraftname_pretty)
                        except Exception as e:
                            logging.debug(f"Exception when loading from {foundpath}: {e}")

        def scan_config_input_dir(path):
            if not os.path.isdir(path):
                raise NotADirectoryError
            for p in os.listdir(path):
                subpath = os.path.join(path, p)
                if os.path.isdir(subpath):
                    scan_config_input_dir(subpath)
                elif os.path.isfile(subpath) and p == "name.lua":
                    foundpath = os.path.dirname(subpath)
                    aircraftname = os.path.basename(foundpath)
                    with open(os.path.join(foundpath, 'name.lua'), "r") as f:
                        for line in f.readlines():
                            if line.startswith("return"):
                                aircraftname_pretty = line.split("'")[1].strip()
                                break
                    logging.debug(f"found aircraft controls for \"{aircraftname_pretty}\" in \"{foundpath}\"")
                    default_lua_path = os.path.join(foundpath, 'joystick', 'default.lua')
                    if not os.path.isfile(default_lua_path):
                        return
                    result = load_device_profile_from_file(
                        default_lua_path,
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
                        self.extract_default_diff_from_profile(aircraftname_pretty)

        scan_mods_aircraft_dir(os.path.join(self.dcs_path, 'Mods', 'aircraft'))
        # scan_config_input_dir(os.path.join(self.dcs_path, 'Config', 'Input'))

    def get_aircrafts(self):
        return self.profiles.keys()

    def get_categories_for_aircraft(self, aircraft):
        categories = set()
        if aircraft not in self.profiles.keys():
            return KeyError
        for commands_list in ["axisCommands", "keyCommands"]:
            if commands_list not in self.profiles[aircraft].keys():
                continue
            mylist = self.profiles[aircraft][commands_list]
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
            raise KeyError
        if category not in self.get_categories_for_aircraft(aircraft):
            raise KeyError
        for commands_list, commandclass in [
            ("axisCommands", AxisCommand),
            ("keyCommands", KeyCommand),
        ]:
            if commands_list not in self.profiles[aircraft].keys():
                continue
            mylist = self.profiles[aircraft][commands_list]
            for command in mylist:
                if "category" in command.keys():
                    cat = command["category"]
                    if isinstance(cat, list):
                        if category in cat:
                            yield commandclass(**command)
                    else:
                        if cat == category:
                            yield commandclass(**command)

    def get_all_axis_commands_for_aircraft(self, aircraft):
        if aircraft not in self.profiles.keys():
            raise KeyError
        if "axisCommands" not in self.profiles[aircraft].keys():
            return
        for command in self.profiles[aircraft]["axisCommands"]:
            yield  AxisCommand(**command)

    def get_aircraft_for_directory(self, aircraftname):
        for key, item in self.profiles.items():
            if item["aircraftname"] == aircraftname:
                return key


class BindingsFrame(customtkinter.CTkFrame):
    selected_device: Device | None

    def __init__(self, master: GUI, **kwargs):
        super().__init__(master, **kwargs)

        self.dpm = DCSProfileManager()
        profiles_found = self.dpm.load_profiles(appdata_path)

        title_row = customtkinter.CTkFrame(master=self)
        title_row.grid(row=0)
        title_label = customtkinter.CTkLabel(master=title_row, text="DCS Input Profiles")
        title_label.grid(row=0, column=0, padx=pad, pady=pad)
        self.load_profiles_button = customtkinter.CTkButton(
            master=title_row,
            text="\u21bb",
            command=self.load_profiles,
            width=30,
        )
        self.load_profiles_button.grid(row=0, column=1, padx=pad, pady=pad)
        self.settings_button = customtkinter.CTkButton(
            master=title_row,
            text="\u26ed",
            command=self.show_settings_popup,
            width=30,
        )
        self.settings_button.grid(row=0, column=2, padx=pad, pady=pad)

        top_button_row = customtkinter.CTkFrame(master=self)
        top_button_row.grid(row=1, sticky="ew")
        self.import_button = PullDownButton(
            master=top_button_row,
            text="Load...",
            values={
                "...from *.swpf-file": self.import_swpf,
                "...from DCS": self.import_dcs,
                "...clear profile": self.clear_diffs,
            }
        )
        self.import_button.grid(row=0, column=0, padx=pad, pady=pad)
        self.profile_name_variable = customtkinter.StringVar(value="unnamed profile")
        self.profile_name_entry = customtkinter.CTkEntry(
            master=top_button_row,
            textvariable=self.profile_name_variable,
            width=300
        )
        self.profile_name_entry.grid(row=0, column=1, sticky="ew", padx=pad, pady=pad)

        self.controls_frame = customtkinter.CTkScrollableFrame(self, width=500)
        self.controls_frame.grid(row=2, sticky="ns", padx=pad, pady=pad)
        self.grid_rowconfigure(2, weight=1)

        bottom_button_row = customtkinter.CTkFrame(master=self)
        bottom_button_row.grid(row=3, sticky="ew")
        self.export_button = PullDownButton(
            master=bottom_button_row,
            text="Share...",
            values={
                "...to *.swpf-file": self.export_swpf
            }
        )
        self.export_button.grid(row=0, column=0, padx=pad, pady=pad)
        self.save_to_savegames_button = customtkinter.CTkButton(
            master=bottom_button_row,
            text="Push to DCS",
            command=self.export_dcs,
        )
        self.save_to_savegames_button.grid(row=0, column=1, padx=pad, pady=pad)

        self.popup = None
        self.selected_device = None
        self.last_aircraft_choice = None
        self.selected_category = None
        self.command_filter_str = ""
        self.controls = dict()
        self.diffs: dict[str, Diff] = dict()
        self.open_popup_with_control = False

        if not profiles_found:
            self.after(100, self.show_settings_popup)
        elif self.dpm.dcs_config_version != self.dpm.get_dcs_version():
            self.load_profiles()

    def show_keybind_popup(self, control):

        def close():
            self.command_filter_str = command_filter_var.get()
            self.last_aircraft_choice = aircraft_selection.get()
            if not issubclass(type(control), AbsoluteAxis):
                self.selected_category = category_selection.get()
            command_filter_var.trace_remove("write", cb_name)
            self.popup.destroy()

        def bind(command, key):
            if aircraft_selection.get() not in self.diffs.keys():
                self.diffs[aircraft_selection.get()] = Diff()
            self.diffs[aircraft_selection.get()].add_diff(command, DiffEntry(key))
            self.populate_controls_list()
            close()

        def switch_aircraft(choice):
            self.last_aircraft_choice = choice
            if not issubclass(type(control), AbsoluteAxis):
                configlist = sorted(list(self.dpm.get_categories_for_aircraft(choice)))
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
            if choice == all_categories_str:
                commandlist = list()
                for cat in self.dpm.get_categories_for_aircraft(ac):
                    commandlist += self.dpm.get_commands_for_aircraft_and_category(aircraft=ac, category=cat)
                self.selected_category = choice
            elif choice == axes_category_str:
                commandlist = self.dpm.get_all_axis_commands_for_aircraft(ac)
            else:
                commandlist = self.dpm.get_commands_for_aircraft_and_category(aircraft=ac, category=choice)
                self.selected_category = choice
            for child in bindings_frame.winfo_children():
                child.destroy()
            i = 0
            for command in sorted(commandlist, key=lambda c: c.name):
                if command_filter_var.get().lower() not in command.name.lower():
                    continue
                btn = customtkinter.CTkButton(
                    master=bindings_frame,
                    text=command.name,
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
        if self.last_aircraft_choice is None:
            self.last_aircraft_choice = sorted(list(self.dpm.get_aircrafts()))[0]
        aircraft_selection = customtkinter.CTkOptionMenu(
            master=self.popup,
            values=sorted(list(self.dpm.get_aircrafts())),
            command=switch_aircraft,
        )
        aircraft_selection.grid(row=0, column=0, sticky="ew", padx=pad, pady=pad)
        aircraft_selection.set(self.last_aircraft_choice)
        if self.selected_category is None:
            self.selected_category = all_categories_str
        if not issubclass(type(control), AbsoluteAxis):
            category_selection = customtkinter.CTkOptionMenu(
                master=self.popup,
                values=[all_categories_str] + sorted(list(self.dpm.get_categories_for_aircraft(self.last_aircraft_choice))),
                command=switch_category,
            )
            category_selection.set(self.selected_category)
            category_selection.grid(row=0, column=1, sticky="ew", padx=pad, pady=pad)
        command_filter_var = customtkinter.StringVar(value=self.command_filter_str)
        cb_name = command_filter_var.trace_add("write", filter_commands)
        command_filter_entry = customtkinter.CTkEntry(
            master=self.popup,
            textvariable=command_filter_var,
        )
        command_filter_entry.grid(row=0, column=2, padx=pad, pady=pad)
        bindings_frame = customtkinter.CTkScrollableFrame(self.popup, width=350)
        bindings_frame.grid(row=1, column=0, columnspan=3, sticky="ns", padx=pad, pady=pad)
        if issubclass(type(control), AbsoluteAxis):
            switch_category(axes_category_str)
        else:
            switch_category(self.selected_category)

    def show_settings_popup(self):
        def load():
            new_dcs_path = dcs_path_selector.path.get()
            new_dcs_savegames_path = dcs_savegames_path_selector.path.get()
            if old_dcs_path != new_dcs_path:
                self.dpm.set_dcs_path(new_dcs_path)
            if old_dcs_savegames_path != new_dcs_savegames_path:
                self.dpm.set_dcs_savegames_path(new_dcs_savegames_path)
            if old_dcs_path != new_dcs_path or old_dcs_savegames_path != new_dcs_savegames_path:
                self.load_profiles()
            self.populate_controls_list()
            self.popup.destroy()

        def back_on_top():
            if self.popup is not None and self.popup.winfo_exists():
                if not dcs_savegames_path_selector.dialog_open and not dcs_path_selector.dialog_open:
                    self.popup.lift()
                self.popup.after(100, back_on_top)

        def switch_callback():
            self.open_popup_with_control = open_popup_with_control_switch.get()

        if self.popup is None or not self.popup.winfo_exists():

            self.popup = customtkinter.CTkToplevel(self)
            self.popup.title(f"Configure DCS Paths")

            label = customtkinter.CTkLabel(self.popup,
                                           text="Please specify DCS paths")
            label.grid(sticky="ew")

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
                command=switch_callback,
            )
            if self.open_popup_with_control:
                open_popup_with_control_switch.select()
            else:
                open_popup_with_control_switch.deselect()
            open_popup_with_control_switch.grid()

            save_settings_button = customtkinter.CTkButton(self.popup, text="Save settings", command=load)
            save_settings_button.grid()

            back_on_top()

    def import_dcs(self):

        def load_from_file(a_dir, a_path):
            logging.debug(f"looking for input profile in {a_path}")
            for filename in os.listdir(a_path):
                if self.selected_device.instance_guid.lower() in filename.lower():
                    a_name = self.dpm.get_aircraft_for_directory(a_dir)
                    if a_name is None:
                        return
                    if a_dir in self.diffs.keys():
                        pass
                    else:
                        self.diffs[a_name] = Diff()
                    self.diffs[a_name].load_from_file(os.path.join(a_path, filename))
                    return
            logging.debug(f"no input profile found for \"{self.selected_device}\" and \"{a_dir}\"")

        if any(diff.unsaved_changes for diff in self.diffs.values()):
            ans = messagebox.askokcancel(
                "Warning",
                "Your profile has unsaved changes! If you continue, those will be lost!",
                parent=self
            )
            if not ans:
                return
        config_input_path = os.path.join(
            self.dpm.dcs_savegames_path,
            "Config",
            "Input",
        )
        for aircraft_directory in os.listdir(config_input_path):
            path = os.path.join(
                config_input_path,
                aircraft_directory,
                "Joystick",
            )
            if not os.path.isdir(path):
                continue
            try:
                load_from_file(aircraft_directory, path)
            except AttributeError:
                continue
        self.populate_controls_list()
        self.profile_name_variable.set("unnamed profile")

    def export_dcs(self):

        def store_to_file(p, d):
            if not os.path.exists(p):
                os.makedirs(p)
            for filename in os.listdir(p):
                if self.selected_device.instance_guid.lower() in filename.lower():
                    d.store_to_file(os.path.join(p, filename))
                    return
            # if there is no valid file there, create one
            filename = str(self.selected_device)
            d.store_to_file(os.path.join(p, filename))

        for aircraft, diff in self.diffs.items():
            path = os.path.join(
                self.dpm.dcs_savegames_path,
                "Config",
                "Input",
                self.dpm.profiles[aircraft]["aircraftname"],
                "Joystick"
            )
            if self.dpm.check_if_dcs_is_running():
                messagebox.showwarning(
                    title="DCS appears to be running!",
                    message=f"You must restart DCS for changes to take effect!",
                )
            corrected_diff = diff - self.dpm.default_diffs[aircraft]
            store_to_file(path, corrected_diff)

    def import_swpf(self):
        path = filedialog.askopenfilename(
            title='Select path',
            filetypes=[("Switchology profile", ".swpf")],
        )
        if not os.path.isfile(path):
            return
        with open(path, "r") as f:
            loaddict = json.load(f)
        if isinstance(self.selected_device, Switchology.SwitchologyDevice):
            if loaddict.get("build_id", "") != self.selected_device.build_id:
                logging.error(f"Selected device's build id \"{self.selected_device.build_id}\" does not match the profile's build id \"{loaddict.get('build_id', '')}\"")
                return
        self.profile_name_variable.set(loaddict.get("profile_name", "unnamed profile"))
        dcsdiffs = loaddict.get("DCSdiffs", {})
        if dcsdiffs is {}:
            logging.error(f"The file does not contain a DCS profile!")
            return
        if any(diff.unsaved_changes for diff in self.diffs.values()):
            ans = messagebox.askokcancel(
                "Warning",
                "Your profile has unsaved changes! If you continue, those will be lost!",
                parent=self
            )
            if not ans:
                return
        self.diffs.clear()
        for aircraft, diff_dict in dcsdiffs.items():
            self.diffs[aircraft] = Diff()
            self.diffs[aircraft].from_dict(diff_dict)
        self.populate_controls_list()
        logging.info(f"Switchology profile loaded from \"{path}\"")

    def export_swpf(self):
        path = filedialog.asksaveasfilename(
            title='Select path',
            filetypes=[("Switchology profile", ".swpf")],
        )
        if not path.endswith(".swpf"):
            path += ".swpf"
        storedict = self.selected_device.get_settings_dict()
        storedict["profile_name"] = self.profile_name_variable.get()
        storedict["DCSdiffs"] = dict()
        for aircraft, diff in self.diffs.items():
            storedict["DCSdiffs"][aircraft] = diff.to_dict()
        with open(path, "w") as f:
            json.dump(storedict, f, indent=4)
        logging.info(f"Switchology profile stored to \"{path}\"")

    def load_profiles(self):
        self.dpm.scan_for_profiles()
        self.dpm.store_profiles(appdata_path)
        self.last_aircraft_choice = None  # sorted(list(self.dpm.get_aircrafts()))[0]

    def populate_controls_list(self):
        def destroy_children(widget):
            for child in widget.winfo_children():
                if issubclass(type(child), ControlIndicator):
                    self.selected_device.unsubscribe(fun=child.update_value)
                destroy_children(child)
                child.destroy()

        destroy_children(self.controls_frame)
        if self.selected_device is None:
            return
        for i, control in enumerate(self.selected_device.controls):
            self.controls[control] = None
            command_name_list = list()
            for aircraft in self.diffs.keys():
                if issubclass(type(control), AbsoluteAxis):
                    diff_dict = self.diffs[aircraft].axis_diffs
                else:
                    diff_dict = self.diffs[aircraft].key_diffs
                for command, entry in diff_dict.items():
                    if control.raw_name in entry.active_controls:
                        self.controls[control] = command
                        command_name_list.append((aircraft, command))
                        # break

            controls_line_frame = customtkinter.CTkFrame(master=self.controls_frame)
            controls_line_frame.grid(row=i, column=0, sticky="ew", pady=3)
            indicator = ControlIndicator(controls_line_frame, control)
            indicator.grid(row=0, column=0, sticky="w", padx=pad, pady=pad)
            self.selected_device.add_subscriber(control, indicator.update_value)
            if self.open_popup_with_control:
                self.selected_device.add_subscriber(control, self.open_popup_on_control)
            button = customtkinter.CTkButton(
                master=controls_line_frame,
                text="\uff0b",
                command=lambda c=control: self.show_keybind_popup(c),
                width=30
            )
            button.grid(row=0, column=1, sticky="w", padx=pad, pady=pad)
            for j, (aircraft, command) in enumerate(command_name_list):
                binding = BindingButton(
                    master=controls_line_frame,
                    text=f"{aircraft.strip()}: {command.name.strip()}",
                    command=lambda a=aircraft, c=command, k=control: self.remove_binding(a, c, k),
                )
                binding.bind('<Enter>', binding.configure,)
                binding.grid(row=j, column=2, sticky="w")

    def remove_binding(self, aircraft, command, control):
        ans = messagebox.askyesnocancel(
            title=f"Remove {command.name}",
            message=f"Do you want to remove \"{command.name}\" from \"{control.raw_name}\" for \"{aircraft}\"?"
        )
        if not ans:
            return
        self.diffs[aircraft].remove_diff(command, DiffEntry(control.raw_name))
        self.populate_controls_list()

    def clear_diffs(self):
        self.profile_name_variable.set("unnamed profile")
        self.diffs.clear()
        self.populate_controls_list()

    def open_popup_on_control(self, value, control):
        if not self.open_popup_with_control:
            return
        if isinstance(control, Button):
            self.show_keybind_popup(control)




class BindingButton(customtkinter.CTkFrame):

    def __init__(self, master, **kwargs):
        text = kwargs.pop("text", "")
        command = kwargs.pop("command", None)
        super().__init__(
            master=master,
            bg_color=master._fg_color,
            fg_color=master._fg_color,
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
            text="\u274C",
            bg_color=self._fg_color,
            fg_color=self._fg_color,
            hover_color="red",
            border_color=self._label._text_color,
            command=command,
            height=button_size,
            width=button_size,
            corner_radius=round(button_size/2),
            border_width=1,
            border_spacing=0,
            font=(customtkinter.CTkFont(), 5),
        )
        self._xbut.grid(row=0, column=1, sticky="w", padx=3)


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
