# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Text
from sqlalchemy import Integer, MetaData, String, Table, UniqueConstraint
import sqlalchemy

import pickle
from workloadmgr import flags
from workloadmgr.openstack.common import log as logging

FLAGS = flags.FLAGS

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    #pickle_coltype = PickleType(pickle.HIGHEST_PROTOCOL)

    services = Table(
        'services', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('host', String(length=255)),
        Column('binary', String(length=255)),
        Column('topic', String(length=255)),
        Column('report_count', Integer, nullable=False),
        Column('disabled', Boolean),
        Column('availability_zone', String(length=255)),
        mysql_engine='InnoDB'
    )

       
    workloads = Table(
        'workloads', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', String(length=255), primary_key=True, nullable=False),
        Column('user_id', String(length=255)),
        Column('project_id', String(length=255)),
        Column('host', String(length=255)),
        Column('availability_zone', String(length=255)),
        Column('display_name', String(length=255)),
        Column('display_description', String(length=255)),
        Column('vault_service', String(length=255)),
        Column('status', String(length=255)),
        mysql_engine='InnoDB'
    )
  
    workload_vms = Table(
        'workload_vms', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', String(length=255), primary_key=True, nullable= False),
        Column('vm_id', String(length=255), nullable= False),
        Column('vm_name', String(length=255), nullable= False),
        Column('workload_id', String(length=255), ForeignKey('workloads.id')),
        mysql_engine='InnoDB'
    )

    scheduled_jobs = Table(
        'scheduled_jobs', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', String(length=255), primary_key=True),
        Column('workload_id', String(length=255), ForeignKey('workloads.id')),
        Column('trigger', String(length=4096), nullable=False),
        Column('func_ref', String(length=1024), nullable=False),
        Column('args', String(length=1024), nullable=False),
        Column('kwargs', String(length=1024), nullable=False),
        Column('name', String(length=1024)),
        Column('misfire_grace_time', Integer, nullable=False),
        Column('coalesce', Boolean, nullable=False),
        Column('max_runs', Integer),
        Column('max_instances', Integer),
        Column('next_run_time', DateTime, nullable=False),
        Column('runs', Integer), mysql_engine='InnoDB')
        
    snapshots = Table(
        'snapshots', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', String(length=255), primary_key=True, nullable= False),
        Column('workload_id', String(length=255), ForeignKey('workloads.id')),
        Column('user_id', String(length=255)),
        Column('project_id', String(length=255)),
        Column('snapshot_type', String(length=32), primary_key=False, nullable= False),
        Column('status', String(length=32), nullable=False),
        mysql_engine='InnoDB'
    )
    
    snapshot_vms = Table(
        'snapshot_vms', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', String(length=255), primary_key=True, nullable= False),
        Column('vm_id', String(length=255), nullable= False),
        Column('vm_name', String(length=255), nullable= False),
        Column('snapshot_id', String(length=255), ForeignKey('snapshots.id')),
        Column('status', String(length=32), nullable=False),
        mysql_engine='InnoDB'
    )
    
    vm_recent_snapshot  = Table(
        'vm_recent_snapshot', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('vm_id', String(length=255), primary_key=True, nullable= False),
        Column('snapshot_id', String(length=255), ForeignKey('snapshots.id')),
        mysql_engine='InnoDB'
    )    
    
    snapshot_vm_resources = Table(
        'snapshot_vm_resources', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', String(length=255), primary_key=True, nullable= False),
        Column('vm_id', String(length=255), nullable= False),
        Column('snapshot_id', String(length=255), ForeignKey('snapshots.id')),
        Column('resource_type', String(length=255)),
        Column('resource_name', String(length=255)),
        Column('resource_pit_id', String(length=255)),                
        Column('status', String(length=32), nullable=False),
        UniqueConstraint('vm_id', 'snapshot_id', 'resource_name'),
        mysql_engine='InnoDB'
    )
    
    snapshot_vm_resource_metadata = Table(
        'snapshot_vm_resource_metadata', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', String(length=255), primary_key=True, nullable= False),
        Column('snapshot_vm_resource_id', String(length=255), ForeignKey('snapshot_vm_resources.id'),nullable=False,index=True),        
        Column('key', String(255), nullable=False),
        Column('value', Text()),
        UniqueConstraint('snapshot_vm_resource_id', 'key'),
        mysql_engine='InnoDB'
    )            
    
    vm_disk_resource_snaps = Table(
        'vm_disk_resource_snaps', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', String(length=255), primary_key=True, nullable= False),
        Column('snapshot_vm_resource_id', String(length=255), ForeignKey('snapshot_vm_resources.id')),
        Column('vm_disk_resource_snap_backing_id', String(length=255), ForeignKey('vm_disk_resource_snaps.id')),
        Column('top', Boolean, default=False),
        Column('vault_service_id', String(255)),
        Column('vault_service_url', String(4096)),    
        Column('vault_service_metadata', String(4096)),         
        Column('status', String(length=32), nullable=False),
        mysql_engine='InnoDB'
    )        
    
    vm_disk_resource_snap_metadata = Table(
        'vm_disk_resource_snap_metadata', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', String(length=255), primary_key=True, nullable= False),
        Column('vm_disk_resource_snap_id', String(length=255), ForeignKey('vm_disk_resource_snaps.id'),nullable=False,index=True),        
        Column('key', String(255), nullable=False),
        Column('value', Text()),
        UniqueConstraint('vm_disk_resource_snap_id', 'key'),
        mysql_engine='InnoDB'
    )        
      
    vm_network_resource_snaps = Table(
        'vm_network_resource_snaps', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('vm_network_resource_snap_id', String(length=255), ForeignKey('snapshot_vm_resources.id'), primary_key=True),
        Column('pickle',String(length=4096)),
        Column('status', String(length=32), nullable=False),
        mysql_engine='InnoDB'
    )        
    
    vm_network_resource_snap_metadata = Table(
        'vm_network_resource_snap_metadata', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', String(length=255), primary_key=True, nullable= False),
        Column('vm_network_resource_snap_id', String(length=255), ForeignKey('vm_network_resource_snaps.vm_network_resource_snap_id'),nullable=False,index=True),        
        Column('key', String(255), nullable=False),
        Column('value', Text()),
        UniqueConstraint('vm_network_resource_snap_id', 'key'),
        mysql_engine='InnoDB'
    ) 
    
    restores = Table(
        'restores', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', String(length=255), primary_key=True, nullable= False),
        Column('snapshot_id', String(length=255), ForeignKey('snapshots.id')),
        Column('user_id', String(length=255)),
        Column('project_id', String(length=255)),
        Column('restore_type', String(length=32), primary_key=False, nullable= False),
        Column('status', String(length=32), nullable=False),
        mysql_engine='InnoDB'
    )
    
    restored_vms = Table(
        'restored_vms', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', String(length=255), primary_key=True, nullable= False),
        Column('vm_id', String(length=255), nullable= False),
        Column('vm_name', String(length=255), nullable= False),
        Column('restore_id', String(length=255), ForeignKey('restores.id')),
        Column('status', String(length=32), nullable=False),
        mysql_engine='InnoDB'
    )
    
   
    restored_vm_resources = Table(
        'restored_vm_resources', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', String(length=255), primary_key=True, nullable= False),
        Column('vm_id', String(length=255), nullable= False),
        Column('restore_id', String(length=255), ForeignKey('restores.id')),
        Column('resource_type', String(length=255)),
        Column('resource_name', String(length=255)),
        Column('status', String(length=32), nullable=False),
        UniqueConstraint('vm_id', 'restore_id', 'resource_name'),
        mysql_engine='InnoDB'
    )
    
    restored_vm_resource_metadata = Table(
        'restored_vm_resource_metadata', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('id', String(length=255), primary_key=True, nullable= False),
        Column('restored_vm_resource_id', String(length=255), ForeignKey('restored_vm_resources.id'),nullable=False,index=True),        
        Column('key', String(255), nullable=False),
        Column('value', Text()),
        UniqueConstraint('restored_vm_resource_id', 'key'),
        mysql_engine='InnoDB'
    )            
   
    # create all tables
    # Take care on create order for those with FK dependencies
    tables = [services,
              workloads,
              workload_vms,
              scheduled_jobs,
              snapshots,
              snapshot_vms,
              vm_recent_snapshot,
              snapshot_vm_resources,
              snapshot_vm_resource_metadata,
              vm_disk_resource_snaps,
              vm_disk_resource_snap_metadata,
              vm_network_resource_snaps,
              vm_network_resource_snap_metadata,
              restores,
              restored_vms,
              restored_vm_resources,
              restored_vm_resource_metadata]

    for table in tables:
        try:
            table.create()
        except Exception:
            LOG.info(repr(table))
            LOG.exception(_('Exception while creating table.'))
            raise

    if migrate_engine.name == "mysql":
        tables = ["services",
                  "workloads",
                  "workload_vms",
                  "scheduled_jobs",
                  "snapshots",
                  "snapshot_vms",
                  "vm_recent_snapshot",
                  "snapshot_vm_resources",
                  "snapshot_vm_resource_metadata",
                  "vm_disk_resource_snaps",
                  "vm_disk_resource_snap_metadata",
                  "vm_network_resource_snaps",
                  "vm_network_resource_snap_metadata",
                  "restores",
                  "restored_vms",
                  "restored_vm_resources",
                  "restored_vm_resource_metadata"]                  

        sql = "SET foreign_key_checks = 0;"
        for table in tables:
            sql += "ALTER TABLE %s CONVERT TO CHARACTER SET utf8;" % table
        sql += "SET foreign_key_checks = 1;"
        sql += "ALTER DATABASE %s DEFAULT CHARACTER SET utf8;" \
            % migrate_engine.url.database
        sql += "ALTER TABLE %s Engine=InnoDB;" % table
        migrate_engine.execute(sql)


def downgrade(migrate_engine):
    LOG.exception(_('Downgrade from initial WorkloadMgr install is unsupported.'))
