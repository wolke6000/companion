import logging

from idna import valid_label_length

import swinput

import customtkinter
from tkinter import Canvas

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
        self.scaling = customtkinter.ScalingTracker.get_widget_scaling(self)
        self.controls_canvas = None

    def refresh(self, device):
        if self.device:
            self.device.unsubscribe_all()
        for child in self.winfo_children():
            child.destroy()
        self.device = device

        self.draw_controls()

    def draw_controls(self):
        self.controls_canvas = Canvas(
            self,
            width=400 * self.scaling,
            height=600 * self.scaling,
            background=self.cget("fg_color")[customtkinter.get_appearance_mode().lower() == 'dark'],
            bd=0,
            highlightthickness=0
        )
        self.controls_canvas.grid(row=0, column=1)
        xpos = 10 * self.scaling
        ypos = 10 * self.scaling

        buttons = self.device.get_buttons()
        if len(buttons) > 0:
            self.controls_canvas.create_text(0, 0, text="Buttons", anchor="nw")
            for i, button in enumerate(self.device.get_buttons()):
                if i%16==0:
                    xpos = 10 * self.scaling
                    ypos += 20 * self.scaling
                ci = ControlIndicatorButton(self, button)
                self.controls_canvas.create_window(xpos, ypos, window=ci)
                self.device.add_subscriber(button, ci.update_value)
                xpos += 20 * self.scaling
            ypos += 30 * self.scaling
            xpos = 10 * self.scaling

        axes = self.device.get_axes()
        if len(axes) > 0:
            self.controls_canvas.create_text(0, ypos, text="Axes", anchor="nw")
            ypos += 10
            for i, axis in enumerate(self.device.get_axes()):
                if i%2 == 0:
                    xpos = 80 * self.scaling
                    ypos += 25 * self.scaling
                ci = ControlIndicatorAxis(self, axis)
                self.controls_canvas.create_window(xpos, ypos, window=ci)
                self.device.add_subscriber(axis, ci.update_value)
                xpos += 160 * self.scaling
            ypos += 30 * self.scaling
            xpos = 10 * self.scaling



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
            self._buttons[bi] = Button(f"B {bi}")

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

    def get_buttons(self):
        return self._buttons.values()

    def get_axes(self):
        return self._axes.values()

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

class ControlIndicatorBase:

    def update_value(self, value):
        pass

    def __init__(self, master, control):
        self.control = control
        self._scaling = customtkinter.ScalingTracker.get_widget_scaling(master)


class ControlIndicatorText(ControlIndicatorBase, customtkinter.CTkLabel):

    def update_value(self, value):
        self.configure(
            text=f"{self.control.name}: {value}",
            # text_color_disabled="green"
        )

    def __init__(self, master, control, **kwargs):
        ControlIndicatorBase.__init__(self, master, control)
        customtkinter.CTkLabel.__init__(self, master, **kwargs)
        self.configure(
            text=f"{self.control.name}: {self.control.value}",
            state='disabled'
        )


class ControlIndicatorButton(ControlIndicatorBase, customtkinter.CTkCanvas):
    bgs = {
        True: "green1",
        False: "darkgray",
    }

    def __init__(self, master, control, size=20, **kwargs):
        ControlIndicatorBase.__init__(self, master, control)
        customtkinter.CTkCanvas.__init__(
            self,
            master=master,
            width=size*self._scaling,
            height=size*self._scaling,
            bg=master["background"],
            bd=0,
            highlightthickness=0
        )
        number = [int(s) for s in control.name.split() if s.isdigit()][0]
        center = int(size/2*self._scaling)
        radius = int(size/2*self._scaling)
        self.circle = self.create_aa_circle(center, center, radius, fill="darkgray")
        self.text = self.create_text(center, center, text=str(number), anchor="center")

    def update_value(self, value):
        if value:
            self.bgs[False] = "darkseagreen"
        self.itemconfig(self.circle, fill=self.bgs.get(value, "black"))

class ControlIndicatorAxis(ControlIndicatorBase, customtkinter.CTkCanvas):
    def __init__(self, master, control:Axis, thickness=20, length=150, **kwargs):
        ControlIndicatorBase.__init__(self, master, control)
        customtkinter.CTkCanvas.__init__(
            self,
            master=master,
            width=length*self._scaling,
            height=thickness*self._scaling,
            bg=master["background"],
            bd=0,
            highlightthickness=0
        )
        self.thickness = thickness*self._scaling
        self.length = length*self._scaling
        x_center = int(length/2*self._scaling)
        y_center = int(thickness/2 *self._scaling)
        self.range = (self.control.max - self.control.min)
        self.used_range_min = control.value
        self.used_range_max = control.value
        self.background = self.create_rectangle(0,0,self.length, self.thickness, fill="darkgray")
        self.used_range = self.create_rectangle(
            self.used_range_min/self.range*self.length + 1,
            1,
            self.used_range_max/self.range*self.length,
            self.thickness,
            fill="darkseagreen",
            outline=""
        )
        self.indicator = self.create_rectangle(self.length/2-1,1,self.length/2+1, self.thickness-1, fill="green1", outline="")
        self.text = self.create_text(x_center, y_center, text=str(control.name), anchor="center")

    def update_value(self, value):
        self.used_range_min = min(self.used_range_min, value)
        self.used_range_max = max(self.used_range_max, value)
        relval = value / self.range
        self.coords(
            self.indicator,  # x0
            relval*self.length-1,  # y0
            1,  # x1
            int(relval*self.length)+1,  # y1
            self.thickness-1
        )
        self.coords(
            self.used_range,
            self.used_range_min / self.range * self.length + 1,
            1,
            self.used_range_max / self.range * self.length,
            self.thickness
        )