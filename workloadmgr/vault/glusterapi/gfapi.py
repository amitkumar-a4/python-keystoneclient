#!/usr/bin/python

from ctypes import *
import os
import sys
import time
import types

# Looks like ctypes is having trouble with dependencies, so just force them to
# load with RTLD_GLOBAL until I figure that out.
glfs = CDLL("libglusterfs.so", RTLD_GLOBAL)
xdr = CDLL("libgfxdr.so", RTLD_GLOBAL)
api = CDLL("libgfapi.so", RTLD_GLOBAL)

# Wow, the Linux kernel folks really play nasty games with this structure.  If
# you look at the man page for stat(2) and then at this definition you'll note
# two discrepancies.  First, we seem to have st_nlink and st_mode reversed.  In
# fact that's exactly how they're defined *for 64-bit systems*; for 32-bit
# they're in the man-page order.  Even uglier, the man page makes no mention of
# the *nsec fields, but they are very much present and if they're not included
# then we get memory corruption because libgfapi has a structure definition
# that's longer than ours and they overwrite some random bit of memory after
# the space we allocated.  Yes, that's all very disgusting, and I'm still not
# sure this will really work on 32-bit because all of the field types are so
# obfuscated behind macros and feature checks.


class Stat (Structure):
    _fields_ = [
        ("st_dev", c_ulong),
        ("st_ino", c_ulong),
        ("st_nlink", c_ulong),
        ("st_mode", c_uint),
        ("st_uid", c_uint),
        ("st_gid", c_uint),
        ("st_rdev", c_ulong),
        ("st_size", c_ulong),
        ("st_blksize", c_ulong),
        ("st_blocks", c_ulong),
        ("st_atime", c_ulong),
        ("st_atimensec", c_ulong),
        ("st_mtime", c_ulong),
        ("st_mtimensec", c_ulong),
        ("st_ctime", c_ulong),
        ("st_ctimensec", c_ulong),
    ]


api.glfs_creat.restype = c_void_p
api.glfs_open.restype = c_void_p
api.glfs_lstat.restype = c_int
api.glfs_lstat.argtypes = [c_void_p, c_char_p, POINTER(Stat)]


class Dirent (Structure):
    _fields_ = [
        ("d_ino", c_ulong),
        ("d_off", c_ulong),
        ("d_reclen", c_ushort),
        ("d_type", c_char),
        ("d_name", c_char * 256),
    ]


api.glfs_opendir.restype = c_void_p
api.glfs_readdir_r.restype = c_int
api.glfs_readdir_r.argtypes = [c_void_p, POINTER(Dirent),
                               POINTER(POINTER(Dirent))]

# There's a bit of ctypes glitchiness around __del__ functions and module-level
# variables.  If we unload the module while we still have references to File or
# Volume objects, the module-level variables might have disappeared by the time
# __del__ gets called.  Therefore the objects hold references which they
# release when __del__ is done.  We only actually use the object-local values
# in __del__; for clarity, we just use the simpler module-level form elsewhere.


class File(object):

    def __init__(self, fd):
        # Add a reference so the module-level variable "api" doesn't
        # get yanked out from under us (see comment above File def'n).
        self._api = api
        self.fd = fd

    def __del__(self):
        self._api.glfs_close(self.fd)
        self._api = None

    # File operations, in alphabetical order.

    def fsync(self):
        return api.glfs_fsync(self.fd)

    def read(self, buflen, flags=0):
        rbuf = create_string_buffer(buflen)
        rc = api.glfs_read(self.fd, rbuf, buflen, flags)
        if rc > 0:
            return rbuf.value[:rc]
        else:
            return rc

    def read_buffer(self, buf, flags=0):
        return api.glfs_read(self.fd, buf, len(buf), flags)

    def write(self, data, flags=0):
        return api.glfs_write(self.fd, data, len(data), flags)

    def fallocate(self, mode, offset, length):
        return api.glfs_fallocate(self.fd, mode, offset, length)

    def discard(self, offset, length):
        return api.glfs_discard(self.fd, offset, length)


