#!/usr/bin/python

import subprocess
import re
import os

from nbd import NbdMount as nbd
from nbd import trycmd

import configdrive

root_path = '/home/ubuntu/tvault-mounts/'


def _(*args):
    return str(args[0])


class log():
    def info(self, *arg):
        print arg[0]

    def exception(self, *arg):
        print arg[0]

    def error(self, *arg):
        print arg[0]

    def debug(self, *arg):
        print arg[0]

    def critical(self, *arg):
        print arg[0]


LOG = log()


def getfdisk_output(mountpath=None):
    partitions = []
    cmdspec = ["sudo", "fdisk", "-l", ]
    if mountpath:
        cmdspec.append(str(mountpath))

    LOG.info(_(" ".join(cmdspec)))
    #stdout_value = check_output(cmdspec, stderr=subprocess.STDOUT)
    process = subprocess.Popen(cmdspec,
                               stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE,
                               bufsize=-1,
                               close_fds=True,
                               shell=False)

    stdout_value, stderr_value = process.communicate()
    parse = False
    for line in stdout_value.split("\n"):
        if parse:
            partition = {}
            fields = line.split()
            if (len(fields) == 0):
                continue
            index = 0
            partition["Device Name"] = fields[index]
            index += 1
            if fields[index] == "*":
                partition["Boot Device"] = str(True)
                index += 1
            else:
                partition["Boot Device"] = str(False)
            partition["start"] = fields[index]
            index += 1
            partition["end"] = fields[index]
            index += 1
            partition["blocks"] = fields[index].strip("+")
            index += 1
            partition["id"] = fields[index].lower()
            index += 1
            partition["system"] = " ".join(fields[index:])
            index += 1
            if len(re.findall(r'\d+', partition['start'])) and\
               len(re.findall(r'\d+', partition['end'])) and\
               len(re.findall(r'\d+', partition['blocks'])):
                partitions.append(partition)

        if "Device" in line and "Boot" in line:
            parse = True
    return partitions


def getgptdisk_output(mountpath=None):
    partitions = []
    cmdspec = ["sudo", "parted", "-s", ]
    if mountpath:
        cmdspec.append(str(mountpath))

    cmdspec.append("print")

    LOG.info(_(" ".join(cmdspec)))
    process = subprocess.Popen(cmdspec,
                               stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE,
                               bufsize=-1,
                               close_fds=True,
                               shell=False)

    stdout_value, stderr_value = process.communicate()
    parse = False
    if not process.returncode:
        for line in stdout_value.split("\n"):
            if parse:
                partition = {}
                fields = line.split()
                if (len(fields) == 0):
                    continue
                index = 0
                partition["Number"] = fields[index]
                index += 1
                partition["start"] = fields[index]
                index += 1
                partition["end"] = fields[index]
                index += 1
                partition["size"] = fields[index]
                index += 1
                partition["filesystem"] = fields[index].lower()
                index += 1
                partition["name"] = " ".join(fields[index:])
                index += 1

                if "0.00B" in partition['start']:
                    partition["Device Name"] = mountpath
                else:
                    partition["Device Name"] = mountpath + partition['Number']

                partitions.append(partition)

            if "Number" in line and "Start" in line and "End" in line and \
                    "Size" in line and "File system" in line and "Flags" in line:
                parse = True
    else:
        partition = {}
        partition["Device Name"] = mountpath
        partitions.append(partition)

    return partitions


def mountdevice(devname, mntpath):
    mountoptions = [[], ["-o", "nouuid"], ["-o", "ro"], ["-o", "ro,noload"]]

    try:
        for opt in mountoptions:
            cmdspec = ["sudo", "mount", ]
            cmdspec += opt
            cmdspec += [devname, mntpath]
            process = subprocess.Popen(cmdspec,
                                       stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE,
                                       bufsize=-1,
                                       close_fds=True,
                                       shell=False)

            stdout_value, stderr_value = process.communicate()

            if process.returncode == 0:
                return
    except BaseException:
        pass


