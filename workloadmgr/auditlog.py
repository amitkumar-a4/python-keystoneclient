# Copyright 2015 TrilioData Inc.
# All Rights Reserved.

import os
import threading
import time
from datetime import datetime
from datetime import timedelta
from workloadmgr.openstack.common import timeutils
from workloadmgr.openstack.common import fileutils
 
_auditloggers = {}
lock = threading.Lock()

def getAuditLogger(name='auditlog', version='unknown', filepath='/opt/stack/data/wlm/auditlogs/auditlog.log'):
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
            auditlogmsg = timeutils.utcnow().strftime("%d-%m-%Y %H:%M:%S.%f")
            auditlogmsg = auditlogmsg + ',' + 'admin' + ',' + context.user_id
            auditlogmsg = auditlogmsg + ',' +  object.get('display_name', 'NA') + ',' + object.get('id', 'NA')  
            auditlogmsg = auditlogmsg + ',' + message + '\n'
            with open(self._filepath, 'a') as auditlogfile:   
                auditlogfile.write(auditlogmsg, *args, **kwargs)
        finally:
            lock.release()
            
    def get_records(self, time_in_minutes):
        records = []
        now = timeutils.utcnow()
        with open(self._filepath) as auditlogfile: 
            for line in auditlogfile:
                values = line.split(",") 
                if (now - datetime.strptime(values[0], "%d-%m-%Y %H:%M:%S.%f")) < timedelta(minutes=time_in_minutes):
                    record = {'Timestamp' : values[0],
                              'UserName': values[1],
                              'UserId': values[2],
                              'ObjectName': values[3],
                              'ObjectId': values[4],
                              'Details':values[5],
                              }
                    records.append(record)
                else:
                    break;
        return records
