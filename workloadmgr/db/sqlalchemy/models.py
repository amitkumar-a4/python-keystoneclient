# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""
SQLAlchemy models for workloadmgr data.
"""

from sqlalchemy import Column, Integer, String, Text, schema, UniqueConstraint
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import ForeignKey, DateTime, Boolean
from sqlalchemy.orm import relationship, backref, object_mapper

from workloadmgr.db.sqlalchemy.session import get_session

from workloadmgr import exception
from workloadmgr import flags
from workloadmgr.openstack.common import timeutils


FLAGS = flags.FLAGS
BASE = declarative_base()


class WorkloadMgrBase(object):
    """Base class for WorkloadMgr Models."""
    __table_args__ = {'mysql_engine': 'InnoDB'}
    __table_initialized__ = False
    created_at = Column(DateTime, default=timeutils.utcnow)
    updated_at = Column(DateTime, onupdate=timeutils.utcnow)
    deleted_at = Column(DateTime)
    deleted = Column(Boolean, default=False)
    metadata = None

    def save(self, raksha = True, session=None):
        """Save this object."""
        if not session:
            session = get_session(raksha)
        session.add(self)
        try:
            session.flush()
        except IntegrityError, e:
            if str(e).endswith('is not unique'):
                raise exception.Duplicate(str(e))
            else:
                raise

    def delete(self, raksha = True, session=None):
        """Delete this object."""
        self.deleted = True
        self.deleted_at = timeutils.utcnow()
        self.save(raksha=raksha, session=session)

    def __setitem__(self, key, value):
        setattr(self, key, value)

    def __getitem__(self, key):
        return getattr(self, key)

    def get(self, key, default=None):
        return getattr(self, key, default)

    def __iter__(self):
        self._i = iter(object_mapper(self).columns)
        return self

    def next(self):
        n = self._i.next().name
        return n, getattr(self, n)

    def update(self, values):
        """Make the model object behave like a dict."""
        for k, v in values.iteritems():
            setattr(self, k, v)

    def iteritems(self):
        """Make the model object behave like a dict.

        Includes attributes from joins."""
        local = dict(self)
        joined = dict([(k, v) for k, v in self.__dict__.iteritems()
                      if not k[0] == '_'])
        local.update(joined)
        return local.iteritems()


class Service(BASE, WorkloadMgrBase):
    """Represents a running service on a host."""

    __tablename__ = 'services'
    id = Column(Integer, primary_key=True)
    host = Column(String(255))  # , ForeignKey('hosts.id'))
    binary = Column(String(255))
    topic = Column(String(255))
    report_count = Column(Integer, nullable=False, default=0)
    disabled = Column(Boolean, default=False)
    availability_zone = Column(String(255), default='workloadmgr')

class VaultServices(BASE, WorkloadMgrBase):
    """Vault service for the backup job"""
    __tablename__ = str('vault_services')
    id = Column(String(255), primary_key=True)

    @property
    def name(self):
        return FLAGS.backup_name_template % self.id

    service_name = Column(String(255))

class WorkloadMgrNode(BASE, WorkloadMgrBase):
    """Represents a running workloadmgr service on a host."""

    __tablename__ = 'workloadmgr_nodes'
    id = Column(Integer, primary_key=True)
    service_id = Column(Integer, ForeignKey('services.id'), nullable=True)


                           
class BackupJob(BASE, WorkloadMgrBase):
    """Represents a backup job of set of VMs."""
    __tablename__ = 'backupjobs'
    id = Column(String(36), primary_key=True)

    @property
    def name(self):
        return FLAGS.backup_name_template % self.id

    user_id = Column(String(255), nullable=False)
    project_id = Column(String(255), nullable=False)

    host = Column(String(255))
    availability_zone = Column(String(255))
    display_name = Column(String(255))
    display_description = Column(String(255))
    vault_service = Column(String(255))
    status = Column(String(255)) 
    

class BackupJobVMs(BASE, WorkloadMgrBase):
    """Represents vms of a backup job"""
    __tablename__ = str('backupjob_vms')
    id = Column(String(255), primary_key=True)

    @property
    def name(self):
        return FLAGS.backup_name_template % self.id

    vm_id = Column(String(255))
    backupjob_id = Column(String(255), ForeignKey('backupjobs.id'))

class ScheduledJobs(BASE, WorkloadMgrBase):
    """Represents a scheduled job"""
    __tablename__ = str('scheduled_jobs')
    id = Column(String(255), primary_key=True)
    backupjob_id = Column(String(255), ForeignKey('backupjobs.id'))
    name = Column(String(1024))
    misfire_grace_time = Column(Integer)
    max_runs = Column(Integer)
    max_instances = Column(Integer)
    next_run_time = Column(DateTime)
    runs = Column(DateTime)
    trigger = Column(String(4096))
    func_ref =  Column(String(1024))
    args = Column(String(1024))
    kwargs = Column(String(1024))
    coalesce = Column(Boolean)

class BackupJobRuns(BASE, WorkloadMgrBase):
    """Represents a backup job instances."""

    __tablename__ = 'backupjobruns'
    id = Column(String(255), primary_key=True)

    @property
    def name(self):
        return FLAGS.backup_name_template % self.id

    user_id = Column(String(255), nullable=False)
    project_id = Column(String(255), nullable=False)
    
    backupjob_id = Column(String(255), ForeignKey('backupjobs.id'))
    backuptype = Column(String(32), nullable=False)
    status =  Column(String(32), nullable=False)

class BackupJobRunVMs(BASE, WorkloadMgrBase):
    """Represents vms of a backup job"""
    __tablename__ = str('backupjobrun_vms')
    id = Column(String(255), primary_key=True)

    @property
    def name(self):
        return FLAGS.backup_name_template % self.id

    vm_id = Column(String(255))
    backupjobrun_id = Column(String(255), ForeignKey('backupjobruns.id'))
    status =  Column(String(32), nullable=False)
    
class VMRecentBackupJobRun(BASE, WorkloadMgrBase):
    """Represents most recent successful backup job run of a VM"""
    __tablename__ = str('vm_recent_backupjobrun')

    vm_id = Column(String(255), primary_key=True)
    @property
    def name(self):
        return FLAGS.backup_name_template % self.vm_id
    
    backupjobrun_id = Column(String(255), ForeignKey('backupjobruns.id'))
    
class BackupJobRunVMResources(BASE, WorkloadMgrBase):
    """Represents vm resoruces of a backup job"""
    __tablename__ = str('backupjobrun_vm_resources')
    id = Column(String(255), primary_key=True)

    @property
    def name(self):
        return FLAGS.backup_name_template % self.id

    vm_id = Column(String(255), ForeignKey('backupjobrun_vms.id'))
    backupjobrun_id = Column(String(255), ForeignKey('backupjobruns.id'))
    resource_type = Column(String(255)) #disk, network, definition
    resource_name = Column(String(4096)) #vda etc.
    status =  Column(String(32), nullable=False)

class VMResourceBackups(BASE, WorkloadMgrBase):
    """Represents the backups of a VM Resource"""
    __tablename__ = str('vm_resource_backups')
    id = Column(String(255), primary_key=True)

    @property
    def name(self):
        return FLAGS.backup_name_template % self.id

    backupjobrun_vm_resource_id = Column(String(255), ForeignKey('backupjobrun_vm_resources.id'))
    vm_resource_backup_backing_id = Column(String(255), ForeignKey('vm_resource_backups.id'))
    top = Column(Boolean, default=False)
    vault_service_id = Column(String(255))
    vault_service_url = Column(String(4096))    
    vault_service_metadata = Column(String(4096))
    status = Column(String(32), nullable=False)    
    status =  Column(String(32), nullable=False)
    
class VMResourceBackupMetadata(BASE, WorkloadMgrBase):
    """Represents  metadata for the backup of a VM Resource"""
    __tablename__ = 'vm_resource_backup_metadata'
    __table_args__ = (UniqueConstraint('vm_resource_backup_id', 'key'), {})

    id = Column(Integer, primary_key=True)
    vm_resource_backup_id = Column(String(36), ForeignKey('vm_resource_backups.id'), nullable=False)
    vm_resource_backup = relationship(VMResourceBackups, backref=backref('metadata'))
    key = Column(String(255), index=True, nullable=False)
    value = Column(Text)
        
def register_models():
    """Register Models and create metadata.

    Called from workloadmgr.db.sqlalchemy.__init__ as part of loading the driver,
    it will never need to be called explicitly elsewhere unless the
    connection is lost and needs to be reestablished.
    """
    from sqlalchemy import create_engine
    models = (Service,
              VaultServices,
              BackupJob,
              BackupJobVMs,
              ScheduledJobs,
              BackupJobRuns,
              BackupJobRunVMs,
              VMResourceBackups,
              VMResourceBackupMetadata
              )
    engine = create_engine(FLAGS.sql_connection, echo=False)
    for model in models:
        model.metadata.create_all(engine)
