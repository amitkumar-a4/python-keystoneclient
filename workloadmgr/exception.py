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
    message = _("Error: %(reason)s")
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
    
class ErrorOccurred(WorkloadMgrException):
    message = "%(reason)s"    

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
    message = _("Unacceptable parameters: %(reason)s")
    code = 400

class Forbidden(WorkloadMgrException):
    message = _("You are not authorized to use %(action)s.")

class AuthorizationFailure(WorkloadMgrException):
    message = _("Authorization failed.")

class MissingCredentialError(WorkloadMgrException):
    msg_fmt = _("Missing required credential: %(required)s")

class InvalidSnapshot(Invalid):
    message = _("Invalid snapshot") + ": %(reason)s"

class InvalidWorkload(Invalid):
    message = _("Invalid workload") + ": %(reason)s"

class InvalidRequest(Invalid):
    message = _("The request is invalid. %(reason)s")


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

class InstanceNotFound(NotFound):
    message = _("Instance %(instance_id)s could not be found.")

class ImageCopyFailure(Invalid):
    message = _("Failed to copy image to volume")
    
class WorkloadTypesNotFound(NotFound):
    message = _("WorkloadTypes could not be found.")
    
class WorkloadTypeNotFound(NotFound):
    message = _("WorkloadType %(workload_type_id)s could not be found.")
    
class WorkloadsNotFound(NotFound):
    message = _("Workloads could not be found.")

    
class WorkloadNotFound(NotFound):
    message = _("Workload %(workload_id)s could not be found.")
    
class WorkloadVMsNotFound(NotFound):
    message = _("WorkloadVMs of %(workload_id)s could not be found.")
        
class WorkloadVMNotFound(NotFound):
    message = _("WorkloadVM %(workload_vm_id)s could not be found.")
    
class SnapshotsOfHostNotFound(NotFound):
    message = _("Snapshots for host: %(host)s could not be found.")


class SnapshotsNotFound(NotFound):
    message = _("Snapshots could not be found.") 

class SnapshotsOfWorkloadNotFound(NotFound):
    message = _("Snapshots of %(workload_id)s could not be found.") 
        
class SnapshotNotFound(NotFound):
    message = _("Snapshot %(snapshot_id)s could not be found.") 

class SnapshotVMsNotFound(NotFound):
    message = _("SnapshotVMs of %(snapshot_id)s could not be found.")
        
class SnapshotVMNotFound(NotFound):
    message = _("SnapshotVM %(snapshot_vm_id)s could not be found.")        

class SnapshotResourcesNotFound(NotFound):
    message = _("Snapshot Resources of %(snapshot_id)s could not be found.")  
    
class SnapshotVMResourcesNotFound(NotFound):
    message = _("SnapshotVMResources of VM %(snapshot_vm_id)s Snapshot %(snapshot_id)s could not be found.")

class SnapshotVMResourceNotFound(NotFound):
    message = _("SnapshotVMResource %(snapshot_vm_resource_id)s could not be found.")
    
class SnapshotVMResourceWithNameNotFound(NotFound):
    message = _("SnapshotVMResource %(resource_name)s of VM %(snapshot_vm_id)s Snapshot %(snapshot_id)s could not be found.")

class SnapshotVMResourceWithPITNotFound(NotFound):
    message = _("SnapshotVMResource %(resource_pit_id)s of VM %(snapshot_vm_id)s Snapshot %(snapshot_id)s could not be found.")

class VMDiskResourceSnapsNotFound(NotFound):
    message = _("VMDiskResourceSnaps of SnapshotVMResource %(snapshot_vm_resource_id)s could not be found.")

class VMDiskResourceSnapNotFound(NotFound):
    message = _("VMDiskResourceSnap %(vm_disk_resource_snap_id)s could not be found.")

class VMDiskResourceSnapTopNotFound(NotFound):
    message = _("Top VMDiskResourceSnap of Snapshot VM Resource %(snapshot_vm_resource_id)s could not be found.")

