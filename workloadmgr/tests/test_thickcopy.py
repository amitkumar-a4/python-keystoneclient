import unittest
import mock
import sys
import os
import subprocess
import os.path
from tempfile import mkstemp
from tempfile import mkdtemp
import time
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
            time.sleep(1)
            cmd = ["umount", "/dev/vg1/"+lv]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        shutil.rmtree(tempdir)

        cmd = ["losetup", "-d", mountpoint]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        vgcmd = ["vgchange", "-an", "vg1"]
        subprocess.check_output(vgcmd, stderr=subprocess.STDOUT)
        return 

    def cleanup():
        deletepv("pvname1")
        if os.path.isfile("vmdk"):
            os.remove("vmdk")
 
    def verify(remotepath, extentsfile, vmdkfile):
        try:
            my_populate_extents(None, None, None, None, remotepath,
                                vmdkfile, extentsfile)
            freedev = subprocess.check_output(["losetup", "-f"],
                                                stderr=subprocess.STDOUT)
            freedev = freedev.strip("\n")

            subprocess.check_output(["losetup", freedev, vmdkfile,],
                                   stderr=subprocess.STDOUT)
            pvinfo = workloadmgr.virt.vmwareapi.thickcopy._getpvinfo(freedev, '0', '1099511627776L')
            # explore VGs and volumes on the disk
            vgs = workloadmgr.virt.vmwareapi.thickcopy.getvgs()
               
            if len(vgs) == 0:
               raise Exception("No VGs found on VMDK. Test failed")
 
            lvs = workloadmgr.virt.vmwareapi.thickcopy.getlvs(vgs[0]['LVM2_VG_NAME'])
            if len(lvs) != 4:
               raise Exception("Number of LVs found is not 4. Test Failed")

            tempdir = mkdtemp()
            for lv in ["lv1", "lv2", "lv3", "lv4"]:
                cmd = ["mount", "-t", "ext4", "/dev/vg1/"+lv, tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                cmd = ["diff", "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                       tempdir + "/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz"]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                time.sleep(1)
                cmd = ["umount", "/dev/vg1/"+lv]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            shutil.rmtree(tempdir)

            for vg in vgs:
                workloadmgr.virt.vmwareapi.thickcopy.deactivatevgs(vg['LVM2_VG_NAME'])
         
        except Exception as ex:
            LOG.exception(ex)
            LOG.info(_(remotepath + " does not have lvm pv"))
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
        dev = {'capacityInBytes': 1099511627776L, 'backing' : {'fileName' : "pvname1"}}
        localvmdkpath = "vmdk"
        workloadmgr.virt.vmwareapi.thickcopy.create_empty_vmdk(localvmdkpath, dev['capacityInBytes'])
        extentsfile, partitions, totalblocks = \
              workloadmgr.virt.vmwareapi.thickcopy.thickcopyextents(None,
                             None, None, None, dev, localvmdkpath)
        return extentsfile, partitions, totalblocks

    try:
        print "Running test_lv_entire_disk(): "
        setup() 
        print "\tSetup complete"
        extentsfile, partitions, totalblocks = test()
        print "\ttest() complete"
        verify("pvname1", extentsfile, "vmdk")
        print "\t verified successfully"
        if os.path.isfile(extentsfile):
            os.remove(extentsfile)
    finally:
        cleanup()
        print"\tcleanup done"

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

        devices.append(assigndevice(mountpoint, 2000896, 1953124351))

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

            tempdir = mkdtemp()
            for lv in ["lv1", "lv2", "lv3", "lv4"]:
                cmd = ["mount", "-t", "ext4", "/dev/vg1/"+lv, tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                cmd = ["cp", "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz", tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                time.sleep(1)
                cmd = ["umount", "/dev/vg1/"+lv]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            shutil.rmtree(tempdir)

            vgcmd = ["vgchange", "-an", "vg1"]
            subprocess.check_output(vgcmd, stderr=subprocess.STDOUT)
            vgcmd = ["vgexport", "vg1"]
            #subprocess.check_output(vgcmd, stderr=subprocess.STDOUT)
            cmd = ["losetup", "-d", dev]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["losetup", "-d", mountpoint]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        return 

    def cleanup():
        for lv in ["lv1", "lv2", "lv3", "lv4"]:
            cmd = ["lvremove", "-f", "/dev/vg1/" + lv]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["vgremove", "vg1"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["losetup", "-a"]
        devs = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        devices = []
        for dev in devs.strip().split("\n"):
            devices.append(dev.strip().split(":")[0].strip())

        for pv in subprocess.check_output(["pvs", "--noheading"]).strip().split("\n"):
            try:
                cmd = ["pvremove", pv.split()[0]]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            except:
                pass

        for dev in sorted(devices, reverse=True):
            cmd = ["losetup", "-d", dev]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

 
    def verify(remotepath, extentsfile, vmdkfile):
        try:
            my_populate_extents(None, None, None, None, remotepath,
                                vmdkfile, extentsfile)

            freedev = assigndevice(vmdkfile, 2000896, 1953124351)

            pvinfo = workloadmgr.virt.vmwareapi.thickcopy._getpvinfo(freedev, '0', (1953124351 - 2000896 + 1) * 512)
            # explore VGs and volumes on the disk
            vgs = workloadmgr.virt.vmwareapi.thickcopy.getvgs()
               
            if len(vgs) == 0:
               raise Exception("No VGs found on VMDK. Test failed")
 
            lvs = workloadmgr.virt.vmwareapi.thickcopy.getlvs(vgs[0]['LVM2_VG_NAME'])
            if len(lvs) != 4:
               raise Exception("Number of LVs found is not 4. Test Failed")

            # this test is assuming one partition per disk. We need additional tests for multiple 
            # partitions per disk
            tempdir = mkdtemp()
            for lv in ["lv1", "lv2", "lv3", "lv4"]:
                cmd = ["mount", "-t", "ext4", "/dev/vg1/"+lv, tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                cmd = ["diff", "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                       tempdir + "/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz"]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                time.sleep(1)
                cmd = ["umount", "/dev/vg1/"+lv]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            shutil.rmtree(tempdir)

            for vg in vgs:
                workloadmgr.virt.vmwareapi.thickcopy.deactivatevgs(vg['LVM2_VG_NAME'])
         
        except Exception as ex:
            LOG.exception(ex)
            LOG.info(_(vmdkfile + " does not have lvm pv"))
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
        dev = {'capacityInBytes': 1099511627776L, 'backing' : {'fileName' : "pvname1"}}
        localvmdkpath = "vmdk"
        workloadmgr.virt.vmwareapi.thickcopy.create_empty_vmdk(localvmdkpath, dev['capacityInBytes'])
        extentsfile, partitions, totalblocks = \
              workloadmgr.virt.vmwareapi.thickcopy.thickcopyextents(None,
                             None, None, None, dev, localvmdkpath)
        return extentsfile, partitions, totalblocks

    try:
        print "Running test_lv_on_partitions():"
        setup() 
        print "\tSetup() complete"
        extentsfile, partitions, totalblocks = test()
        print "\ttest() done"

        # first clean up and then verify so the volume groups do not interfere
        # with existing volume groups
        verify("pvname1", extentsfile, "vmdk")
        print "\tverification done"

        if os.path.isfile(extentsfile):
            os.remove(extentsfile)

    finally:
        deletepv("pvname1")
        if os.path.isfile("vmdk"):
            os.remove("vmdk")
        print "\t cleanup done"

## 
# LVM PV is carved out of 
def test_lvs_on_two_partitions():

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
        cmd = ["parted", mountpoint, "mkpart", "P1", "ext2", str(1024), str("500GB")]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        cmd = ["parted", mountpoint, "mkpart", "P2", "ext2", str("500GB"), str("1000GB")]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        devices.append(assigndevice(mountpoint, 2000896, 976562175))
        devices.append(assigndevice(mountpoint, 976562176, 1953124351))

        for dev in devices:
            cmd = ["pvcreate", dev]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            cmd = ["vgcreate", "vg1" + dev.split("/")[2], dev]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
    
            # create multiple volumes
            for lv in ["lv1", "lv2", "lv3", "lv4"]:
                cmd = ["lvcreate", "-L", "1G", "vg1" + dev.split("/")[2], "-n", dev.split("/")[2] + lv]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            # Format each volume to a filesystem
            for lv in ["lv1", "lv2", "lv3", "lv4"]:
                cmd = ["mkfs", "-t", "ext4", "/dev/vg1" + 
                       dev.split("/")[2] + "/" + dev.split("/")[2] + lv]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            tempdir = mkdtemp()
            for lv in ["lv1", "lv2", "lv3", "lv4"]:
                cmd = ["mount", "-t", "ext4", "/dev/vg1" +
                        dev.split("/")[2] + "/" + dev.split("/")[2] + lv, tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                cmd = ["cp", "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz", tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                time.sleep(1)
                cmd = ["umount", "/dev/vg1" +
                       dev.split("/")[2] + "/" + dev.split("/")[2] + lv]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            shutil.rmtree(tempdir)

        vgcmd = ["vgchange", "-an",]
        subprocess.check_output(vgcmd, stderr=subprocess.STDOUT)

            #vgcmd = ["vgexport", "vg1"]
            #subprocess.check_output(vgcmd, stderr=subprocess.STDOUT)
        for dev in devices:
            cmd = ["losetup", "-d", dev]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["losetup", "-d", mountpoint]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        vgcmd = ["vgchange", "-an",]
        subprocess.check_output(vgcmd, stderr=subprocess.STDOUT)

        return 

    def verify(remotepath, extentsfile, vmdkfile):
        try:
            my_populate_extents(None, None, None, None, remotepath,
                                vmdkfile, extentsfile)

            devices = []
            devices.append(assigndevice(vmdkfile, 2000896, 976562175))
            devices.append(assigndevice(vmdkfile, 976562176, 1953124351))

            pvinfo = workloadmgr.virt.vmwareapi.thickcopy._getpvinfo(devices[0], '0', (976562175 - 2000896 + 1) * 512)
            pvinfo = workloadmgr.virt.vmwareapi.thickcopy._getpvinfo(devices[1], '0', (1953124351 - 976562176 + 1) * 512)

            # explore VGs and volumes on the disk
            vgs = workloadmgr.virt.vmwareapi.thickcopy.getvgs()
               
            if len(vgs) == 0:
               raise Exception("No VGs found on VMDK. Test failed")
 
            lvs = []
            for vg in vgs:
                lvs += workloadmgr.virt.vmwareapi.thickcopy.getlvs(vg['LVM2_VG_NAME'])
            if len(lvs) != 8:
               raise Exception("Number of LVs found is not 8. Test Failed")

            # this test is assuming one partition per disk. We need additional tests for multiple 
            # partitions per disk
            tempdir = mkdtemp()
            for lv in lvs:
                    cmd = ["mount", "-t", "ext4", lv['LVM2_LV_PATH'], tempdir]
                    subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                    cmd = ["diff", "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                           tempdir + "/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz"]
                    subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                    time.sleep(1)
                    cmd = ["umount", lv['LVM2_LV_PATH']]
                    subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            shutil.rmtree(tempdir)

            for vg in vgs:
                workloadmgr.virt.vmwareapi.thickcopy.deactivatevgs(vg['LVM2_VG_NAME'])
         
        except Exception as ex:
            LOG.exception(ex)
            LOG.info(_(vmdkfile + " does not have lvm pv"))
            raise
        finally:
            try:
                for freedev in devices:
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
        dev = {'capacityInBytes': 1099511627776L, 'backing' : {'fileName' : "pvname1"}}
        localvmdkpath = "vmdk"
        workloadmgr.virt.vmwareapi.thickcopy.create_empty_vmdk(localvmdkpath, dev['capacityInBytes'])
        extentsfile, partitions, totalblocks = \
              workloadmgr.virt.vmwareapi.thickcopy.thickcopyextents(None,
                             None, None, None, dev, localvmdkpath)
        return extentsfile, partitions, totalblocks

    try:
        print "Running test_lvs_on_two_partitions():"
        setup() 
        print "\tsetup() complete"
        extentsfile, partitions, totalblock = test()
        print "\ttest() done"

        # first clean up and then verify so the volume groups do not interfere
        # with existing volume groups
        verify("pvname1", extentsfile, "vmdk")
        print "\tverification done"

        if os.path.isfile(extentsfile):
            os.remove(extentsfile)

    finally:
        deletepv("pvname1")
        if os.path.isfile("vmdk"):
            os.remove("vmdk")
        print "\t cleanup done"

## 
# LVM PV is carved out of 
def test_lvs_span_two_partitions():

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
        cmd = ["parted", mountpoint, "mkpart", "P1", "ext2", str(1024), str("500GB")]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        cmd = ["parted", mountpoint, "mkpart", "P2", "ext2", str("500GB"), str("1000GB")]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        devices.append(assigndevice(mountpoint, 2000896, 976562175))
        devices.append(assigndevice(mountpoint, 976562176, 1953124351))

        for dev in devices:
            cmd = ["pvcreate", dev]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["vgcreate", "vg1", ] + devices
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
    
        # create multiple volumes
        for lv in ["lv1", "lv2", "lv3"]:
            cmd = ["lvcreate", "-L", "300G", "vg1", "-n", lv]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        # Format each volume to a filesystem
        for lv in ["lv1", "lv2", "lv3"]:
            cmd = ["mkfs", "-t", "ext4", "/dev/vg1/" + lv]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        tempdir = mkdtemp()
        for lv in ["lv1", "lv2", "lv3"]:
            cmd = ["mount", "-t", "ext4", "/dev/vg1/" + lv, tempdir]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            cmd = ["cp", "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz", tempdir]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            time.sleep(1)
            cmd = ["umount", "/dev/vg1/" + lv]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        shutil.rmtree(tempdir)

        vgcmd = ["vgchange", "-an",]
        subprocess.check_output(vgcmd, stderr=subprocess.STDOUT)

            #vgcmd = ["vgexport", "vg1"]
            #subprocess.check_output(vgcmd, stderr=subprocess.STDOUT)
        for dev in devices:
            cmd = ["losetup", "-d", dev]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["losetup", "-d", mountpoint]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        vgcmd = ["vgchange", "-an",]
        subprocess.check_output(vgcmd, stderr=subprocess.STDOUT)

        return 

    def verify(remotepath, extentsfile, vmdkfile):
        try:
            my_populate_extents(None, None, None, None, remotepath,
                                vmdkfile, extentsfile)

            devices = []
            devices.append(assigndevice(vmdkfile, 2000896, 976562175))
            devices.append(assigndevice(vmdkfile, 976562176, 1953124351))

            pvinfo = workloadmgr.virt.vmwareapi.thickcopy._getpvinfo(devices[0], '0', (976562175 - 2000896 + 1) * 512)
            pvinfo = workloadmgr.virt.vmwareapi.thickcopy._getpvinfo(devices[1], '0', (1953124351 - 976562176 + 1) * 512)

            # explore VGs and volumes on the disk
            vgs = workloadmgr.virt.vmwareapi.thickcopy.getvgs()
               
            if len(vgs) == 0:
               raise Exception("No VGs found on VMDK. Test failed")
 
            lvs = []
            for vg in vgs:
                lvs += workloadmgr.virt.vmwareapi.thickcopy.getlvs(vg['LVM2_VG_NAME'])
            if len(lvs) != 3:
               raise Exception("Number of LVs found is not 3. Test Failed")

            # this test is assuming one partition per disk. We need additional tests for multiple 
            # partitions per disk
            tempdir = mkdtemp()
            for lv in lvs:
                    cmd = ["mount", "-t", "ext4", lv['LVM2_LV_PATH'], tempdir]
                    subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                    cmd = ["diff", "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                           tempdir + "/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz"]
                    subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                    time.sleep(1)
                    cmd = ["umount", lv['LVM2_LV_PATH']]
                    subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            shutil.rmtree(tempdir)

            for vg in vgs:
                workloadmgr.virt.vmwareapi.thickcopy.deactivatevgs(vg['LVM2_VG_NAME'])
         
        except Exception as ex:
            LOG.exception(ex)
            LOG.info(_(vmdkfile + " does not have lvm pv"))
            raise
        finally:
            try:
                for freedev in devices:
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
        dev = {'capacityInBytes': 1099511627776L, 'backing' : {'fileName' : "pvname1"}}
        localvmdkpath = "vmdk"
        workloadmgr.virt.vmwareapi.thickcopy.create_empty_vmdk(localvmdkpath, dev['capacityInBytes'])
        extentsfile, partitions, totalblocks = \
              workloadmgr.virt.vmwareapi.thickcopy.thickcopyextents(None,
                             None, None, None, dev, localvmdkpath)
        return extentsfile, partitions, totalblocks

    try:
        print "Running test_lvs_on_two_partitions():"
        setup() 
        print "\tsetup() complete"
        extentsfile, partitions, totalblocks = test()
        print "\ttest() done"

        # first clean up and then verify so the volume groups do not interfere
        # with existing volume groups
        verify("pvname1", extentsfile, "vmdk")
        print "\tverification done"

        if os.path.isfile(extentsfile):
            os.remove(extentsfile)

    finally:
        deletepv("pvname1")
        if os.path.isfile("vmdk"):
            os.remove("vmdk")
        print "\t cleanup done"

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

        tempdir = mkdtemp()
        for dev in devices:
            cmd = ["mount", "-t", "ext4", dev, tempdir]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            cmd = ["cp", "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz", tempdir]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            time.sleep(1)
            cmd = ["umount", dev]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        shutil.rmtree(tempdir)

        for dev in devices:
            cmd = ["losetup", "-d", dev]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["losetup", "-d", "/dev/loop0"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        return mountpoint

    def cleanup():
        deletepv("pvname1")
        if os.path.isfile("vmdk"):
            os.remove("vmdk")
 
    def verify(remotepath, extentsfile, vmdkfile):
        try:
            my_populate_extents(None, None, None, None, remotepath,
                                vmdkfile, extentsfile)

            partitions = workloadmgr.virt.vmwareapi.thickcopy.read_partition_table(vmdkfile)
            for part in partitions:
                try:
                    freedev = subprocess.check_output(["losetup", "-f"],
                                                        stderr=subprocess.STDOUT)
                    freedev = freedev.strip("\n")

                    subprocess.check_output(["losetup", freedev, vmdkfile, "-o",
                                            str(int(part['start'])*512), "--sizelimit",
                                            str((int(part['end']) - int(part['start']) + 1)/2) + "KiB"],
                                           stderr=subprocess.STDOUT)

                    tempdir = mkdtemp()
                    cmd = ["mount", "-t", "ext4", freedev, tempdir]
                    subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                    cmd = ["diff", "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                           tempdir + "/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz"]
                    subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                    time.sleep(1)
                    cmd = ["umount", freedev]
                    subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                    shutil.rmtree(tempdir)
                finally:
                    if freedev:
                        cmd = ["losetup", "-d", freedev]
                        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
         
        except Exception as ex:
            LOG.exception(ex)
            LOG.info(_(vmdkfile + " does not have lvm pvs"))
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
        dev = {'capacityInBytes': 1099511627776L, 'backing' : {'fileName' : "pvname1"}}
        localvmdkpath = "vmdk"
        workloadmgr.virt.vmwareapi.thickcopy.create_empty_vmdk(localvmdkpath, dev['capacityInBytes'])
        extentsfile, partitions, totalblocks = \
              workloadmgr.virt.vmwareapi.thickcopy.thickcopyextents(None,
                             None, None, None, dev, localvmdkpath)
        return extentsfile, partitions, totalblocks

    try:
        print "Running test_mbr_4_primary_partitions():"
        setup() 
        print "\tSetup() done"
 
        extentsfile, partitions, totalblocks = test()
        print "\t test() done"

        verify("pvname1", extentsfile, "vmdk")
        print "\tverification done"
        if os.path.isfile(extentsfile):
            os.remove(extentsfile)
    finally:
        cleanup()
        print "\t cleanup done"

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

        tempdir = mkdtemp()
        for dev in devices:
            cmd = ["mount", "-t", "ext4", dev, tempdir]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            cmd = ["cp", "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz", tempdir]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            time.sleep(1)
            cmd = ["umount", dev]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        shutil.rmtree(tempdir)

        cmd = ["losetup", "-a"]
        devs = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        devices = []
        for dev in devs.strip().split("\n"):
            devices.append(dev.strip().split(":")[0].strip())

        for dev in sorted(devices, reverse=True):
            cmd = ["losetup", "-d", dev]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        return mountpoint

    def cleanup():

        deletepv("pvname1")
        if os.path.isfile("vmdk"):
            os.remove("vmdk")

    def verify(remotepath, extentsfile, vmdkfile):
        try:
            my_populate_extents(None, None, None, None, remotepath,
                                vmdkfile, extentsfile)

            partitions = workloadmgr.virt.vmwareapi.thickcopy.read_partition_table(vmdkfile)
            for part in partitions:
                if part['id'] == '5' or part['id'] == 'f':
                    continue
                try:

                    freedev = subprocess.check_output(["losetup", "-f"],
                                                        stderr=subprocess.STDOUT)
                    freedev = freedev.strip("\n")

                    subprocess.check_output(["losetup", freedev, vmdkfile, "-o",
                                            str(int(part['start'])*512), "--sizelimit",
                                            str((int(part['end']) - int(part['start']) + 1)/2) + "KiB"],
                                           stderr=subprocess.STDOUT)

                    tempdir = mkdtemp()
                    cmd = ["mount", "-t", "ext4", freedev, tempdir]
                    subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                    cmd = ["diff", "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                           tempdir + "/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz"]
                    subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                    time.sleep(1)
                    cmd = ["umount", freedev]
                    subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                    shutil.rmtree(tempdir)
                finally:
                    if freedev:
                        cmd = ["losetup", "-d", freedev]
                        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
         
        except Exception as ex:
            LOG.exception(ex)
            LOG.info(_(vmdkfile + " does not have lvm pvs"))
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
        dev = {'capacityInBytes': 1099511627776L, 'backing' : {'fileName' : "pvname1"}}
        localvmdkpath = "vmdk"
        workloadmgr.virt.vmwareapi.thickcopy.create_empty_vmdk(localvmdkpath, dev['capacityInBytes'])
        extentsfile, partitions, totalblocks = \
              workloadmgr.virt.vmwareapi.thickcopy.thickcopyextents(None,
                             None, None, None, dev, localvmdkpath)
        return extentsfile, partitions, totalblocks

    try:
        import pdb;pdb.set_trace()
        print "Running test_mbr_3_primary_1_logical_partitions():"
        setup() 
        print "\tSetup done"
        extentsfile, partitions, totalblocks = test()
        print "\ttest() done."
        verify("pvname1", extentsfile, "vmdk")
        print "\tverification done."
        if os.path.isfile(extentsfile):
            os.remove(extentsfile)
    finally:
        cleanup()
        print "\tcleanup done"

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

        tempdir = mkdtemp()
        for dev in devices:
            cmd = ["mount", "-t", "ext4", dev, tempdir]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            cmd = ["cp", "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz", tempdir]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            time.sleep(1)
            cmd = ["umount", dev]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        shutil.rmtree(tempdir)

        cmd = ["losetup", "-a"]
        devs = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        devices = []
        for dev in devs.strip().split("\n"):
            devices.append(dev.strip().split(":")[0].strip())

        for dev in sorted(devices, reverse=True):
            cmd = ["losetup", "-d", dev]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        return mountpoint

    def cleanup():
        deletepv("pvname1")
        if os.path.isfile("vmdk"):
            os.remove("vmdk")

    def verify(remotepath, extentsfile, vmdkfile):
        try:
            my_populate_extents(None, None, None, None, remotepath,
                                vmdkfile, extentsfile)

            partitions = workloadmgr.virt.vmwareapi.thickcopy.read_partition_table(vmdkfile)
            for part in partitions:
                try:
                    freedev = subprocess.check_output(["losetup", "-f"],
                                                        stderr=subprocess.STDOUT)
                    freedev = freedev.strip("\n")

                    subprocess.check_output(["losetup", freedev, vmdkfile, "-o",
                                            str(int(part['start'])*512), "--sizelimit",
                                            str((int(part['end']) - int(part['start']) + 1)/2) + "KiB"],
                                           stderr=subprocess.STDOUT)

                    tempdir = mkdtemp()
                    cmd = ["mount", "-t", "ext4", freedev, tempdir]
                    subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                    cmd = ["diff", "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                           tempdir + "/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz"]
                    subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                    time.sleep(1)
                    cmd = ["umount", freedev]
                    subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                    shutil.rmtree(tempdir)
                finally:
                    if freedev:
                        cmd = ["losetup", "-d", freedev]
                        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
         
        except Exception as ex:
            LOG.exception(ex)
            LOG.info(_(vmdkfile + " does not have lvm pvs"))
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
        dev = {'capacityInBytes': 1099511627776L, 'backing' : {'fileName' : "pvname1"}}
        localvmdkpath = "vmdk"
        workloadmgr.virt.vmwareapi.thickcopy.create_empty_vmdk(localvmdkpath, dev['capacityInBytes'])
        extentsfile, partitions, totalblocks = \
              workloadmgr.virt.vmwareapi.thickcopy.thickcopyextents(None,
                             None, None, None, dev, localvmdkpath)
        return extentsfile, partitions, totalblocks

    try:
        print "Running test_gpt_partitions():"
        setup() 
        print "\tsetup done"

        extentsfile, partitions, totalblocks = test()
        print "\ttest() done"
        verify("pvname1", extentsfile, "vmdk")
        print "\t verification done"

        if os.path.isfile(extentsfile):
            os.remove(extentsfile)
    finally:
        cleanup()
        print "\t cleanup done"

def test_raw_disk():

    def createpv(pvname, capacity):
        try:
            cmd = ["dd", "if=/dev/zero", "of="+pvname, "bs=1", "count=1",
                   "seek=" + str(capacity)]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        except Exception as ex:
            print "Cannot create or mount pvname "
            raise

    def deletepv(pvname):
        os.remove(pvname)

    def setup():
        mountpoint = createpv("pvname1", "1TiB")

    def cleanup():
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
        dev = {'capacityInBytes': 1099511627776L, 'backing' : {'fileName' : "pvname1"}}
        localvmdkpath = "vmdk"
        workloadmgr.virt.vmwareapi.thickcopy.create_empty_vmdk(localvmdkpath, dev['capacityInBytes'])
        extentsfile, partitions, totalblocks = \
              workloadmgr.virt.vmwareapi.thickcopy.thickcopyextents(None,
                             None, None, None, dev, localvmdkpath)
        return extentsfile, partitions, totalblocks

    try:
        print "Running test_raw_disk():"
        setup() 
        print "\tsetup done"

        extentsfile, partitions, totalblocks = test()
        print "\ttest() done"
        
        verify("pvname1", extentsfile, "vmdk")
        print "\t verification done"

        if os.path.isfile(extentsfile):
            os.remove(extentsfile)
    finally:
        cleanup()
        print "\t cleanup done"

# thick copy when the entire disk is partitioned into 4 primary partitions and 
# formatted to ext4 file systems
def test_raw_partition():

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

        cmd = ["losetup", "-d", "/dev/loop0"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        return 

    def cleanup():
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
        dev = {'capacityInBytes': 1099511627776L, 'backing' : {'fileName' : "pvname1"}}
        localvmdkpath = "vmdk"
        workloadmgr.virt.vmwareapi.thickcopy.create_empty_vmdk(localvmdkpath, dev['capacityInBytes'])
        extentsfile, partitions, totalblocks = \
              workloadmgr.virt.vmwareapi.thickcopy.thickcopyextents(None,
                             None, None, None, dev, localvmdkpath)
        return extentsfile, partitions, totalblocks

    try:
        print "Running test_raw_partition():"
        setup() 
        print "\tSetup() done"
 
        extentsfile, partitions, totalblocks = test()
        print "\t test() done"

        if os.path.isfile(extentsfile):
            os.remove(extentsfile)
    finally:
        cleanup()
        print "\t cleanup done"

if __name__ == "__main__":
    #test_lv_entire_disk()
    #test_lv_on_partitions()
    #test_lvs_on_two_partitions()
    #test_lvs_span_two_partitions()
    test_mbr_4_primary_partitions()
    #test_mbr_3_primary_1_logical_partitions()
    #test_gpt_partitions()
    #test_raw_disk()
    #test_raw_partition()
    
