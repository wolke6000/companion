import os
import subprocess
import tempfile
import shutil
import tkinter


def cmd(c):
    print(c)
    p = subprocess.run(c, shell=True, capture_output=True)
    print(p.stdout.decode('ascii'))
    return p.stdout.decode('ascii')


def main():
    p = subprocess.run(["git", "describe", "--always", "--broken"], capture_output=True)
    gitrev = p.stdout.decode('ascii').strip()
    with open("gitrev.py", 'w') as f:
        f.write(f"gitrev = \"{gitrev}\"\n")

    # cleans and creates directories
    buildrespath = os.path.join(os.getcwd(), "buildres")
    if not os.path.isdir(buildrespath):
        os.makedirs(buildrespath)
    buildpath = os.path.join(os.getcwd(), "builds", gitrev)
    try:
        shutil.rmtree(buildpath)
    except FileNotFoundError:
        pass
    os.makedirs(buildpath)

    # download python embeddable package
    python_name = "python-3.11.8-embed-amd64"
    python_zip_path = os.path.join(buildrespath, f'{python_name}.zip')
    if not os.path.isfile(python_zip_path):
        print(f"Downloading {python_name}.zip...")
        cmd(f"curl https://www.python.org/ftp/python/3.11.8/{python_name}.zip -o {python_zip_path}")

    # unzip python embeddable
    python_dir_path = os.path.join(buildpath, python_name)
    os.makedirs(python_dir_path)
    print(f"Extracing {python_name}.zip to {python_dir_path}...")
    cmd(f"tar -xf {python_zip_path} -C {python_dir_path}")
    python_path = os.path.join(python_dir_path, "python.exe")

    # Adjust the installation
    for filename in os.listdir(python_dir_path):
        if all(x in filename for x in ["python3", "._pth"]):
            with open(os.path.join(python_dir_path, filename), 'w') as f:
                f.write(
                    "python311.zip\n"
                    ".\n"
                    "..\n"
                    "import site"
                )
            break
    os.makedirs(os.path.join(f"{python_dir_path}", "DLLs"))

    # download and install pip
    get_pip_path = os.path.join(buildrespath, "get-pip.py")
    if not os.path.isfile(get_pip_path):
        print(f"Downloading get-pip.py...")
        cmd(f"curl https://bootstrap.pypa.io/get-pip.py -o {get_pip_path}")
    if cmd(f"{python_path} -m pip --version") == "":
        print("Running get-pip.py...")
        cmd(f"{python_path} {get_pip_path}")

    # copy repository
    with open(".gitignore", "r") as f:
        gitignore = "".join(f.readlines())
    for item_name in os.listdir(os.getcwd()):
        if item_name in gitignore and item_name not in ["gitrev.py", "res", ".gitignore"]:
            continue
        item_path = os.path.join(os.getcwd(), item_name)
        print(f"Copying {item_path}...")
        if os.path.isdir(item_path):
            cmd(f"xcopy \"{item_path}\\\" \"{os.path.join(buildpath, item_name)}\\\" /s /y")
        else:
            cmd(f"xcopy \"{item_path}\" \"{buildpath}\\*\"")

    # install requirements
    print("Installing requirements...")
    cmd(f"{python_path} -m pip install -r {os.path.join(buildpath, 'requirements.txt')}")

    # write batch file
    print("Writing batch file...")
    basewd = os.getcwd()
    os.chdir(buildpath)
    with open(os.path.join(f"{buildpath}", "Companion App.cmd"), "w") as f:
        f.write(f'start "" .\\{os.path.relpath(python_dir_path)}\pythonw.exe gui.py\n')
        f.write("exit 0")
    os.chdir(basewd)

    # write debug batch file
    print("Writing batch file...")
    basewd = os.getcwd()
    os.chdir(buildpath)
    with open(os.path.join(f"{buildpath}", "Companion App Debug Mode.cmd"), "w") as f:
        f.write(f'start "" .\\{os.path.relpath(python_dir_path)}\pythonw.exe gui.py -d --logfile \"log.txt\"\n')
        f.write("exit 0")
    os.chdir(basewd)

    # copy Tcl, Tk and Tkinter files
    root = tkinter.Tk()
    print("Copying Tcl files...")
    tcl_path = root.tk.exprstring('$tcl_library')
    cmd(f"xcopy \"{tcl_path}\" \"{os.path.join(buildpath, 'Lib', os.path.basename(tcl_path))}\\\" /s /y")
    print("Copying Tk files...")
    tk_path = root.tk.exprstring('$tk_library')
    cmd(f"xcopy \"{tk_path}\" \"{os.path.join(buildpath, 'Lib', os.path.basename(tk_path))}\\\" /s /y")
    tkinter_path = os.path.dirname(tkinter.__file__)
    cmd(f"xcopy \"{tkinter_path}\" \"{os.path.join(python_dir_path, 'Lib', 'site-packages', os.path.basename(tkinter_path))}\\\" /s /y")
    dlls_path = os.path.abspath(os.path.join(tkinter_path, os.pardir, os.pardir, "DLLs"))
    for file in ['tcl86t.dll', 'tk86t.dll', '_tkinter.pyd']:
        cmd(f"xcopy \"{os.path.join(dlls_path, file)}\" \"{buildpath}\\*\"")

    #zip it all up
    print("Compressing into archive...")
    # basewd = os.getcwd()
    # os.chdir(buildpath)
    # cmd(f"tar -acf \"{os.path.join(buildpath, gitrev)}.zip\" --directory==\"{buildpath}\" .")
    # cmd(f"Compress-Archive -Path {buildpath} -DestinationPath \"{os.path.join(buildpath, gitrev)}.zip\"")
    # os.chdir(basewd)
    shutil.make_archive(buildpath, "zip", buildpath)

    print("All done!")


if __name__ == '__main__':
    main()
