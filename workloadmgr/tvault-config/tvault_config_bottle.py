#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright (c) 2014 TrilioData, Inc.
# All Rights Reserved.
#
# The following users are already available:
#  admin/password

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
@bottle.view('landing_page')
def index():
    return {}

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

@bottle.route('/<filename:re:.*\.deb>')
def send_deb(filename):
    return static_file(filename, root='views', mimetype='application/vnd.debian.binary-package')

@bottle.route('/<filename:re:.*\.gz>')
def send_gz(filename):
    return static_file(filename, root='views', mimetype='application/x-gzip')

@bottle.route('/<filename:re:.*\.sh>')
def send_sh(filename):
    return static_file(filename, root='views', mimetype='application/x-sh')

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
    #ip = socket.gethostbyname(socket.gethostname())
    ip = '127.0.0.1'
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
    bottle.request.environ['beaker.session']['error_message'] = ''    
    return dict(error_message = bottle.request.environ['beaker.session']['error_message'])

@bottle.route('/task_status')
@bottle.view('task_status')
@authorize()
def task_status():
    bottle.request.environ['beaker.session']['error_message'] = ''
    return {}

@bottle.route('/configure_host')
@authorize()
def configure_host():
    # Python code to configure storage
    try:
        #configure host
        fh, abs_path = mkstemp()
        new_file = open(abs_path,'w')
        new_file.write('127.0.0.1 localhost\n')
        new_file.write(config_data['floating_ipaddress']+' '+socket.gethostname()+'\n')
        #close temp file
        new_file.close()
        close(fh)
        #Move new file
        command = ['sudo', 'mv', abs_path, "/etc/hosts"];
        subprocess.call(command, shell=False)
        os.chmod('/etc/hosts', 0644)
        command = ['sudo', 'chown', 'root:root', "/etc/hosts"];
        subprocess.call(command, shell=False)

        if len(config_data['name_server']):
            fh, abs_path = mkstemp()
            new_file = open(abs_path,'w')
            new_file.write('nameserver ' + config_data['name_server'] + '\n')
            new_file.write('nameserver 8.8.8.8\n')
            new_file.write('nameserver 8.8.4.4\n')
            if len(config_data['domain_search_order']):
                new_file.write('search ' + config_data['domain_search_order'] + '\n')
                
    
            #close temp file
            new_file.close()
            close(fh)
            #Move new file
            command = ['sudo', 'mv', abs_path, "/etc/resolvconf/resolv.conf.d/base"];
            subprocess.call(command, shell=False)
            os.chmod('/etc/resolvconf/resolv.conf.d/base', 0644)
            command = ['sudo', 'chown', 'root:root', "/etc/resolvconf/resolv.conf.d/base"];
            subprocess.call(command, shell=False)
            command = ['sudo', 'resolvconf',  '-u']
            subprocess.call(command, shell=False)    
        
        command = ['sudo', 'umount', '/dev/vdb']
        subprocess.call(command, shell=False)
        
        command = ['sudo', 'mkfs', '-t', 'ext4', '/dev/vdb']
        subprocess.check_call(command, shell=False) 
        
        command = ['sudo', 'mkdir', '/opt/stack/data/wlm']
        subprocess.call(command, shell=False)
        
        command = ['sudo', 'mount', '/dev/vdb', '/opt/stack/data/wlm']
        subprocess.check_call(command, shell=False) 
        
        #command = ['sudo', 'sh', '-c', "echo '/dev/vdb /opt/stack/data/wlm ext4 defaults 0' >> /etc/fstab"]
        #subprocess.check_call(command, shell=False)        
    except Exception as exception:
        bottle.request.environ['beaker.session']['error_message'] = "Error: %(exception)s" %{'exception': exception,}
        if str(exception.__class__) == "<class 'bottle.HTTPResponse'>":
           raise exception
        else:
           raise exception        
    time.sleep(1)
    return {'status':'Success'}

