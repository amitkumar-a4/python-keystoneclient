# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""
SQLAlchemy models for workloadmgr data.
"""
from datetime import datetime, timedelta
from sqlalchemy import Column, Integer, BigInteger, String, Text, schema, UniqueConstraint, Interval
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import ForeignKey, DateTime, Boolean
from sqlalchemy.orm import relationship, backref, object_mapper

from workloadmgr.db.sqlalchemy.session import get_session

from workloadmgr import exception
from workloadmgr import flags
from workloadmgr.openstack.common import timeutils
from workloadmgr.vault import vault


FLAGS = flags.FLAGS
BASE = declarative_base()


DB_VERSION = '2.6.4'


class WorkloadsBase(object):
    """Base class for Workloads Models."""
    __table_args__ = {'mysql_engine': 'InnoDB'}
    __table_initialized__ = False
    created_at = Column(DateTime, default=timeutils.utcnow)
    updated_at = Column(DateTime, onupdate=timeutils.utcnow)
    deleted_at = Column(DateTime)
    deleted = Column(Boolean, default=False)
    version = Column(String(255), default=DB_VERSION)
    metadata = None

    def save(self, session=None):
        """Save this object."""
        if not session:
            session = get_session()
        session.add(self)
        try:
            session.flush()
        except IntegrityError as e:
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

    def purge(self, session=None):
        """Save this object."""
        if not session:
            session = get_session()
        session.add(self)
        try:
            session.delete(self)
            session.flush()
        except BaseException:
            raise


class Service(BASE, WorkloadsBase):
    """Represents a running service on a host."""

    __tablename__ = 'services'
    __table_args__ = (UniqueConstraint('host', 'topic', 'binary'), {})
    id = Column(Integer, primary_key=True)
    host = Column(String(255))  # , ForeignKey('hosts.id'))
    ip_addresses = Column(String(255))
    binary = Column(String(255))
    topic = Column(String(255))
    report_count = Column(Integer, nullable=False, default=0)
    disabled = Column(Boolean, default=False)
    availability_zone = Column(String(255), default='workloadmgr')


class WorkloadsNode(BASE, WorkloadsBase):
    """Represents a running workloadmgr service on a host."""

    __tablename__ = 'workloadmgr_nodes'
    id = Column(Integer, primary_key=True)
    service_id = Column(Integer, ForeignKey('services.id'), nullable=True)


class VaultStorages(BASE, WorkloadsBase):
    """Represents a vault storages."""

    __tablename__ = 'vault_storages'
    id = Column(String(255), primary_key=True)

    @property
    def name(self):
        return FLAGS.workload_name_template % self.id

    user_id = Column(String(255), nullable=False)
    project_id = Column(String(255), nullable=False)

    type = Column(String(255), nullable=False)
    display_name = Column(String(255))
    display_description = Column(String(255))
    capacity = Column(BigInteger)
    used = Column(BigInteger)
    status = Column(String(32), nullable=False)


class VaultStorageMetadata(BASE, WorkloadsBase):
    """Represents  metadata for vault storage"""
    __tablename__ = 'vault_storage_metadata'
    __table_args__ = (UniqueConstraint('vault_storage_id', 'key'), {})

    id = Column(Integer, primary_key=True)
    vault_storage_id = Column(
        String(255),
        ForeignKey('vault_storages.id'),
        nullable=False)
    vault_storage = relationship(VaultStorages, backref=backref('metadata'))
    key = Column(String(255), index=True, nullable=False)
    value = Column(Text)


class FileSearch(BASE, WorkloadsBase):
    """Types of workloads"""
    __tablename__ = 'file_search'
    id = Column(Integer, primary_key=True)

    @property
    def name(self):
        return FLAGS.workload_name_template % self.id

    vm_id = Column(String(100), nullable=False)
    project_id = Column(String(255), nullable=False)
    user_id = Column(String(255), nullable=False)
    filepath = Column(String(255), nullable=False)
    snapshot_ids = Column(Text)
    json_resp = Column(Text)
    start = Column(Integer)
    end = Column(Integer)
    date_from = Column(String(50))
    date_to = Column(String(50))
    host = Column(String(100))
    error_msg = Column(String(255))
    status = Column(String(10))
    scheduled_at = Column(DateTime)


class WorkloadTypes(BASE, WorkloadsBase):
    """Types of workloads"""
    __tablename__ = 'workload_types'
    id = Column(String(36), primary_key=True)

    @property
    def name(self):
        return FLAGS.workload_name_template % self.id

    user_id = Column(String(255), nullable=False)
    project_id = Column(String(255), nullable=False)

    display_name = Column(String(255))
    display_description = Column(String(255))
    is_public = Column(Boolean)
    status = Column(String(255))


class WorkloadTypeMetadata(BASE, WorkloadsBase):
    """Represents  metadata for the workload type"""
    __tablename__ = 'workload_type_metadata'
    __table_args__ = (UniqueConstraint('workload_type_id', 'key'), {})

    id = Column(Integer, primary_key=True)
    workload_type_id = Column(
        String(36),
        ForeignKey('workload_types.id'),
        nullable=False)
    workload_type = relationship(WorkloadTypes, backref=backref('metadata'))
    key = Column(String(255), index=True, nullable=False)
    value = Column(Text)


class Workloads(BASE, WorkloadsBase):
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
    environment = String(36)
    workload_type_id = Column(String(255), ForeignKey('workload_types.id'))
    error_msg = Column(String(4096))
    source_platform = Column(String(255))
    jobschedule = Column(String(4096))
    vault_storage_id = Column(String(255), ForeignKey('vault_storages.id'))
    status = Column(String(255))


class WorkloadMetadata(BASE, WorkloadsBase):
    """Represents  metadata for the workload"""
    __tablename__ = 'workload_metadata'
    __table_args__ = (UniqueConstraint('workload_id', 'key'), {})

    id = Column(String(255), primary_key=True)
    workload_id = Column(
        String(36),
        ForeignKey('workloads.id'),
        nullable=False)
    workload = relationship(Workloads, backref=backref('metadata'))
    key = Column(String(255), index=True, nullable=False)
    value = Column(Text)


class WorkloadVMs(BASE, WorkloadsBase):
    """Represents vms of a workload"""
    __tablename__ = str('workload_vms')
    id = Column(String(255), primary_key=True)

    @property
    def name(self):
        return FLAGS.workload_name_template % self.id

    vm_id = Column(String(255))
    vm_name = Column(String(255))
    workload_id = Column(String(255), ForeignKey('workloads.id'))
    status = Column(String(255), nullable=False)


class WorkloadVMMetadata(BASE, WorkloadsBase):
    """Represents  metadata for the workload vm"""
    __tablename__ = 'workload_vm_metadata'
    __table_args__ = (UniqueConstraint('workload_vm_id', 'key'), {})

    id = Column(String(255), primary_key=True)
    workload_vm_id = Column(
        String(36),
        ForeignKey('workload_vms.id'),
        nullable=False)
    workload_vm = relationship(WorkloadVMs, backref=backref('metadata'))
    key = Column(String(255), index=True, nullable=False)
    value = Column(Text)


class ScheduledJobs(BASE, WorkloadsBase):
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
    func_ref = Column(String(1024))
    args = Column(String(1024))
    kwargs = Column(String(1024))
    coalesce = Column(Boolean)


class Snapshots(BASE, WorkloadsBase):
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
    display_name = Column(String(255))
    display_description = Column(String(255))
    size = Column(BigInteger)
    restore_size = Column(BigInteger)
    uploaded_size = Column(BigInteger)
    progress_percent = Column(Integer)
    progress_msg = Column(String(255))
    warning_msg = Column(String(4096))
    error_msg = Column(String(4096))
    host = Column(String(255))
    finished_at = Column(DateTime)
    data_deleted = Column(Boolean, default=False)
    pinned = Column(Boolean, default=False)
    time_taken = Column(BigInteger, default=0)
    vault_storage_id = Column(String(255), ForeignKey('vault_storages.id'))
    status = Column(String(32), nullable=False)


class SnapshotMetadata(BASE, WorkloadsBase):
    """Represents  metadata for the snapshot"""
    __tablename__ = 'snapshot_metadata'
    __table_args__ = (UniqueConstraint('snapshot_id', 'key'), {})

    id = Column(String(255), primary_key=True)
    snapshot_id = Column(
        String(36),
        ForeignKey('snapshots.id'),
        nullable=False)
    snapshot = relationship(Snapshots, backref=backref('metadata'))
    key = Column(String(255), index=True, nullable=False)
    value = Column(Text)


class SnapshotVMs(BASE, WorkloadsBase):
    """Represents vms of a workload snapshot"""
    __tablename__ = str('snapshot_vms')
    id = Column(String(255), primary_key=True)

    @property
    def name(self):
        return FLAGS.workload_name_template % self.id

    vm_id = Column(String(255))
    vm_name = Column(String(255))
    snapshot_id = Column(String(255), ForeignKey('snapshots.id'))
    size = Column(BigInteger)
    restore_size = Column(BigInteger)
    snapshot_type = Column(String(32))
    finished_at = Column(DateTime)
    status = Column(String(32), nullable=False)


class SnapshotVMMetadata(BASE, WorkloadsBase):
    """Represents  metadata for the snapshot vm"""
    __tablename__ = 'snapshot_vm_metadata'
    __table_args__ = (UniqueConstraint('snapshot_vm_id', 'key'), {})

    id = Column(String(255), primary_key=True)
    snapshot_vm_id = Column(
        String(36),
        ForeignKey('snapshot_vms.id'),
        nullable=False)
    snapshot_vm = relationship(SnapshotVMs, backref=backref('metadata'))
    key = Column(String(255), index=True, nullable=False)
    value = Column(Text)


class VMRecentSnapshot(BASE, WorkloadsBase):
    """Represents most recent successful snapshot of a VM"""
    __tablename__ = str('vm_recent_snapshot')

    vm_id = Column(String(255), primary_key=True)

    @property
    def name(self):
        return FLAGS.workload_name_template % self.vm_id

    snapshot_id = Column(String(255), ForeignKey('snapshots.id'))


class SnapshotVMResources(BASE, WorkloadsBase):
    """Represents vm resources of a workload"""
    __tablename__ = str('snapshot_vm_resources')
    id = Column(String(255), primary_key=True)

    @property
    def name(self):
        return FLAGS.workload_name_template % self.id

    vm_id = Column(String(255))
    snapshot_id = Column(String(255), ForeignKey('snapshots.id'))
    resource_type = Column(String(255))  # disk, network, definition
    resource_name = Column(String(255))  # vda etc.
    # resource point in time id (id at the time of snapshot)
    resource_pit_id = Column(String(255))
    size = Column(BigInteger)
    restore_size = Column(BigInteger)
    snapshot_type = Column(String(32))
    finished_at = Column(DateTime)
    data_deleted = Column(Boolean, default=False)
    time_taken = Column(BigInteger, default=0)
    status = Column(String(32), nullable=False)


class SnapshotVMResourceMetadata(BASE, WorkloadsBase):
    """Represents  metadata for the snapshot of a VM Resource"""
    __tablename__ = 'snapshot_vm_resource_metadata'
    __table_args__ = (UniqueConstraint('snapshot_vm_resource_id', 'key'), {})

    id = Column(String(255), primary_key=True)
    snapshot_vm_resource_id = Column(
        String(36),
        ForeignKey('snapshot_vm_resources.id'),
        nullable=False)
    snapshot_vm_resource = relationship(
        SnapshotVMResources, backref=backref('metadata'))
    key = Column(String(255), index=True, nullable=False)
    value = Column(Text)


class VMDiskResourceSnaps(BASE, WorkloadsBase):
    """Represents the snapshot of a VM Resource"""
    __tablename__ = str('vm_disk_resource_snaps')
    id = Column(String(255), primary_key=True)

    @property
    def name(self):
        return FLAGS.workload_name_template % self.id

    snapshot_vm_resource_id = Column(
        String(255), ForeignKey('snapshot_vm_resources.id'))
    vm_disk_resource_snap_backing_id = Column(String(255))
    vm_disk_resource_snap_child_id = Column(String(255))
    top = Column(Boolean, default=False)
    vault_url = Column(String(4096))
    vault_metadata = Column(String(4096))
    size = Column(BigInteger)
    restore_size = Column(BigInteger)
    finished_at = Column(DateTime)
    data_deleted = Column(Boolean, default=False)
    time_taken = Column(BigInteger, default=0)
    status = Column(String(32), nullable=False)


class VMDiskResourceSnapMetadata(BASE, WorkloadsBase):
    """Represents  metadata for the snapshot of a VM Resource"""
    __tablename__ = 'vm_disk_resource_snap_metadata'
    __table_args__ = (UniqueConstraint('vm_disk_resource_snap_id', 'key'), {})

    id = Column(String(255), primary_key=True)
    vm_disk_resource_snap_id = Column(
        String(36),
        ForeignKey('vm_disk_resource_snaps.id'),
        nullable=False)
    vm_disk_resource_snap = relationship(
        VMDiskResourceSnaps, backref=backref('metadata'))
    key = Column(String(255), index=True, nullable=False)
    value = Column(Text)


class VMNetworkResourceSnaps(BASE, WorkloadsBase):
    """Represents the  snapshots of a VM Network Resource"""
    __tablename__ = str('vm_network_resource_snaps')
    vm_network_resource_snap_id = Column(
        String(255),
        ForeignKey('snapshot_vm_resources.id'),
        primary_key=True)

    @property
    def name(self):
        return FLAGS.workload_name_template % self.id

    pickle = Column(String(65535))
    status = Column(String(32), nullable=False)


class VMNetworkResourceSnapMetadata(BASE, WorkloadsBase):
    """Represents  metadata for the snapshot of a VM Network Resource"""
    __tablename__ = 'vm_network_resource_snap_metadata'
    __table_args__ = (
        UniqueConstraint(
            'vm_network_resource_snap_id',
            'key'),
        {})

    id = Column(String(255), primary_key=True)
    vm_network_resource_snap_id = Column(String(36), ForeignKey(
        'vm_network_resource_snaps.vm_network_resource_snap_id'), nullable=False)
    vm_network_resource_snap = relationship(
        VMNetworkResourceSnaps, backref=backref('metadata'))
    key = Column(String(255), index=True, nullable=False)
    value = Column(Text)


class VMSecurityGroupRuleSnaps(BASE, WorkloadsBase):
    """Represents the  snapshots of a VM Security Group Rules"""
    __tablename__ = str('vm_security_group_rule_snaps')
    id = Column(String(255), primary_key=True)
    vm_security_group_snap_id = Column(
        String(255),
        ForeignKey('snapshot_vm_resources.id'),
        primary_key=True)

    @property
    def name(self):
        return FLAGS.workload_name_template % self.id

    pickle = Column(String(65535))
    status = Column(String(32), nullable=False)


class VMSecurityGroupRuleSnapMetadata(BASE, WorkloadsBase):
    """Represents  metadata for the snapshot of a VM Security Group Rule"""
    __tablename__ = 'vm_security_group_rule_snap_metadata'
    __table_args__ = (
        UniqueConstraint(
            'vm_security_group_rule_snap_id',
            'key'),
        {})

    id = Column(String(255), primary_key=True)
    vm_security_group_rule_snap_id = Column(String(36), ForeignKey(
        'vm_security_group_rule_snaps.id'), nullable=False)
    vm_security_group_rule_snap = relationship(
        VMSecurityGroupRuleSnaps, backref=backref('metadata'))
    key = Column(String(255), index=True, nullable=False)
    value = Column(Text)


class Restores(BASE, WorkloadsBase):
    """Represents a restore of a workload snapshots."""

    __tablename__ = 'restores'
    id = Column(String(255), primary_key=True)

    @property
    def name(self):
        return FLAGS.workload_name_template % self.id

    user_id = Column(String(255), nullable=False)
    project_id = Column(String(255), nullable=False)

    snapshot_id = Column(String(255), ForeignKey('snapshots.id'))
    restore_type = Column(String(32), nullable=False)
    display_name = Column(String(255))
    display_description = Column(String(255))
    pickle = Column(String(65535))
    size = Column(BigInteger)
    uploaded_size = Column(BigInteger)
    progress_percent = Column(Integer)
    progress_msg = Column(String(255))
    warning_msg = Column(String(4096))
    error_msg = Column(String(4096))
    host = Column(String(255))
    target_platform = Column(String(255))
    finished_at = Column(DateTime)
    time_taken = Column(BigInteger, default=0)
    status = Column(String(32), nullable=False)


class RestoreMetadata(BASE, WorkloadsBase):
    """Represents  metadata for the restore"""
    __tablename__ = 'restore_metadata'
    __table_args__ = (UniqueConstraint('restore_id', 'key'), {})

    id = Column(Integer, primary_key=True)
    restore_id = Column(String(36), ForeignKey('restores.id'), nullable=False)
    restore = relationship(Restores, backref=backref('metadata'))
    key = Column(String(255), index=True, nullable=False)
    value = Column(Text)


class RestoredVMs(BASE, WorkloadsBase):
    """Represents restored vms of a workload snapshot"""
    __tablename__ = str('restored_vms')
    id = Column(String(255), primary_key=True)

    @property
    def name(self):
        return FLAGS.workload_name_template % self.id

    vm_id = Column(String(255))
    vm_name = Column(String(255))
    restore_id = Column(String(255), ForeignKey('restores.id'))
    size = Column(BigInteger)
    restore_type = Column(String(32))
    finished_at = Column(DateTime)
    status = Column(String(32), nullable=False)


class RestoredVMMetadata(BASE, WorkloadsBase):
    """Represents  metadata for the restored vm"""
    __tablename__ = 'restored_vm_metadata'
    __table_args__ = (UniqueConstraint('restored_vm_id', 'key'), {})

    id = Column(Integer, primary_key=True)
    restored_vm_id = Column(
        String(36),
        ForeignKey('restored_vms.id'),
        nullable=False)
    restored_vm = relationship(RestoredVMs, backref=backref('metadata'))
    key = Column(String(255), index=True, nullable=False)
    value = Column(Text)


class RestoredVMResources(BASE, WorkloadsBase):
    """Represents vm resources of a restored snapshot"""
    __tablename__ = str('restored_vm_resources')
    id = Column(String(255), primary_key=True)

    @property
    def name(self):
        return FLAGS.workload_name_template % self.id

    vm_id = Column(String(255))
    restore_id = Column(String(255), ForeignKey('restores.id'))
    resource_type = Column(String(255))  # disk, network, definition
    resource_name = Column(String(255))  # vda etc.
    finished_at = Column(DateTime)
    status = Column(String(32), nullable=False)


class RestoredVMResourceMetadata(BASE, WorkloadsBase):
    """Represents  metadata for the restore of a VM Resource"""
    __tablename__ = 'restored_vm_resource_metadata'
    __table_args__ = (UniqueConstraint('restored_vm_resource_id', 'key'), {})

    id = Column(Integer, primary_key=True)
    restored_vm_resource_id = Column(
        String(36),
        ForeignKey('restored_vm_resources.id'),
        nullable=False)
    restored_vm_resource = relationship(
        RestoredVMResources, backref=backref('metadata'))
    key = Column(String(255), index=True, nullable=False)
    value = Column(Text)


class Tasks(BASE, WorkloadsBase):
    """Represents Tasks"""
    __tablename__ = str('tasks')
    id = Column(String(255), primary_key=True)

    display_name = Column(String(255))
    display_description = Column(String(255))
    finished_at = Column(DateTime)
    result = Column(String(65535))
    status = Column(String(32), nullable=False)


class TaskStatusMessages(BASE, WorkloadsBase):
    """Represents  messages for the task"""
    __tablename__ = 'task_status_messages'

    id = Column(Integer, primary_key=True)
    task_id = Column(String(36), ForeignKey('tasks.id'), nullable=False)
    task = relationship(Tasks, backref=backref('status_messages'))
    status_message = Column(Text)


class Settings(BASE, WorkloadsBase):
    """Represents configurable settings."""

    __tablename__ = 'settings'
    name = Column(String(255), primary_key=True, nullable=False)
    project_id = Column(String(255), primary_key=True, nullable=False)

    user_id = Column(String(255), nullable=False)
    value = Column(Text)
    description = Column(String(255))
    category = Column(String(32))
    type = Column(String(32))
    public = Column(Boolean, default=False)
    hidden = Column(Boolean, default=False)
    status = Column(String(32), nullable=False)


class SettingMetadata(BASE, WorkloadsBase):
    """Setting  metadata"""
    __tablename__ = 'setting_metadata'
    __table_args__ = (
        UniqueConstraint(
            'settings_name',
            'settings_project_id',
            'key'),
        {})

    id = Column(Integer, primary_key=True)
    settings_name = Column(
        String(255),
        ForeignKey('settings.name'),
        nullable=False)
    settings_project_id = Column(String(255), nullable=False)
    settings = relationship(
        Settings, backref=backref(
            'metadata', cascade="all, delete-orphan"))
    key = Column(String(255), index=True, nullable=False)
    value = Column(Text)


class ConfigWorkloads(BASE, WorkloadsBase):
    """Represents a config workload object."""
    __tablename__ = 'config_workloads'

    id = Column(String(255), primary_key=True)
    user_id = Column(String(255), nullable=False)
    project_id = Column(String(255), nullable=False)
    status = Column(String(255))
    jobschedule = Column(String(4096))
    host = Column(String(255))
    backup_media_target = Column(String(2046))
    error_msg = Column(String(4096))


class ConfigWorkloadMetadata(BASE, WorkloadsBase):
    """Represents metadata for the config workload"""
    __tablename__ = 'config_workload_metadata'
    __table_args__ = (UniqueConstraint('config_workload_id', 'key'), {})

    id = Column(String(255), primary_key=True)
    config_workload_id = Column(
        String(255),
        ForeignKey('config_workloads.id'),
        nullable=False)
    config_workload = relationship(
        ConfigWorkloads, backref=backref('metadata'))
    key = Column(String(255), index=True, nullable=False)
    value = Column(Text)


class ConfigBackups(BASE, WorkloadsBase):
    """Represents a configuration backup object."""
    __tablename__ = 'config_backups'
    id = Column(String(255), primary_key=True)
    user_id = Column(String(255), nullable=False)
    project_id = Column(String(255), nullable=False)
    finished_at = Column(DateTime)
    config_workload_id = Column(
        String(255),
        ForeignKey('config_workloads.id'),
        nullable=False)
    display_name = Column(String(255))
    display_description = Column(String(255))
    size = Column(BigInteger)
    host = Column(String(255))
    progress_msg = Column(String(255))
    warning_msg = Column(String(4096))
    error_msg = Column(String(4096))
    time_taken = Column(BigInteger, default=0)
    vault_storage_path = Column(String(4096))
    scheduled_at = Column(DateTime)
    status = Column(String(255), nullable=False)
    data_deleted = Column(Boolean, default=False)


class ConfigBackupMetadata(BASE, WorkloadsBase):
    """Represents  metadata for the config backup"""
    __tablename__ = 'config_backup_metadata'
    __table_args__ = (UniqueConstraint('config_backup_id', 'key'), {})

    id = Column(String(255), primary_key=True)
    config_backup_id = Column(
        String(255),
        ForeignKey('config_backups.id'),
        nullable=False)
    config_backup = relationship(ConfigBackups, backref=backref('metadata'))
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
              VaultStorages,
              VaultStorageMetadata,
              WorkloadTypes,
              WorkloadTypeMetadata,
              Workloads,
              WorkloadMetadata,
              WorkloadVMs,
              WorkloadVMMetadata,
              ScheduledJobs,
              Snapshots,
              SnapshotVMs,
              SnapshotVMMetadata,
              SnapshotVMResources,
              SnapshotVMResourceMetadata,
              VMDiskResourceSnaps,
              VMDiskResourceSnapMetadata,
              VMNetworkResourceSnaps,
              VMNetworkResourceSnapMetadata,
              VMSecurityGroupRuleSnaps,
              VMSecurityGroupRuleSnapMetadata,
              Restores,
              RestoreMetadata,
              RestoredVMs,
              RestoredVMMetadata,
              RestoredVMResources,
              RestoredVMResourceMetadata,
              Tasks,
              TaskStatusMessages,
              Settings,
              SettingMetadata,
              ConfigWorkloads,
              ConfigWorkloadMetadata,
              ConfigBackups,
              ConfigBackupMetadata,
              )
    engine = create_engine(FLAGS.sql_connection, echo=False)
    for model in models:
        model.metadata.create_all(engine)
