import subprocess
import os
import re
import time
from subprocess import call
from subprocess import check_call
from subprocess import check_output
import shutil
from os import remove, close
from contextlib import contextmanager

from Queue import Queue
from Queue import Queue, Empty
from threading import Thread
from tempfile import mkstemp

from workloadmgr import exception
from workloadmgr.openstack.common import log as logging
from workloadmgr.openstack.common.gettextutils import _
from workloadmgr import autolog

LOG = logging.getLogger(__name__)
Logger = autolog.Logger(LOG)

###
#     This file assumes that vmdk has MBR partition table. It iterates thru
#   all the partitions in the partition table and for each partition, it
#   discovers the file system and copies only the blocks that were allocated
#   by the file system.
#   Here is the algorithm to detect the blocks that were allocated by the
#   file system without reading the entire disk.
#   1. The algorithm works for extx class of file systems and assumes
#      intimate knowledge of the file system. We will leverage debugfs
#      (a slightly modified version) to explore the internal datastructures
#      of the file system.
#   2. First it copies the superblock of the file system but copying
#      part['start'], 400 blocks of extent from remote vmdk to local disk
#   3. Using debugfs, it explores the block size and number of block groups
#      of the file system
#   4. It then copies inode blocks and bitmap blocks from each block group
#   5. Using debugfs it opens the file system, identifies only allocated
#      blocks from the bitmap and copies those blocks from the remote
#      disk
##
"""
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
"""

##
# create_empty_vmdk() function as the name suggests creates an empty vmdk
# file at path specified by filepath. the size of the vmdk file is
# specified by capacity
##


def create_empty_vmdk(filepath, capacity):
    vix_disk_lib_env = os.environ.copy()
    vix_disk_lib_env['LD_LIBRARY_PATH'] = '/usr/lib/vmware-vix-disklib/lib64'

    # Create empty vmdk file
    try:
        cmdline = "trilio-vix-disk-cli -create "
        cmdline += "-cap " + str(capacity / (1024 * 1024))
        cmdline += " " + filepath
        check_output(
            cmdline.split(" "),
            stderr=subprocess.STDOUT,
            env=vix_disk_lib_env)
    except subprocess.CalledProcessError as ex:
        LOG.critical(_("cmd: %s resulted in error: %s") % (cmdline, ex.output))
        LOG.exception(ex)
        raise


def enqueue_output(out, queue):
    for line in iter(out.readline, b''):
        queue.put(line)
    out.close()

##
# mount_local_vmdk() mounts the vmdk at the path specified. It returns the
# mounted path
##


@contextmanager
def mount_local_vmdk(diskslist, mntlist, diskonly=False):
    vix_disk_lib_env = os.environ.copy()
    vix_disk_lib_env['LD_LIBRARY_PATH'] = '/usr/lib/vmware-vix-disklib/lib64'

    try:
        vmdkfiles = []
        with open(diskslist, 'r') as f:
            for line in f.read().split():
                vmdkfiles.append(line.rstrip().strip())

        processes = []
        mountpoints = {}
        for vmdkfile in vmdkfiles:

            try:
                fileh, listfile = mkstemp()
                close(fileh)
                with open(listfile, 'w') as f:
                    f.write(vmdkfile)

                cmdspec = [
                    "trilio-vix-disk-cli",
                    "-mount",
                    "-mountpointsfile",
                    mntlist,
                ]
                if diskonly:
                    cmdspec += ['-diskonly']
                cmdspec += [listfile]
                cmd = " ".join(cmdspec)
                LOG.info(_(cmd))
                process = subprocess.Popen(cmdspec,
                                           stdin=subprocess.PIPE,
                                           stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE,
                                           bufsize=-1,
                                           env=vix_disk_lib_env,
                                           close_fds=True,
                                           shell=False)

                queue = Queue()
                read_thread = Thread(
                    target=enqueue_output, args=(
                        process.stdout, queue))
                read_thread.daemon = True  # thread dies with the program
                read_thread.start()

                mountpath = None
                while process.poll() is None:
                    try:
                        try:
                            output = queue.get(timeout=5)
                            LOG.info(_(output))
                        except Empty:
                            continue
                        except Exception as ex:
                            LOG.exception(ex)

                        if output.startswith(
                                "Pausing the process until it is resumed"):
                            break
                    except Exception as ex:
                        LOG.exception(ex)

                if not process.poll() is None:
                    _returncode = process.returncode  # pylint: disable=E1101
                    if _returncode:
                        LOG.debug(_('Result was %s') % _returncode)
                        raise exception.ProcessExecutionError(
                            exit_code=_returncode,
                            stderr=process.stderr.read(),
                            cmd=cmd)
                with open(mntlist, 'r') as f:
                    for line in f:
                        line = line.strip("\n")
                        mountpoints[line.split(":")[0]] = line.split(":")[
                            1].split(";")

                LOG.info(_(mountpoints))
                process.stdin.close()
                processes.append(process)

            except Exception as ex:
                LOG.exception(ex)
                raise
            finally:
                if os.path.isfile(listfile):
                    os.remove(listfile)

        yield mountpoints
    except Exception as ex:
        LOG.exception(ex)
        raise
    finally:
        umount_local_vmdk(processes)

##
# unmounts a vmdk by sending signal 18 to the process that as suspended during mount process
##


def umount_local_vmdk(processes):
    for process in processes:
        process.send_signal(18)
        process.wait()

        _returncode = process.returncode  # pylint: disable=E1101

        if _returncode != 0:
            LOG.debug(_('Result was %s') % _returncode)
            raise exception.ProcessExecutionError(
                exit_code=_returncode,
                stderr=process.stderr.read())


def execute_cmd(cmdspec, env=None):
    process = subprocess.Popen(cmdspec,
                               stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE,
                               bufsize=-1,
                               env=env,
                               close_fds=True,
                               shell=False)
    # TODO: throw exception  on error?
    output, error = process.communicate()
    if process.returncode:
        raise exception.ProcessExecutionError(
            cmd=" ".join(cmdspec),
            description=error,
            exit_code=process.returncode)
    return output, error


def execute_debugfs(cmdspec):
    # Read the superblock and read the blocksize
    debugfs_env = {}
    debugfs_env['DEBUGFS_PAGER'] = '__none__'

    return execute_cmd(cmdspec, debugfs_env)


