import subprocess
import os
import re
from subprocess import call
from subprocess import check_call
from subprocess import check_output
import shutil
from os import remove, close

from Queue import Queue
from Queue import Queue, Empty
from threading  import Thread
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
        check_output(cmdline.split(" "), stderr=subprocess.STDOUT, env=vix_disk_lib_env)
    except subprocess.CalledProcessError as ex:
        LOG.critical(_("cmd: %s resulted in error: %s") %(cmdline, ex.output))
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

def mount_local_vmdk(diskslist, mntlist, diskonly=False): 
    vix_disk_lib_env = os.environ.copy()
    vix_disk_lib_env['LD_LIBRARY_PATH'] = '/usr/lib/vmware-vix-disklib/lib64'

    cmdspec = [ "trilio-vix-disk-cli", "-mount", "-mountpointsfile", mntlist, ]
    if diskonly:
        cmdspec += ['-diskonly']
    cmdspec += [diskslist]
    cmd = " ".join(cmdspec)
    LOG.info(_( cmd ))
    process = subprocess.Popen(cmdspec,
                               stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE,
                               bufsize= -1,
                               env=vix_disk_lib_env,
                               close_fds=True,
                               shell=False)
                
    queue = Queue()
    read_thread = Thread(target=enqueue_output, args=(process.stdout, queue))
    read_thread.daemon = True # thread dies with the program
    read_thread.start()            
                
    mountpath = None
    while process.poll() is None:
        try:
            try:
                output = queue.get(timeout=5)
                LOG.info(_( output ))
            except Empty:
                continue 
            except Exception as ex:
                LOG.exception(ex)

            if output.startswith("Pausing the process until it is resumed"):
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
    mountpoints = {}
    with open(mntlist, 'r') as f:
        for line in f:
            line = line.strip("\n")
            mountpoints[line.split(":")[0]] = line.split(":")[1].split(";")
        
    LOG.info(_( mountpoints ))
    process.stdin.close()
    return process, mountpoints

##
# unmounts a vmdk by sending signal 18 to the process that as suspended during mount process
##
def umount_local_vmdk(process): 
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
                               bufsize= -1,
                               env=env,
                               close_fds=True,
                               shell=False)
    ## TODO: throw exception  on error?
    output, error = process.communicate()
    if process.returncode:
        raise exception.ProcessExecutionError(cmd=" ".join(cmdspec),
                                 description=error, exit_code=process.returncode)
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
        LOG.critical(_("cmd: %s resulted in error: %s") %(cmdspec, ex.output))
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
                   mountpath,]
        check_output(cmdline, stderr=subprocess.STDOUT, env=vix_disk_lib_env)
    except subprocess.CalledProcessError as ex:
        LOG.critical(_("cmd: %s resulted in error: %s") %(cmdline, ex.output))
        LOG.exception(ex)
        raise

def populate_bootrecord(hostip, username, password, vmspec, remotepath,
                        mountpath, diskCapacity):
    diskCapacity = long(diskCapacity) - 400 * 512
    populate_extent(hostip, username, password, vmspec, remotepath,
                     mountpath, 0, 400)
    # GPT disks has second boot record at the end of the disk
    populate_extent(hostip, username, password, vmspec, remotepath,
                     mountpath, diskCapacity/512, 400)
 
    return

