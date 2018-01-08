import sys
import guestfs
import multiprocessing
from multiprocessing import Process
from multiprocessing import Pool, TimeoutError
#from pathos.multiprocessing import ProcessingPool as Pool
import os
import pwd
uid = pwd.getpwnam('nova')[2]
os.setuid(uid)


def f(data):
    g = guestfs.GuestFS(python_return_dict=True)
    drives = data.split(',,')
    filepath = drives[0]
    drives.pop(0)
    snapshot_id = drives[0]
    drives.pop(0)
    for drive in drives:
        g.add_drive_opts(drive, format="qcow2", readonly=1)
    g.set_backend("libvirt")
    g.set_path("/home/nova")
    g.launch()
    dt = {}
    roots = g.list_filesystems()
    lt_drives = []
    for root in roots:
        try:
            g.mount_ro(root, '/')
        except RuntimeError as msg:
            # print "%s (ignored)" % msg
            continue
        val = g.glob_expand(filepath)
        disk = {}
        root = root.replace('s', 'v')
        disk[root] = val
        if len(val) > 0:
            for path in val:
                try:
                    disk[path] = g.stat(path)
                except Exception as ex:
                    disk[path] = ex.message
        lt_drives.append(disk)
        g.umount_all()
    dt[snapshot_id] = lt_drives
    if len(drives) == 0:
        dt[snapshot_id] = 'Snapshot VM deleted'
    g.close()
    return dt


def main(argv):
    processes = max(4, multiprocessing.cpu_count())
    pool = Pool(processes=processes)
    data = argv[0].split('|-|')
    print pool.map(f, data)


if __name__ == '__main__':
    main(sys.argv[1:])

#guestfs = GuestFs()
#it = guestfs.search(['/opt/stack/,snaps_id,ccbf9827-be53-4a38-bae8-82bb2fded6fc'])