def populate_extents(hostip, username, password, vmspec, remotepath,
                     mountpath, extentsfile):

    # copy the boot record to a file
    vix_disk_lib_env = os.environ.copy()
    vix_disk_lib_env['LD_LIBRARY_PATH'] = '/usr/lib/vmware-vix-disklib/lib64'

    try:
        cmdspec = ["trilio-vix-disk-cli", "-downloadextents",
                   remotepath, "-extentfile", extentsfile,
                   "-host", hostip,
                   "-user", username,
                   "-password", password,
                   "-vm", vmspec,
                   mountpath]
        check_output(cmdspec, stderr=subprocess.STDOUT, env=vix_disk_lib_env)
    except subprocess.CalledProcessError as ex:
        LOG.critical(_("cmd: %s resulted in error: %s") % (cmdspec, ex.output))
        LOG.exception(ex)
        raise
##
# Copy an extent specified by start/count from remote disk to
# local disk.
##


def populate_extent(hostip, username, password, vmspec, remotepath,
                    mountpath, start, count):
    # copy the boot record to a file
    vix_disk_lib_env = os.environ.copy()
    vix_disk_lib_env['LD_LIBRARY_PATH'] = '/usr/lib/vmware-vix-disklib/lib64'

    try:
        cmdline = ["trilio-vix-disk-cli",
                   "-download", remotepath,
                   "-host", hostip,
                   "-user", username,
                   "-password", password,
                   "-vm", vmspec,
                   "-start", str(start),
                   "-count", str(count),
                   mountpath, ]
        check_output(cmdline, stderr=subprocess.STDOUT, env=vix_disk_lib_env)
    except subprocess.CalledProcessError as ex:
        LOG.critical(_("cmd: %s resulted in error: %s") % (cmdline, ex.output))
        LOG.exception(ex)
        raise


def populate_bootrecord(hostip, username, password, vmspec, remotepath,
                        mountpath, diskCapacity):
    diskCapacity = long(diskCapacity) - 400 * 512
    populate_extent(hostip, username, password, vmspec, remotepath,
                    mountpath, 0, 400)
    # GPT disks has second boot record at the end of the disk
    populate_extent(hostip, username, password, vmspec, remotepath,
                    mountpath, diskCapacity / 512, 400)

    return

##
# getfdisk_output():
# if the underlying disk is fdisk, read the partition table from the mounted disk
#
##


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

##
# getgptdisk_output():
#    if the underlying disk is gptdisk, read the partition table from
# the mounted disk
#
# Fdisk shows gpt partition as follows:
# stack@openstack01:~/gptsupport$ fdisk -l 1t.img
#
# WARNING: GPT (GUID Partition Table) detected on '1t.img'! The util fdisk doesn't support GPT. Use GNU Parted.
#
#
# Disk 1t.img: 1099.5 GB, 1099511627776 bytes
# 256 heads, 63 sectors/track, 133152 cylinders, total 2147483648 sectors
# Units = sectors of 1 * 512 = 512 bytes
# Sector size (logical/physical): 512 bytes / 512 bytes
# I/O size (minimum/optimal): 512 bytes / 512 bytes
# Disk identifier: 0x00000000
#
# Device Boot      Start         End      Blocks   Id  System
# 1t.img1               1  2147483647  1073741823+  ee  GPT
#
#
# A typical partition to support would be:
#
# stack@openstack01:~/gptsupport$ sgdisk -p 1t.img
# Disk 1t.img: 2147483648 sectors, 1024.0 GiB
# Logical sector size: 512 bytes
# Disk identifier (GUID): 006BE6CD-B6F1-4DBE-9CD5-8207D66A7BEE
# Partition table holds up to 128 entries
# First usable sector is 34, last usable sector is 2147483614
# Partitions will be aligned on 2048-sector boundaries
# Total free space is 900013290 sectors (429.2 GiB)
#
# Number  Start (sector)    End (sector)  Size       Code  Name
#   1            2048       147483614   70.3 GiB    8300  First
#   2       147484672       157483614   4.8 GiB     8300
#   3       157485056       247483614   42.9 GiB    8300  Second
#   4       247484416       347483614   47.7 GiB    8300  Third
#   5       347484160       447483614   47.7 GiB    8300  Forth
#   6       447483904       547483614   47.7 GiB    8300  Fifth
#   7       547483648       647483614   47.7 GiB    8300  Sixth
#   8       647485440       747483614   47.7 GiB    8300  Seventh
#   9       747485184       847483614   47.7 GiB    8300  Eighth
#  10       847484928       947483614   47.7 GiB    8300
#  11       947484672      1047483614   47.7 GiB    8300  Ninth
#  12      1047484416      1147483614   47.7 GiB    8300  Tenth
#  13      1147484160      1247483614   47.7 GiB    8300  Eleventh
#
##


def getgptdisk_output(mountpath=None):
    partitions = []
    cmdspec = ["sudo", "sgdisk", "-p", ]
    if mountpath:
        cmdspec.append(str(mountpath))

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
            partition["blocks"] = str((int(partition['end']) -
                                       int(partition['start']) + 1) / 2)
            index += 2
            partition["id"] = fields[index].lower()
            index += 1
            partition["system"] = " ".join(fields[index:])
            index += 1
            partitions.append(partition)

        if "Number" in line and "Start" in line and "End" in line and \
                "Size" in line and "Code" in line and "Name" in line:
            parse = True
    return partitions


def get_blockgroups(mountpath):

    try:
        # Read the superblock and read the blocksize
        blocksize = 4096
        blockgroups = ""
        cmdspec = ["/opt/stack/workloadmgr/debugfs/debugfs",
                   "-R", "stats -h", mountpath]
        superblock, error = execute_debugfs(cmdspec)

        # get the block size
        for line in superblock.split("\n"):
            LOG.info(_(line))
            if "Block size:" in line:
                blocksize = int(line.split(":")[1].strip())

        cmdspec = ["/opt/stack/workloadmgr/debugfs/debugfs",
                   "-R", "stats", mountpath]

        blockgroups, error = execute_debugfs(cmdspec)
    except Exception as ex:
        LOG.exception(_(ex))
        LOG.error(_("Cannot read block groups from %s") % mountpath)

    return blocksize, blockgroups


