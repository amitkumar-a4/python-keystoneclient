import unittest
import mock
import sys
import os
import re
import subprocess
import os.path
from tempfile import mkstemp
from tempfile import mkdtemp
import time
import shutil
import logging
from contextlib import contextmanager

import workloadmgr
from workloadmgr import exception
from workloadmgr.openstack.common import log as logging
from workloadmgr.openstack.common.gettextutils import _
from workloadmgr import autolog

LOG = logging.getLogger(__name__)
Logger = autolog.Logger(LOG)


def createpv(pvname, capacity, mount=True):
    try:
        cmd = [
            "dd",
            "if=/dev/zero",
            "of=" +
            pvname,
            "bs=1",
            "count=1",
            "seek=" +
            str(capacity)]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        freedev = None
        if mount:
            cmd = ["losetup", "-f"]
            freedev = subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            freedev = freedev.strip("\n")
            cmd = ["losetup", freedev, pvname, ]

            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            return freedev
    except Exception as ex:
        print "Cannot create or mount pvname "
        raise


def deletepv(pvname):
    os.remove(pvname)


currentmodule = sys.modules[__name__]
# Following is the mock code to test the thick copy


def create_empty_vmdk_mock(filepath, capacity):
    cmd = [
        "dd",
        "if=/dev/zero",
        "of=" +
        filepath,
        "bs=1",
        "count=1",
        "seek=" +
        str(capacity)]
    subprocess.check_output(cmd, stderr=subprocess.STDOUT)


@contextmanager
def my_mount_disk(diskslist, mntlist, diskonly=False):
    diskmounts = {}
    with open(diskslist, 'r') as f:
        for line in f:
            line = line.strip().rstrip()
            diskmounts[line] = [line + ";"]

    yield diskmounts


def my_populate_extent(hostip, username, password, vmspec, remotepath,
                       mountpath, start, count):
    cmd = [
        "dd",
        "if=" +
        remotepath,
        "of=" +
        mountpath,
        "bs=512",
        "count=" +
        str(count),
        "seek=" +
        str(start),
        "skip=" +
        str(start),
        "conv=notrunc"]
    subprocess.check_output(cmd, stderr=subprocess.STDOUT)


def my_populate_extents(hostip, username, password, vmspec, remotepath,
                        mountpath, extentsfile):
    with open(extentsfile, 'r') as f:
        for line in f:
            start = int(line.split(",")[0]) / 512
            count = int(line.split(",")[1]) / 512
            my_populate_extent(hostip, username, password, vmspec,
                               remotepath, mountpath, start, count)


def formatfs(mountpath, start, end):
    try:
        freedev = subprocess.check_output(["losetup", "-f"],
                                          stderr=subprocess.STDOUT)
        freedev = freedev.strip("\n")
        subprocess.check_output(["losetup", freedev, mountpath, "-o",
                                 str(int(start) * 512), "--sizelimit",
                                 str((int(end) - int(start) + 1) / 2) + "KiB"],
                                stderr=subprocess.STDOUT)
        cmd = ["mkfs", "-t", "ext4", freedev]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        return freedev
    except Exception as ex:
        print "Cannot create loop device and format the file system"


def assignloopdevice(mountpath, start, end):
    try:
        freedev = subprocess.check_output(["losetup", "-f"],
                                          stderr=subprocess.STDOUT)
        freedev = freedev.strip("\n")
        subprocess.check_output(["losetup", freedev, mountpath, "-o",
                                 str(int(start) * 512), "--sizelimit",
                                 str((int(end) - int(start) + 1) / 2) + "KiB"],
                                stderr=subprocess.STDOUT)
        return freedev
    except Exception as ex:
        print "Cannot create loop device"


@mock.patch('workloadmgr.virt.vmwareapi.thickcopy.populate_extents',
            side_effect=my_populate_extents)
@mock.patch('workloadmgr.virt.vmwareapi.thickcopy.populate_extent',
            side_effect=my_populate_extent)
@mock.patch('workloadmgr.virt.vmwareapi.thickcopy.umount_local_vmdk')
@mock.patch('workloadmgr.virt.vmwareapi.thickcopy.mount_local_vmdk',
            side_effect=my_mount_disk)
@mock.patch('workloadmgr.virt.vmwareapi.thickcopy.create_empty_vmdk',
            side_effect=create_empty_vmdk_mock)
def test(numberofdisks, method1, method2, method3, method4, method5):
    devicemap = []
    for devid in range(1, numberofdisks + 1):
        dev = {'capacityInBytes': 1099511627776,
               'backing': {'fileName': "pvname" + str(devid)}}
        localvmdkpath = "vmdk" + str(devid)
        devicemap.append({'dev': dev, 'localvmdkpath': localvmdkpath})
        workloadmgr.virt.vmwareapi.thickcopy.create_empty_vmdk(
            localvmdkpath, dev['capacityInBytes'])

    extentsinfo = workloadmgr.virt.vmwareapi.thickcopy.thickcopyextents(
        None, None, None, None, devicemap)
    return extentsinfo

#
# thick copy when the entire disk is a logical volume


