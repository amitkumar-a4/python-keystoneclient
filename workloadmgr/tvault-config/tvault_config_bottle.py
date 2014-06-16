#!/usr/bin/env python
#
# Copyright (C) 2013 Federico Ceratto and others, see AUTHORS file.
# Released under LGPLv3+ license, see LICENSE.txt
#
# Cork example web application
#
# The following users are already available:
#  admin/admin, demo/demo
import os
import socket
import fcntl
import struct
from configobj import ConfigObj
import time
import subprocess
from tempfile import mkstemp
from shutil import move
from os import remove, close
from urlparse import urlparse
    
import bottle
from bottle import static_file
from beaker.middleware import SessionMiddleware
from cork import Cork
import logging

import keystoneclient
import keystoneclient.v2_0.client as ksclient
import workloadmgrclient
import workloadmgrclient.v1.client as wlmclient



logging.basicConfig(format='localhost - - [%(asctime)s] %(message)s', level=logging.DEBUG)
log = logging.getLogger(__name__)
bottle.debug(True)

module_dir = os.path.dirname(__file__)
if module_dir:
    os.chdir(os.path.dirname(__file__))
    
TVAULT_SERVICE_PASSWORD = '52T8FVYZJse'

# Use users.json and roles.json in the local example_conf directory
aaa = Cork('conf', email_sender='info@triliodata.com', smtp_url='smtp://smtp.magnet.ie')

# alias the authorization decorator with defaults
authorize = aaa.make_auth_decorator(fail_redirect="/login", role="user")

import datetime
app = bottle.app()
session_opts = {
    'session.cookie_expires': True,
    'session.encrypt_key': 'please use a random key and keep it secret!',
    'session.httponly': True,
    'session.timeout': 3600 * 24,  # 1 day
    'session.type': 'cookie',
    'session.validate_key': True,
}
app = SessionMiddleware(app, session_opts)


# #  Bottle methods  # #

def postd():
    return bottle.request.forms


def post_get(name, default=''):
    return bottle.request.POST.get(name, default).strip()


@bottle.post('/login')
def login():
    """Authenticate users"""
    username = post_get('username')
    password = post_get('password')
    aaa.login(username, password, success_redirect='/change_password', fail_redirect='/login')

@bottle.route('/logout')
def logout():
    aaa.logout(success_redirect='/login')


@bottle.post('/reset_password')
def send_password_reset_email():
    """Send out password reset email"""
    aaa.send_password_reset_email(
        username=post_get('username'),
        email_addr=post_get('email_address')
    )
    return 'Please check your mailbox.'


@bottle.route('/change_password/:reset_code')
@bottle.view('password_change_form')
@authorize()
def change_password(reset_code):
    """Show password change form"""
    return dict(reset_code=reset_code)

@bottle.route('/change_password')
@bottle.view('password_change_form')
@authorize()
def change_password():
    """Show password change form"""
    if aaa.current_user.email_addr == 'admin@localhost.local':
       return {}
    else:
       bottle.redirect("/configure")
     

@bottle.post('/change_password')
@authorize()
def change_password():
    """Change password"""
    aaa.current_user.update(pwd=post_get('newpassword'), email_addr="info@triliodata.com")
    bottle.redirect("/configure")


@bottle.route('/')
@authorize()
def index():
    bottle.redirect("/configure")

# Static pages
@bottle.route('/login')
@bottle.view('login_form')
def login_form():
    """Serve login form"""
    return {}

# Static pages
@bottle.route('/<filename:re:.*\.png>')
def send_image(filename):
    return static_file(filename, root='views', mimetype='image/png')

@bottle.route('/<filename:re:.*\.css>')
def send_css(filename):
    return static_file(filename, root='views', mimetype='text/css')

@bottle.route('/<filename:re:.*\.js>')
def send_css(filename):
    return static_file(filename, root='views', mimetype='text/javascript')

@bottle.route('/<filename:re:.*\.ttf>')
def send_css(filename):
    return static_file(filename, root='views', mimetype='font/ttf')

@bottle.route('/<filename:re:.*\.eot>')
def send_css(filename):
    return static_file(filename, root='views', mimetype='font/eot')

@bottle.route('/<filename:re:.*\.woff>')
def send_css(filename):
    return static_file(filename, root='views', mimetype='font/woff')