def get_usedblockslist_from_part(mountpath, usedblockfile, part, blocksize):

    totalblockscopied = 0
    try:
        cmdspec = ["/opt/stack/workloadmgr/debugfs/debugfs",
                   "-R", "stats -d", mountpath]
        usedblocks, error = execute_debugfs(cmdspec)
    except BaseException:
        # we did not recognize a valid partition on the disk. Copy
        # entire partition
        LOG.info(_("No valid ext fs found on partitin starting at:" +
                   str(part['start'])))
        startblk = 0
        length = (int(part['blocks']) * 1024) / blocksize
        usedblocks = "startblk " + str(startblk) + " length " + str(length)

    partoff = int(part['start']) * 512
    with open(usedblockfile, 'a') as f:
        for line in usedblocks.split("\n"):
            if "startblk" in line or not "length" not in line:
                continue

            extoff = int(re.findall(r'\d+', line)[0])
            length = int(re.findall(r'\d+', line)[1])
            totalblockscopied += length

            extoffsec = partoff + extoff * blocksize
            lengthsec = length * blocksize

            f.write(str(extoffsec) + "," + str(lengthsec) + "\n")

    return totalblockscopied


def get_usedblockslist_from_lv(mountpath, usedblockfiles, lv, pvinfo,
                               blocksize):

    totalblockscopied = {}
    try:
        cmdspec = ["/opt/stack/workloadmgr/debugfs/debugfs",
                   "-R", "stats -d", "/dev/" + lv['LVM2_VG_NAME'] +
                   "/" + lv['LVM2_LV_NAME']]
        usedblocks, error = execute_debugfs(cmdspec)
    except BaseException:
        # we did not recognize a valid file system on the lv.
        # we probably need to bail out and backup the entire
        # partition using cbt
        LOG.info(_("No valid ext fs found on partitin starting on: /dev/" +
                   lv['LVM2_VG_NAME'] + "/" + lv['LVM2_LV_NAME']))
        startblk = 0
        length = int(lv['LVM2_LV_SIZE']) / blocksize
        usedblocks = "startblk " + str(startblk) + " length " + str(length)

    filehandles = {}
    for key, value in usedblockfiles.iteritems():
        filehandles[key] = open(value, "a")
        totalblockscopied[key] = 0

    lvoffset = 0
    for line in usedblocks.split("\n"):
        if "startblk" in line or not "length" not in line:
            continue

        extoff = int(re.findall(r'\d+', line)[0])
        length = int(re.findall(r'\d+', line)[1])

        extoffsec = getlogicaladdrtopvaddr(
            lv, pvinfo, extoff * blocksize, length * blocksize)

        for extoff in extoffsec:
            eoff = int(extoff['offset']) + int(extoff['pv']['PV_DISK_OFFSET'])
            filehandles[extoff['pv']['filename']].write(
                str(eoff) + "," + str(extoff['length']) + "\n")
            totalblockscopied[extoff['pv']['filename']
                              ] += int(extoff['length']) / blocksize

    for key, value in usedblockfiles.iteritems():
        filehandles[key].close()

    return totalblockscopied

##
# copy_free_bitmap_from_part():
#     Creates an empty bitmap vmdk file with the name specified by localvmdkpath
##


def copy_free_bitmap_from_part(hostip, username, password, vmspec, filename,
                               mountpath, startsector,
                               blocksize, blockgroups):

    # Convert the start offset from 512 size into blocksize
    try:
        if int(startsector) * 512 % blocksize:
            LOG.info(_("The partition start %s is not aligned to \
                       file system block size") % startsector)

        partoff = int(startsector) * 512

        # copy bitmap blocks here
        index = 0
        fileh, bitmapfile = mkstemp()
        close(fileh)
        with open(bitmapfile, 'w') as f:
            for line in blockgroups.split("\n"):
                if "block bitmap at" in line and "inode bitmap" in line:

                    bitmapblock = int(
                        re.findall(
                            r'\d+',
                            line.split(":")[1])[0])
                    inodeblock = int(re.findall(r'\d+', line.split(":")[1])[1])

                    index += 1
                    if index % 50 == 0:
                        LOG.info(_("copying bitmapblock: " + str(bitmapblock)))
                        LOG.info(_("copying inodeblock: " + str(bitmapblock)))

                    bitmapsec = partoff + bitmapblock * blocksize
                    inodesec = partoff + inodeblock * blocksize

                    f.write(str(bitmapsec) + "," + str(blocksize) + "\n")
                    f.write(str(inodesec) + "," + str(blocksize) + "\n")

        populate_extents(hostip, username, password, vmspec,
                         filename, mountpath, bitmapfile)
    finally:
        if os.path.isfile(bitmapfile):
            os.remove(bitmapfile)

##
# copy_free_bitmap_from_lv():
#     Creates an empty bitmap vmdk file with the name specified by localvmdkpath
##


def copy_free_bitmap_from_lv(hostip, username, password, vmspec, devmap,
                             lvinfo, pvlist, blocksize, blockgroups):
    # copy bitmap blocks here
    index = 0
    bitmapfileh = {}
    bitmapfiles = {}

    for dmap in devmap:
        filename = dmap['dev']['backing']['fileName']
        fileh, bitmapfiles[filename] = mkstemp()
        close(fileh)
        bitmapfileh[filename] = open(bitmapfiles[filename], "w")

    try:
        for line in blockgroups.split("\n"):
            if "block bitmap at" in line and "inode bitmap" in line:

                bitmapblock = int(re.findall(r'\d+', line.split(":")[1])[0])
                inodeblock = int(re.findall(r'\d+', line.split(":")[1])[1])

                index += 1
                if index % 50 == 0:
                    LOG.info(_("copying bitmapblock: " + str(bitmapblock)))
                    LOG.info(_("copying inodeblock: " + str(bitmapblock)))

                bitmapsec = getlogicaladdrtopvaddr(
                    lvinfo, pvlist, bitmapblock * blocksize, blocksize)
                inodesec = getlogicaladdrtopvaddr(
                    lvinfo, pvlist, inodeblock * blocksize, blocksize)
                for bsec in bitmapsec:
                    boff = int(bsec['offset']) + \
                        int(bsec['pv']['PV_DISK_OFFSET'])
                    bitmapfileh[bsec['pv']['filename']].write(
                        str(boff) + "," + str(blocksize) + "\n")

                for isec in inodesec:
                    ioff = int(isec['offset']) + \
                        int(isec['pv']['PV_DISK_OFFSET'])
                    bitmapfileh[isec['pv']['filename']].write(
                        str(ioff) + "," + str(blocksize) + "\n")

        for dmap in devmap:
            filename = dmap['dev']['backing']['fileName']
            bitmapfileh[filename].close()

        for dmap in devmap:
            filename = bitmapfiles[dmap['dev']['backing']['fileName']]
            populate_extents(hostip, username, password, vmspec,
                             dmap['dev']['backing']['fileName'],
                             dmap['localvmdkpath'], filename)

    except Exception as ex:
        LOG.exception(_(ex))
    finally:
        try:
            for dmap in devmap:
                filename = dmap['dev']['backing']['fileName']
                if os.path.isfile(bitmapfiles[filename]):
                    os.remove(bitmapfiles[filename])
        except BaseException:
            pass

