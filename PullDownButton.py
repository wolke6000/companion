import customtkinter
from typing import Callable, Any, Union
from customtkinter.windows.widgets.core_widget_classes import DropdownMenu

class PullDownButton(customtkinter.CTkButton):

    def __init__(self, master: Any, text: str = "PullDownButton", values: Union[dict[str, Callable] | None ]= None,  **kwargs):

        super().__init__(
            master=master,
            text=text,
            command=self._open_dropdown_menu,
            **kwargs,
        )

        self._values = values

        self._dropdown_menu = DropdownMenu(
            master=self,
            values=list(self._values.keys()),
            command=self._dropdown_callback,
            fg_color=self._fg_color,
            hover_color=self._hover_color,
            text_color=self._text_color,
            # font=dropdown_font
        )

    def _open_dropdown_menu(self):
        self._dropdown_menu.open(
            self.winfo_rootx(),
            self.winfo_rooty() + self._apply_widget_scaling(self._current_height + 0)
        )

    def _dropdown_callback(self, value: str):
        self._values[value]()

def main():

    def fun1():
        print("fun1() called!")

    def fun2():
        print("fun2() caled!")

    tk = customtkinter.CTk()

    PullDownButton(
        master=tk,
        values={
            "Function 1": fun1,
            "Function 2": fun2,
        }
    ).grid()

    tk.mainloop()


if __name__ == "__main__":
    main()
