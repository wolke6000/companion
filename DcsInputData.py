import lupa.lua51 as lupa
from lupa.lua51 import LuaRuntime
import os

from slpp import slpp

from gui import get_devices


# def run_in_dcspath(func):
#     def wrapper(*args, **kwargs):
#         cwd = os.getcwd()
#         os.chdir(dcspath)
#         result = func(*args, **kwargs)
#         os.chdir(cwd)
#         return result
#     return wrapper

def lua_to_py(luatable):
    if not isinstance(luatable, type(lupa.LuaRuntime().table())):
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
                dso[dkey] = lua_to_py(ds[dkey])
        if len(extra_categories) > 0:
            extra_categories.append(dso["category"])
            dso["category"] = extra_categories
        return dso

class DcsInputData:

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

        # os.chdir(r"C:\Users\wolfg\git\companion")

        my_utils = self.loadfile('my_utils.lua')


        cwd = os.getcwd()

        my_utils()

        self._lua.execute(
            "local f, err = loadfile('envTable.lua')\n"
            "envTable = f()"
        )

        os.chdir(dcs_path)

        self._populate_devices()
        self._populate_input_profiles()

        self._lua.execute("lfs = require('lfs')")
        self._lua.execute("InputData = require('Input.Data')")
        self._lua.execute("ProfileDatabase = require('Input.ProfileDatabase')")
        self._lua.execute("DCS = require('DCS')")
        user_config_path = str(os.path.join(dcs_savegames_path, 'Config', 'Input')).replace("\\", "/")
        self._lua.execute(f"InputData.initialize('{user_config_path}/', './Config/Input/')")

        self._lua.execute(f"profileInfos = ProfileDatabase.createDefaultProfilesSet('./Config/Input/', DCS.getInputProfiles())")
        self._lua.execute(
            "for i, profileInfo in ipairs(profileInfos) do\n"
            "   InputData.createProfile(profileInfo\n)"
            "end"
        )

        os.chdir(cwd)

    def _populate_devices(self):
        # populate devices list in lua
        for device in get_devices():
            device_name = device.instance_name + " {" + device.instance_guid.lower() + "}"
            self._lua.execute(f"table.insert(devices, '{device_name}')")

    def _populate_input_profiles(self):
        profiles = {
            "a-10a": {
                "path": './Mods/aircraft/A-10A/Input/a-10a'
            }
        }
        for profile_name, profile in profiles.items():
            self._lua.execute(f"_InputProfiles['{profile_name}'] = {{['path'] = '{profile['path']}' }}")

    def _eval_to_py(self, command: str):
        _lua = self._lua.eval(command)
        _py = lua_to_py(_lua)
        return _py

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
        self._eval_to_py(f"InputData.getProfileNames()")

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

def main():
    dcspath = r"Z:\DCS World OpenBeta"
    dcssavegamespath = r"C:\Users\wolfg\Saved Games"

    profilename = 'A-10A'
    devicename = 'Switchology MCP {C65522F0-8C08-11ef-8003-444553540000}'
    filename = "C:/Users/wolfg/Saved Games/DCS.openbeta/Config/Input/a-10a/joystick/Switchology MCP {C65522F0-8C08-11ef-8003-444553540000}.diff.lua"

    did = DcsInputData(
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