##
# copy_used_blocks():
#     Copies used blocks from remote disk to local disk
##


def copy_used_blocks(hostip, username, password, vmspec, dev,
                     mountpath, usedblocksfile):

    populate_extents(
        hostip,
        username,
        password,
        vmspec,
        dev['backing']['fileName'],
        mountpath,
        usedblocksfile)


def read_partition_table(mountpath=None):
    partitions = getfdisk_output(mountpath)
    if len(partitions) == 1 and partitions[0]['id'] == 'ee':
        # We found a gpt partition
        partitions = getgptdisk_output(mountpath)

    return partitions


def get_partition_table_from_vmdk(hostip, username, password, vmspec,
                                  remotepath, localvmdkpath, extentsfile):
    fileh, listfile = mkstemp()
    close(fileh)
    with open(listfile, 'w') as f:
        f.write(localvmdkpath)

    fileh, mntlist = mkstemp()
    close(fileh)

    with mount_local_vmdk(listfile, mntlist, diskonly=True) as mountpaths:
        for key, value in mountpaths.iteritems():
            partitions = read_partition_table(value[0].split(";")[0].strip())

    # If there is an extended partition, make sure the extended partition
    # logical partition table is populated
    for part in partitions:
        if part['id'] == '5' or part['id'] == 'f':
            extended_part = part
            populate_extent(hostip, username, password, vmspec,
                            remotepath, localvmdkpath,
                            str(extended_part['start']), 2048)

            with open(extentsfile, "a") as f:
                f.write(str(int(extended_part['start']) * 512) + "," +
                        str(2048 * 512) + "\n")

            with mount_local_vmdk(listfile, mntlist, diskonly=True) as mountpaths:
                for key, value in mountpaths.iteritems():
                    partitions = read_partition_table(
                        value[0].split(";")[0].strip())
                    break

            oldpartitiontable = []
            while len(oldpartitiontable) < len(partitions):
                oldpartitiontable = partitions
                for part in oldpartitiontable:
                    if int(part['start']) > int(extended_part['start']) and \
                       int(part['end']) + 2048 < int(extended_part['end']):
                        populate_extent(hostip, username, password, vmspec,
                                        remotepath, localvmdkpath,
                                        str(int(part['end']) + 1), 2048)

                        with open(extentsfile, "a") as f:
                            f.write(str(int(part['end'] + 1) * 512) + "," +
                                    str(2048 * 512) + "\n")

                with mount_local_vmdk(listfile, mntlist, diskonly=True) as mountpaths:
                    for key, value in mountpaths.iteritems():
                        partitions = read_partition_table(
                            value[0].split(";")[0].strip())
                        break
            break

    os.remove(listfile)
    os.remove(mntlist)
    return partitions


def _getpvinfo(mountpath, startoffset='0', length=None):

    subprocess.check_output(["pvscan"], stderr=subprocess.STDOUT)
    subprocess.check_output(["pvdisplay", mountpath], stderr=subprocess.STDOUT)
    LOG.info(_(mountpath + ":" + str(startoffset) + " is part of LVM"))

    cmd = ["pvs", "--noheadings", "--nameprefixes", ]
    pvstr = subprocess.check_output(cmd + [mountpath],
                                    stderr=subprocess.STDOUT)

    pvinfo = {}
    for line in pvstr.strip().split("\n"):
        for attr in line.strip().split(" "):
            if 'LVM2_PV_NAME' in attr.split("=")[0] or\
               'LVM2_VG_NAME' in attr.split("=")[0]:
                pvinfo[attr.split("=")[0]] = attr.split(
                    "=")[1].strip("\'").strip().strip("B")

    cmd = ["pvs", "--noheadings", "--units", "b", "-o",
           "pv_all", "--nameprefixes", ]
    pvstr = subprocess.check_output(cmd + [mountpath],
                                    stderr=subprocess.STDOUT)
    for line in pvstr.strip().split("\n"):
        for attr in line.strip().split(" "):
            if attr.split("=")[0].startswith('LVM2'):
                pvinfo[attr.split("=")[0]] = attr.split("=")[
                    1].strip("\'").strip("B")

    cmd = ["pvs", "--noheadings", "--units", "b", "-o",
           "pvseg_all", "--nameprefixes", ]
    pvstr = subprocess.check_output(cmd + [mountpath],
                                    stderr=subprocess.STDOUT)

    pvinfo['PV_DISK_OFFSET'] = startoffset
    pvinfo['PV_SEGMENTS'] = []
    for seg in pvstr.strip().split("\n"):
        segs = {}
        for attr in seg.strip().split(" "):
            if attr.split("=")[0].startswith('LVM2'):
                segs[attr.split("=")[0]] = attr.split("=")[
                    1].strip("\'").strip("B")
        if len(segs):
            pvinfo['PV_SEGMENTS'].append(segs)

    return pvinfo


def mountdevice(mountpath, startoffset='0', length=None):
    options = []
    if length:
        options = ["-o", startoffset, "--sizelimit", length]

    freedev = subprocess.check_output(["losetup", "-f"],
                                      stderr=subprocess.STDOUT)
    freedev = freedev.strip("\n")

    subprocess.check_output(["losetup", freedev, mountpath, ] + options,
                            stderr=subprocess.STDOUT)
    return freedev


def mountpv(mountpath, startoffset='0', length=None):
    try:
        devpath = mountdevice(mountpath, startoffset, length)
        pvinfo = _getpvinfo(freedev, startoffset, length)
        return freedev, pvinfo
    except Exception as ex:
        LOG.exception(ex)
        LOG.info(_(mountpath + ":" + startoffset + " does not have lvm pv"))
        dismountpv(freedev)
        raise


def dismountpv(devpath):
    subprocess.check_output(["losetup", "-d", devpath],
                            stderr=subprocess.STDOUT)


