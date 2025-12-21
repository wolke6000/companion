import logging
import ctypes
from ctypes import wintypes
from pyglet.input.win32 import directinput
from pyglet.libs.win32 import _user32
from pyglet.libs.win32 import dinput
from pyglet.libs.win32.com import GUID
from pyglet.libs.win32.dinput import DIPROPHEADER, WCHAR, MAX_PATH
import customtkinter


device_classes = dict()

class DIPROPGUIDANDPATH(ctypes.Structure):
    _fields_ = (
        ('diph', DIPROPHEADER),
        ('guidClass', GUID),
        ('wszPath', WCHAR * MAX_PATH)
    )


IOCTL_HID_GET_SERIALNUMBER_STRING = 721346


def guid_to_string(guid):
    return (f"{guid.Data1:08x}-{guid.Data2:04x}-{guid.Data3:04x}-" +
            "".join(f"{x:02x}" for x in guid.Data4[:2]) +
            "-" + "".join(f"{x:02x}" for x in guid.Data4[2:]))


class DeviceViewFrame(customtkinter.CTkFrame):

    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.device = None

    def refresh(self, device):
        if self.device:
            self.device.unsubscribe_all()
        for child in self.winfo_children():
            child.destroy()
        self.device = device
        column = 0
        row = 0
        for control in self.device.get_controls():
            ci = ControlIndicator(self, control)
            ci.grid(row=row, column=column, padx=5, pady=5)
            device.add_subscriber(control, ci.update_value)
            row += 1
            if row > 10:
                column += 1
                row = 0


