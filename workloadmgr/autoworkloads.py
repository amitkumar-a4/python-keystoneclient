#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright (c) 2014 TrilioData, Inc.
# All Rights Reserved.

import logging
import sqlalchemy 
from sqlalchemy import *
from workloadmgr.db.sqlalchemy import models
from workloadmgr import utils
import ConfigParser
from datetime import datetime

from workloadmgr import autolog

from workloadmgr.compute import nova

import urllib2
import json

LOG = logging.getLogger(__name__)
Logger = autolog.Logger(LOG)

cfg = ConfigParser.ConfigParser()
cfg.read(utils.find_config('workloadmgr.conf'))

#Script configurables
DEFAULT_VMS_PER_WORKLOAD = 1
NOVA_SECTION = 'DEFAULT'
DEFAULT_SECTION = 'DEFAULT'

date_obj = datetime.now()
time_format = '%I:%M%p'
date_format = '%m/%d/%Y'
scheduler_date = date_obj.strftime(date_format)
scheduler_time = date_obj.strftime(time_format)

def get_config_value(Section, Option, Key=None):                                            
    if cfg.has_option(Section, Option):                                         
        return cfg.get(Section, Option, Key)                                         
    else:                                                                       
        return None

def get_instances(tenant_name):
    project_ids = {}
    project_ids['project_id'] = tenant_name
    
    url = get_config_value(NOVA_SECTION, 'nova_production_endpoint_template', project_ids)
    cs = nova.novaclient2(get_config_value(NOVA_SECTION, 'nova_admin_auth_url'), 
                          get_config_value(NOVA_SECTION, 'nova_admin_username'), 
                          get_config_value(NOVA_SECTION, 'nova_admin_password'), tenant_name, url)
    return cs.servers.list()

def execute_post(url, values, headers):
    data = json.dumps(values)
    req = urllib2.Request(url, data, headers)
    try:
        response = urllib2.urlopen(req)
        return response.read()
    except urllib2.HTTPError as ex:
           raise ex
    except Exception as ex:
           raise ex   

def execute_get(url, headers):
    req = urllib2.Request(url, headers=headers)
    try:
        response = urllib2.urlopen(req)
        return response.read()
    except urllib2.HTTPError as ex:
           raise ex
    except Exception as ex:
           raise ex

def get_token(tenant_name=None):
    try:
        url = get_config_value(NOVA_SECTION, 'nova_admin_auth_url') + '/tokens'
        if tenant_name == None:
           values = {"auth": {"passwordCredentials": {"username": get_config_value(NOVA_SECTION, 
                     'nova_admin_username'), "password": get_config_value(NOVA_SECTION, 'nova_admin_password')}}}
        else:
             values = {"auth": {"tenantName": tenant_name, "passwordCredentials": 
                      {"username": get_config_value(NOVA_SECTION, 'nova_admin_username'), 
                       "password": get_config_value(NOVA_SECTION, 'nova_admin_password')}}}
        headers = {'Content-Type': 'application/json'}
        data = json.loads(execute_post(url, values, headers))

        if tenant_name == None:
           return data['access']['token']['id']

        return data['access']['token']['id'], data['access']['token']['tenant']['id']
    except Exception as ex:
           print ex
           quit()

def create_workload(inst, tenant_name):
    try:
        workload_payload = {'name': 'New Workload', 'workload_type_id': 'f82ce76f-17fe-438b-aa37-7a023058e50d',
                            'description': 'New Workload', 'source_platform': 'openstack', 'instances': inst, 
                            'jobschedule': {'end_date': 'No End', 'start_time': scheduler_time, 'interval': 
                            '24hr', 'enabled': True, 'retain_value': 30, 'retain_type': '0', 'start_date': 
                        scheduler_date}, 'metadata': {}}  

        token, project_id = get_token(tenant_name)   
        url =  'http://'+get_config_value(DEFAULT_SECTION, 'rabbit_host')+':8780/v1/'+project_id+'/workloads'
        headers = {'Content-Type': 'application/json', 'X-Auth-Token': token}
        data = execute_post(url, {'workload':workload_payload}, headers)
    except Exception as ex:
           pass

def get_all_tenants():
    try:
        token = get_token()
        url = get_config_value(NOVA_SECTION, 'nova_admin_auth_url') + '/tenants'
        headers = {'Content-Type': 'application/json', 'X-Auth-Token': token}
        data = json.loads(execute_get(url, headers))
        return data['tenants']
    except Exception as ex:
           print ex
           quit()
         
def main():
    try:
        engine = create_engine(get_config_value(DEFAULT_SECTION, 'sql_connection'),echo=False)
        auto_wlm_vms = DEFAULT_VMS_PER_WORKLOAD
        config_auto_wlm_vms = get_config_value(DEFAULT_SECTION, 'auto_workload_vm_number')
        if config_auto_wlm_vms is not None:
           auto_wlm_vms = config_auto_wlm_vms

        tenants = get_all_tenants()
        for tenant in tenants:
            instances = get_instances(tenant['name'])
            inst = []
            for instance in instances:
                metadata = instance.metadata
                auto_workload_found = False
                for key in metadata:
                    if key == 'backup_vm':
                       if metadata[key] == 'True':
                          auto_workload_found = True
                
                if instance.status == 'ACTIVE' and auto_workload_found == True:
                   d_inst = {}
                   for row in engine.execute(select([models.WorkloadVMs.__table__]).
                   where(models.WorkloadVMs.__table__.columns.vm_id==instance.id)):
                       items = dict(row.items())
                       if items['vm_id'] == instance.id and items['status'] == 'available':
                          auto_workload_found = False
                          break

                   if auto_workload_found == True:
                      d_inst['instance-id'] = instance.id
                      inst.append(d_inst)

                   if len(inst) == auto_wlm_vms:
                      create_workload(inst, tenant['name'])
                      inst = [] 
    
            if len(inst) > 0:
               create_workload(inst, tenant['name'])
                   
    except Exception as ex:
           print ex
           quit()

if __name__ == "__main__":
    main()

