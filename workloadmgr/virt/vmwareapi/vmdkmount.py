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
from threading import Thread
from tempfile import mkstemp

from workloadmgr import exception
from workloadmgr.openstack.common import log as logging
from workloadmgr.openstack.common.gettextutils import _
from workloadmgr import autolog

LOG = logging.getLogger(__name__)
Logger = autolog.Logger(LOG)


def enqueue_output(out, queue):
    for line in iter(out.readline, b''):
        queue.put(line)
    out.close()


def mount_local_vmdk(vmdkfiles, diskonly=False):
    vix_disk_lib_env = os.environ.copy()
    vix_disk_lib_env['LD_LIBRARY_PATH'] = '/usr/lib/vmware-vix-disklib/lib64'

    try:
        processes = []
        mountpoints = {}
        for vmdkfile in vmdkfiles:
            try:
                fileh, mntlist = mkstemp()
                close(fileh)

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
                if os.path.isfile(mntlist):
                    os.remove(mntlist)

        return processes, mountpoints
    except Exception as ex:
        LOG.exception(ex)
        try:
            umount_local_vmdk(processes)
        except BaseException:
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


def umountdevice(devpath):
    subprocess.check_output(["losetup", "-d", devpath],
                            stderr=subprocess.STDOUT)


def unassignloopdevices(devpaths):
    for key, devpath in devpaths.iteritems():
        try:
            umountdevice(devpath)
        except BaseException:
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
            except BaseException:
                pass

            try:
                cmd = ["partx", "-a", devpath]
                subprocess.check_output(cmd, stderr=subprocess.STDOUT)
            except BaseException:
                pass
        except BaseException:
            unassignloopdevices(devicepaths)
            raise

    return devicepaths
