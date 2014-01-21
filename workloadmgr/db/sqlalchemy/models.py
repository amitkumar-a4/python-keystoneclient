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

    def save(self, session=None):
        """Save this object."""
        if not session:
            session = get_session()
        session.add(self)
        try:
            session.flush()
        except IntegrityError, e:
            if str(e).endswith('is not unique'):
                raise exception.Duplicate(str(e))
            else:
                raise

    def delete(self, session=None):
        """Delete this object."""
        self.deleted = True
        self.deleted_at = timeutils.utcnow()
        self.save(session=session)

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

class WorkloadMgrNode(BASE, WorkloadMgrBase):
    """Represents a running workloadmgr service on a host."""

    __tablename__ = 'workloadmgr_nodes'
    id = Column(Integer, primary_key=True)
    service_id = Column(Integer, ForeignKey('services.id'), nullable=True)
                          
class WorkloadMgr(BASE, WorkloadMgrBase):
    """Represents a workload of set of VMs."""
    __tablename__ = 'workloads'
    id = Column(String(36), primary_key=True)

    @property
    def name(self):
        return FLAGS.workload_name_template % self.id

    user_id = Column(String(255), nullable=False)
    project_id = Column(String(255), nullable=False)

    host = Column(String(255))
    availability_zone = Column(String(255))
    display_name = Column(String(255))
    display_description = Column(String(255))
    vault_service = Column(String(255))
    status = Column(String(255)) 
    

class WorkloadMgrVMs(BASE, WorkloadMgrBase):
    """Represents vms of a workload"""
    __tablename__ = str('workload_vms')
    id = Column(String(255), primary_key=True)

    @property
    def name(self):
        return FLAGS.workload_name_template % self.id

    vm_id = Column(String(255))
    vm_name = Column(String(255))
    workload_id = Column(String(255), ForeignKey('workloads.id'))

class ScheduledJobs(BASE, WorkloadMgrBase):
    """Represents a scheduled job"""
    __tablename__ = str('scheduled_jobs')
    id = Column(String(255), primary_key=True)
    workload_id = Column(String(255), ForeignKey('workloads.id'))
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

class Snapshots(BASE, WorkloadMgrBase):
    """Represents a workload snapshots."""

    __tablename__ = 'snapshots'
    id = Column(String(255), primary_key=True)

    @property
    def name(self):
        return FLAGS.workload_name_template % self.id

    user_id = Column(String(255), nullable=False)
    project_id = Column(String(255), nullable=False)
    
    workload_id = Column(String(255), ForeignKey('workloads.id'))
    snapshot_type = Column(String(32), nullable=False)
    status =  Column(String(32), nullable=False)

class SnapshotVMs(BASE, WorkloadMgrBase):
    """Represents vms of a workload"""
    __tablename__ = str('snapshot_vms')
    id = Column(String(255), primary_key=True)

    @property
    def name(self):
        return FLAGS.workload_name_template % self.id

    vm_id = Column(String(255))
    vm_name = Column(String(255))
    snapshot_id = Column(String(255), ForeignKey('snapshots.id'))
    status =  Column(String(32), nullable=False)
    
class VMRecentSnapshot(BASE, WorkloadMgrBase):
    """Represents most recent successful snapshot of a VM"""
    __tablename__ = str('vm_recent_snapshot')

    vm_id = Column(String(255), primary_key=True)
    @property
    def name(self):
        return FLAGS.workload_name_template % self.vm_id
    
    snapshot_id = Column(String(255), ForeignKey('snapshots.id'))
    
class SnapshotVMResources(BASE, WorkloadMgrBase):
    """Represents vm resoruces of a workload"""
    __tablename__ = str('snapshot_vm_resources')
    id = Column(String(255), primary_key=True)

    @property
    def name(self):
        return FLAGS.workload_name_template % self.id

    vm_id = Column(String(255))
    snapshot_id = Column(String(255), ForeignKey('snapshots.id'))
    resource_type = Column(String(255)) #disk, network, definition
    resource_name = Column(String(255)) #vda etc.
    resource_pit_id = Column(String(255)) #resource point in time id (id at the time of snapshot)    
    status =  Column(String(32), nullable=False)

class VMDiskResourceSnaps(BASE, WorkloadMgrBase):
    """Represents the snapshot of a VM Resource"""
    __tablename__ = str('vm_disk_resource_snaps')
    id = Column(String(255), primary_key=True)

    @property
    def name(self):
        return FLAGS.workload_name_template % self.id

    snapshot_vm_resource_id = Column(String(255), ForeignKey('snapshot_vm_resources.id'))
    vm_disk_resource_snap_backing_id = Column(String(255), ForeignKey('vm_disk_resource_snaps.id'))
    top = Column(Boolean, default=False)
    vault_service_id = Column(String(255))
    vault_service_url = Column(String(4096))    
    vault_service_metadata = Column(String(4096))
    status = Column(String(32), nullable=False)    
    
class VMDiskResourceSnapMetadata(BASE, WorkloadMgrBase):
    """Represents  metadata for the snapshot of a VM Resource"""
    __tablename__ = 'vm_disk_resource_snap_metadata'
    __table_args__ = (UniqueConstraint('vm_disk_resource_snap_id', 'key'), {})

    id = Column(Integer, primary_key=True)
    vm_disk_resource_snap_id = Column(String(36), ForeignKey('vm_disk_resource_snaps.id'), nullable=False)
    vm_disk_resource_snap = relationship(VMDiskResourceSnaps, backref=backref('metadata'))
    key = Column(String(255), index=True, nullable=False)
    value = Column(Text)
    
class VMNetworkResourceSnaps(BASE, WorkloadMgrBase):
    """Represents the  snapshots of a VM Network Resource"""
    __tablename__ = str('vm_network_resource_snaps')
    vm_network_resource_snap_id = Column(String(255), ForeignKey('snapshot_vm_resources.id'), primary_key=True)

    @property
    def name(self):
        return FLAGS.workload_name_template % self.id

    pickle = Column(String(4096))
    status = Column(String(32), nullable=False)    
    
class VMNetworkResourceSnapMetadata(BASE, WorkloadMgrBase):
    """Represents  metadata for the snapshot of a VM Network Resource"""
    __tablename__ = 'vm_network_resource_snap_metadata'
    __table_args__ = (UniqueConstraint('vm_network_resource_snap_id', 'key'), {})

    id = Column(Integer, primary_key=True)
    vm_network_resource_snap_id = Column(String(36), ForeignKey('vm_network_resource_snaps.vm_network_resource_snap_id'), nullable=False)
    vm_network_resource_snap = relationship(VMNetworkResourceSnaps, backref=backref('metadata'))
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
              WorkloadMgr,
              WorkloadMgrVMs,
              ScheduledJobs,
              Snapshots,
              SnapshotVMs,
              VMDiskResourceSnaps,
              VMDiskResourceSnapMetadata,
              VMNetworkResourceSnaps,
              VMNetworkResourceSnapMetadata
              )
    engine = create_engine(FLAGS.sql_connection, echo=False)
    for model in models:
        model.metadata.create_all(engine)
