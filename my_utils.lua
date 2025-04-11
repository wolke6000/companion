package.path = package.path..';./Scripts/?.lua;'
	..'./Scripts/Common/?.lua;./Scripts/UI/?.lua;'
	.. './Scripts/UI/F10View/?.lua;'
	.. './Scripts/Speech/?.lua;'
	.. './dxgui/bind/?.lua;./dxgui/loader/?.lua;./dxgui/skins/skinME/?.lua;./dxgui/skins/common/?.lua;'
	.. './MissionEditor/modules/?.lua;'
	.. './Scripts/Debug/?.lua;'
	.. './Scripts/Input/?.lua;'

printFileLog = function(s) print(s) end

package.loaded["log"] = {
    error = function(s) print('Error: '.. s) end
}
log = require("log")

_ = function(s) return s end

local envTable_

_G["devices"] = {}
_G["envTable"] = {}
_G["_PnPDisabled"] = False

package.loaded["Input"] = {
    getEnvTable = function()
        return envTable
        --if not envTable_ then
        --    local f, err = loadfile('envTable.lua')
        --
        --    if f then
        --        envTable_ = f()
        --    else
        --        print('Cannot load envTable!')
        --    end
        --end
        --return envTable_
        --local f, err = loadfile('C:/Users/wolfg/git/companion/envTable.lua')
        --return f()
        --my_events = {}
        --for i = 0, 9 do
        --    my_events["KEY_"..i] = 1000 + i
        --end
        --my_events["KEY_A"] = 51
        --for i = 0, 128 do
        --    my_events["JOYSTICK_BUTTON"..i.."_OFF"] = i+999
        --end
        --my_events["MOUSE_BUTTON0"] = 5000
        --my_events["MOUSE_BUTTON1"] = 5001
        --my_events["MOUSE_X"] = 5002
        --my_events["MOUSE_Y"] = 5003
        --
        --my_events["KEY_SYSRQ"] = 6000
        --
        --return {
        --    Events = my_events,
        --    Actions = {},
        --}
        end,
    getJoystickDeviceTypeName = function() return 'joystick' end,
    getKeyboardDeviceTypeName = function() return 'keyboard' end,
    getTrackirDeviceTypeName = function() return 'trackir' end,
    getHeadtrackerDeviceTypeName = function() return 'headtracker' end,
    getCustomDeviceTypeName = function() return 'custom' end,
    getMouseDeviceTypeName = function() return 'mouse' end,
    getUnknownDeviceTypeName = function() return 'unknown' end,
    setUnitMarker = function(s)  end,
    addDeviceChangeCallback = function(s)  end,
    getUiLayerName = function() return 'uiInputLayer' end,
    createLayer = function(s) print('createLayer('..s..')') end,
    deleteLayer = function(s) print('deleteLayer('..s..')')  end,
    setDefaultLayer = function(s) print('setDefaultLayer('..s..')')  end,
    setDefaultLayerTop = function() print('setDefaultLayerTop()')  end,
    setTopLayer = function()  end,
    getDevices = function()
        --print('getDevices()')
        --return {
        --    "Keyboard",
        --    "Switchology MCP {C65522F0-8C08-11ef-8003-444553540000}",
        --    "Mouse",
        --}
        return devices
    end,
    getDeviceTypeName = function(s)
        --print('getDeviceTypeName('..s..')')
        if s == 'Keyboard' then
            return 'keyboard'
        end
        if s == "Mouse" then
            return 'mouse'
        end
        return 'joystick'
    end,
    getEventDeviceTypeName = function(event)
        if event < 1024 then return 'keyboard' end
        if event < 2048 then return 'mouse' end
        if event < 3072 then return 'headtracker' end
        if event < 4096 then return 'trackir' end
        return 'joystick'
    end,
    getDeviceId = function(s)
        --print('getDeviceId('..s..')')
        return s
    end,
    addReformer = function(ln, mev, mdi, msw) print('addReformer('..ln..', '..mdi..')') return {} end,
    addKeyCombo = function(ln, kev, did, ref, cd, dp, cu) print('addKeyCombo('..ln..', '..did..')') return {} end,
    setLayerStack = function(s) print('setLayerStack('..s..')') return {} end,
    getLayerStack = function() print('getLayerStack()') return {} end,
    getLoadedLayers = function() print('getLoadedLayers()') return {} end,
    getLayerProfileInfo = function(s) print('getLayerProfileInfo('..s..')') return {} end,
    setPnPDisabled = function (s) _PnPDisabled = s end,
    getPnPDisabled = function() return _PnPDisabled end,
}
Input = require("Input")