@bottle.route('/<filename:re:.*\.otf>')
def send_css(filename):
    return static_file(filename, root='views', mimetype='font/otf')

"""############################ tvault config API's ########################"""

def replace_line(file_path, pattern, substitute):
    #Create temp file
    fh, abs_path = mkstemp()
    new_file = open(abs_path,'w')
    old_file = open(file_path)
    for line in old_file:
        if pattern in line:
            new_file.write(substitute+'\n')
        else:
            new_file.write(line)
    #close temp file
    new_file.close()
    close(fh)
    old_file.close()
    #Remove original file
    remove(file_path)
    #Move new file
    move(abs_path, file_path)
    os.chmod(file_path, 0775)

def get_interface_ip(ifname):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    return socket.inet_ntoa(fcntl.ioctl(s.fileno(), 0x8915, struct.pack('256s',
                            ifname[:15]))[20:24])

def get_lan_ip():
    ip = socket.gethostbyname(socket.gethostname())
    if ip.startswith("127.") and os.name != "nt":
        interfaces = [
            "eth0",
            "eth1",
            "eth2",
            "wlan0",
            "wlan1",
            "wifi0",
            "ath0",
            "ath1",
            "ppp0",
            ]
        for ifname in interfaces:
            try:
                ip = get_interface_ip(ifname)
                break
            except IOError:
                pass
    return ip

@bottle.route('/configure')
@bottle.view('configure_form')
@authorize()
def configure_form():
    return {}

@bottle.route('/task_status')
@bottle.view('task_status')
@authorize()
def task_status():
    return {}

@bottle.route('/register_service')
@authorize()
def register_service():
    # Python code to here register the service with keystone
    if config_data['wlm_controller_node'] == False:
        #nothing to do
        return {'status':'Success'}
    try:
        keystone = ksclient.Client(auth_url=config_data['keystone_admin_url'], 
                                   username=config_data['admin_username'], 
                                   password=config_data['admin_password'], 
                                   tenant_name=config_data['admin_tenant_name'])
        #create user
        try:
            try:
                keystone.users.delete( 't-workloadmgr')
            except Exception as err:
                if str(err.__class__) == "<class 'bottle.HTTPResponse'>":
                   raise err
            
            
            keystone.users.create( 't-workloadmgr', TVAULT_SERVICE_PASSWORD, 'workloadmgr@trilioData.com',
                                   tenant_id=config_data['service_tenant_id'],
                                   enabled=True)
        
        except Exception as err:
            if str(err.__class__) == "<class 'bottle.HTTPResponse'>":
               raise err
            if str(err.__class__) == "<class 'keystoneclient.apiclient.exceptions.Conflict'>":
                pass
            else:
               bottle.redirect("/configure")        
        
        
        try:
            #delete orphan wlm services
            services = keystone.services.list()
            endpoints = keystone.endpoints.list()
            for service in services:
                if service.type == 'workloads':
                    for endpoint in endpoints:
                        if endpoint.service_id == service.id and endpoint.region == config_data['region_name']:
                            keystone.services.delete(service.id)
            #create service and endpoint
            wlm_service = keystone.services.create('trilioVaultWLM', 'workloads', 'trilioVault Workload Manager Service')
            wlm_url = 'http://' + config_data['floating_ipaddress'] + ':8780' + '/v1/$(tenant_id)s'
            keystone.endpoints.create(config_data['region_name'], wlm_service.id, wlm_url, wlm_url, wlm_url)
            
        except Exception as err:
            if str(err.__class__) == "<class 'bottle.HTTPResponse'>":
               raise err
            else:
               raise err                   
    
    except Exception as err:
        if str(err.__class__) == "<class 'bottle.HTTPResponse'>":
           raise err
        else:
           raise err
               
    time.sleep(1)
    return {'status':'Success'}

