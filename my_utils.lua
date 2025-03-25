printFileLog = function(s) print(s) end
log = {
    error = function(s) print('Error: '.. s) end
}

_ = function(s) return s end

package.loaded["Input"] = {
    getEnvTable = function() return {
        Events = {},
        Actions = {},
    } end
}

package.loaded["InputUtils"] = {
    localizeInputString = function(s) return s end
}


Input = require("Input")
InputUtils = require("InputUtils")

turnLocalizationHintsOn_				= false
insideLocalizationHintsFuncCounter_	= 0
insideExternalProfileFuncCounter_		= 0