def getvgs(pvinfos=None):
    subprocess.check_output(["vgscan"], stderr=subprocess.STDOUT)

    # Activate volume groups on the pv
    subprocess.check_output(["vgchange", "-ay"], stderr=subprocess.STDOUT)

    vgcmd = ["vgs", "--noheadings", "--nameprefixes", ]
    vgoutput = subprocess.check_output(vgcmd, stderr=subprocess.STDOUT)

    vglist = []
    for vg in vgoutput.strip().split("\n"):
        vg = vg.strip()
        vginfo = {}
        for attr in vg.strip().split(" "):
            if attr.split("=")[0].startswith('LVM2'):
                vginfo[attr.split("=")[0]] =\
                    attr.split("=")[1].strip("\'").strip("B")

        if len(
                vginfo) and 'LVM2_VG_NAME' in vginfo and vginfo['LVM2_VG_NAME'] != "tvault-appliance-vg":
            vglist.append(vginfo)

    return vglist


def deactivatevgs(vgname):
    if vgname != "tvault-appliance-vg":
        vgcmd = ["vgchange", "-an", vgname]
        subprocess.check_output(vgcmd, stderr=subprocess.STDOUT)


def getloop_part_start_size(loopdev):
    loopdev = loopdev.strip().rstrip()
    if re.search("loop[0-9]+p[0-9]+", loopdev):
        with open('/sys/block/' + re.search("loop[0-9]+", loopdev).group(0) + '/' + re.search("loop[0-9]+p[0-9]+", loopdev).group(0) + '/size', 'r') as f:
            size = int(f.read()) * 512

        with open('/sys/block/' + re.search("loop[0-9]+", loopdev).group(0) + '/' + re.search("loop[0-9]+p[0-9]+", loopdev).group(0) + '/start', 'r') as f:
            start = int(f.read()) * 512
    else:
        start = 0
        with open('/sys/block/' + re.search("loop[0-9]+", loopdev).group(0) + '/size', 'r') as f:
            size = int(f.read()) * 512

    return start, size


def getpvs(vgs):
    subprocess.check_output(["pvscan"], stderr=subprocess.STDOUT)
    pvlist = []

    incompletevgs = set()
    # get the list of volumes
    for vg in vgs:
        vgname = vg['LVM2_VG_NAME']

        vgdisplay = subprocess.check_output(["vgdisplay", "-v", vgname],
                                            stderr=subprocess.STDOUT)
        for line in vgdisplay.split("\n"):
            if "PV Name" in line:
                pvpath = line.strip().rstrip().split("  ")[-1].strip().rstrip()
                if re.search("loop[0-9]+", pvpath):
                    start, size = getloop_part_start_size(pvpath)
                    pvinfo = _getpvinfo(pvpath, start, size)
                    pvlist.append(pvinfo)
                else:
                    incompletevgs.add(vg['LVM2_VG_NAME'])

    # clean up the PVs that were part of incomplete vgs
    purgedpvlist = []
    for pv in pvlist:
        if not pv['LVM2_VG_NAME'] in incompletevgs:
            purgedpvlist.append(pv)

    return purgedpvlist


def getlvs(vgs):
    subprocess.check_output(["lvscan"], stderr=subprocess.STDOUT)

    lvlist = []
    # get the list of volumes
    for vg in vgs:
        vgname = vg['LVM2_VG_NAME']
        lvs = subprocess.check_output(["lvs", "--noheadings", "--units", "b",
                                       "--nameprefixes", vgname],
                                      stderr=subprocess.STDOUT)
        lvnames = []
        for line in lvs.strip().split("\n"):
            lvinfo = {}
            for attr in line.strip().split(" "):
                if attr.split("=")[0].startswith('LVM2'):
                    lvinfo[attr.split("=")[0]] =\
                        attr.split("=")[1].strip("\'").strip("B")

            if not len(lvinfo):
                continue
            lvinfo['LVM2_LV_PATH'] = "/dev/" + \
                vgname + "/" + lvinfo['LVM2_LV_NAME']
            cmd = ["lvs", "--segments", "--noheadings", "--units", "b", "-o",
                   "seg_all", "--nameprefixes",
                   "/dev/" + vgname + "/" + lvinfo['LVM2_LV_NAME']]
            lvsegs = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            lvinfo['LVM_LE_SEGMENTS'] = []
            for seg in lvsegs.strip().split("\n"):
                seginfo = {}
                for attr in seg.strip().split(" "):
                    if attr.split("=")[0].startswith('LVM2'):
                        seginfo[attr.split("=")[0]] =\
                            attr.split("=")[1].strip("\'").strip("B")
                if len(seginfo):
                    lvinfo['LVM_LE_SEGMENTS'].append(seginfo)
            if len(lvinfo):
                lvnames.append(lvinfo)

        lvlist += lvnames

    return lvlist


def getlogicaladdrtopvaddr(lvinfo, pvlist, startoffset, length):
    # first find the LVM segment that this belongs to
    iosegs = []
    for lvseg in lvinfo['LVM_LE_SEGMENTS']:
        if length and int(lvseg['LVM2_SEG_START']) <= startoffset and int(
                lvseg['LVM2_SEG_START']) + int(lvseg['LVM2_SEG_SIZE']) > startoffset:

            seglength = min(length, int(lvseg['LVM2_SEG_START']) +
                            int(lvseg['LVM2_SEG_SIZE']) - startoffset)
            iosegs.append({'lvseg': lvseg, 'startoffset': startoffset -
                           int(lvseg['LVM2_SEG_START']), 'length': seglength})
            startoffset += seglength
            length -= seglength

    # find pvs segments
    pvsegs = []
    for ioseg in iosegs:
        pvname = ioseg['lvseg']['LVM2_SEG_PE_RANGES'].split(":")[0]
        startpe = int(
            ioseg['lvseg']['LVM2_SEG_PE_RANGES'].split(":")[1].split('-')[0])
        endpe = int(
            ioseg['lvseg']['LVM2_SEG_PE_RANGES'].split(":")[1].split('-')[1])
        pesize = int(ioseg['lvseg']['LVM2_SEG_SIZE']) / (endpe - startpe + 1)

        offset = ioseg['startoffset']
        lenseg = ioseg['length']

        for pv in pvlist:
            if pv['LVM2_PV_NAME'] == pvname:
                pvoffset = int(pv['LVM2_PE_START']) + startpe * pesize + offset
                pvlength = lenseg
                pvsegs.append({'pv': pv, 'offset': pvoffset,
                               'length': pvlength})

    return pvsegs


