import datetime
import os
from tempfile import TemporaryDirectory
import requests
import json
from packaging.version import Version, InvalidVersion
from make import cmd
from dotenv import load_dotenv


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


def check_for_update():
    ans_json = request_latest()
    if ans_json.get("status", None) != "200":
        return None
    tag_name = ans_json.get("tag_name")
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

    create_backup(str(datetime.datetime.now()).replace(":", ""))

    ans_json = request_latest()
    zipball_url = ans_json.get('zipball_url')
    with TemporaryDirectory() as temp_dir:
        update_file = f"{temp_dir}\\update.zip"
        update_dir = os.path.join(temp_dir, "update")
        os.mkdir(update_dir)

        # download archive
        token = os.getenv('GITHUB_TOKEN')
        if token:
            header = f"Authorization: Bearer {os.getenv('GITHUB_TOKEN')}"
            cmd(f"curl -H \"{header}\" -L \"{zipball_url}\" -o \"{update_file}\"")  # with authentication token
        else:
            cmd(f"curl -L \"{zipball_url}\" -o \"{update_file}\"")  # without authentication token

        cmd(f"tar -xf \"{update_file}\" -C \"{update_dir}\"")  # unpack archive

        directory = None
        for d in os.listdir(update_dir):
            directory = os.path.join(update_dir, d)
            if os.path.isdir(directory):
                break

        cmd(f"xcopy \"{directory}\" \"{os.getcwd()}\" /s /y")  # copy files

    # write girev
    with open("gitrev.py", 'w') as f:
        f.write(f"gitrev = \"{ans_json.get('tag_name')}\"\n")


def main():
    if check_for_update():
        update()


if __name__ == "__main__":
    main()
