# Copyright 2015 TrilioData Inc.
# All Rights Reserved.

import os
import threading
import time
from datetime import datetime
from datetime import timedelta
from workloadmgr.openstack.common import timeutils
from workloadmgr.openstack.common import fileutils
from oslo.config import cfg
from keystoneclient.v2_0 import client as keystone_v2
from workloadmgr.openstack.common import log as logging
 
auditlog_opts = [
    cfg.StrOpt('auditlog_admin_user',
               default='admin',
               help='auditlog admin user'),
    cfg.StrOpt('keystone_endpoint_url',
               default='http://localhost:35357/v2.0',
               help='keystone endpoint url for connecting to keystone'),                                   
    cfg.StrOpt('audit_log_file',
               default='auditlog.log',
               help='file name to store all audit log entries'),
    cfg.StrOpt('legacy_audit_log_file',
               default='/var/triliovault/auditlogs/auditlog.log',
               help='Legacy audit log file path to store all audit log entries'),
]

LOG = logging.getLogger(__name__)
CONF = cfg.CONF
CONF.register_opts(auditlog_opts) 

_auditloggers = {}
lock = threading.Lock()

def getAuditLogger(name='auditlog', version='unknown', filepath=None):
 
    if filepath is None:
        filepath = os.path.join(CONF.vault_data_directory, CONF.cloud_unique_id)
        filepath = os.path.join(filepath, CONF.audit_log_file)
    
    if name not in _auditloggers:
        _auditloggers[name] = AuditLog(name, version, filepath)
    
    return _auditloggers[name]


class AuditLog(object):
    def __init__(self, name, version, filepath, *args, **kwargs):
        self._name = name
        self._version = version
        self._filepath = filepath
        head, tail = os.path.split(filepath)
        fileutils.ensure_tree(head)

    def log(self, context, message, object=None, *args, **kwargs):
        try:
            lock.acquire()
           
            if message == None:
                message = 'NA'
            if object == None:
                object = {}
            
            user_name = context.user_id
            try:
                keystone = keystone_v2.Client(token=context.auth_token, endpoint=CONF.keystone_endpoint_url)
                user = keystone.users.get(context.user_id)
                user_name = user.name
            except Exception as ex:
                pass
            
            auditlogmsg = timeutils.utcnow().strftime("%d-%m-%Y %H:%M:%S.%f")
            auditlogmsg = auditlogmsg + ',' + user_name + ',' + context.user_id
            display_name = object.get('display_name', 'NA')
            if not display_name:
                display_name = object.get('id', 'NA')
            auditlogmsg = auditlogmsg + ',' +  display_name + ',' + object.get('id', 'NA')  
            auditlogmsg = auditlogmsg + ',' + message + '\n'

            head, tail = os.path.split(self._filepath)
            fileutils.ensure_tree(head)
            with open(self._filepath, 'a') as auditlogfile:   
                auditlogfile.write(auditlogmsg, *args, **kwargs)
        finally:
            lock.release()
            
    def get_records(self, time_in_minutes, time_from, time_to):

        def _get_records_from_audit_file(filename=None):
            records = []

            filename = filename or self._filepath

            head, tail = os.path.split(filename)
            fileutils.ensure_tree(head)        

            if not os.path.exists(filename):
                return records

            def _next_record():
                now = timeutils.utcnow()
                with open(filename) as auditlogfile: 
                    for line in auditlogfile:
                        values = line.split(",") 
                        record_time = datetime.strptime(values[0], "%d-%m-%Y %H:%M:%S.%f") 
                        epoch = time.mktime(record_time.timetuple())
                        offset = datetime.fromtimestamp (epoch) - datetime.utcfromtimestamp (epoch)
                        local_time = datetime.strftime((record_time + offset), "%m/%d/%Y %I:%M:%S.%f %p") 
                        fetch = False
                        if time_in_minutes:
                            if (now - record_time) < timedelta(minutes=time_in_minutes):
                                fetch = True
                        else:
                            if record_time >= time_from and record_time <= time_to:
                                fetch = True

                        if fetch is True:
                            record = {'Timestamp' : local_time,
                                      'UserName': values[1],
                                      'UserId': values[2],
                                      'ObjectName': values[3],
                                      'ObjectId': values[4],
                                      'Details':values[5],
                                      }
                            yield record
                        else:
                            continue

            for rec in _next_record():
                records.append(rec)

            return records

        records = _get_records_from_audit_file()
        # for backward compatilibity
        records += _get_records_from_audit_file(CONF.legacy_audit_log_file)
        return records