--package.loaded["InputUtils"] = {
--    localizeInputString = function(s) return s end,
--    getDevices = function() return {
--        ["DEVICE1"] = {
--            ["name"] = "Thrustmaster HOTAS Warthog",
--            ["guid"] = "{E2A92F50-D6F0-11E6-8000-444553540000}",
--            ["type"] = "joystick",
--            ["physical_name"] = "VID_044F&PID_0402",
--        },
--        ["DEVICE2"] = {
--            ["name"] = "VKBsim Gunfighter Modern Combat",
--            ["guid"] = "{A5C4F850-3BE1-11EB-8000-444553540000}",
--            ["type"] = "joystick",
--            ["physical_name"] = "VID_231D&PID_0120",
--        },
--        -- etc.
--    } end
--}
--InputUtils = require("InputUtils")

package.loaded["i18n"] = {
    ptranslate = function(s) return s end,
}
i18n = require("i18n")

package.loaded["i_18n"] = {
    dtranslate = function(i, s) return s end,
}
i_18n = require("i_18n")

package.loaded["lfs"] = {
    writedir = function() return "C:/Users/wolfg/Saved Games/DCS.openbeta" end,
    attributes = function(path)
        -- Try opening as a file
        local file = io.open(path, "r")
        if file then
            file:close()
            return { mode = "file" }
        end

        -- If not a file, try checking if it's a directory
        local p = io.popen('dir "' .. path .. '" 2>nul')
        if p then
            local output = p:read("*a")
            p:close()

            if output:match("Directory of") then
                return { mode = "directory" }
            end
        end

        return nil  -- not found
    end,
    realpath = function(path)
        --print('lfs.realpath('..path..')')
        local cmd = 'cd "' .. path .. '" 2>nul && cd'
        local p = io.popen(cmd)
        if not p then return nil end

        local result = p:read("*l")
        p:close()
    return result
    end,
    mkdir = function(path)
        local is_windows = package.config:sub(1,1) == "\\"
        local cmd
        if is_windows then
            cmd = string.format('mkdir "%s" 2>nul', path)
        else
            cmd = string.format('mkdir -p "%s" 2>/dev/null', path)
        end
        local result = os.execute(cmd)
        return result == true or result == 0
    end,
}
lfs = require("lfs")

package.loaded["textutil"] = {

}
textutil = require("textutil")

copy_table = function(target, src)
    assert(target ~= src)

    if not target then
        target = {}
    end

    for i, v in pairs(src) do
        if type(v) == 'table' then
            if not target[i] then
                target[i] = {}
            end

            copy_table(target[i], v)
        else
            target[i] = v
        end
    end

    return target
end

package.loaded["me_utilities"] = {
    copyTable = function(target, src)
        return copy_table(target, src)
    end
}
U = require("me_utilities")

_G["_InputProfiles"] = {}
package.loaded["DCS"] = {
    getInputProfiles = function()
        return _InputProfiles
        --return {
        --    ["a-10a"] = {
        --        ["path"] = current_mod_path .. '/Input/a-10a'
        --    },
        --}
    end
}
DCS = require("DCS")

turnLocalizationHintsOn_				= false
insideLocalizationHintsFuncCounter_	= 0
insideExternalProfileFuncCounter_		= 0