@bottle.route('/authenticate_with_keystone')
@authorize()
def authenticate_with_keystone():
    # Authenticate with Keystone
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
        
        
        try:
            #volume
            kwargs = {'service_type': 'volume', 'endpoint_type': 'publicURL', 'region_name': config_data['region_name'],}
            volume_public_url = keystone.service_catalog.url_for(**kwargs)
            config_data['cinder_production_endpoint_template']  =  volume_public_url.replace(
                                                                    volume_public_url.split("/")[-1], 
                                                                    '%(project_id)s')
        except Exception as exception:
            #cinder is optional
            config_data['cinder_production_endpoint_template'] = ''
             
        
        #object
        kwargs = {'service_type': 'object-store', 'endpoint_type': 'publicURL', 'region_name': config_data['region_name'],}
        object_public_url = keystone.service_catalog.url_for(**kwargs)
        config_data['wlm_vault_swift_url']  =  object_public_url.replace(
                                                                object_public_url.split("/")[-1], 
                                                                'AUTH_') 
        config_data['wlm_vault_service']  = 'swift'     
        
        
        
        #workloadmanager
        if  config_data['nodetype'] == 'controller':
            #this is the first node
            config_data['wlm_controller_node'] = True
            config_data['sql_connection'] = 'mysql://root:' + TVAULT_SERVICE_PASSWORD + '@' + config_data['floating_ipaddress'] + '/workloadmgr?charset=utf8'
            config_data['rabbit_host'] = config_data['floating_ipaddress']
            config_data['rabbit_password'] = TVAULT_SERVICE_PASSWORD           
        else:
            kwargs = {'service_type': 'workloads', 'endpoint_type': 'publicURL', 'region_name': config_data['region_name'],}
            wlm_public_url = keystone.service_catalog.url_for(**kwargs)
            parse_result = urlparse(wlm_public_url)
            
            config_data['wlm_controller_node'] = False
            config_data['sql_connection'] = 'mysql://root:' + TVAULT_SERVICE_PASSWORD + '@' + parse_result.hostname + '/workloadmgr?charset=utf8'
            config_data['rabbit_host'] = parse_result.hostname
            config_data['rabbit_password'] = TVAULT_SERVICE_PASSWORD
            
    except Exception as exception:
        bottle.request.environ['beaker.session']['error_message'] = "Error: %(exception)s" %{'exception': exception,}
        if str(exception.__class__) == "<class 'bottle.HTTPResponse'>":
           raise exception
        else:
           raise exception        
    time.sleep(1)
    return {'status':'Success'}

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
            wlm_user = None
            users = keystone.users.list()
            for user in users:
                if user.name == 't-workloadmgr' and user.tenantId == config_data['service_tenant_id']:
                    wlm_user = user
                    break
                
            admin_role = None
            roles = keystone.roles.list()
            for role in roles:
                if role.name == 'admin':
                    admin_role = role
                    break                
                      
            try:
                keystone.users.delete(wlm_user.id)
            except Exception as exception:
                if str(exception.__class__) == "<class 'bottle.HTTPResponse'>":
                   raise exception
            
            
            wlm_user = keystone.users.create('t-workloadmgr', TVAULT_SERVICE_PASSWORD, 'workloadmgr@trilioData.com',
                                             tenant_id=config_data['service_tenant_id'],
                                             enabled=True)
            
            keystone.roles.add_user_role(wlm_user.id, admin_role.id, config_data['service_tenant_id'])
        
        except Exception as exception:
            if str(exception.__class__) == "<class 'keystoneclient.apiclient.exceptions.Conflict'>":
                pass
            elif str(exception.__class__) == "<class 'keystoneclient.openstack.common.apiclient.exceptions.Conflict'>":
                pass            
            else:
                bottle.request.environ['beaker.session']['error_message'] = "Error: %(exception)s" %{'exception': exception,}
                raise exception        
        
        
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
            
        except Exception as exception:
            bottle.request.environ['beaker.session']['error_message'] = "Error: %(exception)s" %{'exception': exception,}
            raise exception                             
    
    except Exception as exception:
        bottle.request.environ['beaker.session']['error_message'] = "Error: %(exception)s" %{'exception': exception,}
        raise exception  
               
    time.sleep(1)
    return {'status':'Success'}

