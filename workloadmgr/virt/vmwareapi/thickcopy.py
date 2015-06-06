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
                        mountpath):
     return populate_extent(hostip, username, password, vmspec, remotepath,
                           mountpath, 0, 400)

##
# getfdisk_output():
# if the underlying disk is fdisk, read the partition table from the mounted disk
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
            partition["id"] = fields[index]
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

def get_usedblockslist(mountpath, usedblockfile, part, blocksize):

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
    
##
# copy_free_bitmap():
#     Creates an empty bitmap vmdk file with the name specified by localvmdkpath
##
def copy_free_bitmap(hostip, username, password, vmspec, dev,
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
# copy_used_blocks():
#     Copies used blocks from remote disk to local disk
##
def copy_used_blocks(hostip, username, password, vmspec, dev,
                     mountpath, usedblocksfile):

     populate_extents(hostip, username, password, vmspec, dev['backing']['fileName'],
                     mountpath, usedblocksfile)

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
def thickcopyextents(hostip, username, password, vmspec, dev, localvmdkpath):
   
    # Read the partition table from the file
    populate_bootrecord(hostip, username, password, vmspec,
                        dev['backing']['fileName'], localvmdkpath)

    fileh, listfile = mkstemp()
    close(fileh)
    with open(listfile, 'w') as f:
        f.write(localvmdkpath)

    fileh, mntlist = mkstemp()
    close(fileh)

    process, mountpaths = mount_local_vmdk(listfile, mntlist, diskonly=True)
    try:
        for key, value in mountpaths.iteritems():
            partitions = getfdisk_output(value[0].split(";")[0].strip())
    finally:
        umount_local_vmdk(process)

    # First copy super blocks of each partition
    #
    for part in partitions:
        populate_extent(hostip, username, password, vmspec,
                        dev['backing']['fileName'],
                        localvmdkpath, str(part['start']), 400)


    # If partition has ext2 or its variant of file system, read the
    # blocksize and all the block groups of the file system
    partblockgroups = {}
    process, mountpaths = mount_local_vmdk(listfile,
                                 mntlist, diskonly=True)
    try:
        for key, value in mountpaths.iteritems():
            mountpath = value[0].split(";")[0].strip()
        for part in partitions:
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
            finally:
                try:
                    subprocess.check_output(["losetup", "-d", freedev],
                              stderr=subprocess.STDOUT)
                except:
                    pass
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
            copy_free_bitmap(hostip, username, password, vmspec, dev,
                             localvmdkpath, part['start'],
                             blocksize, blockgroups)

    fileh, extentsfile = mkstemp()
    close(fileh)
    totalblocks = 0
    for part in partitions:
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
                totalblocks += get_usedblockslist(freedev, extentsfile,
                                                  part, blocksize)
            finally:
                subprocess.check_output(["losetup", "-d", freedev],
                                        stderr=subprocess.STDOUT)
        finally:
            umount_local_vmdk(process)

    return extentsfile, partitions, totalblocks, listfile, mntlist

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