def getpartaddrtopvaddr(part, pvlist, startoffset, length):
    return [{'pv': None, 'offset': startoffset + part['start'] * 512,
             'length': length}]


def copylvextsuperblock(hostip, username, password, vmspec, devmap,
                        lvinfo, pvinfo):

    pvsegs = getlogicaladdrtopvaddr(lvinfo, pvinfo, 0, 400 * 512)
    for pvseg in pvsegs:
        populate_extent(hostip, username, password, vmspec,
                        pvseg['pv']['filename'], pvseg['pv']['localvmdkpath'],
                        str((pvseg['offset'] +
                             int(pvseg['pv']['PV_DISK_OFFSET'])) / 512),
                        str(pvseg['length'] / 512))


def performlvthickcopy(hostip, username, password, vmspec, devmap,
                       lvsrc, srcpvlist, extentsfile):

    try:
        totalblocks = {}
        copylvextsuperblock(hostip, username, password, vmspec,
                            devmap, lvsrc, srcpvlist)

        for pvs, vgs, lvs, mountinfo in mountlvmvgs(hostip, username, password,
                                                    vmspec, devmap):
            if len(vgs) == 0:
                LOG.info(
                    _("This VM does not contain any volume groups. Defaulting to cbt"))
                raise Exception(
                    "This VM does not contain any volume groups. Defaulting to cbt")

            if len(lvs) == 0:
                LOG.info(
                    _("This VM does not contain any logical volumes. Defaulting to cbt"))
                raise Exception(
                    "This VM does not contain any logical volumes. Defaulting to cbt")

            blocksize, blockgroups = get_blockgroups(lvsrc['LVM2_LV_PATH'])

        copy_free_bitmap_from_lv(hostip, username, password, vmspec, devmap,
                                 lvsrc, srcpvlist, blocksize, blockgroups)

        for pvs, vgs, lvs, mountinfo in mountlvmvgs(hostip, username, password,
                                                    vmspec, devmap):
            totalblocks = get_usedblockslist_from_lv(
                lvsrc['LVM2_LV_PATH'], extentsfile, lvsrc, srcpvlist, blocksize)
    except Exception as ex:
        LOG.exception(ex)
        LOG.error(_("Cannot open lv: %s") % (lvsrc['LVM2_LV_PATH']))

    return totalblocks


def mountlvmvgs(hostip, username, password, vmspec, devmap):

    fileh, listfile = mkstemp()
    close(fileh)
    with open(listfile, 'w') as f:
        for dmap in devmap:
            f.write(dmap['localvmdkpath'] + "\n")

    fileh, mntlist = mkstemp()
    close(fileh)

    mountinfo = {}
    vgs = []
    pvs = []
    lvs = []
    try:
        with mount_local_vmdk(listfile, mntlist, diskonly=True) as mountpaths:
            try:
                for key, value in mountpaths.iteritems():
                    mountpath = value[0].split(";")[0].strip()
                    devpath = mountdevice(mountpath)

                    # Add partition mappings here
                    try:
                        cmd = ["partx", "-d", devpath]
                        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                    except BaseException:
                        pass

                    try:
                        cmd = ["partx", "-a", devpath]
                        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                    except BaseException:
                        pass

                    for dmap in devmap:
                        if dmap['localvmdkpath'] == key:
                            mountinfo[key] = {
                                'mountpath': mountpath,
                                'devpath': devpath,
                                'localvmdkpath': key,
                                'filename': dmap['dev']['backing']['fileName']}

                # explore VGs and volumes on the disk
                vgs = getvgs()

                if len(vgs):
                    lvs = getlvs(vgs)
                    if len(lvs):
                        pvs = getpvs(vgs)
                        for index, pv in enumerate(pvs):
                            for key, mount in mountinfo.iteritems():
                                if mount['devpath'] in pv['LVM2_PV_NAME']:
                                    pvs[index]['filename'] = mount['filename']
                                    pvs[index]['localvmdkpath'] = mount['localvmdkpath']

                # purge vms based on pvlist
                purgedvgs = []
                # if pv list does not have any reference to vg, purge the vg
                for vg in vgs:
                    for pv in pvs:
                        if vg['LVM2_VG_NAME'] == pv['LVM2_VG_NAME']:
                            purgedvgs.append(vg)
                            break

                purgedlvs = []
                for lv in lvs:
                    found = False
                    for vg in purgedvgs:
                        if lv['LVM2_VG_NAME'] == vg['LVM2_VG_NAME']:
                            found = True
                            break
                    if found:
                        purgedlvs.append(lv)

                yield pvs, purgedvgs, purgedlvs, mountinfo

            except Exception as ex:
                LOG.exception(ex)
            finally:
                for vg in vgs:
                    deactivatevgs(vg['LVM2_VG_NAME'])

                time.sleep(2)
                for key, mount in mountinfo.iteritems():
                    dismountpv(mount['devpath'])

                time.sleep(2)
                for vg in vgs:
                    try:
                        deactivatevgs(vg['LVM2_VG_NAME'])
                    except BaseException:
                        pass

    finally:
        if os.path.isfile(listfile):
            os.remove(listfile)
        if os.path.isfile(mntlist):
            os.remove(mntlist)


def lvmextents_in_partition(hostip, username, password, vmspec,
                            devmap, extentsfiles):

    totalblocks = 0
    pvdevices = []
    devtopartmap = {}

    # for each LV, check if ext file system on the LV
    for pvs, vgs, lvs, mountinfo in mountlvmvgs(hostip, username, password,
                                                vmspec, devmap):
        pass

    # TODO: we need to take care of the situation when vg is partially present
    totalblocks = {}
    for key, value in extentsfiles.iteritems():
        totalblocks[key] = 0
    for lv in lvs:
        lvtotalblocks = performlvthickcopy(hostip, username,
                                           password, vmspec, devmap,
                                           lv, pvs, extentsfiles)

        for key, value in lvtotalblocks.iteritems():
            totalblocks[key] += lvtotalblocks[key]

    return totalblocks


