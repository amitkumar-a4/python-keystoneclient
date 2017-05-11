import sys
import guestfs
from multiprocessing import Process
from multiprocessing import Pool, TimeoutError
#from pathos.multiprocessing import ProcessingPool as Pool
import os
import pwd
uid = pwd.getpwnam('nova')[2]
os.setuid(uid)

def f(data):
    g = guestfs.GuestFS(python_return_dict=True)
    drives = data.split(',')
    filepath = drives[0]
    drives.pop(0)
    snapshot_id = drives[0]
    drives.pop(0)
    for drive in drives:
        g.add_drive_opts(drive, readonly=1)
    g.set_backend("libvirt")
    g.launch()
    dt = {}
    roots = g.list_filesystems()
    lt_drives = []
    for root in roots:
        try:
            g.mount_ro(root, '/')
        except RuntimeError as msg:
               #print "%s (ignored)" % msg
               continue
        val = g.glob_expand(filepath)
        disk = {}
        disk[root] = val
        lt_drives.append(disk)
        g.umount_all()
    dt[snapshot_id] = lt_drives   
    g.close()
    return dt


def main(argv):
    pool = Pool(processes=4)
    data = argv[0].split('|-|')
    print pool.map(f, data)

if __name__ == '__main__':
    main(sys.argv[1:]) 

#guestfs = GuestFs()
#it = guestfs.search(['/opt/stack/,snaps_id,ccbf9827-be53-4a38-bae8-82bb2fded6fc'])
