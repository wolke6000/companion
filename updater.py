import datetime
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import requests
import json
from packaging.version import Version, InvalidVersion
from make import cmd, sha256_file
from dotenv import load_dotenv
import hashlib
from cryptography.hazmat.primitives import serialization


def verify_manifest(manifest_bytes, signature_bytes):
    public_key = serialization.load_pem_public_key(
        b"""
    -----BEGIN PUBLIC KEY-----
    MCowBQYDK2VwAyEAbXhZyz71RvNnZl8qSzkv8uxCQx57f3RHHz6qmHWQfv8=
    -----END PUBLIC KEY-----
        """
    )
    public_key.verify(signature_bytes, manifest_bytes)

def request_latest():
    load_dotenv()
    owner = "wolke6000"
    repo = "companion"
    url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    token = os.getenv('GITHUB_TOKEN')
    if token:
        headers = {
            "Authorization": f"Bearer {os.getenv('GITHUB_TOKEN')}"
        }
    else:
        headers = None
    ans = requests.get(url, headers=headers)

    return json.loads(ans.text)

def get_latest_prerelease():
    load_dotenv()
    owner = "wolke6000"
    repo = "companion"
    url = f"https://api.github.com/repos/{owner}/{repo}/releases"
    token = os.getenv('GITHUB_TOKEN')
    if token:
        headers = {
            "Authorization": f"Bearer {os.getenv('GITHUB_TOKEN')}"
        }
    else:
        headers = None
    ans = requests.get(url, headers=headers)
    releases = json.loads(ans.text)
    releases.sort(key=lambda x: x["published_at"], reverse=True)
    for release in releases:
        if release["prerelease"]:
            return release

    return None


def check_for_update():
    ans_json = get_latest_prerelease()
    tag_name = ans_json.get("tag_name")
    return tag_name
    latest_version = Version(tag_name)

    try:
        from gitrev import gitrev  # noqa
    except ModuleNotFoundError:
        return tag_name  # Without gitrev file, we don't know our version. Let's update!

    try:
        gitrev_version = Version(gitrev)
    except InvalidVersion:
        return tag_name  # gitrev version is invalid. Let's update!

    if latest_version > gitrev_version:
        return tag_name
    else:
        return None


def create_backup(version):

    def build_file_list(directory):
        filelist = list()
        for file in os.listdir(directory):
            if file in gitignore and file not in ["gitrev.py", "res"]:
                continue
            file_path = os.path.join(directory, file)
            if "backup" in file_path:
                continue  # don't backup backups
            if os.path.isdir(file_path):
                filelist += build_file_list(file_path)
            else:
                filelist.append(file_path)
        return filelist

    with open(".gitignore", "r") as f:
        gitignore = "".join(f.readlines())

    backup_dir = os.path.join(os.getcwd(), "backup", version)
    if not os.path.exists(backup_dir) or not os.path.isdir(backup_dir):
        os.makedirs(backup_dir)

    for filepath in build_file_list(os.getcwd()):
        backup_filepath = os.path.join(backup_dir, os.path.relpath(filepath, os.getcwd()))
        backup_filedir = os.path.dirname(backup_filepath)
        if not os.path.exists(backup_filedir):
            os.makedirs(backup_filedir)
        cmd(f"xcopy \"{filepath}\" \"{backup_filedir}\" /y")  # copy files


def update():

    # create_backup(str(datetime.datetime.now()).replace(":", ""))

    ans_json = get_latest_prerelease()
    update_file = None
    manifest_json_url = None
    manifest_sig_url = None
    for asset in ans_json['assets']:
        if all([x in asset['name'] for x in [".exe", "Companion_Setup_"]]):
            download_url = asset['browser_download_url']
            update_file = os.path.basename(download_url)
        elif asset['name'] == "manifest.json":
            manifest_json_url =  asset['browser_download_url']
        elif asset['name'] == "manifest.sig":
            manifest_sig_url = asset['browser_download_url']

    if update_file is None:
        raise Exception
    if manifest_json_url is None:
        raise Exception
    if manifest_sig_url is None:
        raise Exception


    update_dir = Path(os.environ["LOCALAPPDATA"]) / "Switchology" / "Updater"
    update_dir.mkdir(parents=True, exist_ok=True)
    setup_path = update_dir / update_file
    manifest_json_path = update_dir / 'manifest.json'
    manifest_sig_path = update_dir / 'manifest.sig'

    # download setup and manifest
    token = os.getenv('GITHUB_TOKEN')
    if token:  # with authentication token
        header = f"Authorization: Bearer {os.getenv('GITHUB_TOKEN')}"
        cmd(f"curl -H \"{header}\" -L \"{download_url}\" -o \"{setup_path}\"")
        cmd(f"curl -H \"{header}\" -L \"{manifest_json_url}\" -o \"{manifest_json_path}\"")
        cmd(f"curl -H \"{header}\" -L \"{manifest_sig_url}\" -o \"{manifest_sig_path}\"")
    else:  # without authentication token
        cmd(f"curl -L \"{download_url}\" -o \"{setup_path}\"")
        cmd(f"curl -L \"{manifest_json_url}\" -o \"{manifest_json_path}\"")
        cmd(f"curl -L \"{manifest_sig_url}\" -o \"{manifest_sig_path}\"")

    # verify signature, throws exception if the signature isn't valid:
    # https://cryptography.io/en/latest/hazmat/primitives/asymmetric/dsa/#verification
    with open(manifest_json_path, "rb") as fjson, open(manifest_sig_path, "rb") as fsig:
         verify_manifest(fjson.read(), fsig.read())

    # run setup
    subprocess.Popen(
        [
            setup_path,
            # "/VERYSILENT",
            # "/SUPPRESSMSGBOXES",
            # "/NORESTART",
            # "/CLOSEAPPLICATIONS"
        ]
    )
    sys.exit(0)

    # write girev
    with open("gitrev.py", 'w') as f:
        f.write(f"gitrev = \"{ans_json.get('tag_name')}\"\n")


def main():
    if check_for_update():
        update()


if __name__ == "__main__":
    main()