def process_partitions(hostip, username, password, vmspec, devmap,
                       logicalobjects, extentsfiles):
    totalblocks = {}
    process = None

    # If partition has ext2 or its variant of file system, read the
    # blocksize and all the block groups of the file system
    partblockgroups = {}

    for key, value in extentsfiles.iteritems():
        totalblocks[key] = 0

    for partinfo in logicalobjects['regularpartitions']:
        try:
            localvmdkpath = None
            partition = partinfo['partition']

            if partition['id'] == 'ee' or partition['id'] == '5' \
                    or partition['id'] == 'f':
                continue

            filename = partinfo['filename']
            for dmap in devmap:
                if partinfo['filename'] == dmap['dev']['backing']['fileName']:
                    localvmdkpath = dmap['localvmdkpath']
                    break
            if localvmdkpath is None:
                raise Exception("Something went wrong. Could not find local \
                                 vmdk that corresponds to remotepath")

            # Check for regular partitions
            fileh, listfile = mkstemp()
            close(fileh)
            with open(listfile, 'w') as f:
                f.write(localvmdkpath)

            fileh, mntlist = mkstemp()
            close(fileh)

            with mount_local_vmdk(listfile, mntlist, diskonly=True) as mountpaths:
                for key, value in mountpaths.iteritems():
                    mountpath = value[0].split(";")[0].strip()
                    break

                try:
                    freedev = subprocess.check_output(["losetup", "-f"],
                                                      stderr=subprocess.STDOUT)
                    freedev = freedev.strip("\n")

                    startoffset = str(int(partition['start']) * 512)
                    length = partition['blocks'] + "KiB"
                    options = ["-o", startoffset, "--sizelimit", length]
                    subprocess.check_output(["losetup", freedev, mountpath, ] + options,
                                            stderr=subprocess.STDOUT)
                    # display list of partitions that has ext file system
                    partblockgroups = get_blockgroups(freedev)
                finally:
                    dismountpv(freedev)

            # copy bitmap blocks and inode blocks to empty vmdk
            blocksize = partblockgroups[0]
            blockgroups = partblockgroups[1]
            copy_free_bitmap_from_part(
                hostip,
                username,
                password,
                vmspec,
                filename,
                localvmdkpath,
                partition['start'],
                blocksize,
                blockgroups)

            # Get the list of used blocks for each file system
            with mount_local_vmdk(listfile, mntlist, diskonly=True) as mountpaths:
                for key, value in mountpaths.iteritems():
                    mountpath = value[0].split(";")[0].strip()
                    break

                ##
                # TODO: The used blocks can be pretty big. Make sure
                # we are handling large lists correctly.
                try:
                    freedev = None
                    freedev = subprocess.check_output(["losetup", "-f"],
                                                      stderr=subprocess.STDOUT)
                    freedev = freedev.strip("\n")

                    subprocess.check_output(["losetup",
                                             freedev,
                                             mountpath,
                                             "-o",
                                             str(int(
                                                 partition['start']) * 512),
                                             "--sizelimit",
                                             partition['blocks'] + "KiB"],
                                            stderr=subprocess.STDOUT)
                    blocksize = partblockgroups[0]
                    totalblocks[filename] += get_usedblockslist_from_part(
                        freedev, extentsfiles[filename],
                        partition, blocksize)

                finally:
                    if freedev:
                        dismountpv(freedev)

        except Exception as ex:
            LOG.exception(ex)
            LOG.info(_(partinfo['filename'] + ":" + str(partition) +
                       "partition does not have ext fs. Ignoring now"))
        finally:
            if os.path.isfile(listfile):
                os.remove(listfile)
            if os.path.isfile(mntlist):
                os.remove(mntlist)
    return totalblocks


def discover_lvs_and_partitions(hostip, username, password, vmspec, devmap,
                                partitions):

    totalblocks = 0
    lvmresources = {}
    # create separate list of disks and partitions used by LVM
    # and non lvm
    #
    lvmdisks = []
    lvmpartitions = []
    regularpartitions = []
    rawdisks = []

    try:
        for pvs, vgs, lvs, mountinfo in mountlvmvgs(hostip, username, password,
                                                    vmspec, devmap):
            for pv in pvs:
                for key, mount in mountinfo.iteritems():
                    if mount['devpath'] in pv['LVM2_PV_NAME']:
                        for dmap in devmap:
                            if dmap['localvmdkpath'] == key:
                                lvmresources[pv["LVM2_PV_NAME"]] = \
                                    {'filename': dmap['dev']['backing']['fileName'],
                                     'startoffset': pv['PV_DISK_OFFSET']}

            claimed = set()
            # Identify lvm disks and partitions
            for pv, resinfo in lvmresources.iteritems():
                if re.search("loop[0-9]+p[0-9]+", pv):
                    lvmpartitions.append(resinfo)
                else:
                    lvmdisks.append(resinfo)
                claimed.add(resinfo['filename'] + ':' +
                            str(resinfo['startoffset']))

            # identify raw disks here
            for filename, parttable in partitions.iteritems():
                if filename + ":0" in claimed:
                    continue

                if len(parttable) == 0:
                    rawdisks.append({'filename': filename, 'startoffset': 0})
                else:
                    for part in parttable:
                        if filename + ':' + \
                                str(int(part['start']) * 512) in claimed:
                            continue

                        regularpartitions.append({'filename': filename,
                                                  'partition': part})

        return {'lvmdisks': lvmdisks, 'lvmpartitions': lvmpartitions,
                'regularpartitions': regularpartitions, 'rawdisks': rawdisks}

    except Exception as ex:
        LOG.exception(ex)

##
# Description:
#    Start with regular partitioned disk now.
# Extend it to lvm based snapshots later. This may involve reading the lvm metadata and reconstructing
# the volume. We can only support simple volumes that spans part of the disk for now. We may extend
# this feature to more complex compositions later
#
# Arguments:
#    hostip - vcetner ip address
#    username - admin user name for vcenter
#    password - password for the user
#    vmspec   - moref of the vm that we are backing up
#    devmap   - [{dev: dev, localvmdkpath: localvmdkpath}]
#
# Return Value:
#    extentsinfo = [{extentsfile: extentsfile, partitions:partitions,
#                    totalblocks: totalblocks}]
##