##
# getfdisk_output():
# if the underlying disk is fdisk, read the partition table from the mounted disk
#
##
def getfdisk_output(mountpath=None):
    partitions = []
    cmdspec = ["sudo", "fdisk", "-l",]
    if mountpath:
        cmdspec.append(str(mountpath))

    LOG.info(_( " ".join(cmdspec) ))
    #stdout_value = check_output(cmdspec, stderr=subprocess.STDOUT)
    process = subprocess.Popen(cmdspec,
                               stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE,
                               bufsize= -1,
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
            index = 0;
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
    cmdspec = ["sudo", "sgdisk", "-p",]
    if mountpath:
        cmdspec.append(str(mountpath))

    LOG.info(_( " ".join(cmdspec) ))
    process = subprocess.Popen(cmdspec,
                               stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE,
                               bufsize= -1,
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
            index = 0;
            partition["Number"] = fields[index]
            index += 1
            partition["start"] = fields[index]
            index += 1
            partition["end"] = fields[index]
            index += 1
            partition["blocks"] = str((int(partition['end']) - \
                                   int(partition['start']) + 1)/2)
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

    # Read the superblock and read the blocksize
    cmdspec = ["/opt/stack/workloadmgr/debugfs/debugfs",
               "-R", "stats -h", mountpath]
    superblock, error = execute_debugfs(cmdspec)

    # get the block size
    for line in superblock.split("\n"):
        LOG.info(_( line ))
        if "Block size:" in line:
             blocksize = int(line.split(":")[1].strip())

    cmdspec = ["/opt/stack/workloadmgr/debugfs/debugfs",
               "-R", "stats", mountpath]

    blockgroups, error = execute_debugfs(cmdspec)

    return blocksize, blockgroups

def get_usedblockslist_from_part(mountpath, usedblockfile, part, blocksize):

    totalblockscopied = 0
    try:
        cmdspec = ["/opt/stack/workloadmgr/debugfs/debugfs",
                   "-R", "stats -d", mountpath]
        usedblocks, error = execute_debugfs(cmdspec)
    except:
        ## we did not recognize a valid partition on the disk. Copy
        ## entire partition
        LOG.info(_( "No valid ext fs found on partitin starting at:"
                    + str(part['start']) ))
        startblk = 0
        length = (int(part['blocks']) * 1024)/blocksize
        usedblocks = "startblk " + str(startblk) + " length " + str(length)

    partoff = int(part['start']) * 512
    with open(usedblockfile, 'a') as f:
        for line in usedblocks.split("\n"):
            if not "startblk" in line or not "length" in line:
                continue

            extoff = int(re.findall(r'\d+', line)[0])
            length = int(re.findall(r'\d+', line)[1])
            totalblockscopied += length

            extoffsec = partoff + extoff * blocksize
            lengthsec = length * blocksize

            f.write(str(extoffsec) + "," + str(lengthsec) + "\n")
    return totalblockscopied

def get_usedblockslist_from_lv(mountpath, usedblockfile, lv, pvinfo,
                               blocksize, partoffset = 0):

    totalblockscopied = 0
    try:
        cmdspec = ["/opt/stack/workloadmgr/debugfs/debugfs",
                   "-R", "stats -d", "/dev/" + lv['LVM2_VG_NAME'] +
                   "/" + lv['LVM2_LV_NAME']]
        usedblocks, error = execute_debugfs(cmdspec)
    except:
        ## we did not recognize a valid file system on the lv.
        ## we probably need to bail out and backup the entire
        ## partition using cbt
        LOG.info(_( "No valid ext fs found on partitin starting on: /dev/"
                    + lv['LVM2_VG_NAME'] + "/" + lv['LVM2_LV_NAME']))
        startblk = 0
        ## TODO Here
        length = (int(part['blocks']) * 1024)/blocksize
        usedblocks = "startblk " + str(startblk) + " length " + str(length)

    lvoffset = 0
    with open(usedblockfile, 'a') as f:
        for line in usedblocks.split("\n"):
            if not "startblk" in line or not "length" in line:
                continue

            extoff = int(re.findall(r'\d+', line)[0])
            length = int(re.findall(r'\d+', line)[1])
            totalblockscopied += length

            extoffsec = getlogicaladdrtopvaddr(lv, pvinfo,
                                   extoff * blocksize, length * blocksize)

            for extoff in extoffsec:
                f.write(str(extoff['offset']) + "," + str(extoff['length']) + "\n")

    return totalblockscopied
    
##
# copy_free_bitmap_from_part():
#     Creates an empty bitmap vmdk file with the name specified by localvmdkpath
##
def copy_free_bitmap_from_part(hostip, username, password, vmspec, dev,
                               mountpath, startsector,
                               blocksize, blockgroups):
    # Convert the start offset from 512 size into blocksize
    if int(startsector) * 512 % blocksize:
        LOG.info(_("The partition start %s is not aligned to \
                   file system block size") % startsector)

    partoff = int(startsector) * 512
    # copy bitmap blocks here
    index = 0;
    fileh, filename = mkstemp()
    close(fileh)
    with open(filename, 'w') as f:
        for line in blockgroups.split("\n"):
            if "block bitmap at" in line and "inode bitmap" in line:
            
                bitmapblock = int(re.findall(r'\d+', line.split(":")[1])[0])
                inodeblock = int(re.findall(r'\d+', line.split(":")[1])[1])

                index += 1
                if index % 50 == 0:
                    LOG.info(_( "copying bitmapblock: " + str(bitmapblock) ))
                    LOG.info(_( "copying inodeblock: " + str(bitmapblock)))
 
                bitmapsec = partoff + bitmapblock * blocksize
                inodesec = partoff + inodeblock * blocksize
                f.write(str(bitmapsec) + "," + str(blocksize) + "\n")
                f.write(str(inodesec) + "," + str(blocksize) + "\n")

    populate_extents(hostip, username, password, vmspec,
                     dev['backing']['fileName'], mountpath, filename)

##
# copy_free_bitmap_from_lv():
#     Creates an empty bitmap vmdk file with the name specified by localvmdkpath
##
def copy_free_bitmap_from_lv(hostip, username, password, vmspec, dev,
                             mountpath, lvinfo, pvlist,
                             blocksize, blockgroups):
    # copy bitmap blocks here
    index = 0;
    fileh, filename = mkstemp()
    close(fileh)
    with open(filename, 'w') as f:
        for line in blockgroups.split("\n"):
            if "block bitmap at" in line and "inode bitmap" in line:
            
                bitmapblock = int(re.findall(r'\d+', line.split(":")[1])[0])
                inodeblock = int(re.findall(r'\d+', line.split(":")[1])[1])

                index += 1
                if index % 50 == 0:
                    LOG.info(_( "copying bitmapblock: " + str(bitmapblock) ))
                    LOG.info(_( "copying inodeblock: " + str(bitmapblock)))
 
                bitmapsec = getlogicaladdrtopvaddr(lvinfo, pvlist,
                                   bitmapblock * blocksize, blocksize)
                inodesec = getlogicaladdrtopvaddr(lvinfo, pvlist,
                                   inodeblock * blocksize, blocksize)
                for bsec in bitmapsec:
                    f.write(str(bsec['offset']) + "," + str(blocksize) + "\n")
                for isec in bitmapsec:
                    f.write(str(isec['offset']) + "," + str(blocksize) + "\n")

    populate_extents(hostip, username, password, vmspec,
                     dev['backing']['fileName'], mountpath, filename)

##
# copy_used_blocks():
#     Copies used blocks from remote disk to local disk
##
def copy_used_blocks(hostip, username, password, vmspec, dev,
                     mountpath, usedblocksfile):

     populate_extents(hostip, username, password, vmspec, dev['backing']['fileName'],
                     mountpath, usedblocksfile)

def get_partitions(mountpath=None):
    partitions = getfdisk_output(mountpath)
    if len(partitions) == 1 and partitions[0]['id'] == 'ee':
        # We found a gpt partition
        partitions = getgptdisk_output(mountpath)

    return partitions

def _getpvinfo(mountpath, startoffset = '0', length = None):

    subprocess.check_output(["pvscan"], stderr=subprocess.STDOUT)
    subprocess.check_output(["pvdisplay", mountpath], stderr=subprocess.STDOUT)
    LOG.info(_(mountpath + ":" + startoffset + " is part of LVM"))

    cmd = ["pvs", "--noheadings", "--nameprefixes",]
    pvstr = subprocess.check_output(cmd + [mountpath],
                                    stderr=subprocess.STDOUT)

    pvinfo = {}
    for line in pvstr.strip().split("\n"):
        for attr in line.strip().split(" "):
            if 'LVM2_PV_NAME' in attr.split("=")[0] or\
               'LVM2_VG_NAME' in attr.split("=")[0]:
                pvinfo[attr.split("=")[0]] = attr.split("=")[1].strip("\'").strip().strip("B")

    cmd = ["pvs", "--noheadings", "--units", "b", "-o",
           "pv_all", "--nameprefixes",]
    pvstr = subprocess.check_output(cmd + [mountpath],
                                    stderr=subprocess.STDOUT)
    for line in pvstr.strip().split("\n"):
        for attr in line.strip().split(" "):
            if attr.split("=")[0].startswith('LVM2'):
                pvinfo[attr.split("=")[0]] = attr.split("=")[1].strip("\'").strip("B")

    cmd = ["pvs", "--noheadings", "--units", "b", "-o",
           "pvseg_all", "--nameprefixes",]
    pvstr = subprocess.check_output(cmd + [mountpath],
                                    stderr=subprocess.STDOUT)

    pvinfo['PV_DISK_OFFSET'] = startoffset
    pvinfo['PV_SEGMENTS'] = []
    for seg in pvstr.strip().split("\n"):
        segs = {}
        for attr in seg.strip().split(" "):
            if attr.split("=")[0].startswith('LVM2'):
                segs[attr.split("=")[0]] = attr.split("=")[1].strip("\'").strip("B")
        if len(segs):
            pvinfo['PV_SEGMENTS'].append(segs)

    return pvinfo

def getpvinfo(mountpath, startoffset = '0', length = None):

    options = []
    if length:
        options = ["-o", startoffset, "--sizelimit", length]
    try:
        freedev = subprocess.check_output(["losetup", "-f"],
                                            stderr=subprocess.STDOUT)
        freedev = freedev.strip("\n")

        subprocess.check_output(["losetup", freedev, mountpath,] + options,
                               stderr=subprocess.STDOUT)
        pvinfo = _getpvinfo(freedev, startoffset, length)
        return pvinfo
    except Exception as ex:
        LOG.exception(ex)
        LOG.info(_(mountpath + ":" + startoffset + " does not have lvm pv"))
        return None
    finally:
        try:
            subprocess.check_output(["losetup", "-d", freedev],
                              stderr=subprocess.STDOUT)
        except:
            pass

def getvgs():
    subprocess.check_output(["vgscan"], stderr=subprocess.STDOUT)

    # Activate volume groups on the pv
    subprocess.check_output(["vgchange", "-a", "y"], stderr=subprocess.STDOUT)

    vgcmd = ["vgs", "--noheadings", "--nameprefixes",]
    vgoutput = subprocess.check_output(vgcmd, stderr=subprocess.STDOUT)

    vglist = []
    for vg in vgoutput.strip().split("\n"):
        vg = vg.strip()
        vginfo = {}
        for attr in vg.strip().split(" "):
            if attr.split("=")[0].startswith('LVM2'):
                vginfo[attr.split("=")[0]] =\
                     attr.split("=")[1].strip("\'").strip("B")

        if len(vginfo):
            vglist.append(vginfo)

    return vglist

def deactivatevgs():
    vgcmd = ["vgchange", "-a", "n"]
    subprocess.check_output(["vgchange", "-a", "y"], stderr=subprocess.STDOUT)

def getlvs(vgname):
    subprocess.check_output(["lvscan"], stderr=subprocess.STDOUT)

    # get the list of volumes
    lvs = subprocess.check_output(["lvs", "--noheadings",
                               "--nameprefixes"], stderr=subprocess.STDOUT)
    lvnames = []
    for line in lvs.strip().split("\n"):
        lvinfo = {}
        for attr in line.strip().split(" "):
            if attr.split("=")[0].startswith('LVM2'):
                lvinfo[attr.split("=")[0]] =\
                       attr.split("=")[1].strip("\'").strip("B")

        if not len(lvinfo):
            continue
        lvinfo['LVM2_LV_PATH'] = "/dev/" + vgname + "/" + lvinfo['LVM2_LV_NAME']
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

    return lvnames

def getlogicaladdrtopvaddr(lvinfo, pvlist, startoffset, length):
    # first find the LVM segment that this belongs to
    iosegs = []
    for lvseg in lvinfo['LVM_LE_SEGMENTS']:
        if length and int(lvseg['LVM2_SEG_START']) <= startoffset and\
           int(lvseg['LVM2_SEG_START']) + int(lvseg['LVM2_SEG_SIZE']) > startoffset:

            seglength = min(length, int(lvseg['LVM2_SEG_START']) +\
                                     int(lvseg['LVM2_SEG_SIZE']) - startoffset)
            iosegs.append({'lvseg':lvseg,
                           'startoffset': startoffset - int(lvseg['LVM2_SEG_START']),
                           'length': seglength})
            startoffset += seglength
            length -= seglength

    # find pvs segments
    pvsegs = []
    for ioseg in iosegs:
        pvname = ioseg['lvseg']['LVM2_SEG_PE_RANGES'].split(":")[0]
        startpe = int(ioseg['lvseg']['LVM2_SEG_PE_RANGES'].split(":")[1].split('-')[0])
        endpe = int(ioseg['lvseg']['LVM2_SEG_PE_RANGES'].split(":")[1].split('-')[1])
        pesize = int(ioseg['lvseg']['LVM2_SEG_SIZE'])/(endpe - startpe + 1)

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
    return [{'pv':None, 'offset': startoffset + part['start'] * 512,
             'length': length}]

def copylvextsuperblock(hostip, username, password, vmspec, dev,
                        localvmdkpath, lvinfo, pvinfo):
    
    pvsegs = getlogicaladdrtopvaddr(lvinfo, pvinfo, 0, 400 * 512)
    for pvseg in pvsegs:
        populate_extent(hostip, username, password, vmspec,
                    dev['backing']['fileName'],
                    localvmdkpath,
                    str((pvseg['offset'] + int(pvseg['pv']['PV_DISK_OFFSET']))/512),
                    str(pvseg['length']/512))

def performlvthickcopy(hostip, username, password, vmspec, dev,
                       mountpath, lv, pvinfo, extentsfile):

    copylvextsuperblock(hostip, username, password, vmspec,
                        dev, mountpath, lv, pvinfo)

    # get_blockgroups does not require any IO transfer
    # from remote host
    blocksize, blockgroups= get_blockgroups(lv['LVM2_LV_PATH'])

    copy_free_bitmap_from_lv(hostip, username, password, vmspec, dev,
                             mountpath, lv, pvinfo, blocksize,
                             blockgroups)

    totalblocks = get_usedblockslist_from_lv(lv['LVM2_LV_PATH'], extentsfile,
                                            lv, pvinfo, blocksize)
  
    return totalblocks

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
#    dev      - device to backup
#    localvmdkpath - localvmdk path to save the file
##
def _thickcopyextents(hostip, username, password, vmspec, dev, localvmdkpath):
   
    # Read the partition table from the file
    populate_bootrecord(hostip, username, password, vmspec,
                        dev['backing']['fileName'], localvmdkpath,
                        dev['capacityInBytes'])

    fileh, listfile = mkstemp()
    close(fileh)
    with open(listfile, 'w') as f:
        f.write(localvmdkpath)

    fileh, mntlist = mkstemp()
    close(fileh)

    fileh, extentsfile = mkstemp()
    close(fileh)

    totalblocks = 0
    process, mountpaths = mount_local_vmdk(listfile, mntlist, diskonly=True)
    try:
        for key, value in mountpaths.iteritems():
            partitions = get_partitions(value[0].split(";")[0].strip())
    finally:
        umount_local_vmdk(process)

    # if no partitions found, see if this is raw LVM PV
    if len(partitions) == 0:
        process, mountpaths = mount_local_vmdk(listfile, mntlist, diskonly=True)
        try:
            for key, value in mountpaths.iteritems():
                mountpath = value[0].split(";")[0].strip()
                pvinfo = getpvinfo(mountpath)
                if pvinfo is None:
                    return None, None, None, None, None
                else:
                    # explore VGs and volumes on the disk
                    vgs = getvgs()
               
                    if len(vgs) == 0:
                        return None, None, None, None, None
 
                    lvs = getlvs(vgs[0]['LVM2_VG_NAME'])
                    if len(lvs) == 0:
                        return None, None, None, None, None
         
                    # for each LV, check if ext file system on the LV
                    for lv in lvs:
                        totalblocks += performlvthickcopy(hostip, username,
                                           password, vmspec, dev, mountpath,
                                           lv, [pvinfo], extentsfile)
            return extentsfile, partitions, totalblocks, listfile, mntlist
        finally:
            umount_local_vmdk(process)

        return None, None, None, None, None
         
    # If there is an extended partition, make sure the extended partition
    # logical partition table is populated
    for part in partitions:
        if part['id'] == '5' or part['id'] == 'f':
            extended_part = part
            populate_extent(hostip, username, password, vmspec,
                            dev['backing']['fileName'], localvmdkpath,
                            str(extended_part['start']), 2048)
            process, mountpaths = mount_local_vmdk(listfile, mntlist, diskonly=True)
            try:
                for key, value in mountpaths.iteritems():
                    partitions = get_partitions(value[0].split(";")[0].strip())
                    break
            finally:
                umount_local_vmdk(process)

            oldpartitiontable = []
            while len(oldpartitiontable) < len(partitions):
                oldpartitiontable = partitions
                for part in oldpartitiontable:
                    if int(part['start']) > int(extended_part['start']) and \
                       int(part['end']) + 2048 < int(extended_part['end']):
                        populate_extent(hostip, username, password, vmspec,
                                        dev['backing']['fileName'], localvmdkpath,
                                        str(int(part['end']) + 1), 2048)
                process, mountpaths = mount_local_vmdk(listfile,
                                                       mntlist, diskonly=True)
                try:
                    for key, value in mountpaths.iteritems():
                        partitions = get_partitions(
                                           value[0].split(";")[0].strip())
                        break
                finally:
                    umount_local_vmdk(process)
            break

    # First copy super blocks of each partition
    #
    for part in partitions:
        if part['id'] != 'ee' and part['id'] != '5' and part['id'] != 'f':
            populate_extent(hostip, username, password, vmspec,
                            dev['backing']['fileName'],
                            localvmdkpath, str(part['start']), 400)


    # If partition has ext2 or its variant of file system, read the
    # blocksize and all the block groups of the file system
    exttype = "part"

    partblockgroups = {}
    process, mountpaths = mount_local_vmdk(listfile,
                                 mntlist, diskonly=True)
    try:
        for key, value in mountpaths.iteritems():
            mountpath = value[0].split(";")[0].strip()
            break

        for part in partitions:
            if part['id'] == 'ee' or part['id'] == '5' or part['id'] == 'f':
                continue
            try:
                freedev = subprocess.check_output(["losetup", "-f"],
                                            stderr=subprocess.STDOUT)
                freedev = freedev.strip("\n")
        
                subprocess.check_output(["losetup", freedev, mountpath, "-o",
                               str(int(part['start'])*512), "--sizelimit", part['blocks'] + "KiB"],
                               stderr=subprocess.STDOUT)
                partblockgroups[part['start']] = get_blockgroups(freedev)
            except Exception as ex:
                LOG.info(_(part['start'] + " has unrecognized file system"))
                # Now check if the partition is part of LVM
                exttype = None
            finally:
                try:
                    subprocess.check_output(["losetup", "-d", freedev],
                              stderr=subprocess.STDOUT)
                except:
                    pass

        if not exttype:
            # One or more partitions do not have ext file system.
            # try for LVM based file systems
            exttype = "LVM2"
            pvdevices = []
            pvinfos = []
            for part in partitions:
                if part['id'] == 'ee' or part['id'] == '5' or part['id'] == 'f':
                    continue
                try:
                    freedev = subprocess.check_output(["losetup", "-f"],
                                                stderr=subprocess.STDOUT)
                    freedev = freedev.strip("\n")
        
                    subprocess.check_output(["losetup", freedev, mountpath, "-o",
                                   str(int(part['start'])*512), "--sizelimit",
                                   part['blocks'] + "KiB"],
                                   stderr=subprocess.STDOUT)

                    pvdevices.append(freedev)

                    pvinfo = _getpvinfo(freedev, str(int(part['start'])*512),
                                   part['blocks'] + "KiB")
                    pvinfos.append(pvinfo)
                except Exception as ex:
                    LOG.info(_(part['start'] + " is not part of LVM. Cleaning up"))
                    # Now check if the partition is part of LVM
                    exttype = None
                    for dev in pvdevices:
                        subprocess.check_output(["losetup", "-d", dev],
                                  stderr=subprocess.STDOUT)

                    return None, None, None, None, None

            # explore VGs and volumes on the disk
            vgs = getvgs()
               
            if len(vgs) == 0:
                return None, None, None, None, None
 
            lvs = getlvs(vgs[0]['LVM2_VG_NAME'])
            if len(lvs) == 0:
                return None, None, None, None, None
         
            # for each LV, check if ext file system on the LV
            for lv in lvs:
                totalblocks += performlvthickcopy(hostip, username,
                                           password, vmspec, dev, mountpath,
                                           lv, pvinfos, extentsfile)
            return extentsfile, partitions, totalblocks, listfile, mntlist
    finally:
        umount_local_vmdk(process)

    
    # display list of partitions that has ext file system
    for part in partitions:
        if part['start'] in partblockgroups:
            LOG.info(_(part['start'] + " has extx file system"))
        else:
            LOG.info(_(part['start'] + " unrecognized file system"))
            LOG.info(_("Reverting to VMware CBT based  backup to detech changed blocks"))

    # copy bitmap blocks and inode blocks to empty vmdk 
    for part in partitions:
        if part['start'] in partblockgroups:
            blocksize = partblockgroups[part['start']][0]
            blockgroups = partblockgroups[part['start']][1]
            copy_free_bitmap_from_part(hostip, username, password, vmspec, dev,
                             localvmdkpath, part['start'],
                             blocksize, blockgroups)

    for part in partitions:

        if part['id'] == 'ee' or part['id'] == '5' or part['id'] == 'f':
            continue
        # for each partition on the disk copy only allocated blocks
        # from remote disk

        # Get the list of used blocks for each file system
        process, mountpaths = mount_local_vmdk(listfile,
                                 mntlist, diskonly=True)
        try:
            for key, value in mountpaths.iteritems():
                mountpath = value[0].split(";")[0].strip()
            ##
            # TODO: The used blocks can be pretty big. Make sure
            # we are handling large lists correctly.
            try:
                freedev = subprocess.check_output(["losetup", "-f"],
                                            stderr=subprocess.STDOUT)
                freedev = freedev.strip("\n")
        
                subprocess.check_output(["losetup", freedev, mountpath, "-o",
                               str(int(part['start'])*512), "--sizelimit",
                               part['blocks'] + "KiB"],
                               stderr=subprocess.STDOUT)
                if part['start'] in partblockgroups:
                    blocksize = partblockgroups[part['start']][0]
                else:
                    blocksize = 4096
                totalblocks += get_usedblockslist_from_part(freedev, extentsfile,
                                                  part, blocksize)
            finally:
                subprocess.check_output(["losetup", "-d", freedev],
                                        stderr=subprocess.STDOUT)
        finally:
            umount_local_vmdk(process)

    return extentsfile, partitions, totalblocks, listfile, mntlist

def thickcopyextents(hostip, username, password, vmspec, dev, localvmdkpath):
    try:
        extentsfile, partitions,\
        totalblocks, listfile,\
        mntlist = _thickcopyextents(hostip, username, password,
                         vmspec, dev, localvmdkpath)
        return extentsfile, partitions, totalblocks, listfile, mntlist
    except Exception as ex:
        #LOG.exception(_(ex))
        raise
        return None, None, None, None, None

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

