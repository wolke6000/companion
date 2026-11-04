import os
from dotenv import load_dotenv
import subprocess
import hashlib
import json
from datetime import datetime
import shutil
import tkinter


def cmd(c, check=False):
    print(c, flush=True)
    p = subprocess.run(c, shell=True, stdout=subprocess.PIPE, text=True, errors="replace")
    print(p.stdout, end="", flush=True)
    if check:
        p.check_returncode()
    return p.stdout


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    load_dotenv()

    p = subprocess.run(["git", "describe", "--always", "--broken"], stdout=subprocess.PIPE, check=True)
    gitrev = p.stdout.decode('ascii').strip()

    gitrev_sane = "".join(c for c in gitrev if c.isalnum() or c in [' ', '-', '_', '.']).rstrip()
    if not gitrev or gitrev_sane != gitrev:
        raise ValueError(f"Invalid build version: {gitrev!r}")

    with open("gitrev.py", 'w') as f:
        f.write(f"gitrev = \"{gitrev}\"\n")

    # cleans and creates directories
    buildrespath = os.path.join(os.getcwd(), "buildres")
    if not os.path.isdir(buildrespath):
        os.makedirs(buildrespath)
    buildpath = os.path.join(os.getcwd(), "builds", gitrev)
    staging_path = os.path.join(buildpath, "stage")
    try:
        shutil.rmtree(staging_path)
    except FileNotFoundError:
        pass
    os.makedirs(staging_path)

    # download python embeddable package
    python_name = "python-3.11.8-embed-amd64"
    python_zip_path = os.path.join(buildrespath, f'{python_name}.zip')
    if not os.path.isfile(python_zip_path):
        print(f"Downloading {python_name}.zip...")
        cmd(f"curl --fail --location --show-error https://www.python.org/ftp/python/3.11.8/{python_name}.zip -o {python_zip_path}", check=True)

    # unzip python embeddable
    python_dir_path = os.path.join(staging_path, python_name)
    os.makedirs(python_dir_path)
    print(f"Extracing {python_name}.zip to {python_dir_path}...")
    cmd(f"tar -xf {python_zip_path} -C {python_dir_path}", check=True)
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
        cmd(f"curl --fail --location --show-error https://bootstrap.pypa.io/get-pip.py -o {get_pip_path}", check=True)
    pip_check = subprocess.run([python_path, "-m", "pip", "--version"], capture_output=True)
    if pip_check.returncode != 0:
        print("Running get-pip.py...")
        cmd(f"{python_path} {get_pip_path}", check=True)

    # copy repository
    gitignore = ""
    with open(".gitignore", "r") as f:
        for line in f.readlines():
            if line.startswith("#"):
                continue
            gitignore += line
    for item_name in os.listdir(os.getcwd()):
        if item_name in gitignore and item_name not in ["gitrev.py", "res", ".gitignore", "settings.py"]:
            continue
        item_path = os.path.join(os.getcwd(), item_name)
        print(f"Copying {item_path}...")
        if os.path.isdir(item_path):
            cmd(f"xcopy \"{item_path}\\\" \"{os.path.join(staging_path, item_name)}\\\" /s /y", check=True)
        else:
            cmd(f"xcopy \"{item_path}\" \"{staging_path}\\*\"", check=True)

    # install requirements
    print("Installing requirements...")
    cmd(f"{python_path} -m pip install -r {os.path.join(staging_path, 'requirements.txt')}", check=True)

    # write batch file
    print("Writing batch file...")
    basewd = os.getcwd()
    os.chdir(staging_path)
    with open(os.path.join(f"{staging_path}", "Companion App.cmd"), "w") as f:
        f.write(f'start "" .\\{os.path.relpath(python_dir_path)}\pythonw.exe gui.py\n')
        f.write("exit 0")
    os.chdir(basewd)

    # write debug batch file
    print("Writing batch file...")
    basewd = os.getcwd()
    os.chdir(staging_path)
    with open(os.path.join(f"{staging_path}", "Companion App Debug Mode.cmd"), "w") as f:
        f.write(f'start "" .\\{os.path.relpath(python_dir_path)}\python.exe gui.py -d --logfile \"log.txt\"\n')
        f.write("exit 0")
    os.chdir(basewd)

    # copy Tcl, Tk and Tkinter files
    root = tkinter.Tk()
    print("Copying Tcl files...")
    tcl_path = root.tk.exprstring('$tcl_library')
    cmd(f"xcopy \"{tcl_path}\" \"{os.path.join(staging_path, 'Lib', os.path.basename(tcl_path))}\\\" /s /y", check=True)
    print("Copying Tk files...")
    tk_path = root.tk.exprstring('$tk_library')
    cmd(f"xcopy \"{tk_path}\" \"{os.path.join(staging_path, 'Lib', os.path.basename(tk_path))}\\\" /s /y", check=True)
    tkinter_path = os.path.dirname(tkinter.__file__)
    cmd(f"xcopy \"{tkinter_path}\" \"{os.path.join(python_dir_path, 'Lib', 'site-packages', os.path.basename(tkinter_path))}\\\" /s /y", check=True)
    dlls_path = os.path.abspath(os.path.join(tkinter_path, os.pardir, os.pardir, "DLLs"))
    for file in ['tcl86t.dll', 'tk86t.dll', '_tkinter.pyd']:
        cmd(f"xcopy \"{os.path.join(dlls_path, file)}\" \"{staging_path}\\*\"", check=True)

    # create installer
    print("creating installer...")
    iscc_path = os.environ.get("ISCC_PATH")
    cmd(f"\"{iscc_path}\" installer/setup.iss /Dgitrev={gitrev} /Dsrcdir=\"{staging_path}\"", check=True)

    installer_name = "Companion_Setup.exe"
    installer_path = os.path.join(buildpath, installer_name)

    # create manifest.json
    os.chdir(buildpath)
    print("creating manifest...")
    if os.path.exists("manifest.sig"):
        os.remove("manifest.sig")
    manifest = {
        "version": gitrev,
        "sha256": sha256_file(installer_path),
        "size": os.path.getsize(installer_path),
    }
    with open("manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, separators=(",", ":"), sort_keys=True)

    print("All done!")


if __name__ == '__main__':
    main()

