import os.path
from PIL import ImageTk, Image
from customtkinter import CTkImage

def icon(icon_name: str, width_height: tuple[int, int] | None = None):
    image = Image.open(os.path.join("res", "icons", f"{icon_name}.png"))
    return CTkImage(image, image)