import logging

import swinput

import customtkinter

class AcquireError(Exception):
    pass

device_classes = dict()


class Control:
    def __init__(self, name: None | str):
        self.name = name
        self._value = None

    @property
    def value(self):
        return self._value

    @value.setter
    def value(self, v):
        self._value = v

    def __str__(self):
        return self.name + "(" + self.value + ")"

class Button(Control):

    def __init__(self, name:str):
        super().__init__(name)
        self._value = False

    def __repr__(self):
        return f"Button(\"{self.name}\")"


class Axis(Control):
    def __init__(self, name:str, min:int, max:int):
        super().__init__(name)
        self.min = min
        self.max = max
        self._value = int((max+min)/2)

    def __repr__(self):
        return f"Axis(\"{self.name}\", {self.min}, {self.max})"


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

    def __init__(self, device_info: swinput.SWINPUT_DeviceInfo ):
        self._hash = device_info.device_hash
        self._pid = device_info.pid
        self._vid = device_info.vid
        self._serial_number = device_info.serial_number
        self._hid_path = device_info.hid_path

        self.product_name = device_info.product_name
        self.manufacturer_name = device_info.manufacturer

        self._buttons = dict()
        for bi in range(device_info.button_count):
            self._buttons[bi] = Button(f"B{bi:03d}")

        self._axes = dict()
        for axis_id in range(9):
            if device_info.axes_present & (1 << axis_id):
                self._axes[axis_id] = Axis(f"Axis {swinput.axis_names[axis_id]}", device_info.axes_logical_min[axis_id], device_info.axes_logical_max[axis_id])

        self.subscribers = dict()
        self.subscribers["all"] = list()

    def __del__(self):
        self.close()

    def __repr__(self):
        return self.product_name + " {" + str(self._hash) + "}"

    @property
    def pid(self):
        return self._pid

    @property
    def vid(self):
        return self._vid

    @property
    def hid_path(self):
        return self._hid_path

    @property
    def serial_number(self):
        return self._serial_number

    @property
    def hash(self):
        return self._hash

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

    def close(self):
        self.unsubscribe_all()

    def get_controls(self):
        return (self._buttons | self._axes).values()

    def update_control(self, control, value):
        if value == control.value:
            return
        control.value = value
        logging.debug(f"{self}:{control.name}:{value}")
        for subscriber in self.subscribers["all"]:
            subscriber(control, value)
        if control in self.subscribers.keys():
            for subscriber in self.subscribers[control]:
                subscriber(value)

    def update_button(self, button_index, value):
        self.update_control(self._buttons[button_index], value)

    def update_axis(self, axis_index, value):
        self.update_control(self._axes[axis_index], value)

class ControlIndicator(customtkinter.CTkLabel):

    def update_value(self, value):
        self.configure(
            text=f"{self.control.name}: {value}",
            # text_color_disabled="green"
        )

    def __init__(self, master, control, **kwargs):
        super().__init__(master, **kwargs)
        self.control = control
        self.configure(
            text=f"{self.control.name}: {self.control.value}",
            state='disabled'
        )
