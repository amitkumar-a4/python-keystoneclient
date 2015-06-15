import unittest
import mock
import sys
import os
import subprocess
import os.path
from tempfile import mkstemp
from tempfile import mkdtemp
import shutil

import workloadmgr
from workloadmgr import exception
from workloadmgr.openstack.common import log as logging
from workloadmgr.openstack.common.gettextutils import _
from workloadmgr import autolog

LOG = logging.getLogger(__name__)
Logger = autolog.Logger(LOG)


#
# thick copy when the entire disk is a logical volume
def test_lv_entire_disk():

    def createpv(pvname, capacity):
        try:
            cmd = ["dd", "if=/dev/zero", "of="+pvname, "bs=1", "count=1", "seek=" + str(capacity)]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            cmd = ["losetup", "-f"]
            freedev = subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            freedev = freedev.strip("\n")
            cmd = ["losetup", freedev, pvname,]

            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            return freedev
        except Exception as ex:
            print "Cannot create or mount pvname "
            raise

    def deletepv(pvname):
        os.remove(pvname)

    def setup():
        mountpoint = createpv("pvname1", "1TiB")
   
        cmd = ["pvcreate", mountpoint]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["vgcreate", "vg1", mountpoint]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
    
        # create multiple volumes
        cmd = ["lvcreate", "-L", "1G", "vg1", "-n", "lv1"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["lvcreate", "-L", "2G", "vg1", "-n", "lv2"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["lvcreate", "-L", "3G", "vg1", "-n", "lv3"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["lvcreate", "-L", "4G", "vg1", "-n", "lv4"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        # Format each volume to a filesystem
        cmd = ["mkfs", "-t", "ext4", "/dev/vg1/lv1"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        cmd = ["mkfs", "-t", "ext4", "/dev/vg1/lv2"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        cmd = ["mkfs", "-t", "ext4", "/dev/vg1/lv3"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        cmd = ["mkfs", "-t", "ext4", "/dev/vg1/lv4"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        tempdir = mkdtemp()
        for lv in ["lv1", "lv2", "lv3", "lv4"]:
            cmd = ["mount", "-t", "ext4", "/dev/vg1/"+lv, tempdir]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            cmd = ["cp", "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz", tempdir]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            cmd = ["umount", "/dev/vg1/"+lv]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        shutil.rmtree(tempdir)

        return mountpoint

    def cleanup(mountpoint):
        cmd = ["lvremove", "-f", "/dev/vg1/lv1"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        cmd = ["lvremove", "-f", "/dev/vg1/lv2"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        cmd = ["lvremove", "-f", "/dev/vg1/lv3"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        cmd = ["lvremove", "-f", "/dev/vg1/lv4"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["vgremove", "vg1"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        cmd = ["pvremove", mountpoint]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        cmd = ["losetup", "-d", mountpoint]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        deletepv("pvname1")
        os.remove("vmdk")
 
    def verify(remotepath, extentsfile, vmdkfile):
        partitions = thickcopy.get_partitions(vmdkfile)

        try:
            my_populate_extents(None, None, None, None, remotepath,
                                vmdkfile, extentsfile)
            freedev = subprocess.check_output(["losetup", "-f"],
                                                stderr=subprocess.STDOUT)
            freedev = freedev.strip("\n")

            subprocess.check_output(["losetup", freedev, vmdkfile,],
                                   stderr=subprocess.STDOUT)
            pvinfo = _getpvinfo(freedev, startoffset, length)
            # explore VGs and volumes on the disk
            vgs = getvgs()
               
            if len(vgs) == 0:
               raise Exception("No VGs found on VMDK. Test failed")
 
            lvs = getlvs(vgs[0]['LVM2_VG_NAME'])
            if len(lvs) != 4:
               raise Exception("Number of LVs found is not 4. Test Failed")

            tempdir = mkdtemp()
            for lv in ["lv1", "lv2", "lv3", "lv4"]:
                cmd = ["mount", "-t", "ext4", "/dev/vg1/"+lv, tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                cmd = ["diff", "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                       tempdir + "/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz"]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                cmd = ["umount", "/dev/vg1/"+lv]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            shutil.rmtree(tempdir)
         
        except Exception as ex:
            LOG.exception(ex)
            LOG.info(_(mountpath + ":" + startoffset + " does not have lvm pv"))
            raise
        finally:
            try:
                subprocess.check_output(["losetup", "-d", freedev],
                                  stderr=subprocess.STDOUT)
            except:
                pass

    currentmodule = sys.modules[__name__]
    # Following is the mock code to test the thick copy
    def create_empty_vmdk_mock(filepath, capacity):
        cmd = ["dd", "if=/dev/zero", "of="+filepath, "bs=1", "count=1", "seek=" + str(capacity)]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

    def my_mount_disk(diskslist, mntlist, diskonly=False):
        with open(diskslist, 'r') as f:
            for line in f:
                return None, {'disk1': [line + ";"]}

    def my_populate_extent(hostip, username, password, vmspec, remotepath,
                           mountpath, start, count):
        cmd = ["dd", "if="+remotepath, "of="+mountpath, "bs=512", "count=" +
               str(count), "seek=" + str(start), "skip="+str(start), "conv=notrunc"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

    def my_populate_extents(hostip, username, password, vmspec, remotepath,
                           mountpath, extentsfile):
        with open(extentsfile, 'r') as f:
            for line in f:
                start = int(line.split(",")[0])/512
                count = int(line.split(",")[1])/512
                my_populate_extent(hostip, username, password, vmspec,
                                remotepath, mountpath, start, count)

    @mock.patch('workloadmgr.virt.vmwareapi.thickcopy.populate_extents', side_effect=my_populate_extents)
    @mock.patch('workloadmgr.virt.vmwareapi.thickcopy.populate_extent', side_effect=my_populate_extent)
    @mock.patch('workloadmgr.virt.vmwareapi.thickcopy.umount_local_vmdk')
    @mock.patch('workloadmgr.virt.vmwareapi.thickcopy.mount_local_vmdk', side_effect=my_mount_disk)
    @mock.patch('workloadmgr.virt.vmwareapi.thickcopy.create_empty_vmdk', side_effect=create_empty_vmdk_mock)
    def test(method1, method2, method3, method4, method5):
        dev = {'capacityInBytes': 1099511627776L, 'backing' : {'fileName' : mountpoint}}
        localvmdkpath = "vmdk"
        workloadmgr.virt.vmwareapi.thickcopy.create_empty_vmdk(localvmdkpath, dev['capacityInBytes'])
        extentsfile, partitions, totalblocks, listfile, mntlist = \
              workloadmgr.virt.vmwareapi.thickcopy.thickcopyextents(None,
                             None, None, None, dev, localvmdkpath)
        return extentsfile, partitions, totalblocks, listfile, mntlist

    try:
        mountpoint = setup() 
        extentsfile, partitions, totalblocks, listfile, mntlist = test()
        import pdb;pdb.set_trace()
        verify(mountpoint, extentsfile, "vmdk")
    finally:
        cleanup(mountpoint)

## 
# LVM PV is carved out of 
def test_lv_on_partitions():

    def createpv(pvname, capacity):
        try:
            cmd = ["dd", "if=/dev/zero", "of="+pvname, "bs=1", "count=1", "seek=" + str(capacity)]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            cmd = ["losetup", "-f"]
            freedev = subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            freedev = freedev.strip("\n")
            cmd = ["losetup", freedev, pvname,]

            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            return freedev
        except Exception as ex:
            print "Cannot create or mount pvname "
            raise

    def deletepv(pvname):
        os.remove(pvname)

    def assigndevice(mountpath, start, end):
        try:
            freedev = subprocess.check_output(["losetup", "-f"],
                                               stderr=subprocess.STDOUT)
            freedev = freedev.strip("\n")
            subprocess.check_output(["losetup", freedev, mountpath, "-o",
                               str(int(start)*512), "--sizelimit",
                               str((int(end) - int(start) + 1)/2) + "KiB"],
                               stderr=subprocess.STDOUT)
            return freedev
        except Exception as ex:
            print "Cannot create loop device"

    def setup():
        mountpoint = createpv("pvname1", "1TiB")
   
        cmd = ["parted", mountpoint, "mklabel", "gpt"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        devices = []
        cmd = ["parted", mountpoint, "mkpart", "P1", "ext2", str(1024), str("1000G")]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        devices.append(assigndevice(mountpoint, 1024 * 2, 2 * 1000 * 1024 * 1024))

        for dev in devices:
            cmd = ["pvcreate", dev]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            cmd = ["vgcreate", "vg1", dev]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
    
            # create multiple volumes
            for lv in ["lv1", "lv2", "lv3", "lv4"]:
                cmd = ["lvcreate", "-L", "1G", "vg1", "-n", lv]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            # Format each volume to a filesystem
            for lv in ["lv1", "lv2", "lv3", "lv4"]:
                cmd = ["mkfs", "-t", "ext4", "/dev/vg1/" + lv]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        return mountpoint

    def cleanup():
        cmd = ["lvremove", "-f", "/dev/vg1/lv1"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        cmd = ["lvremove", "-f", "/dev/vg1/lv2"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        cmd = ["lvremove", "-f", "/dev/vg1/lv3"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        cmd = ["lvremove", "-f", "/dev/vg1/lv4"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["vgremove", "vg1"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["losetup", "-a"]
        devs = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        devices = []
        for dev in devs.strip().split("\n"):
            devices.append(dev.strip().split(":")[0].strip())

        for pv in subprocess.check_output(["pvs", "--noheading"]).strip().split("\n"):
            cmd = ["pvremove", pv.split()[0]]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        for dev in sorted(devices, reverse=True):
            cmd = ["losetup", "-d", dev]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        deletepv("pvname1")
        if os.path.isfile("vmdk"):
            os.remove("vmdk")
 
    currentmodule = sys.modules[__name__]
    # Following is the mock code to test the thick copy
    def create_empty_vmdk_mock(filepath, capacity):
        cmd = ["dd", "if=/dev/zero", "of="+filepath, "bs=1", "count=1", "seek=" + str(capacity)]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

    def my_mount_disk(diskslist, mntlist, diskonly=False):
        with open(diskslist, 'r') as f:
            for line in f:
                return None, {'disk1': [line + ";"]}

    def my_populate_extent(hostip, username, password, vmspec, remotepath,
                           mountpath, start, count):
        cmd = ["dd", "if="+remotepath, "of="+mountpath, "bs=512", "count=" +
               str(count), "seek=" + str(start), "skip="+str(start), "conv=notrunc"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

    def my_populate_extents(hostip, username, password, vmspec, remotepath,
                           mountpath, extentsfile):
        with open(extentsfile, 'r') as f:
            for line in f:
                start = int(line.split(",")[0])/512
                count = int(line.split(",")[1])/512
                my_populate_extent(hostip, username, password, vmspec,
                                remotepath, mountpath, start, count)

    @mock.patch('workloadmgr.virt.vmwareapi.thickcopy.populate_extents', side_effect=my_populate_extents)
    @mock.patch('workloadmgr.virt.vmwareapi.thickcopy.populate_extent', side_effect=my_populate_extent)
    @mock.patch('workloadmgr.virt.vmwareapi.thickcopy.umount_local_vmdk')
    @mock.patch('workloadmgr.virt.vmwareapi.thickcopy.mount_local_vmdk', side_effect=my_mount_disk)
    @mock.patch('workloadmgr.virt.vmwareapi.thickcopy.create_empty_vmdk', side_effect=create_empty_vmdk_mock)
    def test(method1, method2, method3, method4, method5):
        dev = {'capacityInBytes': 1099511627776L, 'backing' : {'fileName' : mountpoint}}
        localvmdkpath = "vmdk"
        workloadmgr.virt.vmwareapi.thickcopy.create_empty_vmdk(localvmdkpath, dev['capacityInBytes'])
        extentsfile, partitions, totalblocks, listfile, mntlist = \
              workloadmgr.virt.vmwareapi.thickcopy.thickcopyextents(None,
                             None, None, None, dev, localvmdkpath)
        print extentsfile, partitions, totalblocks, listfile, mntlist

    try:
        mountpoint = setup() 
        test()
    finally:
        cleanup()

#
# thick copy when the entire disk is partitioned into 4 primary partitions and 
# formatted to ext4 file systems
def test_mbr_4_primary_partitions():

    def createpv(pvname, capacity):
        try:
            cmd = ["dd", "if=/dev/zero", "of="+pvname, "bs=1", "count=1",
                   "seek=" + str(capacity)]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            cmd = ["losetup", "-f"]
            freedev = subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            freedev = freedev.strip("\n")
            cmd = ["losetup", freedev, pvname,]

            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            return freedev
        except Exception as ex:
            print "Cannot create or mount pvname "
            raise

    def deletepv(pvname):
        os.remove(pvname)

    def formatfs(mountpath, start, end):
        try:
            freedev = subprocess.check_output(["losetup", "-f"],
                                               stderr=subprocess.STDOUT)
            freedev = freedev.strip("\n")
            subprocess.check_output(["losetup", freedev, mountpath, "-o",
                               str(int(start)*512), "--sizelimit",
                               str((int(end) - int(start) + 1)/2) + "KiB"],
                               stderr=subprocess.STDOUT)
            cmd = ["mkfs", "-t", "ext4", freedev]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            return freedev
        except Exception as ex:
            print "Cannot create loop device and format the file system"

    def setup():
        mountpoint = createpv("pvname1", "1TiB")
        devices = []
   
        cmd = ["parted", mountpoint, "mklabel", "msdos"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["parted", mountpoint, "mkpart", "primary", "ext2", str(1024), str(10240)]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["parted", mountpoint, "mkpart", "primary", "ext2", str(10240), str(2 * 10240)]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["parted", mountpoint, "mkpart", "primary", "ext2", str(2 * 10240), str(10 * 10240)]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["parted", mountpoint, "mkpart", "primary", "ext2", str(10 * 10240), str(100 * 10240)]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        # TODO: Figure out why these start and end sectors resulted from about part commands
        devices.append(formatfs(mountpoint, 2000896, 20000767))
        devices.append(formatfs(mountpoint, 20000768, 39999487))
        devices.append(formatfs(mountpoint, 39999488, 199999487))
        devices.append(formatfs(mountpoint, 199999488, 2000001023))

        return mountpoint, devices

    def cleanup(mountpoint, devices):
        for dev in devices:
            cmd = ["losetup", "-d", dev]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["losetup", "-d", "/dev/loop0"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        deletepv("pvname1")
        if os.path.isfile("vmdk"):
            os.remove("vmdk")
 
    currentmodule = sys.modules[__name__]
    # Following is the mock code to test the thick copy
    def create_empty_vmdk_mock(filepath, capacity):
        cmd = ["dd", "if=/dev/zero", "of="+filepath, "bs=1", "count=1", "seek=" + str(capacity)]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

    def my_mount_disk(diskslist, mntlist, diskonly=False):
        with open(diskslist, 'r') as f:
            for line in f:
                return None, {'disk1': [line + ";"]}

    def my_populate_extent(hostip, username, password, vmspec, remotepath,
                           mountpath, start, count):
        cmd = ["dd", "if="+remotepath, "of="+mountpath, "bs=512", "count=" +
               str(count), "seek=" + str(start), "skip="+str(start), "conv=notrunc"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

    def my_populate_extents(hostip, username, password, vmspec, remotepath,
                           mountpath, extentsfile):
        with open(extentsfile, 'r') as f:
            for line in f:
                start = int(line.split(",")[0])/512
                count = int(line.split(",")[1])/512
                my_populate_extent(hostip, username, password, vmspec,
                                remotepath, mountpath, start, count)

    @mock.patch('workloadmgr.virt.vmwareapi.thickcopy.populate_extents', side_effect=my_populate_extents)
    @mock.patch('workloadmgr.virt.vmwareapi.thickcopy.populate_extent', side_effect=my_populate_extent)
    @mock.patch('workloadmgr.virt.vmwareapi.thickcopy.umount_local_vmdk')
    @mock.patch('workloadmgr.virt.vmwareapi.thickcopy.mount_local_vmdk', side_effect=my_mount_disk)
    @mock.patch('workloadmgr.virt.vmwareapi.thickcopy.create_empty_vmdk', side_effect=create_empty_vmdk_mock)
    def test(method1, method2, method3, method4, method5):
        dev = {'capacityInBytes': 1099511627776L, 'backing' : {'fileName' : mountpoint}}
        localvmdkpath = "vmdk"
        workloadmgr.virt.vmwareapi.thickcopy.create_empty_vmdk(localvmdkpath, dev['capacityInBytes'])
        extentsfile, partitions, totalblocks, listfile, mntlist = \
              workloadmgr.virt.vmwareapi.thickcopy.thickcopyextents(None,
                             None, None, None, dev, localvmdkpath)
        print extentsfile, partitions, totalblocks, listfile, mntlist

    try:
        mountpoint, devices = setup() 
        test()
    finally:
        cleanup(mountpoint, devices)

# thick copy when the entire disk is partitioned into 3 primary partitions and 
# 1 logical partition and each formatted to ext4 file systems
def test_mbr_3_primary_1_logical_partitions():

    def createpv(pvname, capacity):
        try:
            cmd = ["dd", "if=/dev/zero", "of="+pvname, "bs=1", "count=1",
                   "seek=" + str(capacity)]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            cmd = ["losetup", "-f"]
            freedev = subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            freedev = freedev.strip("\n")
            cmd = ["losetup", freedev, pvname,]

            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            return freedev
        except Exception as ex:
            print "Cannot create or mount pvname "
            raise

    def deletepv(pvname):
        os.remove(pvname)

    def formatfs(mountpath, start, end):
        try:
            freedev = subprocess.check_output(["losetup", "-f"],
                                               stderr=subprocess.STDOUT)
            freedev = freedev.strip("\n")
            subprocess.check_output(["losetup", freedev, mountpath, "-o",
                               str(int(start)*512), "--sizelimit",
                               str((int(end) - int(start) + 1)/2) + "KiB"],
                               stderr=subprocess.STDOUT)
            cmd = ["mkfs", "-t", "ext4", freedev]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            return freedev
        except Exception as ex:
            print "Cannot create loop device and format the file system"

    def setup():
        mountpoint = createpv("pvname1", "1TiB")
        devices = []
   
        cmd = ["parted", mountpoint, "mklabel", "msdos"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["parted", mountpoint, "mkpart", "primary", "ext2", str(1024), str(10240)]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["parted", mountpoint, "mkpart", "primary", "ext2", str(10240), str(2 * 10240)]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["parted", mountpoint, "mkpart", "primary", "ext2", str(2 * 10240), str(10 * 10240)]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["parted", mountpoint, "mkpart", "extended", str(10 * 10240), str(100 * 10240)]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["parted", mountpoint, "mkpart", "logical", "ext2", str(11 * 10240), str(20 * 10240)]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        devices.append(formatfs(mountpoint, 2000896, 20000767))
        devices.append(formatfs(mountpoint, 20000768, 39999487))
        devices.append(formatfs(mountpoint, 39999488, 199999487))
        devices.append(formatfs(mountpoint, 220000256, 400001023))

        return mountpoint, devices

    def cleanup():
        cmd = ["losetup", "-a"]
        devs = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        devices = []
        for dev in devs.strip().split("\n"):
            devices.append(dev.strip().split(":")[0].strip())

        for dev in sorted(devices, reverse=True):
            cmd = ["losetup", "-d", dev]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        deletepv("pvname1")
        os.remove("vmdk")
 
    currentmodule = sys.modules[__name__]
    # Following is the mock code to test the thick copy
    def create_empty_vmdk_mock(filepath, capacity):
        cmd = ["dd", "if=/dev/zero", "of="+filepath, "bs=1", "count=1", "seek=" + str(capacity)]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

    def my_mount_disk(diskslist, mntlist, diskonly=False):
        with open(diskslist, 'r') as f:
            for line in f:
                return None, {'disk1': [line + ";"]}

    def my_populate_extent(hostip, username, password, vmspec, remotepath,
                           mountpath, start, count):
        cmd = ["dd", "if="+remotepath, "of="+mountpath, "bs=512", "count=" +
               str(count), "seek=" + str(start), "skip="+str(start), "conv=notrunc"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

    def my_populate_extents(hostip, username, password, vmspec, remotepath,
                           mountpath, extentsfile):
        with open(extentsfile, 'r') as f:
            for line in f:
                start = int(line.split(",")[0])/512
                count = int(line.split(",")[1])/512
                my_populate_extent(hostip, username, password, vmspec,
                                remotepath, mountpath, start, count)

    @mock.patch('workloadmgr.virt.vmwareapi.thickcopy.populate_extents', side_effect=my_populate_extents)
    @mock.patch('workloadmgr.virt.vmwareapi.thickcopy.populate_extent', side_effect=my_populate_extent)
    @mock.patch('workloadmgr.virt.vmwareapi.thickcopy.umount_local_vmdk')
    @mock.patch('workloadmgr.virt.vmwareapi.thickcopy.mount_local_vmdk', side_effect=my_mount_disk)
    @mock.patch('workloadmgr.virt.vmwareapi.thickcopy.create_empty_vmdk', side_effect=create_empty_vmdk_mock)
    def test(method1, method2, method3, method4, method5):
        dev = {'capacityInBytes': 1099511627776L, 'backing' : {'fileName' : mountpoint}}
        localvmdkpath = "vmdk"
        workloadmgr.virt.vmwareapi.thickcopy.create_empty_vmdk(localvmdkpath, dev['capacityInBytes'])
        extentsfile, partitions, totalblocks, listfile, mntlist = \
              workloadmgr.virt.vmwareapi.thickcopy.thickcopyextents(None,
                             None, None, None, dev, localvmdkpath)
        print extentsfile, partitions, totalblocks, listfile, mntlist

    try:
        mountpoint, devices = setup() 
        test()
    finally:
        cleanup()

# thick copy when the entire disk is partitioned into 3 primary partitions and 
# 1 logical partition and each formatted to ext4 file systems
def test_gpt_partitions():

    def createpv(pvname, capacity):
        try:
            cmd = ["dd", "if=/dev/zero", "of="+pvname, "bs=1", "count=1",
                   "seek=" + str(capacity)]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            cmd = ["losetup", "-f"]
            freedev = subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            freedev = freedev.strip("\n")
            cmd = ["losetup", freedev, pvname,]

            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            return freedev
        except Exception as ex:
            print "Cannot create or mount pvname "
            raise

    def deletepv(pvname):
        os.remove(pvname)

    def formatfs(mountpath, start, end):
        try:
            freedev = subprocess.check_output(["losetup", "-f"],
                                               stderr=subprocess.STDOUT)
            freedev = freedev.strip("\n")
            subprocess.check_output(["losetup", freedev, mountpath, "-o",
                               str(int(start)*512), "--sizelimit",
                               str((int(end) - int(start) + 1)/2) + "KiB"],
                               stderr=subprocess.STDOUT)
            cmd = ["mkfs", "-t", "ext4", freedev]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            return freedev
        except Exception as ex:
            print "Cannot create loop device and format the file system"

    def setup():
        mountpoint = createpv("pvname1", "1TiB")
        devices = []
   
        cmd = ["parted", mountpoint, "mklabel", "gpt"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["parted", mountpoint, "mkpart", "P1", "ext2", str(1024), str(10240)]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["parted", mountpoint, "mkpart", "P2", "ext2", str(10240), str(2 * 10240)]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["parted", mountpoint, "mkpart", "P2", "ext2", str(2 * 10240), str(10 * 10240)]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["parted", mountpoint, "mkpart", "P2", str(10 * 10240), str(100 * 10240)]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        devices.append(formatfs(mountpoint, 2000896, 20000767))
        devices.append(formatfs(mountpoint, 20000768, 39999487))
        devices.append(formatfs(mountpoint, 39999488, 199999487))
        devices.append(formatfs(mountpoint, 199999488, 2000001023))
        return mountpoint, devices

    def cleanup():
        cmd = ["losetup", "-a"]
        devs = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        devices = []
        for dev in devs.strip().split("\n"):
            devices.append(dev.strip().split(":")[0].strip())

        for dev in sorted(devices, reverse=True):
            cmd = ["losetup", "-d", dev]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        deletepv("pvname1")
        os.remove("vmdk")

    def verify():
        pass

    currentmodule = sys.modules[__name__]
    # Following is the mock code to test the thick copy
    def create_empty_vmdk_mock(filepath, capacity):
        cmd = ["dd", "if=/dev/zero", "of="+filepath, "bs=1", "count=1", "seek=" + str(capacity)]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

    def my_mount_disk(diskslist, mntlist, diskonly=False):
        with open(diskslist, 'r') as f:
            for line in f:
                return None, {'disk1': [line + ";"]}

    def my_populate_extent(hostip, username, password, vmspec, remotepath,
                           mountpath, start, count):
        cmd = ["dd", "if="+remotepath, "of="+mountpath, "bs=512", "count=" +
               str(count), "seek=" + str(start), "skip="+str(start), "conv=notrunc"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

    def my_populate_extents(hostip, username, password, vmspec, remotepath,
                           mountpath, extentsfile):
        with open(extentsfile, 'r') as f:
            for line in f:
                start = int(line.split(",")[0])/512
                count = int(line.split(",")[1])/512
                my_populate_extent(hostip, username, password, vmspec,
                                remotepath, mountpath, start, count)

    @mock.patch('workloadmgr.virt.vmwareapi.thickcopy.populate_extents', side_effect=my_populate_extents)
    @mock.patch('workloadmgr.virt.vmwareapi.thickcopy.populate_extent', side_effect=my_populate_extent)
    @mock.patch('workloadmgr.virt.vmwareapi.thickcopy.umount_local_vmdk')
    @mock.patch('workloadmgr.virt.vmwareapi.thickcopy.mount_local_vmdk', side_effect=my_mount_disk)
    @mock.patch('workloadmgr.virt.vmwareapi.thickcopy.create_empty_vmdk', side_effect=create_empty_vmdk_mock)
    def test(method1, method2, method3, method4, method5):
        dev = {'capacityInBytes': 1099511627776L, 'backing' : {'fileName' : mountpoint}}
        localvmdkpath = "vmdk"
        workloadmgr.virt.vmwareapi.thickcopy.create_empty_vmdk(localvmdkpath, dev['capacityInBytes'])
        extentsfile, partitions, totalblocks, listfile, mntlist = \
              workloadmgr.virt.vmwareapi.thickcopy.thickcopyextents(None,
                             None, None, None, dev, localvmdkpath)
        print extentsfile, partitions, totalblocks, listfile, mntlist

    try:
        mountpoint, devices = setup() 
        test()
    finally:
        cleanup()

if __name__ == "__main__":
    test_lv_entire_disk()
    #test_lv_on_partitions()
    #test_mbr_4_primary_partitions()
    #test_mbr_3_primary_1_logical_partitions()
    #test_gpt_partitions()