@bottle.route('/configure_api')
@authorize()
def configure_api():
    # Python code to configure api service
    try:
        if config_data['wlm_controller_node'] == True:
            command = ['sudo', 'rm', "/etc/init/wlm-api.override"];
            #shell=FALSE for sudo to work.
            subprocess.call(command, shell=False) 
            
            #configure tvault-gui
            command = ['sudo', 'rm', "/etc/init/tvault-gui.override"];
            subprocess.call(command, shell=False) 
            command = ['sudo', 'rm', "/etc/init/tvault-gui-worker.override"];
            subprocess.call(command, shell=False)         
            command = ['sudo', 'rm', "/etc/init/tvault-gui-worker-1.override"];
            subprocess.call(command, shell=False)        
            command = ['sudo', 'rm', "/etc/init/tvault-gui-web.override"];
            subprocess.call(command, shell=False)         
            command = ['sudo', 'rm', "/etc/init/tvault-gui-web-1.override"];
            subprocess.call(command, shell=False)
                                    
            replace_line('/opt/tvault-gui/config/tvault-gui.yml', 'ip: ', 'ip: ' + config_data['keystone_host'])
            replace_line('/opt/tvault-gui/config/tvault-gui.yml', 'port: ', 'port: ' + str(config_data['keystone_public_port']))
                   
        else:
            command = ['sudo', 'service', 'wlm-api', 'stop'];
            subprocess.call(command, shell=False)
            
            command = ['sudo', 'sh', '-c', "echo manual > /etc/init/wlm-api.override"]
            subprocess.call(command, shell=False)
            
            #configure tvault-gui
            command = ['sudo', 'service', 'tvault-gui', 'stop'];
            subprocess.call(command, shell=False)
            command = ['sudo', 'service', 'tvault-gui-worker', 'stop'];
            subprocess.call(command, shell=False)
            command = ['sudo', 'service', 'tvault-gui-worker-1', 'stop'];
            subprocess.call(command, shell=False)
            command = ['sudo', 'service', 'tvault-gui-web', 'stop'];
            subprocess.call(command, shell=False)
            command = ['sudo', 'service', 'tvault-gui-web-1', 'stop'];
            subprocess.call(command, shell=False)                                                
            
            command = ['sudo', 'sh', '-c', "echo manual > /etc/init/tvault-gui.override"];
            subprocess.call(command, shell=False) 
            command = ['sudo', 'sh', '-c', "echo manual > /etc/init/tvault-gui-worker.override"];
            subprocess.call(command, shell=False)         
            command = ['sudo', 'sh', '-c', "echo manual > /etc/init/tvault-gui-worker-1.override"];
            subprocess.call(command, shell=False)        
            command = ['sudo', 'sh', '-c', "echo manual > /etc/init/tvault-gui-web.override"];
            subprocess.call(command, shell=False)         
            command = ['sudo', 'sh', '-c', "echo manual > /etc/init/tvault-gui-web-1.override"];
            subprocess.call(command, shell=False)
            
    except Exception as err:
        if str(err.__class__) == "<class 'bottle.HTTPResponse'>":
           raise err
        else:
           raise err        
    time.sleep(1)
    return {'status':'Success'}

@bottle.route('/configure_scheduler')
@authorize()
def configure_scheduler():
    # Python code here to configure scheduler
    try:
        if config_data['wlm_controller_node'] == True:
            command = ['sudo', 'rm', "/etc/init/wlm-scheduler.override"];
            #shell=FALSE for sudo to work.
            subprocess.call(command, shell=False)        
        else:
            command = ['sudo', 'service', 'wlm-scheduler', 'stop'];
            #shell=FALSE for sudo to work.
            subprocess.call(command, shell=False)
            
            command = ['sudo', 'sh', '-c', "echo manual > /etc/init/wlm-scheduler.override"]
            #shell=FALSE for sudo to work.
            subprocess.call(command, shell=False)
    except Exception as err:
        if str(err.__class__) == "<class 'bottle.HTTPResponse'>":
           raise err
        else:
           raise err        
    time.sleep(1)
    return {'status':'Success'}