class Device:

    tabs = {
        "View": DeviceViewFrame
    }

    def __init__(self, i_di_device: dinput.IDirectInputDevice8, contents: dinput.DIDEVICEINSTANCE):
        self.i_di_device = i_di_device
        self._pid = None
        self._vid = None
        self._serial_number = None
        self._guidandpath = None

        self.instance_name = contents.tszInstanceName
        self.product_name = contents.tszProductName
        self.instance_guid = guid_to_string(contents.guidInstance)

        self._init_controls()
        self._set_format()

        self.subscribers = dict()
        self.subscribers["all"] = list()

    def __del__(self):
        self.close()
        self.i_di_device.Release()

    def __repr__(self):
        return self.instance_name + " {" + self.instance_guid.lower() + "}.diff.lua"

    def _init_controls(self):
        def _object_enum(object_instance, arg):
            control = directinput._create_control(object_instance.contents)
            if control:
                self.controls.append(control)
            return dinput.DIENUM_CONTINUE
        self.controls = []
        self.i_di_device.EnumObjects(dinput.LPDIENUMDEVICEOBJECTSCALLBACK(_object_enum), None, dinput.DIDFT_ALL)
        self.controls.sort(key=lambda c: c._type)

    def _set_format(self):
        if not self.controls:
            return

        object_formats = (dinput.DIOBJECTDATAFORMAT * len(self.controls))()
        offset = 0
        for object_format, control in zip(object_formats, self.controls):
            object_format.dwOfs = offset
            object_format.dwType = control._type
            offset += 4

        fmt = dinput.DIDATAFORMAT()
        fmt.dwSize = ctypes.sizeof(fmt)
        fmt.dwObjSize = ctypes.sizeof(dinput.DIOBJECTDATAFORMAT)
        fmt.dwFlags = 0
        fmt.dwDataSize = offset
        fmt.dwNumObjs = len(object_formats)
        fmt.rgodf = ctypes.cast(ctypes.pointer(object_formats), dinput.LPDIOBJECTDATAFORMAT)
        self.i_di_device.SetDataFormat(fmt)

        prop = dinput.DIPROPDWORD()
        prop.diph.dwSize = ctypes.sizeof(prop)
        prop.diph.dwHeaderSize = ctypes.sizeof(prop.diph)
        prop.diph.dwObj = 0
        prop.diph.dwHow = dinput.DIPH_DEVICE
        prop.dwData = 64 * ctypes.sizeof(dinput.DIDATAFORMAT)
        self.i_di_device.SetProperty(dinput.DIPROP_BUFFERSIZE, ctypes.byref(prop.diph))

    @property
    def pid(self):
        if self._pid is None:
            prop = dinput.DIPROPDWORD()
            prop.diph.dwSize = ctypes.sizeof(dinput.DIPROPDWORD)
            prop.diph.dwHeaderSize = ctypes.sizeof(dinput.DIPROPHEADER)
            prop.diph.dwObj = 0
            prop.diph.dwHow = dinput.DIPH_DEVICE
            self.i_di_device.GetProperty(24, ctypes.byref(prop.diph))
            self._vid = prop.dwData & 0xFFFF
            self._pid = (prop.dwData >> 16) & 0xFFFF
        return self._pid

    @property
    def vid(self):
        if self._vid is None:
            prop = dinput.DIPROPDWORD()
            prop.diph.dwSize = ctypes.sizeof(dinput.DIPROPDWORD)
            prop.diph.dwHeaderSize = ctypes.sizeof(dinput.DIPROPHEADER)
            prop.diph.dwObj = 0
            prop.diph.dwHow = dinput.DIPH_DEVICE
            self.i_di_device.GetProperty(24, ctypes.byref(prop.diph))
            self._vid = prop.dwData & 0xFFFF
            self._pid = (prop.dwData >> 16) & 0xFFFF
        return self._vid

    @property
    def guidandpath(self):
        if self._guidandpath is None:
            prop = DIPROPGUIDANDPATH()
            prop.diph.dwSize = ctypes.sizeof(DIPROPGUIDANDPATH)
            prop.diph.dwHeaderSize = ctypes.sizeof(dinput.DIPROPHEADER)
            prop.diph.dwObj = 0
            prop.diph.dwHow = dinput.DIPH_DEVICE
            self.i_di_device.GetProperty(12, ctypes.byref(prop.diph))
            self._guidandpath = prop.wszPath
        return self._guidandpath

    @property
    def serial_number(self):
        if self._serial_number is None:
            device_handle = ctypes.windll.kernel32.CreateFileW(self.guidandpath, 0, 3, None, 3, 0, None)
            if device_handle == -1:
                logging.error("Failed to open device handle")
                return ""
            serial_number = ctypes.create_unicode_buffer(256)
            bytes_returned = wintypes.DWORD()
            result = ctypes.windll.kernel32.DeviceIoControl(
                device_handle,
                IOCTL_HID_GET_SERIALNUMBER_STRING,
                None,
                0,
                serial_number,
                ctypes.sizeof(serial_number),
                ctypes.byref(bytes_returned),
                None,
            )
            logging.debug(f"received {bytes_returned.value} bytes of serial number \"{serial_number.value}\"")
            ctypes.windll.kernel32.CloseHandle(device_handle)
            return serial_number.value

    def add_subscriber(self, control, fun):
        if control not in self.subscribers.keys():
            self.subscribers[control] = list()
        self.subscribers[control].append(fun)

    def unsubscribe_all(self):
        for subscriber_key in self.subscribers.keys():
            self.subscribers[subscriber_key].clear()

    def unsubscribe(self, control, fun):
        for control in self.subscribers.keys():
            if fun in self.subscribers[control]:
                self.subscribers[control].remove(fun)

    def open(self):
        for control in self.get_controls():
            control.on_change = lambda value, ctrl=control: self.control_on_change(ctrl, value)
        hwnd = _user32.GetActiveWindow()
        self.i_di_device.SetCooperativeLevel(hwnd, dinput.DISCL_BACKGROUND | dinput.DISCL_NONEXCLUSIVE)
        self.i_di_device.Acquire()

    def close(self):
        self.unsubscribe_all()
        self.i_di_device.Unacquire()

    def get_controls(self):
        return self.controls

    def dispatch_events(self):
        if not self.controls:
            return

        events = (dinput.DIDEVICEOBJECTDATA * 64)()
        n_events = wintypes.DWORD(len(events))
        try:
            self.i_di_device.GetDeviceData(
                ctypes.sizeof(dinput.DIDEVICEOBJECTDATA),
                ctypes.cast(ctypes.pointer(events), dinput.LPDIDEVICEOBJECTDATA),
                ctypes.byref(n_events),
                0
            )
        except OSError:
            return

        for event in events[:n_events.value]:
            index = event.dwOfs // 4
            self.controls[index].value = event.dwData

    def control_on_change(self, control, value):
        logging.debug(f"{self.instance_name}:{control.raw_name}:{value}")
        for subscriber in self.subscribers["all"]:
            subscriber(control, value)
        if control in self.subscribers.keys():
            for subscriber in self.subscribers[control]:
                subscriber(value)


class ControlIndicator(customtkinter.CTkLabel):

    def update_value(self, value):
        self.configure(
            text=f"{self.control.raw_name}: {value}",
            # text_color_disabled="green"
        )

    def __init__(self, master, control, **kwargs):
        super().__init__(master, **kwargs)
        self.control = control
        self.configure(
            text=f"{self.control.raw_name}: {self.control.value}",
            state='disabled'
        )
