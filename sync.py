#!/usr/bin/env python

import argparse
import logging
import sys
import os.path
import time
import yaml
import subprocess

import code

logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
)
_LOGGER = logging.getLogger("rclouned.main")
_CONFIG = {
    "folder": None,
    "remote": None,
    "subdir": "",
    "options": "",
    "interval": 90,
    "dryrun": False,
    "careful": False,
}


class ConfigException(Exception):
    pass


class SyncException(Exception):
    pass


class Sync:
    def __init__(self, configuration):
        self.configuration = configuration
        self.logger = logging.getLogger("rclouned.syncer")

    def config(self, key):
        if key in self.configuration:
            return self.configuration[key]
        else:
            return None

    def acquire_lock(self):
        i = 0
        while os.path.exists(self.config("folder") + ".rclouned/sync.tmp/"):
            i += 1
            self.logger.info(
                "Sync Lock exists. Check whether this is desired and otherwise remove the .rclouned/sync.tmp/ folder. Waiting."
            )
            time.sleep(10 + i ** 2)
        os.mkdir(self.config("folder") + ".rclouned/sync.tmp/")

    def release_lock(self):
        try:
            os.rmdir(self.config("folder") + ".rclouned/sync.tmp/")
        except OSError as e:
            self.logger.warning("Failed to remove Sync Lock.")
            self.logger.exception(e)

    def exec_cmd(self, cmd, check_ec=True):
        self.logger.debug("Running an external command: " + str(cmd))
        exe = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=check_ec,
        )
        self.logger.debug(
            "External command returned with exit code "
            + str(exe.returncode)
            + ", output:"
        )
        self.logger.debug(exe.stdout)
        return exe.stdout

    def exec_rclone(self, cmd, check_ec=True):
        opts = list(filter(lambda x: len(x) > 0, self.config("options").split(" ")))
        if self.config("dryrun") and cmd[0] != "check":
            opts.append("--dry-run")
        return self.exec_cmd(["rclone"] + opts + cmd, check_ec=check_ec)

    def load_last_sync(self):
        try:
            with open(self.config("folder") + ".rclouned/lastsync.txt", "r") as file:
                self.lastsync = time.strptime(
                    file.read().splitlines()[0].strip(), "%Y-%m-%d %H:%M:%S"
                )
        except FileNotFoundError:
            self.lastsync = time.localtime(0)

    def run_check(self):
        self.syncstart = time.strftime("%Y-%m-%d %H:%M:%S")
        cmd = [
            "check",
            "--differ",
            self.config("folder") + ".rclouned/sync.tmp/diff.txt",
            "--missing-on-dst",
            self.config("folder") + ".rclouned/sync.tmp/dst.txt",
            "--missing-on-src",
            self.config("folder") + ".rclouned/sync.tmp/src.txt",
            "--exclude",
            ".rclouned/**",
            self.config("remote") + ":" + self.config("subdir"),
            self.config("folder"),
        ]
        self.exec_rclone(cmd, check_ec=False)

        with open(self.config("folder") + ".rclouned/sync.tmp/diff.txt", "r") as file:
            self.diff = [str.strip() for str in file.read().splitlines()]
        with open(self.config("folder") + ".rclouned/sync.tmp/dst.txt", "r") as file:
            self.dst = [str.strip() for str in file.read().splitlines()]
        with open(self.config("folder") + ".rclouned/sync.tmp/src.txt", "r") as file:
            self.src = [str.strip() for str in file.read().splitlines()]

        os.remove(self.config("folder") + ".rclouned/sync.tmp/diff.txt")
        os.remove(self.config("folder") + ".rclouned/sync.tmp/dst.txt")
        os.remove(self.config("folder") + ".rclouned/sync.tmp/src.txt")

    def get_modtimes(self):
        self.local_check = {}
        self.remote_check = {}

        for file in self.diff:
            self.local_check[file] = None
            self.remote_check[file] = None
        for file in self.dst:
            self.remote_check[file] = None
        for file in self.src:
            self.local_check[file] = None

        with open(
            self.config("folder") + ".rclouned/sync.tmp/local_check.txt", "w"
        ) as file:
            file.write("\n".join(self.local_check.keys()))

        cmd = [
            "lsf",
            "--format",
            "pt",
            "-R",
            "--files-from",
            self.config("folder") + ".rclouned/sync.tmp/local_check.txt",
            self.config("folder"),
        ]
        local_modtimes = self.exec_rclone(cmd)
        for line in [str.strip() for str in local_modtimes.splitlines()]:
            key, modtime = line.split(";")
            self.local_check[key] = time.strptime(modtime, "%Y-%m-%d %H:%M:%S")
        os.remove(self.config("folder") + ".rclouned/sync.tmp/local_check.txt")

        with open(
            self.config("folder") + ".rclouned/sync.tmp/remote_check.txt", "w"
        ) as file:
            file.write("\n".join(self.remote_check.keys()))

        cmd = [
            "lsf",
            "--format",
            "pt",
            "-R",
            "--files-from",
            self.config("folder") + ".rclouned/sync.tmp/remote_check.txt",
            self.config("remote") + ":" + self.config("subdir"),
        ]
        remote_modtimes = self.exec_rclone(cmd)
        for line in [str.strip() for str in remote_modtimes.splitlines()]:
            key, modtime = line.split(";")
            self.remote_check[key] = time.strptime(modtime, "%Y-%m-%d %H:%M:%S")
        os.remove(self.config("folder") + ".rclouned/sync.tmp/remote_check.txt")

    def sort(self):
        conflict_suffix = "_conflict-" + time.strftime("%Y%m%d-%H%M%S")
        self.upload = []
        self.download = []
        self.local_move = []
        self.local_backup = []
        self.remote_backup = []

        for file in self.diff:
            if (
                self.local_check[file] >= self.lastsync
                and self.remote_check[file] < self.lastsync
            ):
                self.upload.append(file)
                if self.config("careful"):
                    self.remote_backup.append(file)
            elif (
                self.local_check[file] < self.lastsync
                and self.remote_check[file] >= self.lastsync
            ):
                self.download.append(file)
                if self.config("careful"):
                    self.local_backup.append(file)
            else:
                self.local_move.append([file, file + conflict_suffix])
                self.download.append(file)
                self.upload.append(file + conflict_suffix)

        for file in self.src:  # missing on remote
            if self.local_check[file] >= self.lastsync:
                self.upload.append(file)
            else:
                self.local_backup.append(file)

        for file in self.dst:  # missing on local
            if self.remote_check[file] >= self.lastsync:
                self.download.append(file)
            else:
                self.remote_backup.append(file)

    def log_summary(self):
        self.logger.info("SYNC PLAN:")
        self.logger.info("Local files to move: " + str(self.local_move))
        self.logger.info("Local files to backup: " + str(self.local_backup))
        self.logger.info("Remote files to backup: " + str(self.remote_backup))
        self.logger.info("Files to upload: " + str(self.upload))
        self.logger.info("Files to download: " + str(self.download))

    def action(self):
        backup_prefix = ".rclouned/backups/" + time.strftime("%Y%m%d-%H%M%S") + "/"

        if not self.config("dryrun"):
            for file in self.local_move:
                self.exec_cmd(
                    [
                        "mv",
                        self.config("folder") + file[0],
                        self.config("folder") + file[1],
                    ]
                )

        if len(self.local_backup):
            with open(
                self.config("folder") + ".rclouned/sync.tmp/local_backup.txt", "w"
            ) as file:
                file.write("\n".join(self.local_backup))
            cmd = [
                "copy",
                "--files-from",
                self.config("folder") + ".rclouned/sync.tmp/local_backup.txt",
                self.config("folder"),
                self.config("folder") + backup_prefix,
            ]
            self.exec_rclone(cmd)
            cmd = [
                "delete",
                "--files-from",
                self.config("folder") + ".rclouned/sync.tmp/local_backup.txt",
                self.config("folder"),
                "--rmdirs",
            ]
            self.exec_rclone(cmd)
            os.remove(self.config("folder") + ".rclouned/sync.tmp/local_backup.txt")

        if len(self.remote_backup):
            with open(
                self.config("folder") + ".rclouned/sync.tmp/remote_backup.txt", "w"
            ) as file:
                file.write("\n".join(self.remote_backup))
            cmd = [
                "copy",
                "--files-from",
                self.config("folder") + ".rclouned/sync.tmp/remote_backup.txt",
                self.config("remote") + ":" + self.config("subdir"),
                self.config("remote") + ":" + self.config("subdir") + backup_prefix,
            ]
            self.exec_rclone(cmd)
            cmd = [
                "delete",
                "--files-from",
                self.config("folder") + ".rclouned/sync.tmp/remote_backup.txt",
                self.config("remote") + ":" + self.config("subdir"),
                "--rmdirs",
            ]
            self.exec_rclone(cmd)
            os.remove(self.config("folder") + ".rclouned/sync.tmp/remote_backup.txt")

        if len(self.upload):
            with open(
                self.config("folder") + ".rclouned/sync.tmp/upload.txt", "w"
            ) as file:
                file.write("\n".join(self.upload))
            cmd = [
                "copy",
                "--files-from",
                self.config("folder") + ".rclouned/sync.tmp/upload.txt",
                self.config("folder"),
                self.config("remote") + ":" + self.config("subdir"),
            ]
            self.exec_rclone(cmd)
            os.remove(self.config("folder") + ".rclouned/sync.tmp/upload.txt")

        if len(self.download):
            with open(
                self.config("folder") + ".rclouned/sync.tmp/download.txt", "w"
            ) as file:
                file.write("\n".join(self.download))
            cmd = [
                "copy",
                "--files-from",
                self.config("folder") + ".rclouned/sync.tmp/download.txt",
                self.config("remote") + ":" + self.config("subdir"),
                self.config("folder"),
            ]
            self.exec_rclone(cmd)
            os.remove(self.config("folder") + ".rclouned/sync.tmp/download.txt")

    def set_last_sync(self):
        with open(self.config("folder") + ".rclouned/lastsync.txt", "w") as file:
            file.write(self.syncstart + "\n")

    def run(self):
        self.load_last_sync()
        self.run_check()
        self.get_modtimes()
        self.sort()
        self.log_summary()
        self.action()
        if not self.config("dryrun"):
            self.set_last_sync()
        # code.interact(local=dict(globals(), **locals()))


