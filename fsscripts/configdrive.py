import json
import subprocess
import re
import time


def readconfigdrive():
    vms = []
    maps = {}
    try:
        mntpath = "/root/mnt"
        devname = "/dev/sr0"
        cmdspec = ["sudo", "mount", ]
        cmdspec += [devname, mntpath]
        process = subprocess.Popen(cmdspec,
                                   stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE,
                                   bufsize=-1,
                                   close_fds=True,
                                   shell=False)

        stdout_value, stderr_value = process.communicate()

        if process.returncode:
            return vms, maps

        time.sleep(10)
        with open("/root/mnt/diskfiles", "r") as f:
            vmdiskmaps = json.loads(f.read())
            for vm, diskmaps in vmdiskmaps.iteritems():
                vms.append(vm)
                for path, disk in diskmaps.iteritems():
                    p = re.compile("_vd[a-z]")
                    vmdisk = p.search(path).group().strip("_")
                    maps[disk] = {'vm': vm, 'vmdisk': vmdisk}
        return vms, maps
    finally:
        try:
            devname = "/dev/sr0"
            cmdspec = ["sudo", "umount", ]
            cmdspec += [devname]
            process = subprocess.Popen(cmdspec,
                                       stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE,
                                       bufsize=-1,
                                       close_fds=True,
                                       shell=False)

            stdout_value, stderr_value = process.communicate()

        except BaseException:
            pass
    return vms, maps