@bottle.route('/configure_service')
@authorize()
def configure_service():
    # Python code here to configure workloadmgr
    try:
        #configure host
        replace_line('/etc/hosts', ' t-vault', config_data['tvault_ipaddress']+' ' + socket.gethostname())
        replace_line('/etc/hosts', config_data['tvault_ipaddress']+' ', config_data['tvault_ipaddress']+' ' + socket.gethostname())
        
        #configure wlm        
        command = ['sudo', 'rm', "/etc/init/wlm-workloads.override"];
        #shell=FALSE for sudo to work.
        subprocess.call(command, shell=False) 
        
        config_wlm = ConfigObj('/etc/workloadmgr/workloadmgr.cfg')
        config_wlm['DEFAULT'] = {}

        config_wlm['DEFAULT']['glance_production_host'] = config_data['glance_production_host']
        config_wlm['DEFAULT']['glance_production_port'] = config_data['glance_production_port']
        
        config_wlm['DEFAULT']['neutron_admin_auth_url'] = config_data['neutron_admin_auth_url'] 
        config_wlm['DEFAULT']['neutron_admin_auth_url'] = config_data['neutron_admin_auth_url']
        config_wlm['DEFAULT']['neutron_admin_auth_url'] = config_data['neutron_admin_auth_url']
        config_wlm['DEFAULT']['neutron_admin_auth_url'] = config_data['neutron_admin_auth_url'] 
        
        config_wlm['DEFAULT']['nova_admin_auth_url'] = config_data['nova_admin_auth_url']
        config_wlm['DEFAULT']['nova_admin_username'] = config_data['nova_admin_username']
        config_wlm['DEFAULT']['nova_admin_username'] = config_data['nova_admin_username']
        config_wlm['DEFAULT']['nova_production_endpoint_template'] = config_data['nova_production_endpoint_template']
        
        config_wlm['DEFAULT']['cinder_production_endpoint_template'] = config_data['cinder_production_endpoint_template']
        
        config_wlm['DEFAULT']['wlm_vault_service'] = config_data['wlm_vault_service']
        config_wlm['DEFAULT']['wlm_vault_swift_url'] = config_data['wlm_vault_swift_url']
        
        config_wlm['DEFAULT']['sql_connection'] = config_data['sql_connection']
        config_wlm['DEFAULT']['rabbit_host'] = config_data['rabbit_host']
        config_wlm['DEFAULT']['rabbit_password'] = config_data['rabbit_password']

        config_wlm.write()
        
        #configure api-paste
        replace_line('/etc/workloadmgr/api-paste.ini', 'auth_host = ', 'auth_host = ' + config_data['keystone_host'])
        replace_line('/etc/workloadmgr/api-paste.ini', 'auth_port = ', 'auth_port = ' + str(config_data['keystone_admin_port']))
        replace_line('/etc/workloadmgr/api-paste.ini', 'auth_protocol = ', 'auth_protocol = ' + config_data['keystone_admin_protocol'])
        
    except Exception as err:
        if str(err.__class__) == "<class 'bottle.HTTPResponse'>":
           raise err
        else:
           raise err        
    time.sleep(1)
    return {'status':'Success'}

@bottle.route('/start_api')
@authorize()
def start_api():
    # Python code to configure api service
    try:
        if config_data['wlm_controller_node'] == True:
            command = ['sudo', 'service', 'wlm-api', 'restart'];
            subprocess.call(command, shell=False)
            
            #configure tvault-gui
            command = ['sudo', 'service', 'tvault-gui', 'restart'];
            subprocess.call(command, shell=False)
            command = ['sudo', 'service', 'tvault-gui-worker', 'restart'];
            subprocess.call(command, shell=False)
            command = ['sudo', 'service', 'tvault-gui-worker-1', 'restart'];
            subprocess.call(command, shell=False)
            command = ['sudo', 'service', 'tvault-gui-web', 'restart'];
            subprocess.call(command, shell=False)
            command = ['sudo', 'service', 'tvault-gui-web-1', 'restart'];
            subprocess.call(command, shell=False)                                                
        
    except Exception as err:
        if str(err.__class__) == "<class 'bottle.HTTPResponse'>":
           raise err
        else:
           raise err        
    time.sleep(2)
    return {'status':'Success'}

@bottle.route('/start_scheduler')
@authorize()
def start_scheduler():
    # Python code here to configure scheduler
    try:
        if config_data['wlm_controller_node'] == True:        
            command = ['sudo', 'service', 'wlm-scheduler', 'restart'];
            #shell=FALSE for sudo to work.
            subprocess.call(command, shell=False)
    except Exception as err:
        if str(err.__class__) == "<class 'bottle.HTTPResponse'>":
           raise err
        else:
           raise err        
    time.sleep(2)
    return {'status':'Success'}

