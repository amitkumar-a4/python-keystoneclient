# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""WorkloadMgr base exception handling.

Includes decorator for re-raising WorkloadMgr-type exceptions.

SHOULD include dedicated exception logging.

"""

from oslo.config import cfg
import webob.exc

from workloadmgr.openstack.common.gettextutils import _
from workloadmgr import flags
from workloadmgr.openstack.common import log as logging

LOG = logging.getLogger(__name__)

exc_log_opts = [
    cfg.BoolOpt('fatal_exception_format_errors',
                default=False,
                help='make exception message format errors fatal'),
]

FLAGS = flags.FLAGS
FLAGS.register_opts(exc_log_opts)


class ConvertedException(webob.exc.WSGIHTTPException):
    def __init__(self, code=0, title="", explanation=""):
        self.code = code
        self.title = title
        self.explanation = explanation
        super(ConvertedException, self).__init__()


class ProcessExecutionError(IOError):
    def __init__(self, stdout=None, stderr=None, exit_code=None, cmd=None,
                 description=None):
        self.exit_code = exit_code
        self.stderr = stderr
        self.stdout = stdout
        self.cmd = cmd
        self.description = description

        if description is None:
            description = _('Unexpected error while running command.')
        if exit_code is None:
            exit_code = '-'
        message = _('%(description)s\nCommand: %(cmd)s\n'
                    'Exit code: %(exit_code)s\nStdout: %(stdout)r\n'
                    'Stderr: %(stderr)r') % locals()
        IOError.__init__(self, message)


class Error(Exception):
    pass


class DBError(Error):
    """Wraps an implementation specific exception."""
    def __init__(self, inner_exception=None):
        self.inner_exception = inner_exception
        super(DBError, self).__init__(str(inner_exception))


def wrap_db_error(f):
    def _wrap(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except UnicodeEncodeError:
            raise InvalidUnicodeParameter()
        except Exception, e:
            LOG.exception(_('DB exception wrapped.'))
            raise DBError(e)
    _wrap.func_name = f.func_name
    return _wrap

class WorkloadMgrException(Exception):
    """Base WorkloadMgr Exception

    To correctly use this class, inherit from it and define
    a 'message' property. That message will get printf'd
    with the keyword arguments provided to the constructor.

    """
    message = _("An unknown exception occurred.")
    code = 500
    headers = {}
    safe = False

    def __init__(self, message=None, **kwargs):
        self.kwargs = kwargs

        if 'code' not in self.kwargs:
            try:
                self.kwargs['code'] = self.code
            except AttributeError:
                pass

        if not message:
            try:
                message = self.message % kwargs

            except Exception as e:
                # kwargs doesn't match a variable in the message
                # log the issue and the kwargs
                LOG.exception(_('Exception in string format operation'))
                for name, value in kwargs.iteritems():
                    LOG.error("%s: %s" % (name, value))
                if FLAGS.fatal_exception_format_errors:
                    raise e
                else:
                    # at least get the core message out if something happened
                    message = self.message

        super(WorkloadMgrException, self).__init__(message)

class InvalidState(WorkloadMgrException):
    message = _("Invalid state") + ": %(reason)s"

class GlanceConnectionFailed(WorkloadMgrException):
    message = _("Connection to glance failed") + ": %(reason)s"


class NotAuthorized(WorkloadMgrException):
    message = _("Not authorized.")
    code = 403


class AdminRequired(NotAuthorized):
    message = _("User does not have admin privileges")


class PolicyNotAuthorized(NotAuthorized):
    message = _("Policy doesn't allow %(action)s to be performed.")


class ImageNotAuthorized(WorkloadMgrException):
    message = _("Not authorized for image %(image_id)s.")


class Invalid(WorkloadMgrException):
    message = _("Unacceptable parameters.")
    code = 400


class InvalidSnapshot(Invalid):
    message = _("Invalid snapshot") + ": %(reason)s"


class InvalidRequest(Invalid):
    message = _("The request is invalid.")


class InvalidResults(Invalid):
    message = _("The results are invalid.")


class InvalidInput(Invalid):
    message = _("Invalid input received") + ": %(reason)s"



class InvalidVolume(Invalid):
    message = _("Invalid volume") + ": %(reason)s"


class InvalidContentType(Invalid):
    message = _("Invalid content type %(content_type)s.")


class InvalidUnicodeParameter(Invalid):
    message = _("Invalid Parameter: "
                "Unicode is not supported by the current database.")


# Cannot be templated as the error syntax varies.
# msg needs to be constructed when raised.
class InvalidParameterValue(Invalid):
    message = _("%(err)s")


class ServiceUnavailable(Invalid):
    message = _("Service is unavailable at this time.")


class ImageUnacceptable(Invalid):
    message = _("Image %(image_id)s is unacceptable: %(reason)s")


class InvalidUUID(Invalid):
    message = _("Expected a uuid but received %(uuid).")


class NotFound(WorkloadMgrException):
    message = _("Resource could not be found.")
    code = 404
    safe = True


class VolumeNotFound(NotFound):
    message = _("Volume %(volume_id)s could not be found.")


class InvalidImageRef(Invalid):
    message = _("Invalid image href %(image_href)s.")


class ImageNotFound(NotFound):
    message = _("Image %(image_id)s could not be found.")


class ServiceNotFound(NotFound):
    message = _("Service %(service_id)s could not be found.")


class HostNotFound(NotFound):
    message = _("Host %(host)s could not be found.")


class SchedulerHostFilterNotFound(NotFound):
    message = _("Scheduler Host Filter %(filter_name)s could not be found.")


class SchedulerHostWeigherNotFound(NotFound):
    message = _("Scheduler Host Weigher %(weigher_name)s could not be found.")


class HostBinaryNotFound(NotFound):
    message = _("Could not find binary %(binary)s on host %(host)s.")


class InvalidReservationExpiration(Invalid):
    message = _("Invalid reservation expiration %(expire)s.")


class InvalidQuotaValue(Invalid):
    message = _("Change would make usage less than 0 for the following "
                "resources: %(unders)s")


class QuotaNotFound(NotFound):
    message = _("Quota could not be found")


class QuotaResourceUnknown(QuotaNotFound):
    message = _("Unknown quota resources %(unknown)s.")


class ProjectQuotaNotFound(QuotaNotFound):
    message = _("Quota for project %(project_id)s could not be found.")


class QuotaClassNotFound(QuotaNotFound):
    message = _("Quota class %(class_name)s could not be found.")


class QuotaUsageNotFound(QuotaNotFound):
    message = _("Quota usage for project %(project_id)s could not be found.")


class ReservationNotFound(QuotaNotFound):
    message = _("Quota reservation %(uuid)s could not be found.")


class OverQuota(WorkloadMgrException):
    message = _("Quota exceeded for resources: %(overs)s")


class FileNotFound(NotFound):
    message = _("File %(file_path)s could not be found.")


class ClassNotFound(NotFound):
    message = _("Class %(class_name)s could not be found: %(exception)s")


class NotAllowed(WorkloadMgrException):
    message = _("Action not allowed.")


class Duplicate(WorkloadMgrException):
    pass


class MigrationError(WorkloadMgrException):
    message = _("Migration error") + ": %(reason)s"


class MalformedRequestBody(WorkloadMgrException):
    message = _("Malformed message body: %(reason)s")


class ConfigNotFound(NotFound):
    message = _("Could not find config at %(path)s")


class PasteAppNotFound(NotFound):
    message = _("Could not load paste app '%(name)s' from %(path)s")


class NoValidHost(WorkloadMgrException):
    message = _("No valid host was found. %(reason)s")


class WillNotSchedule(WorkloadMgrException):
    message = _("Host %(host)s is not up or doesn't exist.")


class QuotaError(WorkloadMgrException):
    message = _("Quota exceeded") + ": code=%(code)s"
    code = 413
    headers = {'Retry-After': 0}
    safe = True


class SnapshotLimitExceeded(QuotaError):
    message = _("Maximum number of snapshots allowed (%(allowed)d) exceeded")


class UnknownCmd(Invalid):
    message = _("Unknown or unsupported command %(cmd)s")


class MalformedResponse(Invalid):
    message = _("Malformed response to command %(cmd)s: %(reason)s")


class BadHTTPResponseStatus(WorkloadMgrException):
    message = _("Bad HTTP response status %(status)s")


class FailedCmdWithDump(WorkloadMgrException):
    message = _("Operation failed with status=%(status)s. Full dump: %(data)s")


class InstanceNotFound(NotFound):
    message = _("Instance %(instance_id)s could not be found.")


class NfsException(WorkloadMgrException):
    message = _("Unknown NFS exception")


class NfsNoSharesMounted(NotFound):
    message = _("No mounted NFS shares found")


class NfsNoSuitableShareFound(NotFound):
    message = _("There is no share which can host %(volume_size)sG")


class GlusterfsException(WorkloadMgrException):
    message = _("Unknown Gluster exception")


class GlusterfsNoSharesMounted(NotFound):
    message = _("No mounted Gluster shares found")


class GlusterfsNoSuitableShareFound(NotFound):
    message = _("There is no share which can host %(volume_size)sG")


class ImageCopyFailure(Invalid):
    message = _("Failed to copy image to volume")


class WorkloadMgrNotFound(NotFound):
    message = _("WorkloadMgr %(workload_id)s could not be found.")

   
class SnapshotNotFound(NotFound):
    message = _("Snapshot %(snapshot_id)s could not be found.")    

class SwiftObjectNotFound(NotFound):
    message = _("SwiftObject %(object_id)s could not be found.")

class InvalidWorkloadMgr(Invalid):
    message = _("Invalid workload: %(reason)s")

class SwiftConnectionFailed(WorkloadMgrException):
    message = _("Connection to swift failed") + ": %(reason)s"

class VMsofWorkloadMgrNotFound(NotFound):
    message = _("VMs for WorkloadMgr %(workload_id)s could not be found.")    
    
class VMsOfSnapshotNotFound(NotFound):
    message = _("VMs for Snapshot %(snapshot_id)s could not be found.")  

class VMRecentSnapshotNotFound(NotFound):
    message = _("Recent successful Snapshot for VM %(vm_id)s could not be found.") 
    
class SnapshotVMResourcesNotFound(NotFound):
    message = _("SnapshotVMResources of VM  %(vm_id)s Snapshot %(snapshot_id)s could not be found.")

class SnapshotVMResourcesWithNameNotFound(NotFound):
    message = _("SnapshotVMResource of VM  %(vm_id)s Snapshot %(snapshot_id)s Resource %(resource_name)s could not be found.")

class SnapshotVMResourcesWithIdNotFound(NotFound):
    message = _("SnapshotVMResource with Id  %(id)s could not be found.")

class VMDiskResourceSnapsNotFound(NotFound):
    message = _("VM Resource snapshots for snapshot_vm_resource_id %(snapshot_vm_resource_id)s could not be found.")
    
class VMNetworkResourceSnapsNotFound(NotFound):
    message = _("VM Resource snapshots for snapshot_vm_resource_id %(snapshot_vm_resource_id)s could not be found.")  
    
class RestoreNotFound(NotFound):
    message = _("Restore %(restore_id)s could not be found.")       
    
class WorkloadNotFound(NotFound):
    message = _("Workload %(workload_id)s could not be found.") 
    
class WorkloadsNotFound(NotFound):
    message = _("Workloads could not be found.")
    
class WorkloadVMNotFound(NotFound):
    message = _("WorkloadVM %(workload_vm_id)s could not be found.") 
    
class WorkloadVMsNotFound(NotFound):
    message = _("WorkloadVMs could not be found.")        
    
class SnapshotVMNotFound(NotFound):
    message = _("SnapshotVM %(snapshot_id)s could not be found.") 
    
class SnapshotVMsNotFound(NotFound):
    message = _("SnapshotVMs could not be found.")    
    
class InvalidWorkloadState(WorkloadMgrException):
    message = _("Invalid workload state: %(state)s") 
    
class DatastoreNotFound(NotFound):
    message = _("Could not find the datastore.")
    
class ResourcePoolNotFound(NotFound):
    message = _("Could not find the resourcepool.")

class VMFolderNotFound(NotFound):
    message = _("Could not find the vmfolder.")
    
class VMNotFound(NotFound):
    message = _("Could not find the VM.")  
    
class NetworkNotFound(NotFound):
    message = _("Could not find the Network.")

class InstanceSuspendFailure(Invalid):
    msg_fmt = _("Failed to suspend instance") + ": %(reason)s"     

class InstanceResumeFailure(Invalid):
    msg_fmt = _("Failed to resume instance: %(reason)s.")   
    
class InstancePowerOffFailure(Invalid):
    msg_fmt = _("Failed to power off instance: %(reason)s.")  
    
class DatacenterNotFound(NotFound):
    message = _("Could not find the Datacenter.")                            