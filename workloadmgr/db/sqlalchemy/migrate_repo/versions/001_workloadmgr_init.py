# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

from datetime import datetime, timedelta
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Text 
from sqlalchemy import Integer, BigInteger, MetaData, String, Table, UniqueConstraint
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

    file_search = Table(
        'file_search', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('version', String(length=255)),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('vm_id', String, nullable=False),
        Column('project_id', String, nullable=False),
        Column('user_id', String, nullable=False),
        Column('filepath', String, nullable=False),
        Column('snapshot_ids', Text),
        Column('json_resp', Text),
        Column('start', Integer),
        Column('end', Integer),
        Column('host', String),
        Column('error_msg', String),
        Column('status', String(10)),
        Column('scheduled_at', DateTime),
        mysql_engine='InnoDB'
    )

    services = Table(
        'services', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('version', String(length=255)),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('host', String(length=255)),
        Column('ip_addresses', String(length=255)),        
        Column('binary', String(length=255)),
        Column('topic', String(length=255)),
        Column('report_count', Integer, nullable=False),
        Column('disabled', Boolean),
        Column('availability_zone', String(length=255)),
        mysql_engine='InnoDB'
    )

    vault_storages = Table(
        'vault_storages', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('version', String(length=255)),
        Column('id', String(length=255), primary_key=True, nullable= False),
        Column('user_id', String(length=255)),
        Column('project_id', String(length=255)),
        Column('type', String(length=32), nullable= False),
        Column('display_name', String(length=255)),
        Column('display_description', String(length=255)),
        Column('capacity', BigInteger, nullable=False),
        Column('used', BigInteger, nullable=False),
        Column('status', String(length=32), nullable=False),
        mysql_engine='InnoDB'
    )
    
    vault_storage_metadata = Table(
        'vault_storage_metadata', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('version', String(length=255)),
        Column('id', String(length=255), primary_key=True, nullable= False),
        Column('vault_storage_id', String(length=255), ForeignKey('vault_storages.id'),nullable=False,index=True),        
        Column('key', String(length=255), nullable=False),
        Column('value', Text()),
        UniqueConstraint('vault_storage_id', 'key'),
        mysql_engine='InnoDB'
    )        

    workload_types = Table(
        'workload_types', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('version', String(length=255)),
        Column('id', String(length=255), primary_key=True, nullable=False),
        Column('user_id', String(length=255)),
        Column('project_id', String(length=255)),
        Column('display_name', String(length=255)),
        Column('display_description', String(length=255)),
        Column('is_public', Boolean, default=False),
        Column('status', String(length=255)),        
        mysql_engine='InnoDB'
    )
    
    workload_type_metadata = Table(
        'workload_type_metadata', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('version', String(length=255)),
        Column('id', String(length=255), primary_key=True, nullable= False),
        Column('workload_type_id', String(length=255), ForeignKey('workload_types.id'),nullable=False,index=True),        
        Column('key', String(255), nullable=False),
        Column('value', Text()),
        UniqueConstraint('workload_type_id', 'key'),
        mysql_engine='InnoDB'
    )     
       
    workloads = Table(
        'workloads', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('version', String(length=255)),
        Column('id', String(length=255), primary_key=True, nullable=False),
        Column('user_id', String(length=255)),
        Column('project_id', String(length=255)),
        Column('host', String(length=255)),
        Column('availability_zone', String(length=255)),
        Column('display_name', String(length=255)),
        Column('display_description', String(length=255)),
        Column('source_platform', String(length=255)),
        Column('workload_type_id', String(length=255), ForeignKey('workload_types.id')),
        Column('error_msg', String(length=4096)),
        Column('jobschedule', String(length=4096)),
        Column('vault_storage_id', String(length=255), ForeignKey('vault_storages.id')),
        Column('status', String(length=255)),
        mysql_engine='InnoDB'
    )
    
    workload_metadata = Table(
        'workload_metadata', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('version', String(length=255)),
        Column('id', String(length=255), primary_key=True, nullable= False),
        Column('workload_id', String(length=255), ForeignKey('workloads.id'),nullable=False,index=True),        
        Column('key', String(255), nullable=False),
        Column('value', Text()),
        UniqueConstraint('workload_id', 'key'),
        mysql_engine='InnoDB'
    )     
  
    workload_vms = Table(
        'workload_vms', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('version', String(length=255)),
        Column('id', String(length=255), primary_key=True, nullable= False),
        Column('vm_id', String(length=255), nullable= False),
        Column('vm_name', String(length=255), nullable= False),
        Column('workload_id', String(length=255), ForeignKey('workloads.id')),
        Column('status', String(length=255)),
        mysql_engine='InnoDB'
    )
    
    workload_vm_metadata = Table(
        'workload_vm_metadata', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('version', String(length=255)),
        Column('id', String(length=255), primary_key=True, nullable= False),
        Column('workload_vm_id', String(length=255), ForeignKey('workload_vms.id'),nullable=False,index=True),        
        Column('key', String(255), nullable=False),
        Column('value', Text()),
        UniqueConstraint('workload_vm_id', 'key'),
        mysql_engine='InnoDB'
    )        

    scheduled_jobs = Table(
        'scheduled_jobs', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('version', String(length=255)),
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
        Column('finished_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('version', String(length=255)),
        Column('id', String(length=255), primary_key=True, nullable= False),
        Column('workload_id', String(length=255), ForeignKey('workloads.id')),
        Column('user_id', String(length=255)),
        Column('project_id', String(length=255)),
        Column('snapshot_type', String(length=32), primary_key=False, nullable= False),
        Column('display_name', String(length=255)),
        Column('display_description', String(length=255)),
        Column('size', BigInteger, nullable=False),
        Column('restore_size', BigInteger, nullable=False),
        Column('uploaded_size', BigInteger, nullable=False),  
        Column('progress_percent', Integer, nullable=False),   
        Column('progress_msg', String(length=255)),
        Column('warning_msg', String(length=4096)),
        Column('error_msg', String(length=4096)),
        Column('host', String(length=255)),
        Column('data_deleted', Boolean, default=False),
        Column('pinned', Boolean, default=False),
        Column('time_taken', BigInteger, default=0),
        Column('vault_storage_id', String(length=255), ForeignKey('vault_storages.id')),
        Column('status', String(length=32), nullable=False),
        mysql_engine='InnoDB'
    )
    
    snapshot_metadata = Table(
        'snapshot_metadata', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('version', String(length=255)),
        Column('id', String(length=255), primary_key=True, nullable= False),
        Column('snapshot_id', String(length=255), ForeignKey('snapshots.id'),nullable=False,index=True),        
        Column('key', String(255), nullable=False),
        Column('value', Text()),
        UniqueConstraint('snapshot_id', 'key'),
        mysql_engine='InnoDB'
    )        
    
    snapshot_vms = Table(
        'snapshot_vms', meta,
        Column('created_at', DateTime),
        Column('finished_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('version', String(length=255)),
        Column('id', String(length=255), primary_key=True, nullable= False),
        Column('vm_id', String(length=255), nullable= False),
        Column('vm_name', String(length=255), nullable= False),
        Column('snapshot_id', String(length=255), ForeignKey('snapshots.id')),
        Column('size', BigInteger, nullable=False),
        Column('restore_size', BigInteger, nullable=False),        
        Column('snapshot_type', String(length=32)),        
        Column('status', String(length=32), nullable=False),
        mysql_engine='InnoDB'
    )
    
    snapshot_vm_metadata = Table(
        'snapshot_vm_metadata', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('version', String(length=255)),
        Column('id', String(length=255), primary_key=True, nullable= False),
        Column('snapshot_vm_id', String(length=255), ForeignKey('snapshot_vms.id'),nullable=False,index=True),        
        Column('key', String(255), nullable=False),
        Column('value', Text()),
        UniqueConstraint('snapshot_vm_id', 'key'),
        mysql_engine='InnoDB'
    )            
    
    vm_recent_snapshot  = Table(
        'vm_recent_snapshot', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('version', String(length=255)),
        Column('vm_id', String(length=255), primary_key=True, nullable= False),
        Column('snapshot_id', String(length=255), ForeignKey('snapshots.id')),
        mysql_engine='InnoDB'
    )    
    
    snapshot_vm_resources = Table(
        'snapshot_vm_resources', meta,
        Column('created_at', DateTime),
        Column('finished_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('version', String(length=255)),
        Column('id', String(length=255), primary_key=True, nullable= False),
        Column('vm_id', String(length=255), nullable= False),
        Column('snapshot_id', String(length=255), ForeignKey('snapshots.id')),
        Column('resource_type', String(length=255)),
        Column('resource_name', String(length=255)),
        Column('resource_pit_id', String(length=255)),
        Column('size', BigInteger, nullable=False),
        Column('restore_size', BigInteger, nullable=False),        
        Column('snapshot_type', String(length=32)),        
        Column('data_deleted', Boolean, default=False),
        Column('time_taken', BigInteger, default=0),
        Column('status', String(length=32), nullable=False),
        UniqueConstraint('vm_id', 'snapshot_id', 'resource_name', 'resource_pit_id'),
        mysql_engine='InnoDB'
    )
    
    snapshot_vm_resource_metadata = Table(
        'snapshot_vm_resource_metadata', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('version', String(length=255)),
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
        Column('finished_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('version', String(length=255)),
        Column('id', String(length=255), primary_key=True, nullable= False),
        Column('snapshot_vm_resource_id', String(length=255), ForeignKey('snapshot_vm_resources.id')),
        Column('vm_disk_resource_snap_backing_id', String(length=255)),
        Column('vm_disk_resource_snap_child_id', String(length=255)),
        Column('top', Boolean, default=False),
        Column('vault_url', String(4096)),    
        Column('vault_metadata', String(4096)),
        Column('size', BigInteger, nullable=False),
        Column('restore_size', BigInteger, nullable=False),
        Column('data_deleted', Boolean, default=False),
        Column('time_taken', BigInteger, default=0),
        Column('status', String(length=32), nullable=False),
        mysql_engine='InnoDB'
    )        
    
    vm_disk_resource_snap_metadata = Table(
        'vm_disk_resource_snap_metadata', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('version', String(length=255)),
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
        Column('version', String(length=255)),
        Column('vm_network_resource_snap_id', String(length=255), ForeignKey('snapshot_vm_resources.id'), primary_key=True),
        Column('pickle',String(length=65535)),
        Column('status', String(length=32), nullable=False),
        mysql_engine='InnoDB'
    )        
    
    vm_network_resource_snap_metadata = Table(
        'vm_network_resource_snap_metadata', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('version', String(length=255)),
        Column('id', String(length=255), primary_key=True, nullable= False),
        Column('vm_network_resource_snap_id', String(length=255), ForeignKey('vm_network_resource_snaps.vm_network_resource_snap_id'),nullable=False,index=True),        
        Column('key', String(255), nullable=False),
        Column('value', Text()),
        UniqueConstraint('vm_network_resource_snap_id', 'key'),
        mysql_engine='InnoDB'
    ) 
    
    vm_security_group_rule_snaps = Table(
        'vm_security_group_rule_snaps', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('version', String(length=255)),
        Column('id', String(length=255), primary_key=True, nullable= False),
        Column('vm_security_group_snap_id', String(length=255), ForeignKey('snapshot_vm_resources.id'), primary_key=True),
        Column('pickle',String(length=65535)),
        Column('status', String(length=32), nullable=False),
        mysql_engine='InnoDB'
    )        
    
    vm_security_group_rule_snap_metadata = Table(
        'vm_security_group_rule_snap_metadata', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('version', String(length=255)),
        Column('id', String(length=255), primary_key=True, nullable= False),
        Column('vm_security_group_rule_snap_id', String(length=255), ForeignKey('vm_security_group_rule_snaps.id'),nullable=False,index=True),        
        Column('key', String(255), nullable=False),
        Column('value', Text()),
        UniqueConstraint('vm_security_group_rule_snap_id', 'key'),
        mysql_engine='InnoDB'
    )     
    
    restores = Table(
        'restores', meta,
        Column('created_at', DateTime),
        Column('finished_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('version', String(length=255)),
        Column('id', String(length=255), primary_key=True, nullable= False),
        Column('snapshot_id', String(length=255), ForeignKey('snapshots.id')),
        Column('user_id', String(length=255)),
        Column('project_id', String(length=255)),
        Column('restore_type', String(length=32), primary_key=False, nullable= False),
        Column('display_name', String(length=255)),
        Column('display_description', String(length=255)),
        Column('pickle',String(length=65535)),        
        Column('size', BigInteger, nullable=False),             
        Column('uploaded_size', BigInteger, nullable=False),          
        Column('progress_percent', Integer, nullable=False),   
        Column('progress_msg', String(length=255)),
        Column('warning_msg', String(length=4096)),
        Column('error_msg', String(length=4096)),
        Column('host', String(length=255)),        
        Column('target_platform', String(length=255)),
        Column('time_taken', BigInteger, default=0),
        Column('status', String(length=32), nullable=False),
        mysql_engine='InnoDB'
    )
    
    restore_metadata = Table(
        'restore_metadata', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('version', String(length=255)),
        Column('id', String(length=255), primary_key=True, nullable= False),
        Column('restore_id', String(length=255), ForeignKey('restores.id'),nullable=False,index=True),        
        Column('key', String(255), nullable=False),
        Column('value', Text()),
        UniqueConstraint('restore_id', 'key'),
        mysql_engine='InnoDB'
    ) 
        
    restored_vms = Table(
        'restored_vms', meta,
        Column('created_at', DateTime),
        Column('finished_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('version', String(length=255)),
        Column('id', String(length=255), primary_key=True, nullable= False),
        Column('vm_id', String(length=255), nullable= False),
        Column('vm_name', String(length=255), nullable= False),
        Column('restore_id', String(length=255), ForeignKey('restores.id')),
        Column('size', BigInteger, nullable=False),
        Column('restore_type', String(length=32)),    
        Column('status', String(length=32), nullable=False),
        mysql_engine='InnoDB'
    )
    
    restored_vm_metadata = Table(
        'restored_vm_metadata', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('version', String(length=255)),
        Column('id', String(length=255), primary_key=True, nullable= False),
        Column('restored_vm_id', String(length=255), ForeignKey('restored_vms.id'),nullable=False,index=True),        
        Column('key', String(255), nullable=False),
        Column('value', Text()),
        UniqueConstraint('restored_vm_id', 'key'),
        mysql_engine='InnoDB'
    )  
       
    restored_vm_resources = Table(
        'restored_vm_resources', meta,
        Column('created_at', DateTime),
        Column('finished_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('version', String(length=255)),
        Column('id', String(length=255), primary_key=True, nullable= False),
        Column('vm_id', String(length=255), nullable= False),
        Column('restore_id', String(length=255), ForeignKey('restores.id')),
        Column('resource_type', String(length=255)),
        Column('resource_name', String(length=255)),
        Column('status', String(length=32), nullable=False),
        UniqueConstraint('id', 'vm_id', 'restore_id', 'resource_name'),
        mysql_engine='InnoDB'
    )
    
    restored_vm_resource_metadata = Table(
        'restored_vm_resource_metadata', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('version', String(length=255)),
        Column('id', String(length=255), primary_key=True, nullable= False),
        Column('restored_vm_resource_id', String(length=255), ForeignKey('restored_vm_resources.id'),nullable=False,index=True),        
        Column('key', String(255), nullable=False),
        Column('value', Text()),
        UniqueConstraint('restored_vm_resource_id', 'key'),
        mysql_engine='InnoDB'
    )
    
    tasks = Table(
        'tasks', meta,
        Column('created_at', DateTime),
        Column('finished_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('version', String(length=255)),
        Column('id', String(length=255), primary_key=True, nullable= False),
        Column('display_name', String(length=255)),
        Column('display_description', String(length=255)),
        Column('result', String(length=65535)),
        Column('status', String(length=32), nullable=False),
        mysql_engine='InnoDB'
    )
    
    task_status_messages = Table(
        'task_status_messages', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('version', String(length=255)),
        Column('id', String(length=255), primary_key=True, nullable= False),
        Column('task_id', String(length=255), ForeignKey('tasks.id'),nullable=False,index=True),        
        Column('status_message', Text()),
        mysql_engine='InnoDB'
    )                        
   
    settings = Table(
        'settings', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('version', String(length=255)),
        Column('user_id', String(length=255)),
        Column('project_id', String(length=255), primary_key=True, nullable= False),
        Column('name', String(length=255), primary_key=True, nullable= False),
        Column('value',  Text()),         
        Column('description', String(length=255)),
        Column('category', String(length=32)), 
        Column('type', String(length=32)),
        Column('public', Boolean),
        Column('hidden', Boolean),                               
        Column('status', String(length=32), nullable=False),
        UniqueConstraint('name', 'project_id'),
        mysql_engine='InnoDB'
    )
    
    setting_metadata = Table(
        'setting_metadata', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Boolean),
        Column('version', String(length=255)),
        Column('id', String(length=255), primary_key=True, nullable= False),
        Column('settings_name', String(length=255), ForeignKey('settings.name'), nullable=False, index=True),
        Column('settings_project_id', String(length=255), ForeignKey('settings.project_id'), nullable=False),        
        Column('key', String(255), nullable=False),
        Column('value', Text()),
        UniqueConstraint('settings_name', 'settings_project_id', 'key'),
        mysql_engine='InnoDB'
    )
    
    # create all tables
    # Take care on create order for those with FK dependencies
    tables = [file_search,
              services,
              vault_storages,
              vault_storage_metadata,              
              workload_types,
              workload_type_metadata,
              workloads,
              workload_metadata,
              workload_vms,
              workload_vm_metadata,
              scheduled_jobs,
              snapshots,
              snapshot_metadata,
              snapshot_vms,
              snapshot_vm_metadata,
              vm_recent_snapshot,
              snapshot_vm_resources,
              snapshot_vm_resource_metadata,
              vm_disk_resource_snaps,
              vm_disk_resource_snap_metadata,
              vm_network_resource_snaps,
              vm_network_resource_snap_metadata,
              vm_security_group_rule_snaps,
              vm_security_group_rule_snap_metadata,
              restores,
              restore_metadata,
              restored_vms,
              restored_vm_metadata,
              restored_vm_resources,
              restored_vm_resource_metadata,
              tasks,
              task_status_messages,
              settings,
              setting_metadata]

    for table in tables:
        try:
            table.create()
        except Exception:
            LOG.info(repr(table))
            LOG.exception(_('Exception while creating table.'))
            raise

    if migrate_engine.name == "mysql":
        tables = [  "file_search",
                    "services",
                    "vault_storages",
                    "vault_storage_metadata",
                    "workload_types",
                    "workload_type_metadata",
                    "workloads",
                    "workload_metadata",
                    "workload_vms",
                    "workload_vm_metadata",
                    "scheduled_jobs",
                    "snapshots",
                    "snapshot_metadata",
                    "snapshot_vms",
                    "snapshot_vm_metadata",
                    "vm_recent_snapshot",
                    "snapshot_vm_resources",
                    "snapshot_vm_resource_metadata",
                    "vm_disk_resource_snaps",
                    "vm_disk_resource_snap_metadata",
                    "vm_network_resource_snaps",
                    "vm_network_resource_snap_metadata",
                    "vm_security_group_rule_snaps",
                    "vm_security_group_rule_snap_metadata",
                    "restores",
                    "restore_metadata",
                    "restored_vms",
                    "restored_vm_metadata",
                    "restored_vm_resources",
                    "restored_vm_resource_metadata",
                    "tasks",
                    "task_status_messages",
                    "settings",
                    "settings_metadata"]                  

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