def lvtodev():
    cmdspec = ["sudo", "lvs", "--noheading", "-o", "lv_path,devices"]
    process = subprocess.Popen(cmdspec,
                               stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE,
                               bufsize=-1,
                               close_fds=True,
                               shell=False)

    stdout_value, stderr_value = process.communicate()

    lv2pv = {}
    for line in stdout_value.split("\n"):
        if len(line.split()) >= 2:
            lv = line.split()[0]
            dev = line.split()[1].split("(")[0]

            if lv not in lv2pv:
                lv2pv[lv] = set([])

            lv2pv[lv].add(dev)

    return lv2pv


def mountvolumes():
    lv2pv = lvtodev()

    cmdspec = ["sudo", "vgscan", ]

    LOG.info(_(" ".join(cmdspec)))
    process = subprocess.Popen(cmdspec,
                               stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE,
                               bufsize=-1,
                               close_fds=True,
                               shell=False)

    stdout_value, stderr_value = process.communicate()

    cmdspec = ["sudo", "lvdisplay", "-c"]

    LOG.info(_(" ".join(cmdspec)))
    process = subprocess.Popen(cmdspec,
                               stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE,
                               bufsize=-1,
                               close_fds=True,
                               shell=False)

    stdout_value, stderr_value = process.communicate()

    mountspath = os.path.join(root_path, "mounts")
    if process.returncode == 0:
        for line in stdout_value.split("\n"):
            fields = line.split(":")
            if len(fields) == 0:
                continue

            lvpath = fields[0].strip()
            if os.path.exists(lvpath):
                volume = os.path.split(lvpath)[1]
                vgname = fields[1]

                vmname = None
                for fsdev, details in maps.iteritems():
                    if 'nbd' in details and details['nbd'] in lv2pv[lvpath]:
                        vmname = details['vm']
                        break

                if not vmname:
                    continue

                vmpath = os.path.join(mountspath, vmname)
                try:
                    os.mkdir(vmpath)
                except BaseException:
                    pass

                vgpath = os.path.join(vmpath, vgname)
                try:
                    os.mkdir(vgpath)
                except BaseException:
                    pass

                mntpath = os.path.join(vgpath, volume)
                try:
                    os.mkdir(mntpath)
                except BaseException:
                    pass

                mountdevice(lvpath, mntpath)


partitions = []

vms, maps = configdrive.readconfigdrive()

for i in range(1, 26):
    diskstr = "/dev/" + "vd" + chr(ord('a') + i)
    if os.path.exists(diskstr):
        partitions += getgptdisk_output(diskstr)
        #partitions += getfdisk_output(diskstr)

# create sub directories for each VM by guid. We will need to add VM name later
for vm in vms:
    mntpath = os.path.join(root_path, "mounts")
    mntpath = os.path.join(mntpath, vm)
    try:
        os.mkdir(mntpath)
    except BaseException:
        pass

for part in partitions:
    image_path = os.path.join(root_path,
                              part["Device Name"].split("/")[2] + ".qcow2")
    cmdspec = ["sudo", "qemu-img", "create", "-f", "qcow2", "-b",
               part["Device Name"],
               image_path]
    LOG.info(_(" ".join(cmdspec)))
    process = subprocess.Popen(cmdspec,
                               stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE,
                               bufsize=-1,
                               close_fds=True,
                               shell=False)

    stdout_value, stderr_value = process.communicate()

    mntpath = os.path.join(root_path, "mounts")
    fsdevname = part["Device Name"].split("/")[2][0:3]
    partnumber = part["Device Name"].split("/")[2][3:]
    vmdevname = maps[fsdevname]['vmdisk']
    mntpath = os.path.join(mntpath, maps[fsdevname]['vm'])
    try:
        os.mkdir(mntpath)
    except BaseException:
        pass
    mntpath = os.path.join(mntpath, vmdevname + str(partnumber) + ".mnt")
    os.mkdir(mntpath)

    nbddevice = nbd(image_path, None)
    nbddevice.get_dev()

    mountdevice(nbddevice.device, mntpath)
    maps[fsdevname]['nbd'] = nbddevice.device

mountvolumes()
