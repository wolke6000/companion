import os
import subprocess
import sys
from pathlib import Path
import requests
import json
import logging
from cryptography.exceptions import InvalidSignature
from packaging.version import Version, InvalidVersion
from make import cmd
from dotenv import load_dotenv
from cryptography.hazmat.primitives import serialization
from tkinter import messagebox


def verify_manifest(manifest_bytes, signature_bytes):
    logging.debug(f"verifying manifest...")
    public_key = serialization.load_pem_public_key(
        b"""
    -----BEGIN PUBLIC KEY-----
    MCowBQYDK2VwAyEAbXhZyz71RvNnZl8qSzkv8uxCQx57f3RHHz6qmHWQfv8=
    -----END PUBLIC KEY-----
        """
    )
    public_key.verify(signature_bytes, manifest_bytes)
    logging.info(f"manifest verified")

def request_latest():
    logging.debug(f"requesting latest version...")
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
    release = json.loads(ans.text)
    logging.info(f"latest version found: \"{release['tag_name']}\"")
    return release

def get_latest_prerelease():
    logging.debug(f"requesting latest version...")
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
            logging.info(f"latest firmware found: \"{release['tag_name']}\"")
            return release
    logging.error(f"no latest firmware found!")
    messagebox.showerror(
        title="No latest version found!",
        message="Could not request latest version from online repository!"
    )
    return None


def check_for_update():
    logging.debug(f"checking for update...")
    ans_json = get_latest_prerelease()
    tag_name = ans_json.get("tag_name")
    return tag_name
    latest_version = Version(tag_name)
    logging.debug(f"latest version in online repository is \"{latest_version}\"")

    try:
        from gitrev import gitrev  # noqa
        logging.debug(f"current local version is \"{gitrev}\"")
    except ModuleNotFoundError:
        logging.error(f"current local version could not be found (gitrev module not found), let's update")
        return tag_name  # Without gitrev file, we don't know our version. Let's update!

    try:
        gitrev_version = Version(gitrev)
    except InvalidVersion:
        return tag_name  # gitrev version is invalid. Let's update!
    logging.error(f"current local version is invalid, let's update")

    if latest_version > gitrev_version:
        logging.debug(f"latest version in online repository newer than current local version, let's update")
        return tag_name
    else:
        return None


def update():
    ans_json = get_latest_prerelease()
    update_file = None
    manifest_json_url = None
    manifest_sig_url = None
    for asset in ans_json['assets']:
        if all([x in asset['name'] for x in [".exe", "Companion_Setup_"]]):
            download_url = asset['browser_download_url']
            logging.debug(f"download url = \"{download_url}\"")
            update_file = os.path.basename(download_url)
        elif asset['name'] == "manifest.json":
            manifest_json_url =  asset['browser_download_url']
            logging.debug(f"manifest json url = \"{manifest_json_url}\"")
        elif asset['name'] == "manifest.sig":
            manifest_sig_url = asset['browser_download_url']
            logging.debug(f"manifest sig url = \"{manifest_sig_url}\"")

    files_not_found_in_assets = list()
    if update_file is None:
        files_not_found_in_assets.append("Companion Setup file")
        logging.error(f"Companion Setup file not found in release assets")
    if manifest_json_url is None:
        files_not_found_in_assets.append("manifest.json")
        logging.error(f"\"manifest.json\" not found in release assets")
    if manifest_sig_url is None:
        files_not_found_in_assets.append("manifest.sig")
        logging.error(f"\"manifest.sig\" not found in release assets")
    if len(files_not_found_in_assets) > 0:
        messagebox.showerror(
            title=f"Some assets for the release are not available for download!",
            message=f"The following assets are not available for download in the release\n"
                    f"{', '.join(files_not_found_in_assets)}\n"
                    f"Update will be aborted"
        )
        return

    update_dir = Path(os.environ["LOCALAPPDATA"]) / "Switchology" / "Updater"
    update_dir.mkdir(parents=True, exist_ok=True)
    setup_path = update_dir / update_file
    manifest_json_path = update_dir / 'manifest.json'
    manifest_sig_path = update_dir / 'manifest.sig'

    # download setup and manifest
    token = os.getenv('GITHUB_TOKEN')
    if token:  # with authentication token
        logging.debug(f"downloading files without token...")
        header = f"Authorization: Bearer {os.getenv('GITHUB_TOKEN')}"
        cmd(f"curl -H \"{header}\" -L \"{download_url}\" -o \"{setup_path}\"")
        cmd(f"curl -H \"{header}\" -L \"{manifest_json_url}\" -o \"{manifest_json_path}\"")
        cmd(f"curl -H \"{header}\" -L \"{manifest_sig_url}\" -o \"{manifest_sig_path}\"")
    else:  # without authentication token
        logging.debug(f"downloading files with token...")
        cmd(f"curl -L \"{download_url}\" -o \"{setup_path}\"")
        cmd(f"curl -L \"{manifest_json_url}\" -o \"{manifest_json_path}\"")
        cmd(f"curl -L \"{manifest_sig_url}\" -o \"{manifest_sig_path}\"")
    logging.info(f"update files downloaded!")

    # verify signature, throws exception if the signature isn't valid:
    logging.debug("verifying download signature")
    # https://cryptography.io/en/latest/hazmat/primitives/asymmetric/dsa/#verification
    try:
        with open(manifest_json_path, "rb") as fjson, open(manifest_sig_path, "rb") as fsig:
             verify_manifest(fjson.read(), fsig.read())
    except InvalidSignature:
        messagebox.showerror(
            title=f"The signature of the downloaded setup file in invalid!",
            message=f"The signature of the downloaded setup file in invalid!\n"
                    f"Update will be aborted"
        )
        logging.error("download signature is invalid!")
        return
    logging.info("download signature is valid!")

    # run setup
    logging.info("running setup...")
    setup_log_path = os.path.join(os.getcwd(), "setuplog.txt")
    subprocess.Popen(
        [
            setup_path,
            # "/VERYSILENT",
            # "/SUPPRESSMSGBOXES",
            # "/NORESTART",
            # "/CLOSEAPPLICATIONS",
            f"/LOG={setup_log_path}"
        ]
    )
    logging.info("shutting down")
    sys.exit(0)


def main():
    if check_for_update():
        update()


if __name__ == "__main__":
    main()