@bottle.route('/start_service')
@authorize()
def start_service():
    # Python code here to configure workloadmgr
    try:
        command = ['sudo', 'service', 'wlm-workloads', 'restart'];
        #shell=FALSE for sudo to work.
        subprocess.call(command, shell=False)
    except Exception as err:
        if str(err.__class__) == "<class 'bottle.HTTPResponse'>":
           raise err
        else:
           raise err        
    time.sleep(2)
    return {'status':'Success'}

@bottle.route('/register_workloadtypes')
@authorize()
def register_workloadtypes():
    # Python code here to configure workloadmgr
    try:    
        if config_data['wlm_controller_node'] == True:
            time.sleep(4)
            wlm = wlmclient.Client(auth_url=config_data['keystone_public_url'], 
                                   username=config_data['admin_username'], 
                                   password=config_data['admin_password'], 
                                   tenant_id=config_data['admin_tenant_id'])
            workload_types = wlm.workload_types.list()
            if len(workload_types) == 0:
                metadata = { 'Username':'string', 'Password':'password', 'Namenode':'string', 'NamenodeSSHPort':'string', 'capabilities':'discover:topology'}
                wlm.workload_types.create(metadata=metadata, is_public = True, name= 'Hadoop', description = 'Hadoop workload')
                
                #MongoDB
                metadata = {'username':'string', 'password':'password', 'host':'string', 'port':'string',
                            'hostusername':'string', 'hostpassword':'password', 'hostsshport':'string',
                            'usesudo':'boolean', 'capabilities':'discover:topology'}         
                wlm.workload_types.create(metadata=metadata, is_public = True, name= 'MongoDB', description = 'MongoDB workload')
                
                #Cassandra
                metadata = {'CassandraNode':'string', 'SSHPort':'string', 'Username':'string', 'Password':'password','capabilities':'discover:topology' }                       
                wlm.workload_types.create(metadata=metadata, is_public = True, name= 'Cassandra', description = 'Cassandra workload')
                
                #Serial
                wlm.workload_types.create(metadata={}, is_public = True, name= 'Serial', description = 'Serial workload that snapshots VM in the order they are recieved')
                
                #Parallel
                wlm.workload_types.create(metadata={}, is_public = True, name= 'Parallel', description = 'Parallel workload that snapshots all VMs in parallel')
                
                #Composite
                metadata = {'capabilities':'workloads', 'workloadgraph':'string'}
                wlm.workload_types.create(metadata=metadata, is_public = True, name= 'Composite', description = 'A workload that consists of other workloads') 
    except Exception as err:
        if str(err.__class__) == "<class 'bottle.HTTPResponse'>":
           raise err
        else:
           raise err                    
    time.sleep(1)
    return {'status':'Success'}