@bottle.route('/configure_api')
@authorize()
def configure_api():
    # Python code to configure api service
    try:
        if config_data['wlm_controller_node'] == True:
            #configure mysql server
            command = ['sudo', 'service', 'mysql', 'start'];
            subprocess.call(command, shell=False)
            stmt = 'GRANT ALL PRIVILEGES ON *.* TO ' +  '\'' + 'root' + '\'' + '@' +'\'' + '%' + '\'' + ' identified by ' + '\'' + TVAULT_SERVICE_PASSWORD + '\'' + ';'
            command = ['sudo', 'mysql', '-uroot', '-p'+TVAULT_SERVICE_PASSWORD, '-h127.0.0.1', '-e', stmt]
            subprocess.call(command, shell=False)
            command = ['sudo', 'service', 'mysql', 'restart'];
            subprocess.call(command, shell=False)
            
            #configure rabittmq
            command = ['sudo', 'invoke-rc.d', 'rabbitmq-server', 'stop']
            subprocess.call(command, shell=False)
            command = ['sudo', 'invoke-rc.d', 'rabbitmq-server', 'start']
            subprocess.call(command, shell=False)
            command = ['sudo', 'rabbitmqctl', 'change_password', 'guest', TVAULT_SERVICE_PASSWORD]
            subprocess.call(command, shell=False)
                     
                
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
                                    
            replace_line('/opt/tvault-gui/config/tvault-gui.yml', '    ip: ', '    ip: ' + config_data['keystone_host'])
            replace_line('/opt/tvault-gui/config/tvault-gui.yml', '    port: ', '    port: ' + str(config_data['keystone_public_port']))
                   
        else:
            command = ['sudo', 'service', 'mysql', 'stop'];
            subprocess.call(command, shell=False)    
            
            command = ['sudo', 'invoke-rc.d', 'rabbitmq-server', 'stop']
            subprocess.call(command, shell=False)
            
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
            
    except Exception as exception:
        bottle.request.environ['beaker.session']['error_message'] = "Error: %(exception)s" %{'exception': exception,}
        raise exception       
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
    except Exception as exception:
        bottle.request.environ['beaker.session']['error_message'] = "Error: %(exception)s" %{'exception': exception,}
        raise exception         
    time.sleep(1)
    return {'status':'Success'}

@bottle.route('/configure_service')
@authorize()
def configure_service():
    # Python code here to configure workloadmgr
    try:
        #configure wlm        
        command = ['sudo', 'rm', "/etc/init/wlm-workloads.override"];
        #shell=FALSE for sudo to work.
        subprocess.call(command, shell=False) 

        replace_line('/etc/workloadmgr/workloadmgr.conf', 'glance_production_host = ', 'glance_production_host = ' + config_data['glance_production_host'])
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'glance_production_port = ', 'glance_production_port = ' + str(config_data['glance_production_port']))
        
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'neutron_admin_auth_url = ', 'neutron_admin_auth_url = ' + config_data['neutron_admin_auth_url'])
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'neutron_production_url = ', 'neutron_production_url = ' + config_data['neutron_production_url'])
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'neutron_admin_username = ', 'neutron_admin_username = ' + config_data['neutron_admin_username'])
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'neutron_admin_password = ', 'neutron_admin_password = ' + config_data['neutron_admin_password'])
        
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'nova_admin_auth_url = ', 'nova_admin_auth_url = ' + config_data['nova_admin_auth_url'])
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'nova_production_endpoint_template = ', 'nova_production_endpoint_template = ' + config_data['nova_production_endpoint_template'])
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'nova_admin_username = ', 'nova_admin_username = ' + config_data['nova_admin_username'])
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'nova_admin_password = ', 'nova_admin_password = ' + config_data['nova_admin_password'])
        
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'cinder_production_endpoint_template = ', 'cinder_production_endpoint_template = ' + config_data['cinder_production_endpoint_template'])
        
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'wlm_vault_service = ', 'wlm_vault_service = ' + config_data['wlm_vault_service'])
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'wlm_vault_swift_url = ', 'wlm_vault_swift_url = ' + config_data['wlm_vault_swift_url'])

        replace_line('/etc/workloadmgr/workloadmgr.conf', 'sql_connection = ', 'sql_connection = ' + config_data['sql_connection'])
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'rabbit_host = ', 'rabbit_host = ' + config_data['rabbit_host'])
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'rabbit_password = ', 'rabbit_password = ' + config_data['rabbit_password'])
        
        #configure api-paste
        replace_line('/etc/workloadmgr/api-paste.ini', 'auth_host = ', 'auth_host = ' + config_data['keystone_host'])
        replace_line('/etc/workloadmgr/api-paste.ini', 'auth_port = ', 'auth_port = ' + str(config_data['keystone_admin_port']))
        replace_line('/etc/workloadmgr/api-paste.ini', 'auth_protocol = ', 'auth_protocol = ' + config_data['keystone_admin_protocol'])
        
    except Exception as exception:
        bottle.request.environ['beaker.session']['error_message'] = "Error: %(exception)s" %{'exception': exception,}
        raise exception      
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
        
    except Exception as exception:
        bottle.request.environ['beaker.session']['error_message'] = "Error: %(exception)s" %{'exception': exception,}
        raise exception         
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
    except Exception as exception:
        bottle.request.environ['beaker.session']['error_message'] = "Error: %(exception)s" %{'exception': exception,}
        raise exception    
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
    except Exception as exception:
        bottle.request.environ['beaker.session']['error_message'] = "Error: %(exception)s" %{'exception': exception,}
        raise exception      
    time.sleep(2)
    return {'status':'Success'}

