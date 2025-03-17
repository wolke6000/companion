import json
import logging
import psutil
from slpp import SLPP
import lupa.lua51 as lupa
from lupa.lua51 import LuaRuntime
import os
import winreg


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