class Dir(object):

    def __init__(self, fd):
        # Add a reference so the module-level variable "api" doesn't
        # get yanked out from under us (see comment above File def'n).
        self._api = api
        self.fd = fd
        self.cursor = POINTER(Dirent)()

    def __del__(self):
        self._api.glfs_closedir(self.fd)
        self._api = None

    def next(self):
        entry = Dirent()
        entry.d_reclen = 256
        rc = api.glfs_readdir_r(self.fd, byref(entry), byref(self.cursor))
        if (rc < 0) or (not self.cursor) or (not self.cursor.contents):
            return rc
        return entry


class Volume(object):

    # Housekeeping functions.

    def __init__(self, host, volid, proto="tcp", port=24007):
        # Add a reference so the module-level variable "api" doesn't
        # get yanked out from under us (see comment above File def'n).
        self._api = api
        self.fs = api.glfs_new(volid)
        api.glfs_set_volfile_server(self.fs, proto, host, port)

    def __del__(self):
        self._api.glfs_fini(self.fs)
        self._api = None

    def set_logging(self, path, level):
        api.glfs_set_logging(self.fs, path, level)

    def mount(self):
        api.glfs_init(self.fs)

    # File operations, in alphabetical order.

    def creat(self, path, flags, mode):
        fd = api.glfs_creat(self.fs, path, flags, mode)
        if not fd:
            return fd
        return File(fd)

    def getxattr(self, path, key, maxlen):
        buf = create_string_buffer(maxlen)
        rc = api.glfs_getxattr(self.fs, path, key, buf, maxlen)
        if rc < 0:
            return rc
        return buf.value[:rc]

    def listxattr(self, path):
        buf = create_string_buffer(512)
        rc = api.glfs_listxattr(self.fs, path, buf, 512)
        if rc < 0:
            return rc
        xattrs = []
        # Parsing character by character is ugly, but it seems like the
        # easiest way to deal with the "strings separated by NUL in one
        # buffer" format.
        i = 0
        while i < rc:
            new_xa = buf.raw[i]
            i += 1
            while i < rc:
                next_char = buf.raw[i]
                i += 1
                if next_char == '\0':
                    xattrs.append(new_xa)
                    break
                new_xa += next_char
        xattrs.sort()
        return xattrs

    def lstat(self, path):
        x = Stat()
        rc = api.glfs_lstat(self.fs, path, byref(x))
        if rc >= 0:
            return x
        else:
            return rc

    def mkdir(self, path):
        return api.glfs_mkdir(self.fs, path)

    def open(self, path, flags):
        fd = api.glfs_open(self.fs, path, flags)
        if not fd:
            return fd
        return File(fd)

    def opendir(self, path):
        fd = api.glfs_opendir(self.fs, path)
        if not fd:
            return fd
        return Dir(fd)

    def rename(self, opath, npath):
        return api.glfs_rename(self.fs, opath, npath)

    def rmdir(self, path):
        return api.glfs_rmdir(self.fs, path)

    def setxattr(self, path, key, value, vlen):
        return api.glfs_setxattr(self.fs, path, key, value, vlen, 0)

    def unlink(self, path):
        return api.glfs_unlink(self.fs, path)


def mount():
    return volume.mount()


def creat(path, flags, mode):
    return volume.creat(path, flags, mode)


def getxattr(path, key, maxlen):
    return volume.getxattr(path, key, maxlen)


def listxattr(path):
    return volume.listxattr(path)


def lstat(path):
    return volume.lstat(path)


def mkdir(path):
    return volume.mkdir(path)


def open(path, flags):
    return volume.open(path, flags)


def opendir(path):
    return volume.opendir(path)


def rmdir(path):
    return volume.rmdir(path)


def setxattr(path, key, value, vlen):
    return volume.setxattr(path, key, value, vlen)


def unlink(path):
    return volume.unlink(path)