def _thickcopyextents(hostip, username, password, vmspec, devmap):

    try:
        # Read the partition table from each device
        partitions = {}
        extentsinfo = {}
        extentsfiles = {}
        totalblocks = {}

        # for each LV, check if ext file system on the LV
        for dmap in devmap:
            fileh, extentsfiles[dmap['dev']['backing']['fileName']] = mkstemp()
            totalblocks[dmap['dev']['backing']['fileName']] = 0
            close(fileh)

        for dmap in devmap:
            filename = dmap['dev']['backing']['fileName']
            capacity = dmap['dev']['capacityInBytes']
            populate_bootrecord(hostip, username, password, vmspec,
                                filename, dmap['localvmdkpath'], capacity)

            with open(extentsfiles[filename], "a") as f:
                f.write(str(0) + "," + str(400 * 512) + "\n")
            totalblocks[filename] += 400 * 512 / 4096

            partitions[filename] = get_partition_table_from_vmdk(
                hostip,
                username,
                password,
                vmspec,
                filename,
                dmap['localvmdkpath'],
                extentsfiles[filename])

            # if no partitions found, see if this is raw LVM PV
            if len(partitions[filename]) > 0:
                # First copy super blocks of each partition
                #
                for part in partitions[filename]:
                    if part['id'] != 'ee' and part['id'] != '5' \
                            and part['id'] != 'f':
                        populate_extent(hostip, username, password, vmspec,
                                        filename, dmap['localvmdkpath'],
                                        str(part['start']), 400)
                        with open(extentsfiles[filename], "a") as f:
                            f.write(str(int(part['start']) * 512) + "," +
                                    str(400 * 512) + "\n")
                        totalblocks[filename] += 400 * 512 / 4096

        # mount all devices here
        # do vg scan
        # sort the partitions/disks into lvms and partitions
        # sort lvs and partitions into ext fs and not ext fs
        logicalobjects = discover_lvs_and_partitions(
            hostip, username, password, vmspec, devmap, partitions)

        # identify rest of partitions that were not part of LVM configuration
        lvmtotalblocks = lvmextents_in_partition(hostip, username, password,
                                                 vmspec, devmap, extentsfiles)
        for key, value in lvmtotalblocks.iteritems():
            totalblocks[key] += lvmtotalblocks[key]

        parttotalblocks = process_partitions(hostip, username, password,
                                             vmspec, devmap, logicalobjects,
                                             extentsfiles)

        for key, value in parttotalblocks.iteritems():
            totalblocks[key] += parttotalblocks[key]

        return {'extentsfiles': extentsfiles, 'totalblocks': totalblocks,
                'partitions': partitions}
    except Exception as ex:
        LOG.exception(ex)
        for key, filename in extentsfiles.iteritems():
            if os.path.isfile(filename):
                os.remove(filename)
        raise


def thickcopyextents(hostip, username, password, vmspec, devmap):
    try:
        return _thickcopyextents(hostip, username, password,
                                 vmspec, devmap)
    except Exception as ex:
        LOG.exception(_(ex))
        return None


"""
def thickcopy(hostip, username, password, vmspec, dev, localvmdkpath):
    extentsfile, partitions,\
       totalblocks, listfile, mntlist = thickcopyextents(hostip,
                                              username, password,
                                              vmspec, dev, localvmdkpath)
    if not extentsfile:
        LOG.info(_( "Cannot use thickcopy to upload snapshot"))
        return

    # Copy used blocks of the file system from remote disk to local disk
    LOG.info(_( "Copying " + str(totalblocks) +\
                " used blocks from remote to local disk"))
    copy_used_blocks(hostip, username, password,
                     vmspec, dev, localvmdkpath, extentsfile)

    LOG.info(_( "Copied.. "))

    for part in partitions:
        #verify the file system can be mounted
        process, mountpaths = mount_local_vmdk(listfile,
                                 mntlist, diskonly=True)
        try:
            for key, value in mountpaths.iteritems():
                mountpath = value[0].split(";")[0].strip()
            ##
            # This will tend to be pretty big
            try:
                freedev = subprocess.check_output(["losetup", "-f"],
                                                stderr=subprocess.STDOUT)
                freedev = freedev.strip("\n")

                subprocess.check_output(["losetup", freedev, mountpath, "-o",
                               str(int(part['start'])*512), "--sizelimit", part['blocks'] + "KiB"],
                               stderr=subprocess.STDOUT)
                cmdspec = ["/opt/stack/workloadmgr/debugfs/debugfs",
                           "-R", "ls", freedev]
                ls, error = execute_debugfs(cmdspec)
                LOG.info(_(ls))
                #input("Enter something: ")
            except:
                LOG.info(_("Cannot display root directory"))
            finally:
                subprocess.check_output(["losetup", "-d", freedev],
                                stderr=subprocess.STDOUT)
        finally:
            umount_local_vmdk(process)
    return True

vmdkfile = "/tmp/disks/vmdk1"
"""

"""
if os.path.isfile(vmdkfile):
    os.remove(vmdkfile)
# Create an empty VMDK file where the snapshot image go
#dev = {'capacityInBytes': 68719476736, 'backing' : {'fileName' : '[Datastore2] centos7/centos7.vmdk'}}
create_empty_vmdk(vmdkfile, dev['capacityInBytes'])
#thickcopy("192.168.1.130", "root", "vmware", 'moref=vm-6023', dev, vmdkfile)
"""

"""
# R1Soft VM
if os.path.isfile(vmdkfile):
    os.remove(vmdkfile)
print "Downloading first disk"
dev = {'capacityInBytes': 21474836480, 'backing' : {'fileName' : '[Datastore4] r1soft/r1soft-000001.vmdk'}}
create_empty_vmdk(vmdkfile, dev['capacityInBytes'])
thickcopy("192.168.1.130", "root", "vmware", 'moref=vm-6020', dev, vmdkfile)

print "Downloading second disk"
if os.path.isfile(vmdkfile):
    os.remove(vmdkfile)
# Create an empty VMDK file where the snapshot image go
dev = {'capacityInBytes': 68719476736, 'backing' : {'fileName' : '[Datastore4] r1soft/r1soft_1-000001.vmdk'}}
create_empty_vmdk(vmdkfile, dev['capacityInBytes'])
thickcopy("192.168.1.130", "root", "vmware", 'moref=vm-6020', dev, vmdkfile)

print "Downloading third disk"
if os.path.isfile(vmdkfile):
    os.remove(vmdkfile)
dev = {'capacityInBytes': 34359738368, 'backing' : {'fileName' : '[datastore1 (2)] r1soft/r1soft-000002.vmdk'}}
create_empty_vmdk(vmdkfile, dev['capacityInBytes'])
thickcopy("192.168.1.130", "root", "vmware", 'moref=vm-6020', dev, vmdkfile)
"""
