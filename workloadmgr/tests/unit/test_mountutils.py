'''
import subprocess
import os
import re
import time
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

#LOG = logging.getLogger(__name__)
#LOG = logging.getLogger('workloadmgr.virt.vmwareapi.driver')
#Logger = autolog.Logger(LOG)

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

def enqueue_output(out, queue):
    for line in iter(out.readline, b''):
        queue.put(line)
    out.close()

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

        lvlist += lvnames

    return lvlist

def getvgs(pvinfos = None):
    subprocess.check_output(["vgscan"], stderr=subprocess.STDOUT)

    # Activate volume groups on the pv
    subprocess.check_output(["vgchange", "-ay"], stderr=subprocess.STDOUT)

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

        if len(vginfo) and 'LVM2_VG_NAME' in vginfo and vginfo['LVM2_VG_NAME'] != "tvault-appliance-vg":
            vglist.append(vginfo)

    return vglist

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

def _getpvinfo(mountpath, startoffset = '0', length = None):

    subprocess.check_output(["pvscan"], stderr=subprocess.STDOUT)
    subprocess.check_output(["pvdisplay", mountpath], stderr=subprocess.STDOUT)
    LOG.info(_(mountpath + ":" + str(startoffset) + " is part of LVM"))

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

def deactivatevgs(vgname):
    if vgname != "tvault-appliance-vg":
        vgcmd = ["vgchange", "-an", vgname]
        subprocess.check_output(vgcmd, stderr=subprocess.STDOUT)

def read_partition_table(mountpath=None):
    partitions = getfdisk_output(mountpath)
    if len(partitions) == 1 and partitions[0]['id'] == 'ee':
        # We found a gpt partition
        partitions = getgptdisk_output(mountpath)

    return partitions

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

                cmdspec = [ "trilio-vix-disk-cli", "-mount", "-mountpointsfile", mntlist, ]
                if diskonly:
                    cmdspec += ['-diskonly']
                cmdspec += [listfile]
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
                with open(mntlist, 'r') as f:
                    for line in f:
                        line = line.strip("\n")
                        mountpoints[line.split(":")[0]] = line.split(":")[1].split(";")

                LOG.info(_( mountpoints ))
                process.stdin.close()
                processes.append(process)

            except Exception as ex:
                LOG.exception(ex)
                raise
            finally:
                if os.path.isfile(listfile):
                    os.remove(listfile)

        return processes, mountpoints
    except Exception as ex:
        LOG.exception(ex)
        try:
            umount_local_vmdk(processes)
        except:
            pass

        raise

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

def mountlvmvgs(mountinfo):
    vgs = []
    pvs = []
    lvs = []
    try:
        # explore VGs and volumes on the disk
        vgs = getvgs()

        if len(vgs):
            lvs = getlvs(vgs)
            if len(lvs):
                pvs = getpvs(vgs)
                for index, pv in enumerate(pvs):
                    for key, mount in mountinfo.iteritems():
                        if mount in pv['LVM2_PV_NAME']:
                            pvs[index]['filename'] = key

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

        return pvs, purgedvgs, purgedlvs, mountinfo

    except Exception as ex:
        LOG.exception(ex)
        for vg in vgs:
            deactivatevgs(vg['LVM2_VG_NAME'])

        time.sleep(2)
        for vg in vgs:
            try:
                deactivatevgs(vg['LVM2_VG_NAME'])
            except:
                pass

def discover_lvs_and_partitions(devicepaths, partitions):

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
        pvs, vgs, lvs, mountinfo = mountlvmvgs(devicepaths)
        for pv in pvs:
            for key, mount in mountinfo.iteritems():
                if mount in pv['LVM2_PV_NAME']:
                    lvmresources[pv["LVM2_PV_NAME"]] = \
                                    {'filename': key,
                                     'startoffset': pv['PV_DISK_OFFSET']}

        claimed = set()
        # Identify lvm disks and partitions
        for pv, resinfo in lvmresources.iteritems():
            if re.search("loop[0-9]+p[0-9]+", pv):
                lvmpartitions.append(resinfo)
            else:
                lvmdisks.append(resinfo)
            claimed.add(resinfo['filename'] + ':' + str(resinfo['startoffset']))

        # identify raw disks here
        for filename, parttable in partitions.iteritems():
            if filename+":0" in claimed:
                continue

            if len(parttable) == 0:
                rawdisks.append({'filename': filename, 'startoffset': 0})
            else:
                for part in parttable:
                    if filename+':'+str(int(part['start']) * 512) in claimed:
                        continue

                    regularpartitions.append({'filename': filename,
                                              'partition': part})

        return {'lvmdisks': lvmdisks, 'lvmpartitions': lvmpartitions,
                'regularpartitions': regularpartitions, 'rawdisks': rawdisks,
                'vgs': vgs, 'lvs': lvs, 'pvs': pvs}

    except Exception as ex:
        LOG.exception(ex)

def mountdevice(mountpath, startoffset = '0', length = None):
    options = []
    if length:
        options = ["-o", startoffset, "--sizelimit", length]

    freedev = subprocess.check_output(["losetup", "-f"],
                                            stderr=subprocess.STDOUT)
    freedev = freedev.strip("\n")

    subprocess.check_output(["losetup", freedev, mountpath,] + options,
                               stderr=subprocess.STDOUT)
    return freedev

def umountdevice(devpath):
    subprocess.check_output(["losetup", "-d", devpath],
                              stderr=subprocess.STDOUT)

def unassignloopdevices(devpaths):
    for key, devpath in devpaths.iteritems():
        try:
            umountdevice(devpath)
        except:
            pass

def assignloopdevices(mountpaths):
    devicepaths = {}
    for key, mountpath in mountpaths.iteritems():
        try:
            devpath = mountdevice(mountpath.pop().strip().rstrip())

            devicepaths[key] = devpath
            # Add partition mappings here
            try:
                cmd = ["partx", "-d", devpath]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            except:
                pass

            try:
                cmd = ["partx", "-a", devpath]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            except:
                pass
        except:
            unassignloopdevices(devicepaths)
            raise

    return devicepaths

def mount_logicalobjects(mountdir, snapshot_id, vmid, logicalobjects):

    # create snapshot directory
    snapshotdir = os.path.join(mountdir, snapshot_id)
    if not os.path.exists(snapshotdir):
        os.makedirs(snapshotdir)

    vmdir = os.path.join(snapshotdir, vmid)
    if not os.path.exists(vmdir):
        os.makedirs(vmdir)

    for part in logicalobjects['regularpartitions']:
        try:
            devpath = vmdir + part['partition']['Device Name']
            os.makedirs(devpath)
            cmd = ["mount", part['partition']['Device Name'], devpath]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        except Exception as ex:
            LOG.exception(ex)

    for lv in logicalobjects['lvs']:
        try:
            lvpath = vmdir + lv['LVM2_LV_PATH']
            os.makedirs(lvpath)
            cmd = ["mount", lv['LVM2_LV_PATH'], lvpath]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        except Exception as ex:
            LOG.exception(ex)

def umount_logicalobjects(mountdir, snapshot_id, vmid, logicalobjects):
    # umount
    snapshotdir = os.path.join(mountdir, snapshot_id)
    vmdir = os.path.join(snapshotdir, vmid)

    for part in logicalobjects['regularpartitions']:
        try:
            devpath = vmdir + part['partition']['Device Name']
            cmd = ["umount", devpath]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            os.removedirs(devpath)
        except Exception as ex:
            LOG.exception(ex)

    for lv in logicalobjects['lvs']:
        try:
            lvpath = vmdir + lv['LVM2_LV_PATH']
            cmd = ["umount", lvpath]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            os.removedirs(lvpath)
        except Exception as ex:
            LOG.exception(ex)

    if os.path.exists(vmdir):
        shutil.rmtree(vmdir, True)

    if os.path.exists(snapshotdir):
        shutil.rmtree(snapshotdir, True)

vmdkfiles=[u'/home/stack/wlmsda1/workload_2a524094-6358-475f-b37b-6cac4b7cc386/snapshot_d4d0be85-f12a-44e3-b7d1-ea665598a70b/vm_id_50223b17-4fee-1f2d-dea4-c1ccbdf5efd6/vm_res_id_550479e5-eafa-46b9-8a0f-55d7455f3de8_Harddisk2/3271e40f-f7a2-4889-84b5-21538180c9f2\n', u'/home/stack/wlmsda1/workload_2a524094-6358-475f-b37b-6cac4b7cc386/snapshot_d4d0be85-f12a-44e3-b7d1-ea665598a70b/vm_id_50223b17-4fee-1f2d-dea4-c1ccbdf5efd6/vm_res_id_64ffbc78-3ac6-473d-b6d6-83016ed05ca0_Harddisk3/36a68e15-c910-4085-85d6-6e1db51e70c2\n', u'/home/stack/wlmsda1/workload_2a524094-6358-475f-b37b-6cac4b7cc386/snapshot_d4d0be85-f12a-44e3-b7d1-ea665598a70b/vm_id_50223b17-4fee-1f2d-dea4-c1ccbdf5efd6/vm_res_id_dea95503-0851-41af-878c-6456241f3bae_Harddisk1/404ed8a8-3628-4fec-b031-13433a5bee47\n']

# We mount vmdk file first?
# Identify the root folder for mounting all snapshot volumes/partitions

mountdir = "/home/stack/tvault-mounts"
snapshot_id = "d4d0be85-f12a-44e3-b7d1-ea665598a70b"
vmid = "50223b17-4fee-1f2d-dea4-c1ccbdf5efd6"

fileh, listfile = mkstemp()
close(fileh)
with open(listfile, 'w') as f:
    for vmdk in vmdkfiles:
        f.write(vmdk)

fileh, mntlist = mkstemp()
close(fileh)

processes, mountpaths = mount_local_vmdk(listfile, mntlist, diskonly=True)
try:
    devpaths = assignloopdevices(mountpaths)
    try:
        partitions = {}
        for vmdk, mountpath in devpaths.iteritems():
            partitions[mountpath] = read_partition_table(mountpath)

        logicalobjects = discover_lvs_and_partitions(devpaths, partitions)

        try:
            mount_logicalobjects(mountdir, snapshot_id, vmid, logicalobjects)

            import pdb;pdb.set_trace()
            umount_logicalobjects(mountdir, snapshot_id, vmid, logicalobjects)
        finally:
            for vg in logicalobjects['vgs']:
                deactivatevgs(vg['LVM2_VG_NAME'])
    finally:
        unassignloopdevices(devpaths)
finally:
    umount_local_vmdk(processes)

if os.path.isfile(listfile):
    os.remove(listfile)
if os.path.isfile(mntlist):
    os.remove(mntlist)
'''
