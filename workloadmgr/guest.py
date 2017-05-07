import sys
import guestfs
#from multiprocessing import Process
#from multiprocessing import Pool, TimeoutError
from pathos.multiprocessing import ProcessingPool as Pool

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
    i = 0
    for root in roots:
        try:
            g.mount_ro(root, '/')
        except RuntimeError as msg:
               print "%s (ignored)" % msg
        val = g.glob_expand(filepath)
        disk = {}
        if 'snapshot_id' in dt:
           disks = dt[snapshot_id]
        disk[drives[i]] = val
        dt[snapshot_id] = disk 
        g.umount_all()
        i = i + 1
    dt['filepath'] = filepath
    return dt


class GuestFs(object):
    """ Libguestfs library class
    """

    def __init__(self):
        self.pool = Pool(processes=4)

    def search(self, data):
        """ 
            Search for file information
        """
      
        it = self.pool.map(f, data)
        return it

guestfs = GuestFs()
it = guestfs.search(['/opt/stack/,snaps_id,ccbf9827-be53-4a38-bae8-82bb2fded6fc'])