@bottle.route('/register_workloadtypes')
@authorize()
def register_workloadtypes():
    # Python code here to configure workloadmgr
    try:    
        if config_data['wlm_controller_node'] == True:
            time.sleep(5)
            wlm = wlmclient.Client(auth_url=config_data['keystone_public_url'], 
                                   username=config_data['admin_username'], 
                                   password=config_data['admin_password'], 
                                   tenant_id=config_data['admin_tenant_id'])
            workload_types = wlm.workload_types.list()
            
            workload_type_names = {'Hadoop':False,
                                   'MongoDB':False,
                                   'Cassandra':False,
                                   'Serial':False,
                                   'Parallel':False,
                                   'Composite':False,}
                       
            for workload_type in workload_types:
                workload_type_names[workload_type.name] = True
                
            if workload_type_names['Hadoop'] == False:
                #Hadoop
                time.sleep(2)
                metadata = { 'Namenode':'string', 'NamenodeSSHPort':'string', 'Username':'string', 'Password':'password', 'capabilities':'discover:topology'}
                wlm.workload_types.create(metadata=metadata, is_public = True, name= 'Hadoop', description = 'Hadoop workload')
            
            if workload_type_names['MongoDB'] == False:
                #MongoDB
                time.sleep(2)
                metadata = {'HostUsername':'string', 'HostPassword':'password', 'HostSSHPort':'string', 'DBHost':'string',
                            'DBPort':'string', 'DBUser':'string', 'DBPassword':'password',
                            'RunAsRoot':'boolean', 'capabilities':'discover:topology'}         
                wlm.workload_types.create(metadata=metadata, is_public = True, name= 'MongoDB', description = 'MongoDB workload')
                
            if workload_type_names['Cassandra'] == False:                
                #Cassandra
                time.sleep(2)
                metadata = {'CassandraNode':'string', 'SSHPort':'string', 'Username':'string', 'Password':'password','capabilities':'discover:topology' }                       
                wlm.workload_types.create(metadata=metadata, is_public = True, name= 'Cassandra', description = 'Cassandra workload')
                
            if workload_type_names['Serial'] == False:
                #Serial
                time.sleep(2)
                wlm.workload_types.create(metadata={}, is_public = True, name= 'Serial', description = 'Serial workload that snapshots VM in the order they are recieved')
            
            if workload_type_names['Parallel'] == False:    
                #Parallel
                time.sleep(2)
                wlm.workload_types.create(metadata={}, is_public = True, name= 'Parallel', description = 'Parallel workload that snapshots all VMs in parallel')
            
            if workload_type_names['Composite'] == False:    
                #Composite
                time.sleep(2)
                metadata = {'capabilities':'workloads', 'workloadgraph':'string'}
                wlm.workload_types.create(metadata=metadata, is_public = True, name= 'Composite', description = 'A workload that consists of other workloads')
                 
    except Exception as exception:
        bottle.request.environ['beaker.session']['error_message'] = "Error: %(exception)s" %{'exception': exception,}
        raise exception                    
    time.sleep(1)
    return {'status':'Success'}

@bottle.post('/configure')
@authorize()
def configure():
    global config_data
    config_data = {}
    bottle.request.environ['beaker.session']['error_message'] = ''
    
    try:    
        config_inputs = bottle.request.POST
       
        config_data['nodetype'] = config_inputs['nodetype']
        config_data['tvault_ipaddress'] = get_lan_ip()
        config_data['floating_ipaddress'] = config_inputs['floating-ipaddress']
        config_data['name_server'] = config_inputs['name-server']
        config_data['domain_search_order'] = config_inputs['domain-search-order']        
        
    
        
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
 
        bottle.redirect("/task_status")
    except Exception as exception:
        bottle.request.environ['beaker.session']['error_message'] = "Error: %(exception)s" %{'exception': exception,}
        if str(exception.__class__) == "<class 'bottle.HTTPResponse'>":
           raise exception
        else:
           bottle.redirect("/configure")

    
# #  Web application main  # #

def main():

    # Start the Bottle webapp
    bottle.debug(True)
    bottle.run(host='0.0.0.0', app=app, quiet=False, reloader=True, port=80)

if __name__ == "__main__":
    main()