@bottle.post('/configure')
@authorize()
def configure():
    global config_data
    config_data = {}
    config_inputs = bottle.request.POST
   
    config_data['tvault_ipaddress'] = get_lan_ip()
       
    config_data['floating_ipaddress'] = config_inputs['floating-ipaddress']
    config_data['keystone_admin_url'] = config_inputs['keystone-admin-url']
    config_data['keystone_public_url'] = config_inputs['keystone-public-url']
    config_data['admin_username'] = config_inputs['admin-username']
    config_data['admin_password'] = config_inputs['admin-password']
    config_data['admin_tenant_name'] = config_inputs['admin-tenant-name']
    config_data['region_name'] = config_inputs['region-name']
    
    parse_result = urlparse(config_data['keystone_admin_url'])
    config_data['keystone_host'] = parse_result.hostname
    config_data['keystone_admin_port'] = parse_result.port
    config_data['keystone_admin_protocol'] = parse_result.scheme
    
    parse_result = urlparse(config_data['keystone_public_url'])
    config_data['keystone_public_port'] = parse_result.port
    config_data['keystone_public_protocol'] = parse_result.scheme
 
    try:
        #test admin url
        keystone = ksclient.Client(auth_url=config_data['keystone_admin_url'], 
                                   username=config_data['admin_username'], 
                                   password=config_data['admin_password'], 
                                   tenant_name=config_data['admin_tenant_name'])
        tenants = keystone.tenants.list()
        for tenant in tenants:
            if tenant.name == 'service':
                config_data['service_tenant_id'] = tenant.id
            if tenant.name == config_data['admin_tenant_name']:
                config_data['admin_tenant_id'] = tenant.id            
                
        if 'service_tenant_id' not in config_data:
            raise Exception('No service tenant found')
        
    
        #test public url
        keystone = ksclient.Client(auth_url=config_data['keystone_public_url'], 
                                   username=config_data['admin_username'], 
                                   password=config_data['admin_password'])
        tenants = keystone.tenants.list()
        
        keystone = ksclient.Client(auth_url=config_data['keystone_admin_url'], 
                                   username=config_data['admin_username'], 
                                   password=config_data['admin_password'], 
                                   tenant_name=config_data['admin_tenant_name']) 
        
         
        
        #image
        kwargs = {'service_type': 'image', 'endpoint_type': 'publicURL', 'region_name': config_data['region_name'],}
        image_public_url = keystone.service_catalog.url_for(**kwargs)
        parse_result = urlparse(image_public_url)
        config_data['glance_production_host'] = parse_result.hostname
        config_data['glance_production_port'] = parse_result.port
        
        
        #network       
        kwargs = {'service_type': 'network', 'endpoint_type': 'publicURL', 'region_name': config_data['region_name'],}
        network_public_url = keystone.service_catalog.url_for(**kwargs)
        config_data['neutron_production_url'] = network_public_url
        config_data['neutron_admin_auth_url'] = config_data['keystone_public_url']
        config_data['neutron_admin_username'] = config_data['admin_username']
        config_data['neutron_admin_password'] = config_data['admin_password']
        
        #compute       
        kwargs = {'service_type': 'compute', 'endpoint_type': 'publicURL', 'region_name': config_data['region_name'],}
        compute_public_url = keystone.service_catalog.url_for(**kwargs)
        config_data['nova_production_endpoint_template']  =  compute_public_url.replace(
                                                                compute_public_url.split("/")[-1], 
                                                                '%(project_id)s')  
        config_data['nova_admin_auth_url'] = config_data['keystone_public_url']
        config_data['nova_admin_username'] = config_data['admin_username']
        config_data['nova_admin_password'] = config_data['admin_password']
        
        
        #volume
        kwargs = {'service_type': 'volume', 'endpoint_type': 'publicURL', 'region_name': config_data['region_name'],}
        volume_public_url = keystone.service_catalog.url_for(**kwargs)
        config_data['cinder_production_endpoint_template']  =  volume_public_url.replace(
                                                                volume_public_url.split("/")[-1], 
                                                                '%(project_id)s')
        
        #object
        kwargs = {'service_type': 'object-store', 'endpoint_type': 'publicURL', 'region_name': config_data['region_name'],}
        object_public_url = keystone.service_catalog.url_for(**kwargs)
        config_data['wlm_vault_swift_url']  =  object_public_url.replace(
                                                                object_public_url.split("/")[-1], 
                                                                'AUTH_') 
        config_data['wlm_vault_service']  = 'swift'     
        
        
        
        #workloadmanager
        if  config_inputs['nodetype'] == 'controller':
            #this is the first node
            config_data['wlm_controller_node'] = True
            config_data['sql_connection'] = 'mysql://root:TVAULT_SERVICE_PASSWORD@' + config_data['tvault_ipaddress'] + '/workloadmgr?charset=utf8'
            config_data['rabbit_host'] = config_data['tvault_ipaddress']
            config_data['rabbit_password'] = TVAULT_SERVICE_PASSWORD           
        else:
            kwargs = {'service_type': 'workloads', 'endpoint_type': 'publicURL', 'region_name': config_data['region_name'],}
            wlm_public_url = keystone.service_catalog.url_for(**kwargs)
            parse_result = urlparse(image_public_url)
            
            config_data['wlm_controller_node'] = False
            config_data['sql_connection'] = 'mysql://root:TVAULT_SERVICE_PASSWORD@' + parse_result.hostname + '/workloadmgr?charset=utf8'
            config_data['rabbit_host'] = parse_result.hostname
            config_data['rabbit_password'] = TVAULT_SERVICE_PASSWORD

        bottle.redirect("/task_status")
    except Exception as err:
        if str(err.__class__) == "<class 'bottle.HTTPResponse'>":
           raise err
        else:
           bottle.redirect("/configure")

# #  Web application main  # #

def main():

    # Start the Bottle webapp
    bottle.debug(True)
    bottle.run(host='0.0.0.0', app=app, quiet=False, reloader=True, port=8000)

if __name__ == "__main__":
    main()