def test_lv_entire_disk():

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
            cmd = ["mount", "-t", "ext4", "/dev/vg1/" + lv, tempdir]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            cmd = [
                "cp",
                "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                tempdir]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            time.sleep(1)
            cmd = ["umount", tempdir]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        shutil.rmtree(tempdir)

        cmd = ["losetup", "-d", mountpoint]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        vgcmd = ["vgchange", "-an", "vg1"]
        subprocess.check_output(vgcmd, stderr=subprocess.STDOUT)
        return

    def cleanup():
        pass

    def verify(extentsinfo):
        try:
            freedevs = []
            if not extentsinfo:
                print "extentsinfo is null. Test failed"
                raise Exception("extentsinfo is null. Test failed")

            if len(extentsinfo['extentsfiles']) != 1:
                print "Number of extents files is not 1. Test failed"
                raise Exception("extentsinfo is null. Test failed")

            for key, value in extentsinfo['extentsfiles'].iteritems():
                my_populate_extents(None, None, None, None, key,
                                    "vmdk" + key.split("pvname")[1], value)

            for key, value in extentsinfo['extentsfiles'].iteritems():
                freedev = subprocess.check_output(["losetup", "-f"],
                                                  stderr=subprocess.STDOUT)
                freedev = freedev.strip("\n")

                subprocess.check_output(["losetup", freedev, "vmdk" + key.split("pvname")[1], ],
                                        stderr=subprocess.STDOUT)

                pvinfo = workloadmgr.virt.vmwareapi.thickcopy._getpvinfo(
                    freedev)
                freedevs.append(freedev)

            # explore VGs and volumes on the disk
            vgs = workloadmgr.virt.vmwareapi.thickcopy.getvgs()

            if len(vgs) != 1:
                print "Number of VGs is not 1"
                raise Exception(
                    "Number of VGs found on VMDK is not 1. Test failed")

            lvs = workloadmgr.virt.vmwareapi.thickcopy.getlvs(vgs)
            if len(lvs) != 4:
                print "Number of LVs found is not 4. Test Failed"
                raise Exception("Number of LVs found is not 4. Test Failed")

            tempdir = mkdtemp()
            for lv in ["lv1", "lv2", "lv3", "lv4"]:
                cmd = ["mount", "-t", "ext4", "/dev/vg1/" + lv, tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                cmd = [
                    "diff",
                    "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                    tempdir +
                    "/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz"]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                time.sleep(1)
                cmd = ["umount", tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            shutil.rmtree(tempdir)

        except Exception as ex:
            print "Exception in verification. Verification failed"
            raise
        finally:
            for vg in vgs:
                workloadmgr.virt.vmwareapi.thickcopy.deactivatevgs(
                    vg['LVM2_VG_NAME'])

            try:
                for freedev in freedevs:
                    subprocess.check_output(["losetup", "-d", freedev],
                                            stderr=subprocess.STDOUT)
            except BaseException:
                pass

    try:
        print "Running test_lv_entire_disk(): "
        setup()
        print "\tSetup complete"

        extentsinfo = test(1)
        print "\ttest() complete"
        verify(extentsinfo)

        print "\t verified successfully"
    finally:
        cleanup()
        if extentsinfo and 'extentsfiles' in extentsinfo:
            for key, value in extentsinfo['extentsfiles'].iteritems():
                if os.path.isfile(value):
                    os.remove(value)

        for i in range(1, 2):
            deletepv("pvname" + str(i))
            if os.path.isfile("vmdk" + str(i)):
                os.remove("vmdk" + str(i))

        print"\tcleanup done"
        pass

##
# LVM PV is carved out of


def test_lv_on_partitions():

    def setup():
        mountpoint = createpv("pvname1", "1TiB")

        cmd = ["parted", mountpoint, "mklabel", "gpt"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        devices = []
        cmd = [
            "parted",
            mountpoint,
            "mkpart",
            "P1",
            "ext2",
            str(1024),
            str("1000G")]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        devices.append(assignloopdevice(mountpoint, 2000896, 1953124351))

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
                cmd = ["mount", "-t", "ext4", "/dev/vg1/" + lv, tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                cmd = [
                    "cp",
                    "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                    tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                time.sleep(1)
                cmd = ["umount", tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            shutil.rmtree(tempdir)

            vgcmd = ["vgchange", "-an", "vg1"]
            subprocess.check_output(vgcmd, stderr=subprocess.STDOUT)
            cmd = ["losetup", "-d", dev]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["losetup", "-d", mountpoint]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        return

    def cleanup():
        for i in range(1, 2):
            deletepv("pvname" + str(i))
            if os.path.isfile("vmdk" + str(i)):
                os.remove("vmdk" + str(i))

    def verify(extentsinfo):
        try:
            freedevs = []
            if not extentsinfo:
                print "extentsinfo is null. Test failed"
                raise Exception("extentsinfo is null. Test failed")

            if len(extentsinfo['extentsfiles']) != 1:
                print "Number of extents files is not 1. Test failed"
                raise Exception("extentsinfo is null. Test failed")

            for key, value in extentsinfo['extentsfiles'].iteritems():
                my_populate_extents(None, None, None, None, key,
                                    "vmdk" + key.split("pvname")[1], value)

            for key, value in extentsinfo['extentsfiles'].iteritems():
                freedev = subprocess.check_output(["losetup", "-f"],
                                                  stderr=subprocess.STDOUT)
                freedev = freedev.strip("\n")

                subprocess.check_output(["losetup", freedev, "vmdk" + key.split("pvname")[1], ],
                                        stderr=subprocess.STDOUT)

                pvinfo = workloadmgr.virt.vmwareapi.thickcopy._getpvinfo(
                    freedev + "p1")
                freedevs.append(freedev)

            vgs = workloadmgr.virt.vmwareapi.thickcopy.getvgs()

            if len(vgs) != 1:
                print "Number VGs found on VMDK is not 1. Test failed"
                raise Exception(
                    "Number VGs found on VMDK is not 1. Test failed")

            lvs = workloadmgr.virt.vmwareapi.thickcopy.getlvs(vgs)
            if len(lvs) != 4:
                print "Number of LVs found is not 4. Test Failed"
                raise Exception("Number of LVs found is not 4. Test Failed")

            # this test is assuming one partition per disk. We need additional tests for multiple
            # partitions per disk
            tempdir = mkdtemp()
            for lv in ["lv1", "lv2", "lv3", "lv4"]:
                cmd = ["mount", "-t", "ext4", "/dev/vg1/" + lv, tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                cmd = [
                    "diff",
                    "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                    tempdir +
                    "/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz"]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                time.sleep(1)
                cmd = ["umount", tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            shutil.rmtree(tempdir)

        except Exception as ex:
            print "Exception in verification. Verification failed"
            raise
        finally:
            for vg in vgs:
                workloadmgr.virt.vmwareapi.thickcopy.deactivatevgs(
                    vg['LVM2_VG_NAME'])

            for freedev in freedevs:
                try:
                    subprocess.check_output(["losetup", "-d", freedev],
                                            stderr=subprocess.STDOUT)
                except BaseException:
                    pass

    try:
        print "Running test_lv_on_partitions():"
        setup()
        print "\tSetup() complete"
        extentsinfo = test(1)
        print "\ttest() done"

        # first clean up and then verify so the volume groups do not interfere
        # with existing volume groups
        verify(extentsinfo)
        print "\tverification done"

    finally:
        if extentsinfo and 'extentsfiles' in extentsinfo:
            for key, value in extentsinfo['extentsfiles'].iteritems():
                if os.path.isfile(value):
                    os.remove(value)

        for i in range(1, 2):
            deletepv("pvname" + str(i))
            if os.path.isfile("vmdk" + str(i)):
                os.remove("vmdk" + str(i))
        print "\t cleanup done"

##
# LVM PV is carved out of


def test_lv_part_mixed():

    def setup():
        mountpoint = createpv("pvname1", "1TiB")

        cmd = ["parted", mountpoint, "mklabel", "gpt"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        devices = []
        cmd = [
            "parted",
            mountpoint,
            "mkpart",
            "P1",
            "ext2",
            str(1024),
            str("500GB")]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        cmd = [
            "parted",
            mountpoint,
            "mkpart",
            "P2",
            "ext2",
            str("500GB"),
            str("1000GB")]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        devices.append(assignloopdevice(mountpoint, 2000896, 976562175))
        devices.append(assignloopdevice(mountpoint, 976562176, 1953124351))

        for dev in devices[1:]:
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
                cmd = ["mount", "-t", "ext4", "/dev/vg1/" + lv, tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                cmd = [
                    "cp",
                    "/opt/stack/workloadmgr/trilio-vix-disk-cli/" +
                    "VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                    tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                time.sleep(1)
                cmd = ["umount", tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            shutil.rmtree(tempdir)

            vgcmd = ["vgchange", "-an", "vg1"]
            subprocess.check_output(vgcmd, stderr=subprocess.STDOUT)
            vgcmd = ["vgexport", "vg1"]
            #subprocess.check_output(vgcmd, stderr=subprocess.STDOUT)
            cmd = ["losetup", "-d", dev]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        for dev in devices[0:1]:
            cmd = ["mkfs", "-t", "ext4", dev]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            cmd = ["losetup", "-d", dev]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["losetup", "-d", mountpoint]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        return

    def verify(extentsinfo):
        try:
            freedevs = []
            if not extentsinfo:
                print "extentsinfo is null. Test failed"
                raise Exception("extentsinfo is null. Test failed")

            if len(extentsinfo['extentsfiles']) != 1:
                print "Number of extents files is not 1. Test failed"
                raise Exception("extentsinfo is null. Test failed")

            for key, value in extentsinfo['extentsfiles'].iteritems():
                my_populate_extents(None, None, None, None, key,
                                    "vmdk" + key.split("pvname")[1], value)

            for key, value in extentsinfo['extentsfiles'].iteritems():
                freedev = subprocess.check_output(["losetup", "-f"],
                                                  stderr=subprocess.STDOUT)
                freedev = freedev.strip("\n")

                subprocess.check_output(["losetup", freedev, "vmdk" + key.split("pvname")[1], ],
                                        stderr=subprocess.STDOUT)

                pvinfo = workloadmgr.virt.vmwareapi.thickcopy._getpvinfo(
                    freedev + "p1")
                pvinfo = workloadmgr.virt.vmwareapi.thickcopy._getpvinfo(
                    freedev + "p2")
                freedevs.append(freedev)

            vgs = workloadmgr.virt.vmwareapi.thickcopy.getvgs()

            if len(vgs) != 1:
                print "Number VGs found on VMDK is not 1. Test failed"
                raise Exception(
                    "Number VGs found on VMDK is not 1. Test failed")

            lvs = workloadmgr.virt.vmwareapi.thickcopy.getlvs(vgs)
            if len(lvs) != 4:
                print "Number of LVs found is not 4. Test Failed"
                raise Exception("Number of LVs found is not 4. Test Failed")

            # this test is assuming one partition per disk. We need additional tests for multiple
            # partitions per disk
            tempdir = mkdtemp()
            for lv in ["lv1", "lv2", "lv3", "lv4"]:
                cmd = ["mount", "-t", "ext4", "/dev/vg1/" + lv, tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                cmd = [
                    "diff",
                    "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                    tempdir +
                    "/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz"]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                time.sleep(1)
                cmd = ["umount", tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            shutil.rmtree(tempdir)

            tempdir = mkdtemp()
            cmd = ["mount", "-t", "ext4", freedev + "p1", tempdir]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            cmd = [
                "diff",
                "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                tempdir +
                "/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz"]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            time.sleep(1)
            cmd = ["umount", tempdir]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            shutil.rmtree(tempdir)

        except Exception as ex:
            print "Exception in verification. Verification failed"
            raise
        finally:
            for vg in vgs:
                workloadmgr.virt.vmwareapi.thickcopy.deactivatevgs(
                    vg['LVM2_VG_NAME'])

            for freedev in freedevs:
                try:
                    subprocess.check_output(["losetup", "-d", freedev],
                                            stderr=subprocess.STDOUT)
                except BaseException:
                    pass

    try:
        print "Running test_lv_part_mixed():"
        setup()
        print "\tSetup() complete"
        extentsinfo = test(1)
        print "\ttest() done"

        # first clean up and then verify so the volume groups do not interfere
        # with existing volume groups
        print "\tverification done"

    finally:
        if extentsinfo and 'extentsfiles' in extentsinfo:
            for key, value in extentsinfo['extentsfiles'].iteritems():
                if os.path.isfile(value):
                    os.remove(value)

        for i in range(1, 2):
            deletepv("pvname" + str(i))
            if os.path.isfile("vmdk" + str(i)):
                os.remove("vmdk" + str(i))
        print "\t cleanup done"

##
# LVM PV is carved out of


def test_part_lv_mixed():

    def setup():
        mountpoint = createpv("pvname1", "1TiB")

        cmd = ["parted", mountpoint, "mklabel", "gpt"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        devices = []
        cmd = [
            "parted",
            mountpoint,
            "mkpart",
            "P1",
            "ext2",
            str(1024),
            str("500GB")]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        cmd = [
            "parted",
            mountpoint,
            "mkpart",
            "P2",
            "ext2",
            str("500GB"),
            str("1000GB")]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        devices.append(assignloopdevice(mountpoint, 2000896, 976562175))
        devices.append(assignloopdevice(mountpoint, 976562176, 1953124351))

        for dev in devices[0:1]:
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
                cmd = ["mount", "-t", "ext4", "/dev/vg1/" + lv, tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                cmd = [
                    "cp",
                    "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                    tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                time.sleep(1)
                cmd = ["umount", tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            shutil.rmtree(tempdir)

            vgcmd = ["vgchange", "-an", "vg1"]
            subprocess.check_output(vgcmd, stderr=subprocess.STDOUT)
            vgcmd = ["vgexport", "vg1"]
            #subprocess.check_output(vgcmd, stderr=subprocess.STDOUT)
            cmd = ["losetup", "-d", dev]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        for dev in devices[1:]:
            cmd = ["mkfs", "-t", "ext4", dev]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            cmd = ["losetup", "-d", dev]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["losetup", "-d", mountpoint]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        return

    try:
        print "Running test_part_lv_mixed():"
        setup()
        print "\tSetup() complete"
        extentsfile, partitions, totalblocks = test()
        print "\ttest() done"

        # first clean up and then verify so the volume groups do not interfere
        # with existing volume groups
        assert extentsfile is None
        print "\tverification done"

    finally:
        deletepv("pvname1")
        if os.path.isfile("vmdk"):
            os.remove("vmdk")
        print "\t cleanup done"

##
# LVM PV is carved out of


def test_part_lv_mixed_with_tvault_vg():

    def setup():
        tvaultmount = createpv("tvault-root", "1TiB")
        cmd = ["parted", tvaultmount, "mklabel", "gpt"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        devices = []
        cmd = [
            "parted",
            tvaultmount,
            "mkpart",
            "P1",
            "ext2",
            str(1024),
            str("1000G")]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        devices.append(assignloopdevice(tvaultmount, 2000896, 1953124351))

        for dev in devices:
            cmd = ["pvcreate", dev]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            cmd = ["vgcreate", "tvault-appliance-vg", dev]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            # create multiple volumes
            for lv in ["lv1", "lv2", "lv3", "lv4"]:
                cmd = ["lvcreate", "-L", "1G", "tvault-appliance-vg", "-n", lv]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            # Format each volume to a filesystem
            for lv in ["lv1", "lv2", "lv3", "lv4"]:
                cmd = ["mkfs", "-t", "ext4", "/dev/tvault-appliance-vg/" + lv]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            tempdir = mkdtemp()
            for lv in ["lv1", "lv2", "lv3", "lv4"]:
                cmd = [
                    "mount",
                    "-t",
                    "ext4",
                    "/dev/tvault-appliance-vg/" +
                    lv,
                    tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                cmd = [
                    "cp",
                    "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                    tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                time.sleep(1)
                cmd = ["umount", tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            shutil.rmtree(tempdir)

        mountpoint = createpv("pvname1", "1TiB")

        cmd = ["parted", mountpoint, "mklabel", "gpt"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        devices = []
        cmd = [
            "parted",
            mountpoint,
            "mkpart",
            "P1",
            "ext2",
            str(1024),
            str("500GB")]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        cmd = [
            "parted",
            mountpoint,
            "mkpart",
            "P2",
            "ext2",
            str("500GB"),
            str("1000GB")]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        devices.append(assignloopdevice(mountpoint, 2000896, 976562175))
        devices.append(assignloopdevice(mountpoint, 976562176, 1953124351))

        for dev in devices[0:1]:
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
                cmd = ["mount", "-t", "ext4", "/dev/vg1/" + lv, tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                cmd = ["cp", "/opt/stack/workloadmgr/trilio-vix-disk-cli/\
                              VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                       tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                time.sleep(1)
                cmd = ["umount", tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            shutil.rmtree(tempdir)

            vgcmd = ["vgchange", "-an", "vg1"]
            subprocess.check_output(vgcmd, stderr=subprocess.STDOUT)
            vgcmd = ["vgexport", "vg1"]
            #subprocess.check_output(vgcmd, stderr=subprocess.STDOUT)
            cmd = ["losetup", "-d", dev]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        for dev in devices[1:]:
            cmd = ["mkfs", "-t", "ext4", dev]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            cmd = ["losetup", "-d", dev]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["losetup", "-d", mountpoint]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        return

    def cleanup():
        vgcmd = ["vgchange", "-an", "tvault-appliance-vg"]
        subprocess.check_output(vgcmd, stderr=subprocess.STDOUT)
        vgcmd = ["vgexport", "tvault-appliance-vg"]
        #subprocess.check_output(vgcmd, stderr=subprocess.STDOUT)
        cmd = ["losetup", "-d", "/dev/loop1"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["losetup", "-d", "/dev/loop0"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        deletepv("tvault-root")

    try:
        print "Running test_part_lv_mixed_with_tvault_vg():"
        setup()
        print "\tSetup() complete"
        extentsfile, partitions, totalblocks = test()
        print "\ttest() done"

        # first clean up and then verify so the volume groups do not interfere
        # with existing volume groups
        assert extentsfile is None
        print "\tverification done"

    finally:
        deletepv("pvname1")
        if os.path.isfile("vmdk"):
            os.remove("vmdk")
        cleanup()
        print "\t cleanup done"

##
# LVM PV is carved out of


def test_lvs_on_two_partitions():

    def setup():
        mountpoint = createpv("pvname1", "1TiB")

        cmd = ["parted", mountpoint, "mklabel", "gpt"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        devices = []
        cmd = [
            "parted",
            mountpoint,
            "mkpart",
            "P1",
            "ext2",
            str(1024),
            str("500GB")]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        cmd = [
            "parted",
            mountpoint,
            "mkpart",
            "P2",
            "ext2",
            str("500GB"),
            str("1000GB")]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        devices.append(assignloopdevice(mountpoint, 2000896, 976562175))
        devices.append(assignloopdevice(mountpoint, 976562176, 1953124351))

        for dev in devices:
            cmd = ["pvcreate", dev]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            cmd = ["vgcreate", "vg1" + dev.split("/")[2], dev]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            # create multiple volumes
            for lv in ["lv1", "lv2", "lv3", "lv4"]:
                cmd = [
                    "lvcreate",
                    "-L",
                    "1G",
                    "vg1" +
                    dev.split("/")[2],
                    "-n",
                    dev.split("/")[2] +
                    lv]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            # Format each volume to a filesystem
            for lv in ["lv1", "lv2", "lv3", "lv4"]:
                cmd = ["mkfs", "-t", "ext4", "/dev/vg1" +
                       dev.split("/")[2] + "/" + dev.split("/")[2] + lv]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            tempdir = mkdtemp()
            for lv in ["lv1", "lv2", "lv3", "lv4"]:
                cmd = [
                    "mount",
                    "-t",
                    "ext4",
                    "/dev/vg1" +
                    dev.split("/")[2] +
                    "/" +
                    dev.split("/")[2] +
                    lv,
                    tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                cmd = [
                    "cp",
                    "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                    tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                time.sleep(1)
                cmd = ["umount", tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            shutil.rmtree(tempdir)

        vgcmd = ["vgchange", "-an", ]
        subprocess.check_output(vgcmd, stderr=subprocess.STDOUT)

        #vgcmd = ["vgexport", "vg1"]
        #subprocess.check_output(vgcmd, stderr=subprocess.STDOUT)
        for dev in devices:
            cmd = ["losetup", "-d", dev]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["losetup", "-d", mountpoint]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        vgcmd = ["vgchange", "-an", ]
        subprocess.check_output(vgcmd, stderr=subprocess.STDOUT)

        return

    def verify(remotepath, extentsfile, vmdkfile):
        try:
            my_populate_extents(None, None, None, None, remotepath,
                                vmdkfile, extentsfile)

            devices = []
            devices.append(assignloopdevice(vmdkfile, 2000896, 976562175))
            devices.append(assignloopdevice(vmdkfile, 976562176, 1953124351))

            pvinfo = workloadmgr.virt.vmwareapi.thickcopy._getpvinfo(
                devices[0], '0', (976562175 - 2000896 + 1) * 512)
            pvinfo = workloadmgr.virt.vmwareapi.thickcopy._getpvinfo(
                devices[1], '0', (1953124351 - 976562176 + 1) * 512)

            # explore VGs and volumes on the disk
            vgs = workloadmgr.virt.vmwareapi.thickcopy.getvgs()

            if len(vgs) == 0:
                print "No VGs found on VMDK. Test failed"
                raise Exception("No VGs found on VMDK. Test failed")

            lvs = []
            for vg in vgs:
                lvs += workloadmgr.virt.vmwareapi.thickcopy.getlvs(
                    vg['LVM2_VG_NAME'])
            if len(lvs) != 8:
                print "Number of LVs found is not 8. Test Failed"
                raise Exception("Number of LVs found is not 8. Test Failed")

            # this test is assuming one partition per disk. We need additional tests for multiple
            # partitions per disk
            tempdir = mkdtemp()
            for lv in lvs:
                cmd = ["mount", "-t", "ext4", lv['LVM2_LV_PATH'], tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                cmd = [
                    "diff",
                    "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                    tempdir +
                    "/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz"]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                time.sleep(1)
                cmd = ["umount", tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            shutil.rmtree(tempdir)

            for vg in vgs:
                workloadmgr.virt.vmwareapi.thickcopy.deactivatevgs(
                    vg['LVM2_VG_NAME'])

        except Exception as ex:
            print "Exception in verification. Verification failed"
            raise
        finally:
            try:
                for freedev in devices:
                    subprocess.check_output(["losetup", "-d", freedev],
                                            stderr=subprocess.STDOUT)
            except BaseException:
                pass
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

    def setup():
        mountpoint = createpv("pvname1", "1TiB")

        cmd = ["parted", mountpoint, "mklabel", "gpt"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        devices = []
        cmd = [
            "parted",
            mountpoint,
            "mkpart",
            "P1",
            "ext2",
            str(1024),
            str("500GB")]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        cmd = [
            "parted",
            mountpoint,
            "mkpart",
            "P2",
            "ext2",
            str("500GB"),
            str("1000GB")]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        devices.append(assignloopdevice(mountpoint, 2000896, 976562175))
        devices.append(assignloopdevice(mountpoint, 976562176, 1953124351))

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

            cmd = [
                "cp",
                "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                tempdir]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            time.sleep(1)
            cmd = ["umount", tempdir]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        shutil.rmtree(tempdir)

        vgcmd = ["vgchange", "-an", ]
        subprocess.check_output(vgcmd, stderr=subprocess.STDOUT)

        #vgcmd = ["vgexport", "vg1"]
        #subprocess.check_output(vgcmd, stderr=subprocess.STDOUT)
        for dev in devices:
            cmd = ["losetup", "-d", dev]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["losetup", "-d", mountpoint]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        vgcmd = ["vgchange", "-an", ]
        subprocess.check_output(vgcmd, stderr=subprocess.STDOUT)

        return

    def verify(remotepath, extentsfile, vmdkfile):
        try:
            my_populate_extents(None, None, None, None, remotepath,
                                vmdkfile, extentsfile)

            devices = []
            devices.append(assignloopdevice(vmdkfile, 2000896, 976562175))
            devices.append(assignloopdevice(vmdkfile, 976562176, 1953124351))

            pvinfo = workloadmgr.virt.vmwareapi.thickcopy._getpvinfo(
                devices[0], '0', (976562175 - 2000896 + 1) * 512)
            pvinfo = workloadmgr.virt.vmwareapi.thickcopy._getpvinfo(
                devices[1], '0', (1953124351 - 976562176 + 1) * 512)

            # explore VGs and volumes on the disk
            vgs = workloadmgr.virt.vmwareapi.thickcopy.getvgs()

            if len(vgs) == 0:
                print "No VGs found on VMDK. Test failed"
                raise Exception("No VGs found on VMDK. Test failed")

            lvs = []
            for vg in vgs:
                lvs += workloadmgr.virt.vmwareapi.thickcopy.getlvs(
                    vg['LVM2_VG_NAME'])
            if len(lvs) != 3:
                print "Number of LVs found is not 3. Test Failed"
                raise Exception("Number of LVs found is not 3. Test Failed")

            # this test is assuming one partition per disk. We need additional tests for multiple
            # partitions per disk
            tempdir = mkdtemp()
            for lv in lvs:
                cmd = ["mount", "-t", "ext4", lv['LVM2_LV_PATH'], tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                cmd = [
                    "diff",
                    "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                    tempdir +
                    "/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz"]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                time.sleep(1)
                cmd = ["umount", tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            shutil.rmtree(tempdir)

            for vg in vgs:
                workloadmgr.virt.vmwareapi.thickcopy.deactivatevgs(
                    vg['LVM2_VG_NAME'])

        except Exception as ex:
            print "Exception in verification. Verification failed"
            raise
        finally:
            try:
                for freedev in devices:
                    subprocess.check_output(["losetup", "-d", freedev],
                                            stderr=subprocess.STDOUT)
            except BaseException:
                pass
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

    def setup():
        mountpoint = createpv("pvname1", "1TiB")
        devices = []

        cmd = ["parted", mountpoint, "mklabel", "msdos"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = [
            "parted",
            mountpoint,
            "mkpart",
            "primary",
            "ext2",
            str(1024),
            str(10240)]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["parted", mountpoint, "mkpart", "primary",
               "ext2", str(10240), str(2 * 10240)]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["parted", mountpoint, "mkpart", "primary",
               "ext2", str(2 * 10240), str(10 * 10240)]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["parted", mountpoint, "mkpart", "primary",
               "ext2", str(10 * 10240), str(100 * 10240)]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        # TODO: Figure out why these start and end sectors resulted from about
        # part commands
        devices.append(formatfs(mountpoint, 2000896, 20000767))
        devices.append(formatfs(mountpoint, 20000768, 39999487))
        devices.append(formatfs(mountpoint, 39999488, 199999487))
        devices.append(formatfs(mountpoint, 199999488, 2000001023))

        tempdir = mkdtemp()
        for dev in devices:
            cmd = ["mount", "-t", "ext4", dev, tempdir]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            cmd = [
                "cp",
                "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                tempdir]
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

            partitions = workloadmgr.virt.vmwareapi.thickcopy.read_partition_table(
                vmdkfile)
            for part in partitions:
                try:
                    freedev = subprocess.check_output(["losetup", "-f"],
                                                      stderr=subprocess.STDOUT)
                    freedev = freedev.strip("\n")

                    subprocess.check_output(["losetup",
                                             freedev,
                                             vmdkfile,
                                             "-o",
                                             str(int(part['start']) * 512),
                                             "--sizelimit",
                                             str((int(part['end']) - int(part['start']) + 1) / 2) + "KiB"],
                                            stderr=subprocess.STDOUT)

                    tempdir = mkdtemp()
                    cmd = ["mount", "-t", "ext4", freedev, tempdir]
                    subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                    cmd = [
                        "diff",
                        "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                        tempdir +
                        "/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz"]
                    subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                    time.sleep(1)
                    cmd = ["umount", tempdir]
                    subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                    shutil.rmtree(tempdir)
                finally:
                    if freedev:
                        cmd = ["losetup", "-d", freedev]
                        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        except Exception as ex:
            print "Exception in verification. Verification failed"
            raise
        finally:
            try:
                subprocess.check_output(["losetup", "-d", freedev],
                                        stderr=subprocess.STDOUT)
            except BaseException:
                pass
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

    def setup():
        mountpoint = createpv("pvname1", "1TiB")
        devices = []

        cmd = ["parted", mountpoint, "mklabel", "msdos"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = [
            "parted",
            mountpoint,
            "mkpart",
            "primary",
            "ext2",
            str(1024),
            str(10240)]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["parted", mountpoint, "mkpart", "primary",
               "ext2", str(10240), str(2 * 10240)]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["parted", mountpoint, "mkpart", "primary",
               "ext2", str(2 * 10240), str(10 * 10240)]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["parted", mountpoint, "mkpart",
               "extended", str(10 * 10240), str(100 * 10240)]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["parted", mountpoint, "mkpart", "logical",
               "ext2", str(11 * 10240), str(20 * 10240)]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        devices.append(formatfs(mountpoint, 2000896, 20000767))
        devices.append(formatfs(mountpoint, 20000768, 39999487))
        devices.append(formatfs(mountpoint, 39999488, 199999487))
        devices.append(formatfs(mountpoint, 220000256, 400001023))

        tempdir = mkdtemp()
        for dev in devices:
            cmd = ["mount", "-t", "ext4", dev, tempdir]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            cmd = [
                "cp",
                "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                tempdir]
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

            partitions = workloadmgr.virt.vmwareapi.thickcopy.read_partition_table(
                vmdkfile)
            for part in partitions:
                if part['id'] == '5' or part['id'] == 'f':
                    continue
                try:

                    freedev = subprocess.check_output(["losetup", "-f"],
                                                      stderr=subprocess.STDOUT)
                    freedev = freedev.strip("\n")

                    subprocess.check_output(["losetup",
                                             freedev,
                                             vmdkfile,
                                             "-o",
                                             str(int(part['start']) * 512),
                                             "--sizelimit",
                                             str((int(part['end']) - int(part['start']) + 1) / 2) + "KiB"],
                                            stderr=subprocess.STDOUT)

                    tempdir = mkdtemp()
                    cmd = ["mount", "-t", "ext4", freedev, tempdir]
                    subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                    cmd = [
                        "diff",
                        "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                        tempdir +
                        "/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz"]
                    subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                    time.sleep(1)
                    cmd = ["umount", tempdir]
                    subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                    shutil.rmtree(tempdir)
                finally:
                    if freedev:
                        cmd = ["losetup", "-d", freedev]
                        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        except Exception as ex:
            print "Exception in verification. Verification failed"
            raise
        finally:
            try:
                subprocess.check_output(["losetup", "-d", freedev],
                                        stderr=subprocess.STDOUT)
            except BaseException:
                pass

    try:
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

    def setup():
        mountpoint = createpv("pvname1", "1TiB")
        devices = []

        cmd = ["parted", mountpoint, "mklabel", "gpt"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = [
            "parted",
            mountpoint,
            "mkpart",
            "P1",
            "ext2",
            str(1024),
            str(10240)]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["parted", mountpoint, "mkpart", "P2",
               "ext2", str(10240), str(2 * 10240)]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["parted", mountpoint, "mkpart", "P2",
               "ext2", str(2 * 10240), str(10 * 10240)]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["parted", mountpoint, "mkpart",
               "P2", str(10 * 10240), str(100 * 10240)]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        devices.append(formatfs(mountpoint, 2000896, 20000767))
        devices.append(formatfs(mountpoint, 20000768, 39999487))
        devices.append(formatfs(mountpoint, 39999488, 199999487))
        devices.append(formatfs(mountpoint, 199999488, 2000001023))

        tempdir = mkdtemp()
        for dev in devices:
            cmd = ["mount", "-t", "ext4", dev, tempdir]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            cmd = [
                "cp",
                "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                tempdir]
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

            partitions = workloadmgr.virt.vmwareapi.thickcopy.read_partition_table(
                vmdkfile)
            for part in partitions:
                try:
                    freedev = subprocess.check_output(["losetup", "-f"],
                                                      stderr=subprocess.STDOUT)
                    freedev = freedev.strip("\n")

                    subprocess.check_output(["losetup",
                                             freedev,
                                             vmdkfile,
                                             "-o",
                                             str(int(part['start']) * 512),
                                             "--sizelimit",
                                             str((int(part['end']) - int(part['start']) + 1) / 2) + "KiB"],
                                            stderr=subprocess.STDOUT)

                    tempdir = mkdtemp()
                    cmd = ["mount", "-t", "ext4", freedev, tempdir]
                    subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                    cmd = [
                        "diff",
                        "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                        tempdir +
                        "/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz"]
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
            print "Exception in verification. Verification failed"
            raise
        finally:
            try:
                subprocess.check_output(["losetup", "-d", freedev],
                                        stderr=subprocess.STDOUT)
            except BaseException:
                pass

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

    def setup():
        mountpoint = createpv("pvname1", "1TiB", False)

    def cleanup():
        deletepv("pvname1")
        if os.path.isfile("vmdk"):
            os.remove("vmdk")

    try:
        print "Running test_raw_disk():"
        setup()
        print "\tsetup done"

        extentsfile, partitions, totalblocks = test()
        print "\ttest() done"

        if extentsfile and os.path.isfile(extentsfile):
            os.remove(extentsfile)
    finally:
        cleanup()
        print "\t cleanup done"

# thick copy when the entire disk is partitioned into 4 primary partitions and
# formatted to ext4 file systems


def test_raw_partition():

    def setup():
        mountpoint = createpv("pvname1", "1TiB")
        devices = []

        cmd = ["parted", mountpoint, "mklabel", "msdos"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = [
            "parted",
            mountpoint,
            "mkpart",
            "primary",
            "ext2",
            str(1024),
            str(10240)]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["parted", mountpoint, "mkpart", "primary",
               "ext2", str(10240), str(2 * 10240)]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["parted", mountpoint, "mkpart", "primary",
               "ext2", str(2 * 10240), str(10 * 10240)]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["parted", mountpoint, "mkpart", "primary",
               "ext2", str(10 * 10240), str(100 * 10240)]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["losetup", "-d", "/dev/loop0"]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        return

    def cleanup():
        deletepv("pvname1")
        if os.path.isfile("vmdk"):
            os.remove("vmdk")

    try:
        print "Running test_raw_partition():"
        setup()
        print "\tSetup() done"

        extentsfile, partitions, totalblocks = test()
        print "\t test() done"

        if extentsfile and os.path.isfile(extentsfile):
            os.remove(extentsfile)
    finally:
        cleanup()
        print "\t cleanup done"

# thick copy when the entire disk is a logical volume


def test_lv_entire_disks():

    def setup():
        mountpoints = []
        for i in range(1, 5):
            mountpoints.append(createpv("pvname" + str(i), "1TiB"))

        for mountpoint in mountpoints:
            cmd = ["pvcreate", mountpoint]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["vgcreate", "vg1", ] + mountpoints
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
            cmd = ["mount", "-t", "ext4", "/dev/vg1/" + lv, tempdir]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            cmd = [
                "cp",
                "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                tempdir]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            time.sleep(1)
            cmd = ["umount", tempdir]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        shutil.rmtree(tempdir)

        for mountpoint in mountpoints:
            cmd = ["losetup", "-d", mountpoint]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        vgcmd = ["vgchange", "-an", "vg1"]
        subprocess.check_output(vgcmd, stderr=subprocess.STDOUT)

        return

    def cleanup():
        for i in range(1, 5):
            deletepv("pvname" + str(i))
            if os.path.isfile("vmdk" + str(i)):
                os.remove("vmdk" + str(i))

    def verify(extentsinfo):
        try:
            freedevs = []
            if not extentsinfo:
                print "extentsinfo is null. Test failed"
                raise Exception("extentsinfo is null. Test failed")

            for key, value in extentsinfo['extentsfiles'].iteritems():
                my_populate_extents(None, None, None, None, key,
                                    "vmdk" + key.split("pvname")[1], value)

            for key, value in extentsinfo['extentsfiles'].iteritems():
                freedev = subprocess.check_output(["losetup", "-f"],
                                                  stderr=subprocess.STDOUT)
                freedev = freedev.strip("\n")

                subprocess.check_output(["losetup", freedev, "vmdk" + key.split("pvname")[1], ],
                                        stderr=subprocess.STDOUT)

                pvinfo = workloadmgr.virt.vmwareapi.thickcopy._getpvinfo(
                    freedev, '0', '1099511627776L')
                freedevs.append(freedev)

            # explore VGs and volumes on the disk
            vgs = workloadmgr.virt.vmwareapi.thickcopy.getvgs()

            if len(vgs) == 0:
                print "No VGs found on VMDK. Test failed"
                raise Exception("No VGs found on VMDK. Test failed")

            lvs = workloadmgr.virt.vmwareapi.thickcopy.getlvs(vgs)
            if len(lvs) != 4:
                print "Number of LVs found is not 4. Test Failed"
                raise Exception("Number of LVs found is not 4. Test Failed")

            tempdir = mkdtemp()
            for lv in ["lv1", "lv2", "lv3", "lv4"]:
                cmd = ["mount", "-t", "ext4", "/dev/vg1/" + lv, tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                cmd = [
                    "diff",
                    "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                    tempdir +
                    "/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz"]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                time.sleep(1)
                cmd = ["umount", tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            shutil.rmtree(tempdir)

            for vg in vgs:
                workloadmgr.virt.vmwareapi.thickcopy.deactivatevgs(
                    vg['LVM2_VG_NAME'])

        except Exception as ex:
            print "Exception in verification. Verification failed"
            raise
        finally:
            for freedev in freedevs:
                try:
                    subprocess.check_output(["losetup", "-d", freedev],
                                            stderr=subprocess.STDOUT)
                except BaseException:
                    pass

    try:
        extentsinfo = None

        print "Running test_lv_entire_disks(): "
        setup()
        print "\tSetup complete"

        extentsinfo = test(4)
        print "\ttest() complete"

        verify(extentsinfo)
        print "\t verified successfully"

    finally:
        if extentsinfo and extentsinfo['extentsfiles']:
            for key, value in extentsinfo['extentsfiles'].iteritems():
                if os.path.isfile(value):
                    os.remove(value)
        cleanup()
        print"\tcleanup done"

# thick copy when the entire disk is a logical volume with one disk missing
# thick copy should bailout and fall back on cbt based backup


def test_lv_entire_disks_with_one_disk_missing():

    def setup():
        mountpoints = []
        for i in range(1, 5):
            mountpoints.append(createpv("pvname" + str(i), "1TiB"))

        for mountpoint in mountpoints:
            cmd = ["pvcreate", mountpoint]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["vgcreate", "vg1", ] + mountpoints
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
            cmd = ["mount", "-t", "ext4", "/dev/vg1/" + lv, tempdir]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            cmd = [
                "cp",
                "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                tempdir]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            time.sleep(1)
            cmd = ["umount", tempdir]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        shutil.rmtree(tempdir)

        vgcmd = ["vgchange", "-an", "vg1"]
        subprocess.check_output(vgcmd, stderr=subprocess.STDOUT)

        for mountpoint in mountpoints:
            cmd = ["losetup", "-d", mountpoint]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        for i in range(1, 5)[3:]:
            deletepv("pvname" + str(i))

        return

    def cleanup():
        for i in range(1, 5):
            if os.path.isfile("pvname" + str(i)):
                deletepv("pvname" + str(i))
            if os.path.isfile("vmdk" + str(i)):
                os.remove("vmdk" + str(i))

    def verify(extentsinfo):
        try:
            if not extentsinfo:
                print "extentsinfo is null. Test failed"
                raise Exception("extentsinfo is null. Test failed")

            for key, value in extentsinfo['totalblocks'].iteritems():
                if extentsinfo['totalblocks'][key]:
                    print "Total blocks should be zero"
                    raise Exception("Total blocks should be zero")
        except Exception as ex:
            print "Exception in verification. Verification failed"
            raise
        finally:
            try:
                subprocess.check_output(["losetup", "-d", freedev],
                                        stderr=subprocess.STDOUT)
            except BaseException:
                pass

    try:
        print "Running test_lv_entire_disks_with_one_disk_missing(): "
        setup()
        print "\tSetup complete"
        extentsinfo = test(3)
        print "\ttest() complete"
        verify(extentsinfo)
        print "\t verified successfully"

    finally:
        cleanup()
        print"\tcleanup done"

# thick copy when each disk is a single partition for PV
# thick copy should return the list of extent files


def test_lvm_on_single_partition():

    def setup():
        mountpoints = []
        for i in range(1, 5):
            mountpoints.append(createpv("pvname" + str(i), "1TiB"))

        devices = []
        for mountpoint in mountpoints:
            cmd = ["parted", mountpoint, "mklabel", "gpt"]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            cmd = [
                "parted",
                mountpoint,
                "mkpart",
                "P1",
                "ext2",
                str(1024),
                str("1TiB")]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            devices.append(mountpoint + "p1")

        for dev in devices:
            cmd = ["pvcreate", dev]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["vgcreate", "vg1", ] + devices
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
            cmd = ["mount", "-t", "ext4", "/dev/vg1/" + lv, tempdir]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            cmd = [
                "cp",
                "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                tempdir]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            time.sleep(1)
            cmd = ["umount", tempdir]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        shutil.rmtree(tempdir)

        vgcmd = ["vgchange", "-an", "vg1"]
        subprocess.check_output(vgcmd, stderr=subprocess.STDOUT)

        for mountpoint in mountpoints:
            cmd = ["losetup", "-d", mountpoint]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        return

    def cleanup():
        for i in range(1, 5):
            deletepv("pvname" + str(i))
            if os.path.isfile("vmdk" + str(i)):
                os.remove("vmdk" + str(i))

    def verify(extentsinfo):
        try:
            freedevs = []
            if not extentsinfo:
                print "extentsinfo is null. Test failed"
                raise Exception("extentsinfo is null. Test failed")

            for key, value in extentsinfo['extentsfiles'].iteritems():
                my_populate_extents(None, None, None, None, key,
                                    "vmdk" + key.split("pvname")[1], value)

            for key, value in extentsinfo['extentsfiles'].iteritems():
                freedev = subprocess.check_output(["losetup", "-f"],
                                                  stderr=subprocess.STDOUT)
                freedev = freedev.strip("\n")

                subprocess.check_output(["losetup", freedev, "vmdk" + key.split("pvname")[1], ],
                                        stderr=subprocess.STDOUT)

                pvinfo = workloadmgr.virt.vmwareapi.thickcopy._getpvinfo(
                    freedev + "p1")
                freedevs.append(freedev)

            vgs = workloadmgr.virt.vmwareapi.thickcopy.getvgs()

            if len(vgs) == 0:
                print "No VGs found on VMDK. Test failed"
                raise Exception("No VGs found on VMDK. Test failed")

            lvs = []

            lvs += workloadmgr.virt.vmwareapi.thickcopy.getlvs(vgs)

            if len(lvs) != 4:
                print "Number of LVs found is not 4. Test Failed"
                raise Exception("Number of LVs found is not 4. Test Failed")

            tempdir = mkdtemp()
            for lv in ["lv1", "lv2", "lv3", "lv4"]:
                cmd = ["mount", "-t", "ext4", "/dev/vg1/" + lv, tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                cmd = [
                    "diff",
                    "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                    tempdir +
                    "/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz"]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                time.sleep(1)
                cmd = ["umount", tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            shutil.rmtree(tempdir)

            for vg in vgs:
                workloadmgr.virt.vmwareapi.thickcopy.deactivatevgs(
                    vg['LVM2_VG_NAME'])

        except Exception as ex:
            print "Exception in verification. Verification failed"
            raise
        finally:
            for freedev in freedevs:
                try:
                    subprocess.check_output(["losetup", "-d", freedev],
                                            stderr=subprocess.STDOUT)
                except BaseException:
                    pass

    try:
        print "Running test_lvm_on_single_partition(): "
        setup()
        print "\tSetup complete"
        extentsinfo = test(4)
        print "\ttest() complete"
        verify(extentsinfo)
        print "\t verified successfully"

    finally:
        cleanup()
        print"\tcleanup done"

# thick copy when we have mix of lvms and partitions
# thick copy should return the list of extent files


def test_mix_of_lvm_and_partitions():

    def setup():
        try:
            mountpoints = []
            for i in range(1, 5):
                mountpoints.append(createpv("pvname" + str(i), "1TiB"))

            devices = []
            for mountpoint in mountpoints:
                cmd = ["parted", mountpoint, "mklabel", "gpt"]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            for mountpoint in mountpoints[0:2]:
                cmd = [
                    "parted",
                    mountpoint,
                    "mkpart",
                    "P1",
                    "ext2",
                    str(1024),
                    str("1TiB")]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)

                devices.append(mountpoint + "p1")

            for mountpoint in mountpoints[2:]:
                cmd = [
                    "parted",
                    mountpoint,
                    "mkpart",
                    "P1",
                    "ext2",
                    str(1024),
                    str("250GiB")]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)

                cmd = [
                    "parted",
                    mountpoint,
                    "mkpart",
                    "P2",
                    "ext3",
                    str("250GiB"),
                    str("500GiB")]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)

                cmd = [
                    "parted",
                    mountpoint,
                    "mkpart",
                    "P3",
                    "ext3",
                    str("500GiB"),
                    str("750GiB")]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)

                cmd = [
                    "parted",
                    mountpoint,
                    "mkpart",
                    "P4",
                    "ext3",
                    str("750GiB"),
                    str("900GiB")]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)

                cmd = [
                    "parted",
                    mountpoint,
                    "mkpart",
                    "P5",
                    "ext3",
                    str("900GiB"),
                    str("1000GiB")]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            for dev in devices:
                cmd = ["pvcreate", dev]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            cmd = ["vgcreate", "vg1", ] + devices
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
            for lv in ["lv1", "lv2", "lv3", "lv4"]:
                cmd = ["mkfs", "-t", "ext4", "/dev/vg1/" + lv]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            for mountpoint in mountpoints[2:]:
                for part in [1, 2, 3, 4, 5]:
                    cmd = ["mkfs", "-t", "ext4", mountpoint + "p" + str(part)]
                    subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            tempdir = mkdtemp()
            for lv in ["lv1", "lv2", "lv3", "lv4"]:
                cmd = ["mount", "-t", "ext4", "/dev/vg1/" + lv, tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                cmd = [
                    "cp",
                    "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                    tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                time.sleep(1)
                cmd = ["umount", tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            shutil.rmtree(tempdir)

            tempdir = mkdtemp()
            for mountpoint in mountpoints[2:]:
                for part in [1, 2, 3, 4, 5]:
                    cmd = [
                        "mount",
                        "-t",
                        "ext4",
                        mountpoint +
                        "p" +
                        str(part),
                        tempdir]
                    subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                    cmd = [
                        "cp",
                        "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                        tempdir]
                    subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                    time.sleep(1)
                    cmd = ["umount", tempdir]
                    subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            shutil.rmtree(tempdir)

        finally:
            vgcmd = ["vgchange", "-an", "vg1"]
            subprocess.check_output(vgcmd, stderr=subprocess.STDOUT)

            for mountpoint in mountpoints:
                cmd = ["losetup", "-d", mountpoint]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        return

    def cleanup():
        for i in range(1, 5):
            deletepv("pvname" + str(i))
            if os.path.isfile("vmdk" + str(i)):
                os.remove("vmdk" + str(i))

    def verify(extentsinfo):
        try:
            freedevs = []
            partdevs = []
            vgs = []

            if not extentsinfo:
                print "extentsinfo is null. Test failed"
                raise Exception("extentsinfo is null. Test failed")

            for key, value in extentsinfo['extentsfiles'].iteritems():
                my_populate_extents(None, None, None, None, key,
                                    "vmdk" + key.split("pvname")[1], value)

            for key, value in extentsinfo['extentsfiles'].iteritems():
                freedev = subprocess.check_output(["losetup", "-f"],
                                                  stderr=subprocess.STDOUT)
                freedev = freedev.strip("\n")

                subprocess.check_output(["losetup", freedev, "vmdk" + key.split("pvname")[1], ],
                                        stderr=subprocess.STDOUT)

                freedevs.append(freedev)
                if int(key.split("pvname")[1]) in [1, 2]:
                    pvinfo = workloadmgr.virt.vmwareapi.thickcopy._getpvinfo(
                        freedev + "p1")
                else:
                    partdevs.append(freedev)

            # explore VGs and volumes on the disk
            vgs = workloadmgr.virt.vmwareapi.thickcopy.getvgs()

            if len(vgs) == 0:
                print "No VGs found on VMDK. Test failed"
                raise Exception("No VGs found on VMDK. Test failed")

            lvs = workloadmgr.virt.vmwareapi.thickcopy.getlvs(vgs)
            if len(lvs) != 4:
                print "Number of LVs found is not 4. Test Failed"
                raise Exception("Number of LVs found is not 4. Test Failed")

            tempdir = mkdtemp()
            for lv in ["lv1", "lv2", "lv3", "lv4"]:
                cmd = ["mount", "-t", "ext4", "/dev/vg1/" + lv, tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                cmd = [
                    "diff",
                    "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                    tempdir +
                    "/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz"]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                time.sleep(1)
                cmd = ["umount", tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            shutil.rmtree(tempdir)

            tempdir = mkdtemp()
            for mountpoint in partdevs:
                for part in [1, 2, 3, 4, 5]:
                    cmd = [
                        "mount",
                        "-t",
                        "ext4",
                        mountpoint +
                        "p" +
                        str(part),
                        tempdir]
                    subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                    cmd = [
                        "diff",
                        "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                        tempdir +
                        "/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz"]
                    subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                    time.sleep(1)
                    cmd = ["umount", tempdir]
                    subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            shutil.rmtree(tempdir)

        except Exception as ex:
            logging.exception("Exception in verification. Verification failed")
            raise
        finally:
            for vg in vgs:
                workloadmgr.virt.vmwareapi.thickcopy.deactivatevgs(
                    vg['LVM2_VG_NAME'])

            for freedev in freedevs:
                try:
                    subprocess.check_output(["losetup", "-d", freedev],
                                            stderr=subprocess.STDOUT)
                except BaseException:
                    pass

    try:
        print "Running test_mix_of_lvm_and_partitions(): "
        setup()
        print "\tSetup complete"
        extentsinfo = test(4)
        print "\ttest() complete"
        verify(extentsinfo)
        print "\t verified successfully"

    finally:
        cleanup()
        print"\tcleanup done"

# thick copy when we have mix of lvms and partitions
# thick copy should return the list of extent files


def test_mix_of_lvm_and_partitions_with_unformatted():

    def setup():
        mountpoints = []
        for i in range(1, 5):
            mountpoints.append(createpv("pvname" + str(i), "1TiB"))

        devices = []
        for mountpoint in mountpoints:
            cmd = ["parted", mountpoint, "mklabel", "gpt"]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        for mountpoint in mountpoints[0:2]:
            cmd = [
                "parted",
                mountpoint,
                "mkpart",
                "P1",
                "ext2",
                str(1024),
                str("1TiB")]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            devices.append(mountpoint + "p1")

        for mountpoint in mountpoints[2:]:
            cmd = [
                "parted",
                mountpoint,
                "mkpart",
                "P1",
                "ext2",
                str(1024),
                str("250GiB")]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            cmd = [
                "parted",
                mountpoint,
                "mkpart",
                "P2",
                "xfs",
                str("250GiB"),
                str("500GiB")]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            cmd = [
                "parted",
                mountpoint,
                "mkpart",
                "P3",
                "ext2",
                str("500GiB"),
                str("1TiB")]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        for dev in devices:
            cmd = ["pvcreate", dev]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["vgcreate", "vg1", ] + devices
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
        for lv in ["lv1", "lv2", "lv3", "lv4"]:
            cmd = ["mkfs", "-t", "ext4", "/dev/vg1/" + lv]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        for mountpoint in mountpoints[2:]:
            for part in ["1"]:
                cmd = ["mkfs", "-t", "ext4", mountpoint + "p" + part]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        for mountpoint in mountpoints[2:]:
            for part in ["2"]:
                cmd = ["mkfs", "-t", "xfs", mountpoint + "p" + part]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        tempdir = mkdtemp()
        for lv in ["lv1", "lv2", "lv3"]:
            cmd = ["mount", "-t", "ext4", "/dev/vg1/" + lv, tempdir]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            cmd = [
                "cp",
                "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                tempdir]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            time.sleep(1)
            cmd = ["umount", tempdir]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        shutil.rmtree(tempdir)

        tempdir = mkdtemp()
        for mountpoint in mountpoints[2:]:
            for part in ["1"]:
                cmd = ["mount", "-t", "ext4", mountpoint + "p" + part, tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                cmd = ["cp", "/opt/stack/workloadmgr/trilio-vix-disk-cli/" +
                             "VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                       tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                time.sleep(1)
                cmd = ["umount", tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        shutil.rmtree(tempdir)

        tempdir = mkdtemp()
        for mountpoint in mountpoints[2:]:
            for part in ["2"]:
                cmd = ["mount", "-t", "xfs", mountpoint + "p" + part, tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                cmd = ["cp", "/opt/stack/workloadmgr/trilio-vix-disk-cli/" +
                             "VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                       tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                time.sleep(1)
                cmd = ["umount", tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        shutil.rmtree(tempdir)

        vgcmd = ["vgchange", "-an", "vg1"]
        subprocess.check_output(vgcmd, stderr=subprocess.STDOUT)

        for mountpoint in mountpoints:
            cmd = ["losetup", "-d", mountpoint]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        return

    def cleanup():
        for i in range(1, 5):
            deletepv("pvname" + str(i))
            if os.path.isfile("vmdk" + str(i)):
                os.remove("vmdk" + str(i))

    def verify(extentsinfo):
        try:
            freedevs = []
            partdevs = []
            vgs = []
            if not extentsinfo:
                print "extentsinfo is null. Test failed"
                raise Exception("extentsinfo is null. Test failed")

            # Add stuff to verify the file system here. We should do with
            # small file systems, instead of tera bytes

        except Exception as ex:
            print "Exception in verification. Verification failed"
            raise
        finally:
            for vg in vgs:
                workloadmgr.virt.vmwareapi.thickcopy.deactivatevgs(
                    vg['LVM2_VG_NAME'])

            for freedev in freedevs:
                try:
                    subprocess.check_output(["losetup", "-d", freedev],
                                            stderr=subprocess.STDOUT)
                except BaseException:
                    pass

    try:
        print "Running test_mix_of_lvm_and_partitions_with_unformatted(): "
        setup()
        print "\tSetup complete"
        extentsinfo = test(4)
        print "\ttest() complete"
        verify(extentsinfo)
        print "\t verified successfully"

    finally:
        cleanup()
        print"\tcleanup done"

# thick copy when we have mix of lvms and partitions
# thick copy should return the list of extent files


def test_mix_of_lvm_and_partitions_with_unformatted_raw_disks():

    def setup():
        mountpoints = []
        for i in range(1, 5):
            mountpoints.append(createpv("pvname" + str(i), "1TiB"))

        devices = []
        for mountpoint in mountpoints:
            cmd = ["parted", mountpoint, "mklabel", "gpt"]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        for mountpoint in mountpoints[0:2]:
            cmd = [
                "parted",
                mountpoint,
                "mkpart",
                "P1",
                "ext2",
                str(1024),
                str("1TiB")]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            devices.append(mountpoint + "p1")

        # will leave pvname2 as raw
        #

        for mountpoint in mountpoints[3:]:
            cmd = [
                "parted",
                mountpoint,
                "mkpart",
                "P1",
                "ext2",
                str(1024),
                str("250GiB")]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            cmd = [
                "parted",
                mountpoint,
                "mkpart",
                "P2",
                "ext2",
                str("250GiB"),
                str("750GiB")]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        for dev in devices:
            cmd = ["pvcreate", dev]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["vgcreate", "vg1", ] + devices
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
        for lv in ["lv1", "lv2", "lv3", "lv4"]:
            cmd = ["mkfs", "-t", "ext4", "/dev/vg1/" + lv]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        for mountpoint in mountpoints[3:]:
            for part in ["1"]:
                cmd = ["mkfs", "-t", "ext4", mountpoint + "p" + str(part)]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        tempdir = mkdtemp()
        for lv in ["lv1", "lv2", "lv3", "lv4"]:
            cmd = ["mount", "-t", "ext4", "/dev/vg1/" + lv, tempdir]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            cmd = ["cp", "/opt/stack/workloadmgr/trilio-vix-disk-cli/" +
                         "VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                   tempdir]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            time.sleep(1)
            cmd = ["umount", tempdir]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        shutil.rmtree(tempdir)

        tempdir = mkdtemp()
        for mountpoint in mountpoints[3:]:
            for part in [1]:
                cmd = [
                    "mount",
                    "-t",
                    "ext4",
                    mountpoint +
                    "p" +
                    str(part),
                    tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                cmd = ["cp", "/opt/stack/workloadmgr/trilio-vix-disk-cli/" +
                       "VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                       tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                time.sleep(1)
                cmd = ["umount", tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        shutil.rmtree(tempdir)

        vgcmd = ["vgchange", "-an", "vg1"]
        subprocess.check_output(vgcmd, stderr=subprocess.STDOUT)

        for mountpoint in mountpoints:
            cmd = ["losetup", "-d", mountpoint]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        return

    def cleanup():
        for i in range(1, 5):
            if os.path.isfile("pvname" + str(i)):
                deletepv("pvname" + str(i))
            if os.path.isfile("vmdk" + str(i)):
                os.remove("vmdk" + str(i))

    def verify(extentsinfo):
        try:
            freedevs = []
            vgs = []
            partdev = []
            if not extentsinfo:
                print "extentsinfo is null. Test failed"
                raise Exception("extentsinfo is null. Test failed")

            for key, value in extentsinfo['extentsfiles'].iteritems():
                my_populate_extents(None, None, None, None, key,
                                    "vmdk" + key.split("pvname")[1], value)

            for key, value in extentsinfo['extentsfiles'].iteritems():
                freedev = subprocess.check_output(["losetup", "-f"],
                                                  stderr=subprocess.STDOUT)
                freedev = freedev.strip("\n")

                subprocess.check_output(["losetup", freedev, "vmdk" + key.split("pvname")[1], ],
                                        stderr=subprocess.STDOUT)

                freedevs.append(freedev)
                if int(key.split("pvname")[1]) in [1, 2]:
                    pvinfo = workloadmgr.virt.vmwareapi.thickcopy._getpvinfo(
                        freedev + "p1")
                elif int(key.split("pvname")[1]) in [4]:
                    partdev.append(freedev)

            # explore VGs and volumes on the disk
            vgs = workloadmgr.virt.vmwareapi.thickcopy.getvgs()

            if len(vgs) == 0:
                print "No VGs found on VMDK. Test failed"
                raise Exception("No VGs found on VMDK. Test failed")

            lvs = workloadmgr.virt.vmwareapi.thickcopy.getlvs(vgs)
            if len(lvs) != 4:
                print "Number of LVs found is not 4. Test Failed"
                raise Exception("Number of LVs found is not 4. Test Failed")

            tempdir = mkdtemp()
            for lv in ["lv1", "lv2", "lv3", "lv4"]:
                cmd = ["mount", "-t", "ext4", "/dev/vg1/" + lv, tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                cmd = [
                    "diff",
                    "/opt/stack/workloadmgr/trilio-vix-disk-cli/" +
                    "VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                    tempdir +
                    "/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz"]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                time.sleep(1)
                cmd = ["umount", tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            shutil.rmtree(tempdir)

            tempdir = mkdtemp()
            for mountpoint in partdev:
                for part in [1]:
                    cmd = [
                        "mount",
                        "-t",
                        "ext4",
                        mountpoint +
                        "p" +
                        str(part),
                        tempdir]
                    subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                cmd = [
                    "diff",
                    "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                    tempdir +
                    "/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz"]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                time.sleep(1)
                cmd = ["umount", tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            shutil.rmtree(tempdir)

        except Exception as ex:
            print "Exception in verification. Verification failed"
            raise
        finally:
            for vg in vgs:
                workloadmgr.virt.vmwareapi.thickcopy.deactivatevgs(
                    vg['LVM2_VG_NAME'])

            for freedev in freedevs:
                try:
                    subprocess.check_output(["losetup", "-d", freedev],
                                            stderr=subprocess.STDOUT)
                except BaseException:
                    pass

    try:
        print "Running test_mix_of_lvm_and_partitions_with_unformatted_raw_disks(): "
        setup()
        print "\tSetup complete"

        extentsinfo = test(4)
        print "\ttest() complete"

        verify(extentsinfo)
        print "\t verified successfully"

    finally:
        cleanup()
        print"\tcleanup done"

# thick copy when we have mix of lvms and partitions
# thick copy should return the list of extent files


def test_mix_of_lvm_and_regular_partitions_on_same_disk():

    def setup():
        mountpoints = []
        for i in range(1, 5):
            mountpoints.append(createpv("pvname" + str(i), "1TiB"))

        devices = []
        for mountpoint in mountpoints:
            cmd = ["parted", mountpoint, "mklabel", "gpt"]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        for mountpoint in mountpoints:
            cmd = ["parted", mountpoint, "mkpart", "P1", "ext2",
                   str(1024), str("250GiB")]
            subprocess.check_output(
                cmd, stderr=subprocess.STDOUT)  # p1 regular volume

            cmd = ["parted", mountpoint, "mkpart", "P2", "ext2",
                   str("250GiB"), str("500GiB")]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            devices.append(mountpoint + "p2")  # p2 has lvm

        for dev in devices:
            cmd = ["pvcreate", dev]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["vgcreate", "vg1", ] + devices
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        # create multiple volumes
        for lv in ["lv1", "lv2", "lv3", "lv4"]:
            cmd = ["lvcreate", "-L", "1G", "vg1", "-n", lv]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        # Format each volume to a filesystem
        for lv in ["lv1", "lv2", "lv3", "lv4"]:
            cmd = ["mkfs", "-t", "ext4", "/dev/vg1/" + lv]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        for mountpoint in mountpoints:
            for part in ["1"]:
                cmd = ["mkfs", "-t", "ext4", mountpoint + "p" + str(part)]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        tempdir = mkdtemp()
        for lv in ["lv1", "lv2", "lv3", "lv4"]:
            cmd = ["mount", "-t", "ext4", "/dev/vg1/" + lv, tempdir]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            cmd = ["cp", "/opt/stack/workloadmgr/trilio-vix-disk-cli/" +
                         "VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz", tempdir]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            time.sleep(1)
            cmd = ["umount", tempdir]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        shutil.rmtree(tempdir)

        tempdir = mkdtemp()
        for mountpoint in mountpoints:
            for part in ["1"]:
                cmd = [
                    "mount",
                    "-t",
                    "ext4",
                    mountpoint +
                    "p" +
                    str(part),
                    tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                cmd = [
                    "cp",
                    "/opt/stack/workloadmgr/trilio-vix-disk-cli/" +
                    "VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                    tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                time.sleep(1)
                cmd = ["umount", tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        shutil.rmtree(tempdir)

        vgcmd = ["vgchange", "-an", "vg1"]
        subprocess.check_output(vgcmd, stderr=subprocess.STDOUT)

        for mountpoint in mountpoints:
            cmd = ["losetup", "-d", mountpoint]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        return

    def cleanup():
        for i in range(1, 5):
            deletepv("pvname" + str(i))
            if os.path.isfile("vmdk" + str(i)):
                os.remove("vmdk" + str(i))

    def verify(extentsinfo):
        try:
            freedevs = []
            vgs = []
            partdev = []
            if not extentsinfo:
                print "extentsinfo is null. Test failed"
                raise Exception("extentsinfo is null. Test failed")

            for key, value in extentsinfo['extentsfiles'].iteritems():
                my_populate_extents(None, None, None, None, key,
                                    "vmdk" + key.split("pvname")[1], value)

            for key, value in extentsinfo['extentsfiles'].iteritems():
                freedev = subprocess.check_output(["losetup", "-f"],
                                                  stderr=subprocess.STDOUT)
                freedev = freedev.strip("\n")

                subprocess.check_output(["losetup", freedev, "vmdk" + key.split("pvname")[1], ],
                                        stderr=subprocess.STDOUT)

                freedevs.append(freedev)
                pvinfo = workloadmgr.virt.vmwareapi.thickcopy._getpvinfo(
                    freedev + "p2")

            vgs = workloadmgr.virt.vmwareapi.thickcopy.getvgs()

            if len(vgs) == 0:
                print "No VGs found on VMDK. Test failed"
                raise Exception("No VGs found on VMDK. Test failed")

            lvs = workloadmgr.virt.vmwareapi.thickcopy.getlvs(vgs)
            if len(lvs) != 4:
                print "Number of LVs found is not 4. Test Failed"
                raise Exception("Number of LVs found is not 4. Test Failed")

            tempdir = mkdtemp()
            for lv in ["lv1", "lv2", "lv3", "lv4"]:
                cmd = ["mount", "-t", "ext4", "/dev/vg1/" + lv, tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                cmd = [
                    "diff",
                    "/opt/stack/workloadmgr/trilio-vix-disk-cli/" +
                    "VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                    tempdir +
                    "/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz"]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                time.sleep(1)
                cmd = ["umount", tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            shutil.rmtree(tempdir)

            tempdir = mkdtemp()
            for mountpoint in freedevs:
                for part in ["1"]:
                    cmd = [
                        "mount",
                        "-t",
                        "ext4",
                        mountpoint +
                        "p" +
                        str(part),
                        tempdir]
                    subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                    cmd = [
                        "diff",
                        "/opt/stack/workloadmgr/trilio-vix-disk-cli/" +
                        "VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                        tempdir]
                    subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                    time.sleep(1)
                    cmd = ["umount", tempdir]
                    subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            shutil.rmtree(tempdir)

        except Exception as ex:
            print "Exception in verification. Verification failed"
            raise
        finally:
            for vg in vgs:
                workloadmgr.virt.vmwareapi.thickcopy.deactivatevgs(
                    vg['LVM2_VG_NAME'])

            for freedev in freedevs:
                try:
                    subprocess.check_output(["losetup", "-d", freedev],
                                            stderr=subprocess.STDOUT)
                except BaseException:
                    pass

    try:
        print "Running test_mix_of_lvm_and_regular_partitions_on_same_disk(): "

        setup()
        print "\tSetup complete"

        extentsinfo = test(4)
        print "\ttest() complete"

        verify(extentsinfo)
        print "\t verified successfully"

    finally:
        cleanup()
        print"\tcleanup done"

# thick copy when each disk is a single partition for PV
# thick copy should return the list of extent files


def test_multiple_vgs_multiple_disk():

    def setup():
        mountpoints = []
        for i in range(1, 6):
            mountpoints.append(createpv("pvname" + str(i), "1TiB"))

        devices = []
        for mountpoint in mountpoints:
            cmd = ["parted", mountpoint, "mklabel", "gpt"]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            cmd = [
                "parted",
                mountpoint,
                "mkpart",
                "P1",
                "ext2",
                str(1024),
                str("1TiB")]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            devices.append(mountpoint + "p1")

        for dev in devices:
            cmd = ["pvcreate", dev]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["vgcreate", "vg1", ] + devices[0:2]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["vgcreate", "vg2", ] + devices[2:4]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        cmd = ["vgcreate", "tvault-appliance-vg", ] + devices[4:5]
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        # create multiple volumes
        for vg in ["vg1", "vg2", "tvault-appliance-vg"]:
            cmd = ["lvcreate", "-L", "1G", vg, "-n", "lv1"]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            cmd = ["lvcreate", "-L", "2G", vg, "-n", "lv2"]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            cmd = ["lvcreate", "-L", "3G", vg, "-n", "lv3"]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            cmd = ["lvcreate", "-L", "4G", vg, "-n", "lv4"]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        # Format each volume to a filesystem
        tempdir = mkdtemp()
        for vg in ["vg1", "vg2", "tvault-appliance-vg"]:
            for lv in ["lv1", "lv2", "lv3", "lv4"]:
                cmd = ["mkfs", "-t", "ext4", "/dev/" + vg + "/" + lv]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)

                cmd = ["mount", "-t", "ext4", "/dev/" + vg + "/" + lv, tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                cmd = [
                    "cp",
                    "/opt/stack/workloadmgr/trilio-vix-disk-cli/" +
                    "VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                    tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                time.sleep(1)
                cmd = ["umount", tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        shutil.rmtree(tempdir)

        for vg in ["vg1", "vg2", "tvault-appliance-vg"]:
            vgcmd = ["vgchange", "-an", vg]
            subprocess.check_output(vgcmd, stderr=subprocess.STDOUT)

        for mountpoint in mountpoints:
            cmd = ["losetup", "-d", mountpoint]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

        # mount tvaultvg
        freedev = subprocess.check_output(["losetup", "-f"],
                                          stderr=subprocess.STDOUT)
        freedev = freedev.strip("\n")

        subprocess.check_output(["losetup", freedev, "pvname5", ],
                                stderr=subprocess.STDOUT)
        return

    def cleanup():
        for i in range(1, 6):
            deletepv("pvname" + str(i))
            if os.path.isfile("vmdk" + str(i)):
                os.remove("vmdk" + str(i))

    def verify(extentsinfo):
        try:
            freedevs = []
            vgs = []
            partdev = []
            if not extentsinfo:
                print "extentsinfo is null. Test failed"
                raise Exception("extentsinfo is null. Test failed")

            for key, value in extentsinfo['extentsfiles'].iteritems():
                my_populate_extents(None, None, None, None, key,
                                    "vmdk" + key.split("pvname")[1], value)

            for key, value in extentsinfo['extentsfiles'].iteritems():
                if key == "pvname5":
                    continue

                freedev = subprocess.check_output(["losetup", "-f"],
                                                  stderr=subprocess.STDOUT)
                freedev = freedev.strip("\n")

                subprocess.check_output(["losetup", freedev, "vmdk" + key.split("pvname")[1], ],
                                        stderr=subprocess.STDOUT)

                freedevs.append(freedev)
                pvinfo = workloadmgr.virt.vmwareapi.thickcopy._getpvinfo(
                    freedev + "p1")

            vgs = workloadmgr.virt.vmwareapi.thickcopy.getvgs()

            if len(vgs) == 0:
                print "No VGs found on VMDK. Test failed"
                raise Exception("No VGs found on VMDK. Test failed")

            lvs = workloadmgr.virt.vmwareapi.thickcopy.getlvs(vgs)
            if len(lvs) != 8:
                print "Number of LVs found is not 8. Test Failed"
                raise Exception("Number of LVs found is not 8. Test Failed")

            tempdir = mkdtemp()
            for lv in ["lv1", "lv2", "lv3", "lv4"]:
                cmd = ["mount", "-t", "ext4", "/dev/vg1/" + lv, tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                cmd = [
                    "diff",
                    "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                    tempdir +
                    "/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz"]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                time.sleep(1)
                cmd = ["umount", tempdir]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            shutil.rmtree(tempdir)

        except Exception as ex:
            print "Exception in verification. Verification failed"
            raise
        finally:
            for vg in vgs:
                workloadmgr.virt.vmwareapi.thickcopy.deactivatevgs(
                    vg['LVM2_VG_NAME'])

            for freedev in freedevs:
                try:
                    subprocess.check_output(["losetup", "-d", freedev],
                                            stderr=subprocess.STDOUT)
                except BaseException:
                    pass

    try:
        print "Running test_multiple_vgs_multiple_disk(): "

        setup()
        print "\tSetup complete"

        extentsinfo = test(4)
        print "\ttest() complete"

        verify(extentsinfo)
        print "\t verified successfully"

    finally:
        cleanup()
        print"\tcleanup done"

# thick copy when each disk is a single partition for PV
# thick copy should return the list of extent files


def test_multiple_vgs_multiple_disk_small_partition():

    def setup():
        mountpoints = []
        try:
            mountpoints.append(createpv("pvname1", "10GiB"))  # /dev/sda
            mountpoints.append(createpv("pvname2", "20GiB"))  # /dev/sdb
            mountpoints.append(createpv("pvname3", "20GiB"))  # /dev/sdc
            mountpoints.append(createpv("pvname4", "20GiB"))  # /dev/sdd
            mountpoints.append(createpv("pvname5", "10GiB"))  # /dev/sde
            mountpoints.append(createpv("pvname6", "10GiB"))

            devices = []
            cmd = ["parted", mountpoints[0], "mklabel", "gpt"]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            cmd = [
                "parted",
                mountpoints[0],
                "mkpart",
                "P1",
                "ext2",
                str(1024),
                str("1GiB")]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            cmd = [
                "parted",
                mountpoints[0],
                "mkpart",
                "P2",
                "ext2",
                str("1GiB"),
                str("10GiB")]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            devices.append(mountpoints[0] + "p1")
            devices.append(mountpoints[0] + "p2")

            cmd = ["parted", mountpoints[1], "mklabel", "gpt"]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            cmd = [
                "parted",
                mountpoints[1],
                "mkpart",
                "P1",
                "ext2",
                str(1024),
                str("20GiB")]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            cmd = ["parted", mountpoints[2], "mklabel", "gpt"]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            cmd = [
                "parted",
                mountpoints[2],
                "mkpart",
                "P1",
                "ext2",
                str(1024),
                str("1028MiB")]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            cmd = [
                "parted",
                mountpoints[2],
                "mkpart",
                "P2",
                "ext2",
                str("1029MiB"),
                str("20GiB")]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            devices.append(mountpoints[2] + "p1")
            devices.append(mountpoints[2] + "p2")

            devices.append(mountpoints[3])
            devices.append(mountpoints[5])

            cmd = ["parted", mountpoints[4], "mklabel", "gpt"]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            cmd = [
                "parted",
                mountpoints[4],
                "mkpart",
                "P1",
                "ext2",
                str(1024),
                str("10GiB")]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            for dev in devices:
                cmd = ["pvcreate", dev]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            cmd = ["vgcreate", "vg1", ] + [devices[2]] + [devices[3]]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            cmd = ["vgcreate", "vg2", ] + [devices[4]]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            cmd = ["vgcreate", "centos-os", ] + [devices[1]]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            cmd = ["vgcreate", "tvault-appliance-vg", ] + [devices[5]]
            subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            # create multiple volumes
            for vg in ["vg1", "vg2", "tvault-appliance-vg", "centos-os"]:
                cmd = ["lvcreate", "-L", "1G", vg, "-n", "lv1"]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)

                cmd = ["lvcreate", "-L", "1G", vg, "-n", "lv2"]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)

                cmd = ["lvcreate", "-L", "1G", vg, "-n", "lv3"]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)

                cmd = ["lvcreate", "-L", "1G", vg, "-n", "lv4"]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            # Format each volume to a filesystem
            tempdir = mkdtemp()
            for vg in ["vg1", "vg2", "tvault-appliance-vg", "centos-os"]:
                for lv in ["lv1", "lv2", "lv3", "lv4"]:
                    cmd = ["mkfs", "-t", "ext4", "/dev/" + vg + "/" + lv]
                    subprocess.check_output(cmd, stderr=subprocess.STDOUT)

                    cmd = [
                        "mount",
                        "-t",
                        "ext4",
                        "/dev/" +
                        vg +
                        "/" +
                        lv,
                        tempdir]
                    subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                    cmd = [
                        "cp",
                        "/opt/stack/workloadmgr/trilio-vix-disk-cli/" +
                        "VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                        tempdir]
                    subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                    time.sleep(1)
                    cmd = ["umount", tempdir]
                    subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            shutil.rmtree(tempdir)

            for vg in ["vg1", "vg2", "tvault-appliance-vg", "centos-os"]:
                vgcmd = ["vgchange", "-an", vg]
                subprocess.check_output(vgcmd, stderr=subprocess.STDOUT)

            for mountpoint in mountpoints:
                cmd = ["losetup", "-d", mountpoint]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)

            # mount tvaultvg
            freedev = subprocess.check_output(["losetup", "-f"],
                                              stderr=subprocess.STDOUT)
            freedev = freedev.strip("\n")

            subprocess.check_output(["losetup", freedev, "pvname5", ],
                                    stderr=subprocess.STDOUT)
        except BaseException:
            vgcmd = ["vgchange", "-an"]
            subprocess.check_output(vgcmd, stderr=subprocess.STDOUT)

            for mountpoint in mountpoints:
                cmd = ["losetup", "-d", mountpoint]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            raise
        return

    def cleanup():
        for i in range(1, 7):
            deletepv("pvname" + str(i))
            if os.path.isfile("vmdk" + str(i)):
                os.remove("vmdk" + str(i))

    def verify(extentsinfo):
        try:
            import pdb
            pdb.set_trace()
            freedevs = []
            vgs = []
            partdev = []
            if not extentsinfo:
                print "extentsinfo is null. Test failed"
                raise Exception("extentsinfo is null. Test failed")

            for key, value in extentsinfo['extentsfiles'].iteritems():
                my_populate_extents(None, None, None, None, key,
                                    "vmdk" + key.split("pvname")[1], value)

            for key, value in extentsinfo['extentsfiles'].iteritems():

                freedev = subprocess.check_output(["losetup", "-f"],
                                                  stderr=subprocess.STDOUT)
                freedev = freedev.strip("\n")

                subprocess.check_output(["losetup", freedev, "vmdk" + key.split("pvname")[1], ],
                                        stderr=subprocess.STDOUT)

                freedevs.append(freedev)

            vgs = workloadmgr.virt.vmwareapi.thickcopy.getvgs()

            if len(vgs) == 0:
                print "No VGs found on VMDK. Test failed"
                raise Exception("No VGs found on VMDK. Test failed")

            lvs = workloadmgr.virt.vmwareapi.thickcopy.getlvs(vgs)
            if len(lvs) != 12:
                print "Number of LVs found is not 8. Test Failed"
                raise Exception("Number of LVs found is not 8. Test Failed")

            tempdir = mkdtemp()
            for vg in ["vg1", "vg2", "centos-os"]:
                for lv in ["lv1", "lv2", "lv3", "lv4"]:
                    cmd = [
                        "mount",
                        "-t",
                        "ext4",
                        "/dev/" +
                        vg +
                        "/" +
                        lv,
                        tempdir]
                    subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                    cmd = [
                        "diff",
                        "/opt/stack/workloadmgr/trilio-vix-disk-cli/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz",
                        tempdir +
                        "/VMware-vix-disklib-5.5.3-1909144.x86_64.tar.gz"]
                    subprocess.check_output(cmd, stderr=subprocess.STDOUT)
                    time.sleep(1)
                    cmd = ["umount", tempdir]
                    subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            shutil.rmtree(tempdir)

        except Exception as ex:
            print "Exception in verification. Verification failed"
            raise
        finally:
            for vg in vgs:
                workloadmgr.virt.vmwareapi.thickcopy.deactivatevgs(
                    vg['LVM2_VG_NAME'])

            for freedev in freedevs:
                try:
                    subprocess.check_output(["losetup", "-d", freedev],
                                            stderr=subprocess.STDOUT)
                except BaseException:
                    pass

    try:
        print "Running test_multiple_vgs_multiple_disk_small_partition(): "

        setup()
        print "\tSetup complete"

        extentsinfo = test(4)
        print "\ttest() complete"

        verify(extentsinfo)
        print "\t verified successfully"

    finally:
        cleanup()
        print"\tcleanup done"


if __name__ == "__main__":
    test_lv_entire_disk()
    # test_lv_on_partitions()
    # test_lvs_on_two_partitions()
    # test_lvs_span_two_partitions()
    # test_mbr_4_primary_partitions()
    # test_mbr_3_primary_1_logical_partitions()
    # test_gpt_partitions()
    # test_raw_disk()
    # test_raw_partition()
    # test_lv_part_mixed()
    # test_part_lv_mixed()
    # test_part_lv_mixed_with_tvault_vg()

    # Add multiple disks per VG test cases
    # test_lv_entire_disks()
    # test_lv_entire_disks_with_one_disk_missing()
    # test_lvm_on_single_partition()
    # test_mix_of_lvm_and_partitions()
    # test_mix_of_lvm_and_partitions_with_unformatted()
    # test_mix_of_lvm_and_partitions_with_unformatted_raw_disks()
    # test_mix_of_lvm_and_regular_partitions_on_same_disk()
    # test_multiple_vgs_multiple_disk()
    # test_multiple_vgs_multiple_disk_small_partition()
    # smaller disk with large number of disks and create stripped lv
    # to really test logical to physical mapping
    # create a test case that a volume or partition has xfs filesystem