def wait_for_folder():
    i = 0
    while not os.path.exists(_CONFIG["folder"]):
        i += 1
        _LOGGER.info("Folder does not exist. Waiting.")
        time.sleep(10 + i ** 2)


def parse_config():
    global _CONFIG
    if not _CONFIG["folder"][-1] == "/":
        _CONFIG["folder"] += "/"
    if not os.path.isdir(_CONFIG["folder"] + ".rclouned/"):
        raise ConfigException(".rclouned folder not found.")
    if not os.path.isfile(_CONFIG["folder"] + ".rclouned/config.yaml"):
        raise ConfigException("Configuration file not found.")

    with open(_CONFIG["folder"] + ".rclouned/config.yaml", "r") as file:
        config = yaml.load(file, Loader=yaml.SafeLoader)
        _CONFIG |= config

    if not _CONFIG["remote"]:
        raise ConfigException("No remote configured.")


def sync_loop():
    # code.interact(local=dict(globals(), **locals()))
    while True:
        start = time.time()
        _LOGGER.info("Starting a new sync.")
        syncer = Sync(_CONFIG)
        syncer.acquire_lock()
        try:
            syncer.run()
        except SyncException as e:
            _LOGGER.warning("Error during sync!")
            _LOGGER.exception(e)
        finally:
            syncer.release_lock()
        runtime = time.time() - start
        _LOGGER.info("Sync ended. Runtime " + str(runtime) + "s.")
        if not (_CONFIG["interval"] - runtime) < 0:
            try:
                time.sleep(int(_CONFIG["interval"] - runtime))
            except KeyboardInterrupt:
                _LOGGER.info("KeyboardInterrupt detected. Quitting.")
                sys.exit(0)


def main():
    global _CONFIG
    parser = argparse.ArgumentParser()
    parser.add_argument("-v", "--verbose", action="count", default=0)
    parser.add_argument("folder", default=None, help="The folder to synchronize.")
    args = parser.parse_args()

    if args.verbose == 1:
        _LOGGER.setLevel(20)
    elif args.verbose >= 2:
        _LOGGER.setLevel(10)

    _CONFIG["folder"] = args.folder

    try:
        wait_for_folder()

        parse_config()

        sync_loop()
    except Exception as e:
        _LOGGER.critical("rclouned encountered a critical error and cannot continue.")
        _LOGGER.exception(e)
        sys.exit(1)


if __name__ == "__main__":
    main()