class VMNetworkResourceSnapsNotFound(NotFound):
    message = _("VMNetworkResourceSnaps of SnapshotVMResource %(snapshot_vm_resource_id)s could not be found.")

class VMNetworkResourceSnapNotFound(NotFound):
    message = _("VMNetworkResourceSnap %(vm_network_resource_snap_id)s could not be found.")


class VMSecurityGroupRuleSnapsNotFound(NotFound):
    message = _("VMSecurityGroupRuleSnaps of VMSecurityGroupSnap %(vm_security_group_snap_id)s could not be found.")

class VMSecurityGroupRuleSnapNotFound(NotFound):
    message = _("VMSecurityGroupRuleSnap %(vm_security_group_rule_snap_id)s of VMSecurityGroup %(vm_security_group_snap_id)could not be found.")


class RestoresNotFound(NotFound):
    message = _("Restores could not be found.") 

class RestoresOfSnapshotNotFound(NotFound):
    message = _("Restores of %(snapshot_id)s could not be found.") 
        
class RestoreNotFound(NotFound):
    message = _("Restore %(restore_id)s could not be found.") 

class RestoredVMsNotFound(NotFound):
    message = _("RestoredVMs of %(restore_id)s could not be found.")
        
class RestoredVMNotFound(NotFound):
    message = _("RestoredVM %(restored_vm_id)s could not be found.")

class RestoredResourcesNotFound(NotFound):
    message = _("Restored Resources of %(restore_id)s could not be found.")  
    
class RestoredVMResourcesNotFound(NotFound):
    message = _("RestoredVMResources of VM %(restore_vm_id)s Restore %(restore_id)s could not be found.")

class RestoredVMResourceNotFound(NotFound):
    message = _("RestoredVMResource %(restore_vm_resource_id)s could not be found.")

class RestoredVMResourceWithNameNotFound(NotFound):
    message = _("RestoredVMResource %(resource_name)s of VM %(restore_vm_id)s Restore %(restore_id)s could not be found.")

class RestoredVMResourceWithIdNotFound(NotFound):
    message = _("RestoredVMResource %(id)s is not be found.")

    
class SwiftConnectionFailed(WorkloadMgrException):
    message = _("Connection to swift failed") + ": %(reason)s"

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
    
class SettingNotFound(NotFound):
    message = _("Setting %(setting_name)s could not be found.") 
    
class VaultStorageNotFound(NotFound):
    message = _("VaultStoreage %(vault_storage_id)s could not be found.")         

class TaskNotFound(NotFound):
    message = _("Task %(task_id)s could not be found.")

class InvalidLicense(Invalid):
    pass

class InternalError(Invalid):
    pass

class TransferNotFound(NotFound):
    message = _("Transfer %(transfer_id)s could not be found.")

class TransferNotAllowed(Invalid):
    message = _("Transfer %(workload_id)s is not allowed within the same cloud.")

class MediaNotSupported(Invalid):
    message = _("Transfer %(media)s is not allowed within the same cloud.")

class BackupTargetOffline(Invalid):
    message = _("Backup %(endpoint)s is offline. Cannot be accessed")

class InvalidNFSMountPoint(Invalid):
    pass

class ProjectNotFound(NotFound):
    message = _("Project %(project_id)s could not be found.")

class UserNotFound(NotFound):
    message = _("User %(user_id)s could not be found.")

class RoleNotFound(NotFound):
    message = _("User %(user_id)s does not have role '%(role_name)s' on "
                "project %(project_id)s")

class ConfigWorkload(WorkloadMgrException):
    message = _("%(message)")

class ConfigWorkloadNotFound(NotFound):
    message = _("Config Workload %(id)s could not be found.")

class ConfigBackupNotFound(NotFound):
    message = _("Config backup %(backup_id)s could not be found.")
