#!/usr/bin/env
# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright (c) 2014 TrilioData, Inc.
# All Rights Reserved.
#
# The following users are already available:
#  admin/password

import base64
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
from xml.dom.minidom import parseString
import ConfigParser
import tarfile
import shutil
import datetime
from threading  import Thread
import uuid
    
import bottle
from bottle import static_file, ServerAdapter
from beaker.middleware import SessionMiddleware
from cork import Cork
import logging

import keystoneclient.v2_0.client as ksclient
from keystoneauth1.identity.generic import password
from keystoneauth1 import session
from keystoneclient import client
import workloadmgrclient
import workloadmgrclient.v1.client as wlmclient
from workloadmgr.compute import nova
from workloadmgr.openstack.common.gettextutils import _

import sqlalchemy 
from sqlalchemy import *
from workloadmgr.db.sqlalchemy import models
from pytz import all_timezones
from tzlocal import get_localzone

from workloadmgr import auditlog
from workloadmgr.openstack.common import timeutils

logging.basicConfig(format='localhost - - [%(asctime)s] %(message)s', level=logging.WARNING)
log = logging.getLogger(__name__)
bottle.debug(True)


module_dir = os.path.dirname(__file__)
if module_dir:
    os.chdir(os.path.dirname(__file__))
    
TVAULT_SERVICE_PASSWORD = '52T8FVYZJse'
TVAULT_CONFIGURATION_TYPE = 'openstack'
TVAULT_RABBITMQ_DEB_PATH = '/opt/stack/workloadmgr/workloadmgr/tvault-config/views/debs/amd64/rabbitmq-server_3.2.4-1_all.deb'
WLM_USER = 'nova'
SSL_INSECURE = True
SSL_VERIFY = False

# Use users.json and roles.json in the local example_conf directory
aaa = Cork('conf', email_sender='info@triliodata.com', smtp_url='smtp://smtp.magnet.ie')

# alias the authorization decorator with defaults
authorize = aaa.make_auth_decorator(fail_redirect="/login", role="user")

def get_https_app(app):
    def https_app(environ, start_response):
        environ['wsgi.url_scheme'] = 'https'
        return app(environ, start_response)
    return https_app

app = get_https_app(bottle.app())
session_opts = {
    'session.auto': True,
    'session.cookie_expires': True,
    'session.encrypt_key': '52T8FVYZJse',
    'session.httponly': True,
    'session.timeout': 1200,  # 20 min
    'session.type': 'cookie',
    'session.validate_key': True,
}
app = SessionMiddleware(app, session_opts)
class SSLWSGIRefServer(ServerAdapter):
    def run(self, handler):
        from wsgiref.simple_server import make_server, WSGIRequestHandler
        import ssl
        if self.quiet:
            class QuietHandler(WSGIRequestHandler):
                def log_request(*args, **kw): pass
            self.options['handler_class'] = QuietHandler
        srv = make_server(self.host, self.port, handler, **self.options)
        srv.socket = ssl.wrap_socket (
             srv.socket,
             keyfile='/etc/tvault/ssl/localhost.key',
             certfile='/etc/tvault/ssl/localhost.crt',  # path to certificate
             server_side=True)
        srv.serve_forever()

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
       bottle.redirect("/home")
     
@bottle.post('/change_password')
@authorize()
def change_password():
    """Change password"""
    aaa.current_user.update(pwd=post_get('newpassword'), email_addr="info@triliodata.com")
    bottle.redirect("/home")

@bottle.route('/landing_page_openstack')
@bottle.view('landing_page_openstack')
def landing_page_openstack():
    return {'version': models.DB_VERSION}
    
@bottle.route('/landing_page_vmware')
@bottle.view('landing_page_vmware')
def landing_page_vmware():
    return {'version': models.DB_VERSION}    

@bottle.route('/')
def index():
    scheme = bottle.request.urlparts[0]
    if scheme == 'http':
        # request is http; redirect to https
        bottle.redirect(bottle.request.url.replace('http', 'https', 1))
    else:
        bottle.redirect(bottle.request.url + 'landing_page_' + TVAULT_CONFIGURATION_TYPE)

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

@bottle.route('/upstart/<filename:re:.*\.log>')
@authorize()
def send_upstart_logs(filename):
    return static_file(filename, root='/var/log/upstart', mimetype='text/plain', download=True)


@bottle.route('/tvault/workloadmgr/<filename:re:.*\.log>')
@authorize()
def send_wlm_logs(filename):
    return static_file(filename, root='/var/log/workloadmgr', mimetype='text/plain', download=True)

@bottle.route('/tvault/workloadmgr/<filename:re:.*\.log.1>')
@authorize()
def send_wlm_logs1(filename):
    return static_file(filename, root='/var/log/workloadmgr', mimetype='text/plain', download=True)

@bottle.route('/tvault/tvault-gui/<filename:re:.*\.log>')
@authorize()
def send_tvault_gui_logs(filename):
    return static_file(filename, root='/var/log/tvault-gui', mimetype='text/plain', download=True)

@bottle.route('/tvault/tvault-gui/<filename:re:.*\.log.1>')
@authorize()
def send_tvault_gui_logs1(filename):
    return static_file(filename, root='/var/log/tvault-gui', mimetype='text/plain', download=True)

@bottle.route('/tvault/nova/<filename:re:.*\.log>')
@authorize()
def send_nova_logs(filename):
    return static_file(filename, root='/var/log/nova', mimetype='text/plain', download=True)

@bottle.route('/tvault/nova/<filename:re:.*\.log.1>')
@authorize()
def send_nova_logs1(filename):
    return static_file(filename, root='/var/log/nova', mimetype='text/plain', download=True)

@bottle.route('/tvault/neutron/<filename:re:.*\.log>')
@authorize()
def send_neutron_logs(filename):
    return static_file(filename, root='/var/log/neutron', mimetype='text/plain', download=True)

@bottle.route('/tvault/neutron/<filename:re:.*\.log.1>')
@authorize()
def send_neutron_logs1(filename):
    return static_file(filename, root='/var/log/neutron', mimetype='text/plain', download=True)

@bottle.route('/tvault/keystone/<filename:re:.*\.log>')
@authorize()
def send_keystone_logs(filename):
    return static_file(filename, root='/var/log/keystone', mimetype='text/plain', download=True)
    
@bottle.route('/tvault-contego-install.sh')
def send_tvault_contego_install():
    return static_file('tvault-contego-install.sh', root='/opt/stack/contego/install-scripts', mimetype='text/plain', download=True)    

@bottle.route('/tvault-contego-install.answers')
def send_tvault_contego_install():
    return static_file('tvault-contego-install.answers', root='/opt/stack/contego/install-scripts', mimetype='text/plain', download=True)

@bottle.route('/tvault-ansible-scripts.tar.gz')
def send_ansible_scripts():
    return static_file('tvault-ansible-scripts-' + models.DB_VERSION + '.tar.gz', root='/home/pypi/packages/', mimetype='application/x-gzip', download=True)

@bottle.route('/tvault-horizon-plugin-install.sh')
def send_tvault_horizon_plugin_install():
    return static_file('tvault-horizon-plugin-install.sh', root='/opt/stack/horizon-tvault-plugin/install-scripts', mimetype='text/plain', download=True)    
    
@bottle.route('/tvault_panel.py')
def send_tvault_horizon_panel():
    return static_file('tvault_panel.py', root='/opt/stack/horizon-tvault-plugin/install-scripts', mimetype='text/plain', download=True)    

@bottle.route('/tvault_panel_group.py')
def send_tvault_horizon_panel_group():
    return static_file('tvault_panel_group.py', root='/opt/stack/horizon-tvault-plugin/install-scripts', mimetype='text/plain', download=True)    
    

@authorize()
def send_tvault_logs():
    try:
        try:
            shutil.rmtree('/tmp/tvaultlogs')
        except Exception as exception:
            pass
        os.mkdir('/tmp/tvaultlogs')
        logtarfilename = '/tmp/tvaultlogs/tvaultlogs_' + datetime.datetime.now().strftime("%d_%m_%Y_%H_%M_%S") + '.tar'
        logtar = tarfile.open(name=logtarfilename, mode='w:gz')
        if os.path.exists('/var/log/workloadmgr'):
            logtar.add('/var/log/workloadmgr')
        logtar.close()
        return static_file(os.path.basename(logtarfilename), root='/tmp/tvaultlogs', mimetype='text/plain', download=True)
    except Exception as exception:
        raise exception
    
@bottle.route('/tvault/tvaultlogs_all')
@authorize()
def send_tvaultlogs_all():
    try:
        try:
            shutil.rmtree('/tmp/tvaultlogs_all')
        except Exception as exception:
            pass
        os.mkdir('/tmp/tvaultlogs_all')
        logtarfilename = '/tmp/tvaultlogs_all/tvaultlogs_' + datetime.datetime.now().strftime("%d_%m_%Y_%H_%M_%S") + '.tar'
        logtar = tarfile.open(name=logtarfilename, mode='w:gz')
        if os.path.exists('/var/log/workloadmgr'):
            logtar.add('/var/log/workloadmgr')
        if os.path.exists('/var/log/tvault-gui'):
            logtar.add('/var/log/tvault-gui')
        if os.path.exists('/var/log/nova'):
            logtar.add('/var/log/nova')
        if os.path.exists('/var/log/glance'):
            logtar.add('/var/log/glance')
        if os.path.exists('/var/log/keystone'):
            logtar.add('/var/log/keystone')
        if os.path.exists('/var/log/upstart'):
            logtar.add('/var/log/upstart')

        logtar.close()
        return static_file(os.path.basename(logtarfilename), root='/tmp/tvaultlogs_all', mimetype='text/plain', download=True)
    except Exception as exception:
        raise exception    
    
"""############################ tvault config API's ########################"""

def replace_line(file_path, pattern, substitute, starts_with = False):
    #Create temp file
    fh, abs_path = mkstemp()
    new_file = open(abs_path,'w')
    old_file = open(file_path)
    for line in old_file:
        if starts_with == True:
            if line.startswith(pattern):
                new_file.write(substitute+'\n')
            else:
                new_file.write(line)            
        else:
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

def _authenticate_with_vcenter():
    if config_data['configuration_type'] == 'vmware':
        from workloadmgr.virt.vmwareapi import vim
        vim_obj = vim.Vim(protocol="https", host=config_data['vcenter'])
        session = vim_obj.Login(vim_obj.get_service_content().sessionManager,
                                userName=config_data['vcenter_username'],
                                password=config_data['vcenter_password'])
        vim_obj.Logout(vim_obj.get_service_content().sessionManager)
        
def _authenticate_with_swift(config_data):
    if config_data['configuration_type'] == 'vmware' or config_data['configuration_type'] == 'openstack':
        if config_data['swift_auth_url'] and len(config_data['swift_auth_url']) > 0:
            from swiftclient.service import SwiftService, SwiftError
            from swiftclient.exceptions import ClientException
            
            _opts = {}
            if config_data['swift_auth_version'] == 'KEYSTONE_V2' or (config_data['keystone_auth_version'] == 2 and config_data['swift_auth_version'] == 'KEYSTONE'):
                _opts = {'verbose': 1, 'os_username': config_data['swift_username'], 'os_user_domain_name': None, 'os_cacert': None, 
                         'os_tenant_name': config_data['swift_tenantname'], 'os_user_domain_id': config_data['swift_domain_id'], 
                         'os_domain_id': config_data['swift_domain_id'], 'prefix': None, 'auth_version': '2.0', 
                         'ssl_compression': True, 'os_password': config_data['swift_password'], 'os_user_id': None, 'os_project_id': None, 
                         'long': False, 'totals': False, 'snet': False, 'os_tenant_id': None, 'os_project_name': None, 
                         'os_service_type': None, 'insecure': SSL_INSECURE, 'os_help': None, 'os_project_domain_id': None, 
                         'os_storage_url': None, 'human': False, 'auth': config_data['swift_auth_url'], 
                         'os_auth_url': config_data['swift_auth_url'], 'user': config_data['swift_username'], 'key': config_data['swift_password'], 
                         'os_region_name': config_data['region_name'], 'info': False, 'retries': 5, 'os_auth_token': None, 'delimiter': None, 
                         'os_options': {'project_name': None, 'region_name': config_data['region_name'], 'tenant_name': config_data['swift_tenantname'], 
                                        'user_domain_name': None, 
                                        'endpoint_type': None, 'object_storage_url': None, 'project_domain_id': None, 'user_id': None, 
                                        'user_domain_id': config_data['swift_domain_id'], 'domain_id': config_data['swift_domain_id'],'tenant_id': None,
                                        'service_type': None, 'project_id': None, 
                                        'auth_token': None, 'project_domain_name': None}, 
                         'debug': False, 'os_project_domain_name': None, 'os_endpoint_type': None}
            elif config_data['swift_auth_version'] == 'KEYSTONE_V3' or (config_data['keystone_auth_version'] == 3 and config_data['swift_auth_version'] == 'KEYSTONE'):
                _opts = {'verbose': 1, 'os_username': config_data['swift_username'], 'os_user_domain_name': None, 'os_cacert': None, 
                         'os_tenant_name': config_data['swift_tenantname'], 'os_user_domain_id': config_data['swift_domain_id'], 
                         'os_domain_id': config_data['swift_domain_id'],'prefix': None, 'auth_version': '3', 
                         'ssl_compression': True, 'os_password': config_data['swift_password'], 'os_user_id': None, 'os_project_id': None, 
                         'long': False, 'totals': False, 'snet': False, 'os_tenant_id': None, 'os_project_name': config_data['swift_tenantname'], 
                         'os_service_type': None, 'insecure': SSL_INSECURE, 'os_help': None, 'os_project_domain_id': config_data['swift_domain_id'], 
                         'os_storage_url': None, 'human': False, 'auth': config_data['swift_auth_url'], 
                         'os_auth_url': config_data['swift_auth_url'], 'user': config_data['swift_username'], 'key': config_data['swift_password'], 
                         'os_region_name': config_data['region_name'], 'info': False, 'retries': 5, 'os_auth_token': None, 'delimiter': None, 
                         'os_options': {'project_name': config_data['swift_tenantname'], 'region_name': config_data['region_name'], 
                                        'tenant_name': config_data['swift_tenantname'], 
                                        'user_domain_name': None, 
                                        'endpoint_type': None, 'object_storage_url': None, 'project_domain_id': config_data['swift_domain_id'], 'user_id': None, 
                                        'user_domain_id': config_data['swift_domain_id'], 'domain_id': config_data['swift_domain_id'],
                                        'tenant_id': None, 'service_type': None, 'project_id': None, 
                                        'auth_token': None, 'project_domain_name': None}, 
                         'debug': False, 'os_project_domain_name': None, 'os_endpoint_type': None}

            elif config_data['swift_auth_version'] == 'TEMPAUTH':
                _opts = {'verbose': 1, 'os_username': None, 'os_user_domain_name': None, 'os_cacert': None, 
                         'os_tenant_name': None, 'os_user_domain_id': None, 'prefix': None, 'auth_version': '1.0', 
                         'ssl_compression': True, 'os_password': None, 'os_user_id': None, 'os_project_id': None, 
                         'long': False, 'totals': False, 'snet': False, 'os_tenant_id': None, 'os_project_name': None, 
                         'os_service_type': None, 'insecure': SSL_INSECURE, 'os_help': None, 'os_project_domain_id': None, 
                         'os_storage_url': None, 'human': False, 'auth': config_data['swift_auth_url'], 
                         'os_auth_url': None, 'user': config_data['swift_username'], 'key': config_data['swift_password'], 
                         'os_region_name': None, 'info': False, 'retries': 5, 'os_auth_token': None, 'delimiter': None, 
                         'os_options': {'project_name': None, 'region_name': None, 'tenant_name': None, 'user_domain_name': None, 
                                        'endpoint_type': None, 'object_storage_url': None, 'project_domain_id': None, 'user_id': None, 
                                        'user_domain_id': None, 'tenant_id': None, 'service_type': None, 'project_id': None, 
                                        'auth_token': None, 'project_domain_name': None}, 
                         'debug': False, 'os_project_domain_name': None, 'os_endpoint_type': None}
               
            with SwiftService(options=_opts) as swift:
                try:
                    stats_parts_gen = swift.list()
                    for stats in stats_parts_gen:
                        if stats["success"]:
                            pass
                        else:
                            raise stats["error"]                
                except SwiftError as e:
                    raise

def _validate_keystone_client_and_version(admin_url=True, retry=0):
    try:
        is_admin_url = admin_url
        auth_url = config_data['keystone_admin_url']
        if admin_url == False:
           auth_url = config_data['keystone_public_url']

        if retry == 0:
           auth = password.Password(auth_url=auth_url,
                                    username=config_data['admin_username'],
                                    password=config_data['admin_password'],
                                    #project_name=config_data['admin_tenant_name'],
                                    user_domain_id=config_data['domain_name'],
                                    domain_id=config_data['domain_name'],
                                    )
        else:
              auth = password.Password(auth_url=auth_url,
                                    username=config_data['admin_username'],
                                    password=config_data['admin_password'],
                                    project_name=config_data['admin_tenant_name'],
                                    )
        sess = session.Session(auth=auth, verify=SSL_VERIFY)
        keystone = client.Client(session=sess, auth_url=auth_url, insecure=SSL_INSECURE)
        if keystone.version == 'v3':
            tenants = keystone.projects.list()
            config_data['keystone_auth_version'] = 3
        elif keystone.version == 'v2.0':
            tenants = keystone.tenants.list()
            config_data['keystone_auth_version'] = 2
        return (keystone, tenants)
    except Exception as ex:
           if retry == 1:
              raise ex
           _validate_keystone_client_and_version(is_admin_url, retry=1)


def _authenticate_with_keystone():
    # Authenticate with Keystone
    #test admin url
    try:
        keystone, tenants = _validate_keystone_client_and_version() 
    except Exception as e:
           raise Exception( "KeystoneError:Unable to connect to keystone Admin URL "+e.message  )

    if keystone.version == 'v3':
       keystone_endpoints = keystone.endpoints.list(service=keystone.services.find(type='identity').id, region=config_data['region_name'])
       for endpoint in keystone_endpoints:
           if endpoint.interface == 'public':
              keystone_public_url = endpoint.url
           elif endpoint.interface == 'internal':
                keystone_internal_url = endpoint.url
           elif endpoint.interface == 'admin':
                keystone_admin_url = endpoint.url
    else:
         endpoint = keystone.endpoints.find(service_id=keystone.services.find(type='identity').id,
                                                   region=config_data['region_name'])
         keystone_public_url = endpoint.publicurl
         keystone_internal_url = endpoint.internalurl
         keystone_admin_url = endpoint.adminurl

    if keystone_admin_url != config_data['keystone_admin_url']:
       raise Exception( "KeystoneError:Please enter correct keystone admin url ")

    
    if keystone_public_url == config_data['keystone_public_url']:
       config_data['endpoint_type'] = 'publicURL'
       v3_str = 'public'
    elif keystone_internal_url == config_data['keystone_public_url']:
         config_data['endpoint_type'] = 'internalURL'
         v3_str = 'internal'

    if 'endpoint_type' not in config_data:
       raise Exception( "KeystoneError:Please enter correct keystone public/internal url ")
  
    for tenant in tenants:
        if tenant.name == 'service' or tenant.name == 'services':
            config_data['service_tenant_id'] = tenant.id
            config_data['service_tenant_name'] = tenant.name
            config_data['service_tenant_domain_id'] = 'default'
            if hasattr(tenant, 'domain_id'):
               config_data['service_tenant_domain_id'] = tenant.domain_id
        if tenant.name == config_data['admin_tenant_name']:
            config_data['admin_tenant_id'] = tenant.id            
    
    if 'admin_tenant_id' not in config_data:
       raise Exception('Entered invalid admin tenant name')       
    if 'service_tenant_id' not in config_data:
        if config_data['configuration_type'] == 'vmware':
            config_data['service_tenant_id'] = config_data['admin_tenant_id']
        else:
            raise Exception('No service tenant found')
    
    #test public url
    try:
        keystone, tenants = _validate_keystone_client_and_version(admin_url=False)
    except Exception as e:      
            raise Exception("KeystoneError:Unable to connect to keystone Public URL "+e.message  )
        
    keystone, tenants = _validate_keystone_client_and_version() 

    configure_mysql()
    configure_rabbitmq()
    configure_keystone()
    configure_nova()
    configure_neutron()
    configure_glance()
    configure_horizon()

    #image
    if keystone.version == 'v3':
        image_public_url = keystone.endpoints.find(service_id=keystone.services.find(type='image').id, 
                                                   region=config_data['region_name'], interface=v3_str).url
    else:
        image_public_url = getattr(keystone.endpoints.find(service_id=keystone.services.find(type='image').id, 
                                                   region=config_data['region_name']), v3_str+"url")

    parse_result = urlparse(image_public_url)
    config_data['glance_production_api_servers'] = image_public_url
    config_data['glance_production_host'] = parse_result.hostname
    config_data['glance_production_port'] = parse_result.port
    
    
    #network
    try:
        if keystone.version == 'v3':
           network_public_url = keystone.endpoints.find(service_id=keystone.services.find(type='network').id, 
                                                        region=config_data['region_name'], interface=v3_str).url
        else:
             network_public_url = getattr(keystone.endpoints.find(service_id=keystone.services.find(type='network').id, 
                                                          region=config_data['region_name']), v3_str+"url")
        config_data['neutron_production_url'] = network_public_url
    except Exception as ex:
        config_data['neutron_production_url'] = "unavailable"
        
    config_data['neutron_admin_auth_url'] = config_data['keystone_public_url']
    config_data['neutron_admin_username'] = config_data['admin_username']
    config_data['neutron_admin_password'] = config_data['admin_password']
    config_data['neutron_admin_tenant_name'] = config_data['admin_tenant_name']
    
    #compute
    if keystone.version == 'v3':
        compute_public_url = keystone.endpoints.find(service_id=keystone.services.find(type='compute').id, 
                                                     region=config_data['region_name'], interface=v3_str).url
    else:
        compute_public_url = getattr(keystone.endpoints.find(service_id=keystone.services.find(type='compute').id,
                                                     region=config_data['region_name']), v3_str+"url")

  
    def _get_service_endpoint(public_url):
        comps = public_url.split("/")
        return "%s//%s/%s" % (comps[0], comps[2], comps[3]) + "/%(project_id)s"

    config_data['nova_production_endpoint_template'] = \
        _get_service_endpoint(compute_public_url)

    config_data['nova_admin_auth_url'] = config_data['keystone_public_url']
    config_data['nova_admin_username'] = config_data['admin_username']
    config_data['nova_admin_password'] = config_data['admin_password']
    
    
    try:
        #volume
        if keystone.version == 'v3':
            volume_public_url = keystone.endpoints.find(service_id=keystone.services.find(type='volume').id,
                                                       region=config_data['region_name'], interface=v3_str).url
        else:
            volume_public_url = getattr(keystone.endpoints.find(service_id=keystone.services.find(type='volume').id,
                                                        region=config_data['region_name']), v3_str+"url")

        config_data['cinder_production_endpoint_template'] = \
            _get_service_endpoint(volume_public_url)

    except Exception as exception:
        #cinder is optional
        config_data['cinder_production_endpoint_template'] = ''
         
    try:        
        #object
        if keystone.version == 'v3':
            object_public_url = keystone.endpoints.find(service_id=keystone.services.find(type='object-store').id, 
                                                       region=config_data['region_name'], interface=v3_str).url
        else:
            object_public_url = getattr(keystone.endpoints.find(service_id=keystone.services.find(type='object-store').id, 
                                                        region=config_data['region_name']), v3_str+"url")

        config_data['vault_swift_url'] = object_public_url.replace(
                                             object_public_url.split("/")[-1], 'AUTH_') 
    except Exception as exception:
        #swift is not configured
        config_data['vault_swift_url'] = ''
    
    #workloadmanager
    if  config_data['nodetype'] == 'controller':
        #this is the first node
        config_data['sql_connection'] = 'mysql://root:' + TVAULT_SERVICE_PASSWORD + '@' + config_data['floating_ipaddress'] + '/workloadmgr?charset=utf8'
        config_data['rabbit_host'] = config_data['floating_ipaddress']
        config_data['rabbit_password'] = TVAULT_SERVICE_PASSWORD           
    else:
        if keystone.version == 'v3':
            wlm_public_url = keystone.endpoints.find(service_id=keystone.services.find(type='workloads').id, 
                                                    region=config_data['region_name'], interface='public').url
        else:
            wlm_public_url = keystone.endpoints.find(service_id=keystone.services.find(type='workloads').id, 
                                                      region=config_data['region_name']).publicurl
        parse_result = urlparse(wlm_public_url)
        
        config_data['sql_connection'] = 'mysql://root:' + TVAULT_SERVICE_PASSWORD + '@' + parse_result.hostname + '/workloadmgr?charset=utf8'
        config_data['rabbit_host'] = parse_result.hostname
        config_data['rabbit_password'] = TVAULT_SERVICE_PASSWORD

def _register_service():
    # Python code to  register workloadmgr with keystone
    if config_data['configuration_type'] == 'vmware':
        authenticate_with_keystone()
    
    keystone, tenants = _validate_keystone_client_and_version()
 
    def _get_users_list():
        users = keystone.users.list()
        if keystone.version == 'v3':
            users += keystone.users.list(domain="default")
        seen = set()
        users = [x for x in users if x.id not in seen and not seen.add(x.id)]
        return users
 
    if config_data['nodetype'] != 'controller':
        config_data['triliovault_user_domain_id'] = 'default'
        wlm_user = None
        users = _get_users_list()
        for user in users:
            if user.name in ('compute', 'nova'):
                if hasattr(user, 'domain_id'):
                    config_data['triliovault_user_domain_id'] = user.domain_id
            if keystone.version == 'v3':
                if user.name == config_data['workloadmgr_user']:
                    wlm_user = user
            else:
                if user.name == config_data['workloadmgr_user'] and \
                    user.tenantId == config_data['service_tenant_id']:
                    wlm_user = user

        if wlm_user is None:
            raise Exception("Trilio Vault Appliance controller node may not have been configured. Cannot find 'triliovault' user")

        config_data['cloud_unique_id'] = wlm_user.id
        return {'status':'Success'}
    
   
    if config_data['configuration_type'] == 'openstack':
        #create user
        try:
            config_data['triliovault_user_domain_id'] = 'default'
            wlm_user = None
            users = _get_users_list()
            for user in users:
                if user.name in ('compute', 'nova'):
                   if hasattr(user, 'domain_id'):
                      config_data['triliovault_user_domain_id'] = user.domain_id
                if keystone.version == 'v3':
                   if user.name == config_data['workloadmgr_user']:
                      wlm_user = user
                else:
                     if user.name == config_data['workloadmgr_user'] and user.tenantId == config_data['service_tenant_id']:
                        wlm_user = user
                
            admin_role = None
            roles = keystone.roles.list()
            for role in roles:
                if role.name == 'admin':
                    admin_role = role
                    break                
     
            # assign know roles otherwise default to one of the roles
            rolenames = [role.name for role in roles \
                         if role.name not in ['ResellerAdmin', 'service',
                                              'admin', 'services']]

            if config_data['trustee_role'] is None:
               if '_member_' in rolenames: 
                  config_data['trustee_role'] = '_member_'
               elif 'Member' in rolenames:
                    config_data['trustee_role'] = 'Member'
               elif 'member' in rolenames:
                    config_data['trustee_role'] = 'member'
               else:
                    config_data['trustee_role'] = rolenames.pop(0)

            if wlm_user == None:
                if keystone.version == 'v3':
                   wlm_user = keystone.users.create(name=config_data['workloadmgr_user'],
                                                    password=config_data['workloadmgr_user_password'],
                                                    email='workloadmgr@trilio.io',
                                                    domain=config_data['triliovault_user_domain_id'],
                                                    default_project=config_data['service_tenant_id'],
                                                    enabled=True)
                   keystone.roles.grant(role=admin_role.id, user=wlm_user.id,
                                        project=config_data['service_tenant_id'])
                else:
                     wlm_user = keystone.users.create(config_data['workloadmgr_user'],
                                                 config_data['workloadmgr_user_password'],
                                                 'workloadmgr@trilio.io',
                                                 tenant_id=config_data['service_tenant_id'],
                                                 enabled=True)
                     keystone.roles.add_user_role(wlm_user.id, admin_role.id, config_data['service_tenant_id'])

            config_data['cloud_unique_id'] = wlm_user.id

        except Exception as exception:
            bottle.request.environ['beaker.session']['error_message'] = "Error: %(exception)s" %{'exception': exception,}
            raise exception        
        
    #delete orphan wlm services
    services = keystone.services.list()
    endpoints = keystone.endpoints.list()
    for service in services:
        if service.type == 'workloads':
            for endpoint in endpoints:
                if endpoint.service_id == service.id and endpoint.region == config_data['region_name']:
                    keystone.services.delete(service.id)
    #create service and endpoint
    if keystone.version == 'v3':
       wlm_service = keystone.services.create(name='TrilioVaultWLM',
                                              type='workloads',
                                              description='Trilio Vault Workload Manager Service',
                                              enabled=True)
    else:
         wlm_service = keystone.services.create('TrilioVaultWLM', 'workloads',
                                           'Trilio Vault Workload Manager Service')

    wlm_url = 'http://' + config_data['tvault_primary_node'] + ':8780' + '/v1/$(tenant_id)s'
    if keystone.version == 'v3':
       keystone.endpoints.create(region=config_data['region_name'],
                                 service=wlm_service.id,
                                 url=wlm_url,
                                 interface='public',
                                 enabled=True)
    else:
         keystone.endpoints.create(config_data['region_name'],
                              wlm_service.id, wlm_url, wlm_url, wlm_url)
        
    return {'status':'Success'}

def _register_workloadtypes():
    # Python code here to register workloadtypes
    if config_data['nodetype'] == 'controller':
        time.sleep(5)
        wlm = wlmclient.Client(auth_url=config_data['keystone_public_url'], 
                               username=config_data['admin_username'], 
                               password=config_data['admin_password'], 
                               tenant_id=config_data['admin_tenant_id'],
                               domain_name=config_data['domain_name'],
                               insecure=SSL_INSECURE,
                               )
        start_time = timeutils.utcnow()
        while 1:
               try:
                   workload_types = wlm.workload_types.list()
                   break
               except Exception as ex:
                      time.sleep(10)
                      now = timeutils.utcnow()
                      if (now - start_time) > datetime.timedelta(minutes=8):
                         raise ex
        
        workload_type_names = {'Hadoop':False,
                               'MongoDB':False,
                               'Cassandra':False,
                               'Serial':False,
                               'Parallel':False,
                               'Composite':False,}
                   
        for workload_type in workload_types:
            workload_type_names[workload_type.name] = True
            
        if workload_type_names['Hadoop'] == False:
            """ Do not created Hadoop workload type until it is fully supported
            #Hadoop
            time.sleep(2)
            metadata = {'Namenode':'{"default": "", "display_name": "Hadoop Host", "required": "True", "type": "string", "tooltip": "Enter the ipaddress of a Hadoop node", "restore_option": "False", "group_name": "Host Settings"}', 
                        'NamenodeSSHPort':'{"default": "22", "display_name": "SSH Port", "required": "False", "type": "string", "tooltip":"Enter ssh port number", "restore_option": "False", "group_name": "Host Settings"}', 
                        'Username':'{"default": "", "display_name": "Username", "required": "True", "type": "string", "tooltip":"Enter database host username", "restore_option": "False", "group_name": "Host Settings"}', 
                        'Password':'{"default": "", "display_name": "Password", "required": "True", "type": "password", "tooltip":"Enter database host password", "restore_option": "False", "group_name": "Host Settings"}', 
                        'capabilities':'discover:topology',
                        'group_ordering' :'[{"ordinal": 10, "name": "Host Settings"}]'}
            
            wlm.workload_types.create(metadata=metadata, is_public = True, 
                                      name= 'Hadoop', description = 'Hadoop workload',
                                      id = '09f7b42e-75da-4f77-8c34-0aef60b3d62e')
            """
        if config_data['configuration_type'] == 'openstack' and workload_type_names['MongoDB'] == True:
            wlm.workload_types.delete('11b71eeb-8b69-42e2-9862-872ae5b2afce')
            
        if config_data['configuration_type'] == 'vmware' and workload_type_names['MongoDB'] == False:
            #MongoDB
            time.sleep(2)
            metadata = {'HostUsername':'{"default": "", "display_name": "Username", "required": "True", "type": "string", "tooltip":"Enter database host username", "restore_option": "False", "group_name": "Host Settings", "ordinal":10, "index":1}', 
                        'HostPassword':'{"default": "", "display_name": "Password", "required": "True", "type": "password", "tooltip":"Enter database host password", "restore_option": "False", "group_name": "Host Settings", "ordinal":20, "index":2}', 
                        'HostSSHPort':'{"default": "22", "display_name": "SSH Port", "required": "False", "type": "string", "tooltip":"Enter ssh port number", "restore_option": "False", "group_name": "Host Settings", "ordinal":40, "index":4}', 
                        'DBHost':'{"default": "", "display_name": "Database Host", "required": "True", "type": "string", "tooltip": "Enter the hostname/ipaddress of MongoDB node(For Sharded Cluster: mongos node, for Replica Set: mongod node)", "restore_option": "False", "group_name": "Host Settings", "ordinal":30, "index":3}',
                        'DBPort':'{"default": "27017", "display_name": "Database Port", "required": "False", "type": "string", "tooltip": "Enter the MongoDB database port(For Sharded Cluster: mongos port, for Replica Set: mongod port)", "restore_option": "False", "group_name": "Database Settings", "ordinal":30, "index":3}', 
                        'DBUser':'{"default": "", "display_name": "Database Username", "required": "False", "type": "string", "tooltip": "MongoDB username if authentication is enabled", "restore_option": "False", "group_name": "Database Settings", "ordinal":10, "index":1}', 
                        'DBPassword':'{"default": "", "display_name": "Database Password", "required": "False", "type": "password", "tooltip": "MongoDB password", "restore_option": "False", "group_name": "Database Settings", "ordinal":20, "index":2}',
                        'RunAsRoot':'{"default": "True", "display_name": "Run As Root", "required": "False", "type": "boolean", "tooltip": "Runs mongo command as root", "restore_option": "False", "group_name": "Database Settings", "ordinal":40, "index":4}', 
                        'capabilities':'discover:topology',
                        'group_ordering':'[{"ordinal": 10, "name": "Host Settings"}, {"ordinal": 20, "name": "Database Settings"}]'}         
            wlm.workload_types.create(metadata=metadata, is_public = True, 
                                      name= 'MongoDB', description = 'MongoDB workload',
                                      id = '11b71eeb-8b69-42e2-9862-872ae5b2afce')
            
        if config_data['configuration_type'] == 'openstack' and workload_type_names['Cassandra'] == True:
            wlm.workload_types.delete('2c1f45ec-e53b-49cd-b554-228404ece244')
            
        if config_data['configuration_type'] == 'vmware' and workload_type_names['Cassandra'] == False:                
            #Cassandra
            time.sleep(2)
            metadata = {'CassandraNode':'{"default": "", "display_name": "Database Host", "required": "True", "type": "string", "tooltip": "Enter the ipaddress of a Cassandra node", "restore_option": "False", "group_name": "Host Settings", "index":3}', 
                        'SSHPort':'{"default": "22", "display_name": "SSH Port", "required": "False", "type": "string", "tooltip":"Enter ssh port number", "restore_option": "False", "group_name": "Host Settings", "index":4}', 
                        'Username':'{"default": "", "display_name": "Username", "required": "True", "type": "string", "tooltip":"Enter database host username", "restore_option": "False", "group_name": "Host Settings", "index":1}', 
                        'Password':'{"default": "", "display_name": "Password", "required": "True", "type": "password", "tooltip":"Enter database host password", "restore_option": "False", "group_name": "Host Settings", "index":2}',
                        'IPAddress':'{"default": "192.168.1.160", "display_name": "IP Address", "required": "True", "type": "string", "tooltip":"Enter ip address for restored VM", "restore_option": "True", "per_vm": "True", "group_name": "Cassandra Restore Options", "index":2}',
                        'Nodename':'{"default": "Cassandra1-Restored", "display_name": "Hostname", "required": "True", "type": "string", "tooltip":"Enter separated hostname for restored VM", "restore_option": "True", "per_vm": "True", "group_name": "Cassandra Restore Options", "index":3}',
                        'Netmask':'{"default": "255.255.255.0", "display_name": "Netmask", "required": "True", "type": "string", "tooltip":"Netmask for IP addresses", "restore_option": "True", "group_name": "Cassandra Restore Options", "index":4}',
                        'Broadcast':'{"default": "192.168.1.255", "display_name": "Broadcast", "required": "True", "type": "string", "tooltip":"Broadcast address for new IP subnet", "restore_option": "True", "group_name": "Cassandra Restore Options", "index":6}',
                        'Gateway':'{"default": "192.168.1.1", "display_name": "Gateway", "required": "True", "type": "string", "tooltip":"Gateway address for new IP addresses", "restore_option": "True", "group_name": "Cassandra Restore Options", "index":5}',
                        'capabilities':'discover:topology',
                        'group_ordering':'[{"ordinal": 10, "name": "Host Settings"}, {"ordinal": 20, "Optional": "True", "name": "Cassandra Restore Options"}]'}                       
            wlm.workload_types.create(metadata=metadata, is_public = True, 
                                      name= 'Cassandra', description = 'Cassandra workload',
                                      id = '2c1f45ec-e53b-49cd-b554-228404ece244')
            
        if workload_type_names['Serial'] == False:
            #Serial
            time.sleep(2)
            wlm.workload_types.create(metadata={}, is_public = True, 
                                      name= 'Serial', description = 'Serial workload that snapshots VM in the specified order',
                                      id = 'f82ce76f-17fe-438b-aa37-7a023058e50d')
        
        if workload_type_names['Parallel'] == False:    
            #Parallel
            time.sleep(2)
            wlm.workload_types.create(metadata={}, is_public = True, 
                                      name= 'Parallel', description = 'Parallel workload that snapshots all VMs in parallel',
                                      id = '2ddd528d-c9b4-4d7e-8722-cc395140255a')
            
        if config_data['configuration_type'] == 'openstack' and workload_type_names['Composite'] == True:
            wlm.workload_types.delete('54947065-2a59-494a-ab64-b6501c139a82')
                    
        if config_data['configuration_type'] == 'vmware' and workload_type_names['Composite'] == False:    
            #Composite
            time.sleep(2)
            metadata = {'capabilities':'workloads', 'workloadgraph':'string'}
            wlm.workload_types.create(metadata=metadata, is_public = True, 
                                      name= 'Composite', description = 'A workload that consists of other workloads',
                                      id = '54947065-2a59-494a-ab64-b6501c139a82')
    
    if config_data['configuration_type'] == 'openstack':
        config_data['config_status'] = 'success'
        persist_config()    
    return {'status':'Success'}

def _workloads_import():
    if config_data['nodetype'] == 'controller':
        if config_data['workloads_import'] is True:
            wlm = wlmclient.Client(auth_url=config_data['keystone_public_url'], 
                                   username=config_data['admin_username'], 
                                   password=config_data['admin_password'], 
                                   tenant_id=config_data['admin_tenant_id'],
                                   domain_name=config_data['domain_name'],
                                   insecure=SSL_INSECURE)            
            wlm.workloads.importworkloads()

    return {'status':'Success'}
                     
def configure_mysql():
    if config_data['nodetype'] == 'controller':
        #configure mysql server
        command = ['sudo', 'rm', "/etc/init/mysql.override"];
        subprocess.call(command, shell=False)              
        command = ['sudo', 'service', 'mysql', 'start'];
        subprocess.call(command, shell=False)
        stmt = 'GRANT ALL PRIVILEGES ON *.* TO ' +  '\'' + 'root' + '\'' + '@' +'\'' + '%' + '\'' + ' identified by ' + '\'' + TVAULT_SERVICE_PASSWORD + '\'' + ';'
        command = ['sudo', 'mysql', '-uroot', '-p'+TVAULT_SERVICE_PASSWORD, '-h127.0.0.1', '-e', stmt]
        subprocess.call(command, shell=False)
        command = ['sudo', 'service', 'mysql', 'restart'];
        subprocess.call(command, shell=False)
    else:
        command = ['sudo', 'service', 'mysql', 'stop'];
        subprocess.call(command, shell=False)    
        command = ['sudo', 'sh', '-c', "echo manual > /etc/init/mysql.override"];
        subprocess.call(command, shell=False)
        
def configure_rabbitmq():
    if config_data['nodetype'] == 'controller':                    
        #configure rabittmq
        command = ['sudo', 'apt-get', 'remove', '--purge', "rabbitmq-server", '-y'];
        #subprocess.call(command, shell=False)
        command = ['sudo', 'dpkg', '-i', TVAULT_RABBITMQ_DEB_PATH];
        subprocess.call(command, shell=False)
        command = ['sudo', 'rm', "/etc/init/rabbitmq-server.override"];
        #subprocess.call(command, shell=False)     
        time.sleep(10)
        command = ['sudo', 'rabbitmqctl', 'change_password', 'guest', TVAULT_SERVICE_PASSWORD]
        subprocess.call(command, shell=False)
        command = ['sudo', '/etc/init.d/rabbitmq-server', 'restart']
        subprocess.call(command, shell=False)
    else:
        command = ['sudo', 'invoke-rc.d', 'rabbitmq-server', 'stop']
        subprocess.call(command, shell=False)
        command = ['sudo', 'sh', '-c', "echo manual > /etc/init/rabbitmq-server.override"];
        subprocess.call(command, shell=False)     

def configure_keystone():
    def _get_user_id_from_name(name):
        for user in keystone.users.list():
            if hasattr(user,'name'):
                if user.name == name:
                    return user.id
            else:
                if user.id == name:
                    return user.id   
        
    if config_data['nodetype'] == 'controller' and config_data['configuration_type'] == 'vmware':
        #configure keystone
        replace_line('/etc/keystone/keystone.conf', 'admin_endpoint = ', 'admin_endpoint = ' + 
                     "http://" + config_data['tvault_primary_node'] + ":%(admin_port)s/")            
        replace_line('/etc/keystone/keystone.conf', 'public_endpoint = ', 'public_endpoint = ' + 
                     "http://" + config_data['tvault_primary_node'] + ":%(public_port)s/")            
        replace_line('/etc/keystone/keystone.conf', 'connection = ', 'connection = ' + 
                     "mysql://root:52T8FVYZJse@" + config_data['tvault_primary_node'] + "/keystone?charset=utf8")            
        replace_line('/etc/keystone/keystone.conf', 'log_dir = ', 'log_dir = ' + '/var/log/keystone')
        
        Config = ConfigParser.RawConfigParser()
        Config.read('/etc/keystone/keystone.conf')
        Config.set('ldap','url', config_data['ldap_server_url'])
        Config.set('ldap','suffix', config_data['ldap_domain_name_suffix'])
        Config.set('ldap','user_tree_dn', config_data['ldap_user_tree_dn'])
        Config.set('ldap','user', config_data['ldap_user_dn'])
        Config.set('ldap','password', config_data['ldap_user_password'])
        Config.set('ldap','use_dumb_member', config_data['ldap_use_dumb_member'])
        Config.set('ldap','user_allow_create', config_data['ldap_user_allow_create'])
        Config.set('ldap','user_allow_update', config_data['ldap_user_allow_update'])
        Config.set('ldap','user_allow_delete', config_data['ldap_user_allow_delete'])
        Config.set('ldap','tenant_allow_create', config_data['ldap_tenant_allow_create'])
        Config.set('ldap','tenant_allow_update', config_data['ldap_tenant_allow_update'])
        Config.set('ldap','tenant_allow_delete', config_data['ldap_tenant_allow_delete'])
        Config.set('ldap','role_allow_create', config_data['ldap_role_allow_create'])
        Config.set('ldap','role_allow_update', config_data['ldap_role_allow_update'])
        Config.set('ldap','role_allow_delete', config_data['ldap_role_allow_delete'])
        Config.set('ldap','user_objectclass', config_data['ldap_user_objectclass'])
        Config.set('ldap','user_name_attribute', config_data['ldap_user_name_attribute'])

        with open('/etc/keystone/keystone.conf', 'wb') as configfile:
            Config.write(configfile)         

        command = ['sudo', 'rm', "/etc/init/keystone.override"];
        subprocess.call(command, shell=False)
        command = ['sudo', 'service', 'keystone', 'restart'];
        subprocess.call(command, shell=False)
        time.sleep(8) 
        try:
            keystone = ksclient.Client(endpoint=config_data['keystone_admin_url'],
                                       insecure=True,
                                       token='52T8FVYZJse')
                                       #username=config_data['admin_username'], 
                                       #password=config_data['admin_password'], 
                                       #tenant_name=config_data['admin_tenant_name'])
                                       
            keystone.management_url = config_data['keystone_admin_url']                
            #delete orphan keystone services
            services = keystone.services.list()
            endpoints = keystone.endpoints.list()
            for service in services:
                if service.type == 'identity' or service.type == 'keystone':
                    for endpoint in endpoints:
                        if endpoint.service_id == service.id and endpoint.region == config_data['region_name']:
                            keystone.services.delete(service.id)
            #create service and endpoint
            identity_service = keystone.services.create('keystone', 'identity', 'Trilio Vault Identity Service')
            public_url = 'http://' + config_data['tvault_primary_node'] + ':5000' + '/v2.0'
            admin_url = 'http://' + config_data['tvault_primary_node'] + ':35357' + '/v2.0'
            keystone.endpoints.create(config_data['region_name'], identity_service.id, public_url, admin_url, public_url)

            for tenant in keystone.tenants.list():
                if tenant.name == 'admin':
                    admin_tenant_id = tenant.id
                if tenant.name == 'service':
                    service_tenant_id = tenant.id                      
            for role in keystone.roles.list():
                if role.name == 'admin':
                    admin_role_id = role.id
                    
            user_id = _get_user_id_from_name(config_data['vcenter_username'])
            if user_id is None:
                keystone.users.create(config_data['vcenter_username'], config_data['vcenter_password'],
                                      email=None, tenant_id=admin_tenant_id, enabled=True) 
                user_id = _get_user_id_from_name(config_data['vcenter_username'])
                    
            try:           
                keystone.roles.add_user_role(user=user_id, role=admin_role_id, tenant=admin_tenant_id)
            except ksclient.exceptions.Conflict as exception:
                pass

        except Exception as exception:
            bottle.request.environ['beaker.session']['error_message'] = "Error: %(exception)s" %{'exception': exception,}
            raise exception                            
        
    else:
        command = ['sudo', 'service', 'keystone', 'stop'];
        subprocess.call(command, shell=False)
        command = ['sudo', 'sh', '-c', "echo manual > /etc/init/keystone.override"];
        subprocess.call(command, shell=False)
        
def configure_nova():
    if config_data['nodetype'] == 'controller' and config_data['configuration_type'] == 'vmware':
        #configure nova
        replace_line('/etc/nova/nova.conf', 'neutron_url = ', 'neutron_url = ' + 
                     "http://" + config_data['tvault_primary_node'] + ":9696") 
        replace_line('/etc/nova/nova.conf', 'neutron_admin_auth_url = ', 'neutron_admin_auth_url = ' + config_data['keystone_admin_url'])
        replace_line('/etc/nova/nova.conf', 'glance_api_servers = ', 'glance_api_servers = ' + 
                     config_data['tvault_primary_node'] + ":9292")      
        replace_line('/etc/nova/nova.conf', 'rabbit_host = ', 'rabbit_host = ' + config_data['tvault_primary_node'])  
        replace_line('/etc/nova/nova.conf', 'ec2_dmz_host = ', 'ec2_dmz_host = ' + config_data['tvault_primary_node'])                        
        replace_line('/etc/nova/nova.conf', 'vncserver_proxyclient_address = ', 'vncserver_proxyclient_address = ' + config_data['tvault_primary_node']) 
        replace_line('/etc/nova/nova.conf', 'vncserver_listen = ', 'vncserver_listen = ' + config_data['tvault_primary_node']) 
        replace_line('/etc/nova/nova.conf', 'xvpvncproxy_base_url = ', 'xvpvncproxy_base_url = ' + 
                     "http://" + config_data['tvault_primary_node'] + ":6081/console")                            
        replace_line('/etc/nova/nova.conf', 'novncproxy_base_url = ', 'novncproxy_base_url = ' + 
                     "http://" + config_data['tvault_primary_node'] + ":6080/vnc_auto.html")          
        replace_line('/etc/nova/nova.conf', 'sql_connection = ', 'sql_connection = ' + 
                     "mysql://root:52T8FVYZJse@" + config_data['tvault_primary_node'] + "/nova?charset=utf8")  
        replace_line('/etc/nova/nova.conf', 'my_ip = ', 'my_ip = ' + config_data['tvault_primary_node'])             
        replace_line('/etc/nova/nova.conf', 's3_host = ', 's3_host = ' + config_data['tvault_primary_node'])  
        replace_line('/etc/nova/nova.conf', 'auth_host = ', 'auth_host = ' + config_data['tvault_primary_node'])
        replace_line('/etc/nova/nova.conf', 'html5proxy_base_url = ', 'html5proxy_base_url = ' + 
                     "http://" + config_data['tvault_primary_node'] + ":6082/spice_auto.html")    
        replace_line('/etc/nova/nova.conf', 'log_dir = ', 'log_dir = ' + '/var/log/nova')
        
        replace_line('/etc/nova/nova.conf', 'host_password = ', 'host_password = ' + config_data['vcenter_password'])               
        replace_line('/etc/nova/nova.conf', 'host_username = ', 'host_username = ' + config_data['vcenter_username'])               
        replace_line('/etc/nova/nova.conf', 'host_ip = ', 'host_ip = ' + config_data['vcenter'])
        
        replace_line('/etc/nova/nova.conf', 'admin_user = ', 'admin_user = ' + config_data['vcenter_username'], starts_with=True)
        replace_line('/etc/nova/nova.conf', 'admin_password = ', 'admin_password = ' + config_data['vcenter_password'], starts_with=True)
        replace_line('/etc/nova/nova.conf', 'neutron_admin_username = ', 'neutron_admin_username = ' + config_data['vcenter_username'])
        replace_line('/etc/nova/nova.conf', 'neutron_admin_password = ', 'neutron_admin_password = ' + config_data['vcenter_password'])
        
        """
        ConfigParser will not work for multiple values option
        Config = ConfigParser.RawConfigParser()
        Config.read('/etc/nova/nova.conf')
        Config.set('keystone_authtoken','admin_user', config_data['vcenter_username'])
        Config.set('keystone_authtoken','admin_password', config_data['vcenter_password'])
        Config.set('DEFAULT','neutron_admin_username', config_data['vcenter_username'])
        Config.set('DEFAULT','neutron_admin_password', config_data['vcenter_password'])        
        with open('/etc/nova/nova.conf', 'wb') as configfile:
            Config.write(configfile)
        """         
        
        
        command = ['sudo', 'rm', "/etc/init/nova-compute.override"];
        subprocess.call(command, shell=False)                                                 
        command = ['sudo', 'rm', "/etc/init/nova-cert.override"];
        subprocess.call(command, shell=False)   
        command = ['sudo', 'rm', "/etc/init/nova-api.override"];
        subprocess.call(command, shell=False)   
        command = ['sudo', 'rm', "/etc/init/nova-consoleauth.override"];
        subprocess.call(command, shell=False)   
        command = ['sudo', 'rm', "/etc/init/nova-conductor.override"];
        subprocess.call(command, shell=False)   
        command = ['sudo', 'rm', "/etc/init/nova-scheduler.override"];
        subprocess.call(command, shell=False)   
        command = ['sudo', 'rm', "/etc/init/nova-novncproxy.override"];
        subprocess.call(command, shell=False)   
        command = ['sudo', 'rm', "/etc/init/nova-xvpvncproxy.override"];
        subprocess.call(command, shell=False) 
        
        command = ['sudo', 'service', 'nova-compute', 'restart'];
        subprocess.call(command, shell=False)
        command = ['sudo', 'service', 'nova-cert', 'restart'];
        subprocess.call(command, shell=False)
        command = ['sudo', 'service', 'nova-api', 'restart'];
        subprocess.call(command, shell=False)
        command = ['sudo', 'service', 'nova-consoleauth', 'restart'];
        subprocess.call(command, shell=False)
        command = ['sudo', 'service', 'nova-conductor', 'restart'];
        subprocess.call(command, shell=False)
        command = ['sudo', 'service', 'nova-scheduler', 'restart'];
        subprocess.call(command, shell=False)
        command = ['sudo', 'service', 'nova-novncproxy', 'restart'];
        subprocess.call(command, shell=False)
        command = ['sudo', 'service', 'nova-xvpvncproxy', 'restart'];
        subprocess.call(command, shell=False)
        
        try:
            keystone = ksclient.Client(auth_url=config_data['keystone_admin_url'], 
                                       insecure=True,
                                       username=config_data['admin_username'], 
                                       password=config_data['admin_password'], 
                                       tenant_name=config_data['admin_tenant_name'])                
            #delete orphan nova services
            services = keystone.services.list()
            endpoints = keystone.endpoints.list()
            for service in services:
                if service.type == 'compute' or service.type == 'computev3':
                    for endpoint in endpoints:
                        if endpoint.service_id == service.id and endpoint.region == config_data['region_name']:
                            keystone.services.delete(service.id)
            #create service and endpoint
            compute_service_v2 = keystone.services.create('nova', 'compute', 'Trilio Vault Compute Service')
            public_url = 'http://' + config_data['tvault_primary_node'] + ':8774' + '/v2/$(tenant_id)s'
            keystone.endpoints.create(config_data['region_name'], compute_service_v2.id, public_url, public_url, public_url)
            
            compute_service_v3 = keystone.services.create('trilioVaultCS-V3', 'computev3', 'Trilio Vault Compute Service')
            public_url = 'http://' + config_data['tvault_primary_node'] + ':8774' + '/v3/$(tenant_id)s'
            keystone.endpoints.create(config_data['region_name'], compute_service_v3.id, public_url, public_url, public_url)
        except Exception as exception:
            bottle.request.environ['beaker.session']['error_message'] = "Error: %(exception)s" %{'exception': exception,}
            raise exception                            

    else:
        command = ['sudo', 'service', 'nova-compute', 'stop'];
        subprocess.call(command, shell=False)
        command = ['sudo', 'service', 'nova-cert', 'stop'];
        subprocess.call(command, shell=False)
        command = ['sudo', 'service', 'nova-api', 'stop'];
        subprocess.call(command, shell=False)
        command = ['sudo', 'service', 'nova-consoleauth', 'stop'];
        subprocess.call(command, shell=False)
        command = ['sudo', 'service', 'nova-conductor', 'stop'];
        subprocess.call(command, shell=False)
        command = ['sudo', 'service', 'nova-scheduler', 'stop'];
        subprocess.call(command, shell=False)
        command = ['sudo', 'service', 'nova-novncproxy', 'stop'];
        subprocess.call(command, shell=False)
        command = ['sudo', 'service', 'nova-xvpvncproxy', 'stop'];
        subprocess.call(command, shell=False)
                                            
        command = ['sudo', 'sh', '-c', "echo manual > /etc/init/nova-compute.override"];
        subprocess.call(command, shell=False)                                                 
        command = ['sudo', 'sh', '-c', "echo manual > /etc/init/nova-cert.override"];
        subprocess.call(command, shell=False)   
        command = ['sudo', 'sh', '-c', "echo manual > /etc/init/nova-api.override"];
        subprocess.call(command, shell=False)   
        command = ['sudo', 'sh', '-c', "echo manual > /etc/init/nova-consoleauth.override"];
        subprocess.call(command, shell=False)   
        command = ['sudo', 'sh', '-c', "echo manual > /etc/init/nova-conductor.override"];
        subprocess.call(command, shell=False)   
        command = ['sudo', 'sh', '-c', "echo manual > /etc/init/nova-scheduler.override"];
        subprocess.call(command, shell=False)   
        command = ['sudo', 'sh', '-c', "echo manual > /etc/init/nova-novncproxy.override"];
        subprocess.call(command, shell=False)   
        command = ['sudo', 'sh', '-c', "echo manual > /etc/init/nova-xvpvncproxy.override"];
        subprocess.call(command, shell=False)   

def configure_neutron():
    if config_data['nodetype'] == 'controller' and config_data['configuration_type'] == 'vmware':
        #configure neutron
        replace_line('/etc/neutron/neutron.conf', 'rabbit_host = ', 'rabbit_host = ' + config_data['tvault_primary_node'])  
        replace_line('/etc/neutron/neutron.conf', 'auth_host = ', 'auth_host = ' + config_data['tvault_primary_node'])  
        replace_line('/etc/neutron/neutron.conf', 'log_dir = ', 'log_dir = ' + '/var/log/neutron')
                               
        replace_line('/etc/neutron/metadata_agent.ini', 'nova_metadata_ip = ', 'nova_metadata_ip = ' + config_data['tvault_primary_node']) 
        replace_line('/etc/neutron/metadata_agent.ini', 'auth_url = ', 'auth_url = ' + config_data['keystone_public_url'])
        
        replace_line('/etc/neutron/plugins/ml2/ml2_conf.ini', 'connection = ', 'connection = ' + 
                     "mysql://root:52T8FVYZJse@" + config_data['tvault_primary_node'] + "/neutron_ml2?charset=utf8")  
        replace_line('/etc/neutron/plugins/ml2/ml2_conf.ini', 'local_ip = ', 'local_ip = ' + config_data['tvault_primary_node'])

        replace_line('/etc/neutron/neutron.conf', 'admin_user = ', 'admin_user = ' + config_data['vcenter_username'])
        replace_line('/etc/neutron/neutron.conf', 'admin_password = ', 'admin_password = ' + config_data['vcenter_password'])

        replace_line('/etc/neutron/metadata_agent.ini', 'admin_user = ', 'admin_user = ' + config_data['vcenter_username'])
        replace_line('/etc/neutron/metadata_agent.ini', 'admin_password = ', 'admin_password = ' + config_data['vcenter_password'])
        
        """
        ConfigParser doesn't support multiple values
        Config = ConfigParser.RawConfigParser()
        Config.read('/etc/neutron/neutron.conf')
        Config.set('keystone_authtoken','admin_user', config_data['vcenter_username'])
        Config.set('keystone_authtoken','admin_password', config_data['vcenter_password'])
        with open('/etc/neutron/neutron.conf', 'wb') as configfile:
            Config.write(configfile)  
            
        Config = ConfigParser.RawConfigParser()
        Config.read('/etc/neutron/metadata_agent.ini')
        Config.set('DEFAULT','admin_user', config_data['vcenter_username'])
        Config.set('DEFAULT','admin_password', config_data['vcenter_password'])
        with open('/etc/neutron/metadata_agent.ini', 'wb') as configfile:
            Config.write(configfile)
        """              
        
        command = ['sudo', 'rm', "/etc/init/neutron-dhcp-agent.override"];
        subprocess.call(command, shell=False)    
        command = ['sudo', 'rm', "/etc/init/neutron-metadata-agent.override"];
        subprocess.call(command, shell=False)    
        command = ['sudo', 'rm', "/etc/init/neutron-plugin-openvswitch-agent.override"];
        subprocess.call(command, shell=False)    
        command = ['sudo', 'rm', "/etc/init/neutron-l3-agent.override"];
        subprocess.call(command, shell=False)    
        command = ['sudo', 'rm', "/etc/init/neutron-server.override"];
        subprocess.call(command, shell=False)
        
        command = ['sudo', 'service', 'neutron-dhcp-agent', 'restart'];
        subprocess.call(command, shell=False)
        command = ['sudo', 'service', 'neutron-metadata-agent', 'restart'];
        subprocess.call(command, shell=False)
        command = ['sudo', 'service', 'neutron-plugin-openvswitch-agent', 'restart'];
        subprocess.call(command, shell=False)
        command = ['sudo', 'service', 'neutron-l3-agent', 'restart'];
        subprocess.call(command, shell=False)
        command = ['sudo', 'service', 'neutron-server', 'restart'];
        subprocess.call(command, shell=False)        
              
        try:
            keystone = ksclient.Client(auth_url=config_data['keystone_admin_url'], 
                                       insecure=True,
                                       username=config_data['admin_username'], 
                                       password=config_data['admin_password'], 
                                       tenant_name=config_data['admin_tenant_name'])               
            #delete orphan neutron services
            services = keystone.services.list()
            endpoints = keystone.endpoints.list()
            for service in services:
                if service.type == 'network':
                    for endpoint in endpoints:
                        if endpoint.service_id == service.id and endpoint.region == config_data['region_name']:
                            keystone.services.delete(service.id)
            #create service and endpoint
            network_service = keystone.services.create('neutron', 'network', 'Trilio Vault Network Service')
            public_url = 'http://' + config_data['tvault_primary_node'] + ':9696' + '/'
            keystone.endpoints.create(config_data['region_name'], network_service.id, public_url, public_url, public_url)

        except Exception as exception:
            bottle.request.environ['beaker.session']['error_message'] = "Error: %(exception)s" %{'exception': exception,}
            raise exception                            
    else:
        command = ['sudo', 'service', 'neutron-dhcp-agent', 'stop'];
        subprocess.call(command, shell=False)
        command = ['sudo', 'service', 'neutron-metadata-agent', 'stop'];
        subprocess.call(command, shell=False)
        command = ['sudo', 'service', 'neutron-plugin-openvswitch-agent', 'stop'];
        subprocess.call(command, shell=False)
        command = ['sudo', 'service', 'neutron-l3-agent', 'stop'];
        subprocess.call(command, shell=False)
        command = ['sudo', 'service', 'neutron-server', 'stop'];
        subprocess.call(command, shell=False)
        
        command = ['sudo', 'sh', '-c', "echo manual > /etc/init/neutron-dhcp-agent.override"];
        subprocess.call(command, shell=False)    
        command = ['sudo', 'sh', '-c', "echo manual > /etc/init/neutron-metadata-agent.override"];
        subprocess.call(command, shell=False)    
        command = ['sudo', 'sh', '-c', "echo manual > /etc/init/neutron-plugin-openvswitch-agent.override"];
        subprocess.call(command, shell=False)    
        command = ['sudo', 'sh', '-c', "echo manual > /etc/init/neutron-l3-agent.override"];
        subprocess.call(command, shell=False)    
        command = ['sudo', 'sh', '-c', "echo manual > /etc/init/neutron-server.override"];
        subprocess.call(command, shell=False)           

def configure_glance():
    if config_data['nodetype'] == 'controller' and config_data['configuration_type'] == 'vmware':
        #configure glance
        replace_line('/etc/glance/glance-api.conf', 'sql_connection = ', 'sql_connection = ' + 
                     "mysql://root:52T8FVYZJse@" + config_data['tvault_primary_node'] + "/glance?charset=utf8")
        replace_line('/etc/glance/glance-api.conf', 'rabbit_host = ', 'rabbit_host = ' + config_data['tvault_primary_node'])  
        replace_line('/etc/glance/glance-api.conf', 'auth_uri = ', 'auth_uri = ' + 
                     "http://" + config_data['tvault_primary_node'] + ":5000/")                      
        replace_line('/etc/glance/glance-api.conf', 'auth_host = ', 'auth_host = ' + config_data['tvault_primary_node']) 
        
        replace_line('/etc/glance/glance-cache.conf', 'auth_url = ', 'auth_url = ' + config_data['keystone_admin_url'])
        
        replace_line('/etc/glance/glance-registry.conf', 'sql_connection = ', 'sql_connection = ' + 
                     "mysql://root:52T8FVYZJse@" + config_data['tvault_primary_node'] + "/glance?charset=utf8")            
        replace_line('/etc/glance/glance-registry.conf', 'auth_uri = ', 'auth_uri = ' + 
                     "http://" + config_data['tvault_primary_node'] + ":5000/")      
        replace_line('/etc/glance/glance-registry.conf', 'auth_host = ', 'auth_host = ' + config_data['tvault_primary_node']) 
        
        Config = ConfigParser.RawConfigParser()
        Config.read('/etc/glance/glance-api.conf')
        Config.set('keystone_authtoken','admin_user', config_data['vcenter_username'])
        Config.set('keystone_authtoken','admin_password', config_data['vcenter_password'])
        with open('/etc/glance/glance-api.conf', 'wb') as configfile:
            Config.write(configfile) 
            
        Config = ConfigParser.RawConfigParser()
        Config.read('/etc/glance/glance-cache.conf')
        Config.set('DEFAULT','admin_user', config_data['vcenter_username'])
        Config.set('DEFAULT','admin_password', config_data['vcenter_password'])
        with open('/etc/glance/glance-cache.conf', 'wb') as configfile:
            Config.write(configfile)   
            
        Config = ConfigParser.RawConfigParser()
        Config.read('/etc/glance/glance-registry.conf')
        Config.set('keystone_authtoken','admin_user', config_data['vcenter_username'])
        Config.set('keystone_authtoken','admin_password', config_data['vcenter_password'])
        with open('/etc/glance/glance-registry.conf', 'wb') as configfile:
            Config.write(configfile)                                 
        
        command = ['sudo', 'rm', "/etc/init/glance-registry.override"];
        subprocess.call(command, shell=False)      
        command = ['sudo', 'rm', "/etc/init/glance-api.override"];
        subprocess.call(command, shell=False)  
        
        command = ['sudo', 'service', 'glance-registry', 'restart'];
        subprocess.call(command, shell=False)
        command = ['sudo', 'service', 'glance-api', 'restart'];
        subprocess.call(command, shell=False)        
        
        try:
            keystone = ksclient.Client(auth_url=config_data['keystone_admin_url'], 
                                       insecure=True,
                                       username=config_data['admin_username'], 
                                       password=config_data['admin_password'], 
                                       tenant_name=config_data['admin_tenant_name'])               
            #delete orphan glance services
            services = keystone.services.list()
            endpoints = keystone.endpoints.list()
            for service in services:
                if service.type == 'image':
                    for endpoint in endpoints:
                        if endpoint.service_id == service.id and endpoint.region == config_data['region_name']:
                            keystone.services.delete(service.id)
            #create service and endpoint
            image_service = keystone.services.create('glance', 'image', 'Trilio Vault Image Service')
            public_url = 'http://' + config_data['tvault_primary_node'] + ':9292'
            keystone.endpoints.create(config_data['region_name'], image_service.id, public_url, public_url, public_url)

        except Exception as exception:
            bottle.request.environ['beaker.session']['error_message'] = "Error: %(exception)s" %{'exception': exception,}
            raise exception                            

    else:
        #glance
        command = ['sudo', 'service', 'glance-registry', 'stop'];
        subprocess.call(command, shell=False)
        command = ['sudo', 'service', 'glance-api', 'stop'];
        subprocess.call(command, shell=False)
        
        command = ['sudo', 'sh', '-c', "echo manual > /etc/init/glance-registry.override"];
        subprocess.call(command, shell=False)      
        command = ['sudo', 'sh', '-c', "echo manual > /etc/init/glance-api.override"];
        subprocess.call(command, shell=False) 
        
def configure_horizon():
    if config_data['nodetype'] == 'controller': 
        #configure horizon
        if config_data['configuration_type'] == 'vmware':
            replace_line('/opt/stack/horizon/openstack_dashboard/local/local_settings.py',
                         'OPENSTACK_HOST = ', 'OPENSTACK_HOST = ' + '"' + config_data['tvault_primary_node'] + '"')
        elif config_data['configuration_type'] == 'openstack':
            replace_line('/opt/stack/horizon/openstack_dashboard/local/local_settings.py',
                         'OPENSTACK_HOST = ', 'OPENSTACK_HOST = ' + '"' + config_data['keystone_host'] + '"')
            if 'https' in config_data['keystone_public_url']: 
                replace_line('/opt/stack/horizon/openstack_dashboard/local/local_settings.py',
                             'OPENSTACK_KEYSTONE_URL = ', 'OPENSTACK_KEYSTONE_URL = "https://%s:5000/v2.0" % OPENSTACK_HOST')
                replace_line('/opt/stack/horizon/openstack_dashboard/local/local_settings.py',
                             'OPENSTACK_SSL_NO_VERIFY = ', 'OPENSTACK_SSL_NO_VERIFY = True')
            
        command = ['sudo', 'rm', "/etc/init/apache2.override"];
        subprocess.call(command, shell=False)
        
        command = ['sudo', 'service', 'apache2', 'restart'];
        subprocess.call(command, shell=False)
    else:
         if config_data['configuration_type'] == 'openstack':
            replace_line('/opt/stack/horizon/openstack_dashboard/local/local_settings.py',
                         'OPENSTACK_HOST = ', 'OPENSTACK_HOST = ' + '"' + config_data['keystone_host'] + '"')
            if 'https' in config_data['keystone_public_url']: 
                replace_line('/opt/stack/horizon/openstack_dashboard/local/local_settings.py',
                             'OPENSTACK_KEYSTONE_URL = ', 'OPENSTACK_KEYSTONE_URL = "https://%s:5000/v2.0" % OPENSTACK_HOST')
                replace_line('/opt/stack/horizon/openstack_dashboard/local/local_settings.py',
                             'OPENSTACK_SSL_NO_VERIFY = ', 'OPENSTACK_SSL_NO_VERIFY = True')

            command = ['sudo', 'rm', "/etc/init/apache2.override"];
            subprocess.call(command, shell=False)

            command = ['sudo', 'service', 'apache2', 'restart'];
            subprocess.call(command, shell=False)
         else:
              command = ['sudo', 'service', 'apache2', 'stop'];
              subprocess.call(command, shell=False)             
              command = ['sudo', 'sh', '-c', "echo manual > /etc/init/apache2.override"];
              subprocess.call(command, shell=False)

@bottle.route('/services/<service_display_name>/<action>')
@authorize()
def service_action(service_display_name, action):
    bottle.request.environ['beaker.session']['error_message'] = ''
    services = {'api_service' : 'wlm-api',
                'scheduler_service' : 'wlm-scheduler',
                'workloads_service' : 'wlm-workloads',
                'inventory_service' : 'nova-api',
                'tvault_gui_service' :'tvault-gui',}  
    try:
        Config = ConfigParser.RawConfigParser()
        Config.read('/etc/tvault-config/tvault-config.conf')
        config_data = dict(Config._defaults)
        config_status = config_data.get('config_status', 'not_configured')
        nodetype = config_data.get('nodetype', 'not_configured')
    except Exception as exception:
        config_status = 'not_configured'
        nodetype = 'not_configured'  
        
    try:
        if service_display_name not in services:
            bottle.redirect("/services")
        if config_status == 'not_configured':
            bottle.redirect("/services")
        if nodetype != 'controller' and service_display_name in ['api_service','scheduler_service','inventory_service',]:
            bottle.redirect("/services")
        if action not in ['start', 'stop']:
            bottle.redirect("/services")
        command = ['sudo', 'service', services[service_display_name], action];
        subprocess.call(command, shell=False)        
    except Exception as exception:
        bottle.request.environ['beaker.session']['error_message'] = "Error: %(exception)s" %{'exception': exception,}
        raise exception
        
    bottle.redirect("/services_openstack")
    bottle.request.environ['beaker.session']['error_message'] = ''    
    return dict(error_message = bottle.request.environ['beaker.session']['error_message'])
           
@bottle.route('/services')
@authorize()
def services():
    bottle.redirect("/services_openstack")
    bottle.request.environ['beaker.session']['error_message'] = ''    
    return dict(error_message = bottle.request.environ['beaker.session']['error_message'])                         

@bottle.route('/services_openstack')
@bottle.view('services_page_vmware')
@authorize()
def services_vmware():
    bottle.request.environ['beaker.session']['error_message'] = ''
    services = {'api_service' : 'wlm-api',
                'scheduler_service' : 'wlm-scheduler',
                'workloads_service' : 'wlm-workloads',
                } 
    
    config_status = 'not_configured'
    nodetype = 'not_configured'
    try:
        Config = ConfigParser.RawConfigParser()
        Config.read('/etc/tvault-config/tvault-config.conf')
        config_data = dict(Config._defaults)
        config_status = config_data.get('config_status', 'not_configured')
        nodetype = config_data.get('nodetype', 'not_configured')
        
        command = ['sudo', 'initctl', 'list'];
        output = subprocess.check_output(command, shell=False)
    except Exception as exception:
        output = ''    
    
    output_lines = output.split('\n')
    for service_display_name, service_name in services.iteritems():
        if config_status == 'not_configured':
            services[service_display_name] = 'Not Configured'
            continue            
        if nodetype != 'controller' and service_display_name in ['api_service','scheduler_service','inventory_service',]:
            services[service_display_name] = 'Not Applicable'
            continue        
        for line in output_lines:
            if service_name in line:
                if 'running' in line:
                    services[service_display_name] = 'Running'
                elif 'stop' in line:
                    services[service_display_name] = 'Stopped'
                else:
                    services[service_display_name] = 'Unknown'
                break
        if services[service_display_name] not in ['Running', 'Stopped', 'Unknown']:
            services[service_display_name] = 'Not Applicable'

                   
    services['error_message'] = bottle.request.environ['beaker.session']['error_message']
    return services      

@bottle.route('/troubleshooting')
@authorize()
def troubleshooting():
    bottle.redirect("/troubleshooting_" + TVAULT_CONFIGURATION_TYPE)
    bottle.request.environ['beaker.session']['error_message'] = ''    
    return dict(error_message = bottle.request.environ['beaker.session']['error_message']) 

"""############################ tvault Troubleshooting ########################"""

def get_default_reset_cbt_output():
    reset_cbt_output = 'Specify comma seperated virtual machine names.'
    reset_cbt_output = reset_cbt_output + '\n\n' + 'Reset involves the following operations:'
    reset_cbt_output = reset_cbt_output + '\n\t' + 'Remove any previous snapshots'
    reset_cbt_output = reset_cbt_output + '\n\t' + 'Set changed block tracking to false'
    reset_cbt_output = reset_cbt_output + '\n\t' + 'Create a temporary snapshot'
    reset_cbt_output = reset_cbt_output + '\n\t' + 'Remove the temporary snapshot'
    reset_cbt_output = reset_cbt_output + '\n\n' + "If the VM was in 'powered on' state before initiating the reset, *-ctk.vmdk needs to be removed manually from the datastores."
    return reset_cbt_output  
 
@bottle.route('/troubleshooting_' + TVAULT_CONFIGURATION_TYPE)
@bottle.view('troubleshooting_page_' + TVAULT_CONFIGURATION_TYPE)
@authorize()
def troubleshooting_vmware():
    bottle.request.environ['beaker.session']['error_message'] = ''
    values = {}
    values['ping_output'] = ''
    values['reset_cbt_output'] = get_default_reset_cbt_output()
    values['error_message'] = bottle.request.environ['beaker.session']['error_message']
    return values

@bottle.post('/troubleshooting_ping')
@bottle.view('troubleshooting_page_' + TVAULT_CONFIGURATION_TYPE)
@authorize()
def troubleshooting_vmware():
    bottle.request.environ['beaker.session']['error_message'] = ''
    values = {}
    values['reset_cbt_output'] = get_default_reset_cbt_output()
    try:
        values['ping_address'] = bottle.request.POST['ping_address']
        command = ['sudo', 'ping', '-c 6', values['ping_address']];
        output = subprocess.check_output(command, shell=False)                
        values['ping_output'] = output
    except subprocess.CalledProcessError as ex:
        values['ping_output'] = str(ex.output)
    except Exception as ex:
        values['ping_output'] = str(ex)
    
    values['error_message'] = bottle.request.environ['beaker.session']['error_message']
    return values


@bottle.post('/troubleshooting_vmware_reset_cbt')
@bottle.view('troubleshooting_page_vmware')
@authorize()
def troubleshooting_vmware():
    bottle.request.environ['beaker.session']['error_message'] = ''
    values = {}
    values['ping_output'] = ''
    output = ''
    try:
        values['reset_cbt_vms'] = bottle.request.POST['reset_cbt_vms']
        Config = ConfigParser.RawConfigParser()
        Config.read('/etc/tvault-config/tvault-config.conf')
        config_data = dict(Config._defaults)
        config_status = config_data.get('config_status', 'not_configured')
        vcenter = config_data.get('vcenter', 'not_configured')
        vcenter_username = config_data.get('vcenter_username', 'not_configured')
        vcenter_password = config_data.get('vcenter_password', 'not_configured')
        if config_status == 'not_configured':
            raise Exception("Trilio Vault Appliance is not configured")
                
        from workloadmgr.virt.vmwareapi.driver import VMwareAPISession
        from workloadmgr.virt.vmwareapi import vim
        from workloadmgr.virt.vmwareapi import vm_util
        from workloadmgr.virt.vmwareapi import vim_util

        session = VMwareAPISession(host_ip = vcenter, 
                                   username = vcenter_username, 
                                   password = vcenter_password, 
                                   retry_count = 3, 
                                   scheme="https")           
        
        output = 'Virtual Machine(s): ' + values['reset_cbt_vms']
        for vm_name in values['reset_cbt_vms'].split(","):
            output = output + '\n' + 'Resetting CBT for ' + vm_name
            vm_refs = vm_util.get_vms_ref_from_name(session, vm_name)
            if not vm_refs:
                output = output + '\n' + "ERROR: Virtual Machine '" + vm_name + "' not found."
                continue
            if len(vm_refs) == 0:
                output = output + '\n' + "ERROR: Virtual Machine '" + vm_name + "' not found."
                continue  
            if len(vm_refs) != 1:
                output = output + '\n' + "ERROR: Multiple Virtual Machines with name '" + vm_name + "' found."
                continue 
            vm_ref =  vm_refs[0]               
            rootsnapshot = session._call_method(vim_util,"get_dynamic_property", vm_ref, "VirtualMachine", "rootSnapshot")
            if rootsnapshot:
                remove_snapshot_task = session._call_method(session._get_vim(), 
                                                                  "RemoveSnapshot_Task", 
                                                                  rootsnapshot[0][0], 
                                                                  removeChildren=True)
                session._wait_for_task("12345", remove_snapshot_task)
                output = output + '\n' + 'Removed previous snapshots for ' + vm_name                

            client_factory = session._get_vim().client.factory
            config_spec = client_factory.create('ns0:VirtualMachineConfigSpec')
            config_spec.changeTrackingEnabled = False
            reconfig_task = session._call_method( session._get_vim(),
                                                        "ReconfigVM_Task", vm_ref,
                                                        spec=config_spec)
            session._wait_for_task("12345", reconfig_task)
            output = output + '\n' + 'Disabled changed block tracking for ' + vm_name
            
            snapshot_task = session._call_method(
                            session._get_vim(),
                            "CreateSnapshot_Task", vm_ref,
                            name="snapshot_to_reset_cbt",
                            description="Snapshot taken to reset cbt",
                            memory=False,
                            quiesce=True)
            task_info = session._wait_for_task("12345", snapshot_task)
            snapshot_ref = task_info.result
            if not snapshot_ref:
                raise Exception("Failed to create temporary snapshot for Virtul Machine '" + vm_name + "'")            
            output = output + '\n' + 'Created temporary snapshot for ' + vm_name                
            remove_snapshot_task = session._call_method(session._get_vim(), 
                                                              "RemoveSnapshot_Task", 
                                                              snapshot_ref, 
                                                              removeChildren=True)
            session._wait_for_task("12345", remove_snapshot_task)                                                                   
            output = output + '\n' + 'Removed temporary snapshot for ' + vm_name 

        values['reset_cbt_output'] = output
    except subprocess.CalledProcessError as ex:
        values['reset_cbt_output'] = output + '\n' + str(ex.output)
    except Exception as ex:
        values['reset_cbt_output'] = output + '\n' + str(ex)
    
    values['error_message'] = bottle.request.environ['beaker.session']['error_message']
    return values

@bottle.route('/logs')
@bottle.view('logs_page_vmware')
@authorize()
def logs():
    bottle.request.environ['beaker.session']['error_message'] = ''    
    return dict(error_message = bottle.request.environ['beaker.session']['error_message']) 

@bottle.route('/logs_openstack')
@bottle.view('logs_page_vmware')
@authorize()
def logs_openstack():
    bottle.request.environ['beaker.session']['error_message'] = ''    
    return dict(error_message = bottle.request.environ['beaker.session']['error_message'])
            
@bottle.route('/configure')
@authorize()
def configure_form():
    bottle.redirect(bottle.request.url + '_' + TVAULT_CONFIGURATION_TYPE)

@bottle.route('/configure_vmware')
@bottle.view('configure_form_vmware')
@authorize()
def configure_form_vmware():
    if not 'error_message' in bottle.request.environ['beaker.session']:
       bottle.request.environ['beaker.session']['error_message'] = ''
    Config = ConfigParser.RawConfigParser()
    Config.read('/etc/tvault-config/tvault-config.conf')
    config_data = dict(Config._defaults)

    config_database = {}
    if 'sql_connection' in config_data:       
       engine = create_engine(config_data['sql_connection'])
       for row in engine.execute(select([models.Settings.__table__]).where(models.Settings.__table__.columns.project_id=='Configurator')):
           items = dict(row.items())
           config_database[items['name']] = items['value']      
       config_database['refresh'] = 0 
       if config_data['nodetype'] == 'additional':
          config_database['nodetype'] = config_data['nodetype']
    else:
         config_database['refresh'] = 1

    timezone = get_localzone().zone
    config_database['timezones'] = all_timezones
    config_database['timezone'] = timezone
    config_database['error_message'] = bottle.request.environ['beaker.session']['error_message']
    return config_database

@bottle.route('/configure_openstack')
@bottle.view('configure_form_openstack')
@authorize()
def configure_form_openstack():
    if not 'error_message' in bottle.request.environ['beaker.session']:
       bottle.request.environ['beaker.session']['error_message'] = ''
    Config = ConfigParser.RawConfigParser()
    Config.read('/etc/tvault-config/tvault-config.conf')
    config_data = dict(Config._defaults)
    timezone = get_localzone().zone
    config_data['timezones'] = all_timezones
    config_data['timezone'] = timezone
    if 'storage_nfs_options' not in config_data:
       config_data['storage_nfs_options'] = 'nolock,soft,timeo=180,intr'
    roles = ['_member_','Member','member']
    config_data['roles'] = roles
    if 'trustee_role' not in config_data:
       config_data['trustee_role'] = ''
    config_data['error_message'] = bottle.request.environ['beaker.session']['error_message']
    return config_data

@bottle.route('/task_status_vmware')
@bottle.view('task_status_vmware')
@authorize()
def task_status_vmware():
    bottle.request.environ['beaker.session']['error_message'] = ''
    config_data['error_message'] = bottle.request.environ['beaker.session']['error_message']    
    return config_data

@bottle.route('/task_status_openstack')
@bottle.view('task_status_openstack')
@authorize()
def task_status():
    bottle.request.environ['beaker.session']['error_message'] = ''
    config_data['error_message'] = bottle.request.environ['beaker.session']['error_message']
    return config_data

@bottle.route('/configure_host')
@authorize()
def configure_host():
    # Python code to configure storage
    try:
        #configure host
        prev_hostname = socket.gethostname()
        hostname = config_data['guest_name']
        fh, abs_path = mkstemp()
        new_file = open(abs_path,'w')
        new_file.write(hostname+'\n')
        new_file.close()
        close(fh)
        command = ['sudo', 'apt-get', 'remove', '--purge', "rabbitmq-server", '-y'];
        subprocess.call(command, shell=False)
        command = ['sudo', 'mv', abs_path, "/etc/hostname"];
        subprocess.call(command, shell=False)
        os.chmod('/etc/hostname', 0644)
        command = ['sudo', 'chown', 'root:root', "/etc/hostname"];
        command = ['sudo', 'service', 'hostname', 'restart']
        subprocess.call(command, shell=False)
        command = ['sudo', 'service', 'networking', 'restart']
        subprocess.call(command, shell=False)

        fh, abs_path = mkstemp()
        new_file = open(abs_path,'w')
        new_file.write('127.0.0.1 localhost\n')
        new_file.write('127.0.0.1 '+socket.gethostname()+'\n')
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
   
        config_data['sql_connection'] = 'mysql://root:' + TVAULT_SERVICE_PASSWORD + '@' + config_data['floating_ipaddress'] + '/workloadmgr?charset=utf8'
        engine = create_engine(config_data['sql_connection'])
        update = models.Service.__table__.update().where(models.Service.__table__.columns.host == prev_hostname).\
                 values({'host' : socket.gethostname()})
        engine.execute(update)
               
        if len(config_data['name_server']):
            fh, abs_path = mkstemp()
            new_file = open(abs_path,'w')
            new_file.write('nameserver ' + config_data['name_server'] + '\n')
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
            try:
                #dhcp
                replace_line('/etc/dhcp/dhclient.conf', 'prepend domain-name-servers ', 
                             'prepend domain-name-servers ' + config_data['name_server'] + ';')
                command = ['sudo', 'dhclient']
                subprocess.call(command, shell=False)                 
            except:
                pass

        def cleanup_mount(path):
            try:
                command = ['sudo', 'umount', '-f', path]
                subprocess.call(command, shell=False)
            except Exception as exception:
                pass
        
            try:
                command = ['sudo', 'umount', '-f', path]
                subprocess.call(command, shell=False)
            except Exception as exception:
                pass           
        
            try:
                command = ['sudo', 'umount', '-l', path]
                subprocess.call(command, shell=False)
            except Exception as exception:
                pass                

            try:
                command = ['sudo', 'service', 'tvault-swift', 'stop'];
                subprocess.call(command, shell=False)
            except:
                   pass

        def mount_share(mountpath, nfsshare, nfsoptions):
            with open('/proc/mounts','r') as procfile:
                mounts = [{line.split()[1]:line.split()[0]}
                          for line in procfile.readlines() if line.split()[1] == mountpath]
            setting_str = nfsshare+ \
                              '        %s        nfs     %s  0       0\n' % (mountpath, nfsoptions)
            if len(mounts) == 0 or mounts[0].get(mountpath, None) != nfsshare:
                command = ['timeout', '-sKILL', '30' , 'sudo', 'mount', '-o', nfsoptions, nfsshare, mountpath]
                subprocess.check_call(command, shell=False)
            else:
                found = 0
                with open('/etc/fstab', 'r') as ins:
                    for line in ins:
                        if line == setting_str:
                           found = 1
                           break
                if found == 0:
                    fs_file = open('/etc/fstab', 'a')
                    fs_file.write(setting_str)
                    fs_file.close()

                try:
                    temp_file_name = os.path.join(mountpath, str(uuid.uuid4()) + '_test.txt')
                    command = ['sudo', '-u', WLM_USER, 'touch', temp_file_name]
                    subprocess.check_call(command, shell=False)
                    command = 'echo Test | sudo -u '+WLM_USER+' tee '+temp_file_name
                    subprocess.check_call(command, shell=True)
                    command = 'sudo -u '+WLM_USER+' cat '+temp_file_name
                    subprocess.check_call(command, shell=True)
                    command = ['sudo', '-u', WLM_USER, 'rm', '-rf', temp_file_name]
                    subprocess.check_call(command, shell=False)
                except Exception as exception:
                    command = ['sudo', '-u', WLM_USER, 'rm', '-rf', temp_file_name]
                    subprocess.check_call(command, shell=False)
                    raise Exception("Failed to verify R/W permissions of the NFS export: " + nfsshare)

        tmpfs_path = os.path.join(config_data['vault_data_directory_old'], "tmpfs")
        if os.path.exists(tmpfs_path) and os.path.ismount(tmpfs_path):
            cleanup_mount(tmpfs_path)

        if os.path.exists(config_data['vault_data_directory_old']) and \
            os.path.ismount(config_data['vault_data_directory_old']):
            cleanup_mount(config_data['vault_data_directory_old'])

        cleanup_mount(os.path.join(config_data['vault_data_directory']))
        if os.path.exists(config_data['vault_data_directory']):
            for d in os.listdir(config_data['vault_data_directory']):
                if os.path.ismount(os.path.join(config_data['vault_data_directory'], d)):
                    cleanup_mount(os.path.join(config_data['vault_data_directory'], d))

        nfsoptions = config_data['storage_nfs_options']
        for idx, nfsshare in enumerate(str.split(config_data['storage_nfs_export'], ',')):
            if nfsshare == '' or (config_data['swift_auth_version'] == 'KEYSTONE' or config_data['swift_auth_version'] == 'TEMPAUTH'):
               continue
            replace_line('/etc/hosts.allow', 'rpcbind : ', 'rpcbind : ' + str.split(nfsshare, ':')[0])
            command = ['sudo', 'service', 'rpcbind', 'restart']
            subprocess.call(command, shell=False)
            base64encode = base64.b64encode(nfsshare)

            mountpath = os.path.join(config_data['vault_data_directory'], base64encode)
            if not os.path.isdir(mountpath):
                command = ['sudo', 'mkdir', '-p', mountpath]
                subprocess.call(command, shell=False)

            # make sure we have right permissions
            os.chmod(mountpath, 0777)
            mount_share(mountpath, nfsshare, nfsoptions)
            """
            if idx == 0:
                command = ['timeout', '-sKILL', '30' ,
                           'sudo', 'mount',
                           '--bind', mountpath,
                           config_data['vault_data_directory_old']]
                subprocess.check_call(command, shell=False)
                mount_share(config_data['vault_data_directory_old'], nfsshare)
            """


        if config_data['ntp_enabled'] != 'off' and config_data['ntp_enabled'] != 'False':
            ntp_setup()
    except Exception as exception:
        bottle.request.environ['beaker.session']['error_message'] = "Error: %(exception)s" %{'exception': exception,}
        if str(exception.__class__) == "<class 'bottle.HTTPResponse'>":
           raise exception
        else:
            return bottle.HTTPResponse(status=500,body="Error")
    time.sleep(1)
    return {'status':'Success'}


@bottle.route('/authenticate_with_vcenter')
@authorize()
def authenticate_with_vcenter():
    # Authenticate with vCenter
    for i in range(0,1):
        try:
            _authenticate_with_vcenter()
            time.sleep(1)
            return {'status':'Success'}            
        except Exception as exception:
            pass
    
    try:
        _authenticate_with_vcenter()
    except Exception as exception:
        bottle.request.environ['beaker.session']['error_message'] = "Error: %(exception)s" %{'exception': exception,}
        if str(exception.__class__) == "<class 'bottle.HTTPResponse'>":
           raise exception
        else:
           return bottle.HTTPResponse(status=500,body="Error")
    time.sleep(1)
    return {'status':'Success'}

@bottle.route('/authenticate_with_swift')
@authorize()
def authenticate_with_swift():
    # Authenticate with swift
    for i in range(0,1):
        try:
            _authenticate_with_swift(config_data)
            time.sleep(1)
            return {'status':'Success'}            
        except Exception as exception:
            pass    
    try:
        _authenticate_with_swift(config_data)
    except Exception as exception:
        bottle.request.environ['beaker.session']['error_message'] = "Error: %(exception)s" %{'exception': exception,}
        if str(exception.__class__) == "<class 'bottle.HTTPResponse'>":
           raise exception
        else:
           return bottle.HTTPResponse(status=500,body="Error")
    time.sleep(1)
    return {'status':'Success'}
        
@bottle.route('/authenticate_with_keystone')
@authorize()
def authenticate_with_keystone():
    # Authenticate with Keystone
    for i in range(0,1):
        try:
            _authenticate_with_keystone()
            time.sleep(1)
            return {'status':'Success'}            
        except Exception as exception:
            if "KeystoneError:" in exception.message:
                bottle.request.environ['beaker.session']['error_message'] = " %(exception)s" %{'exception': exception,}
                return bottle.HTTPResponse(status=500,body="Error")
            else:
                pass
    try:        
        _authenticate_with_keystone()
    except Exception as exception:
        bottle.request.environ['beaker.session']['error_message'] = "Error: %(exception)s" %{'exception': exception,}
        if str(exception.__class__) == "<class 'bottle.HTTPResponse'>":
           raise exception
        else:    
           return bottle.HTTPResponse(status=500,body="Error")
    time.sleep(1)
    return {'status':'Success'}    


@bottle.route('/register_service')
@authorize()
def register_service():
    # Python code to  register workloadmgr with keystone
    for i in range(0,1):
        try:
            _register_service()
            time.sleep(1)
            return {'status':'Success'}            
        except Exception as exception:
            pass    
    try:
        _register_service()
    except Exception as exception:
        bottle.request.environ['beaker.session']['error_message'] = "Error: %(exception)s" %{'exception': exception,}
        if str(exception.__class__) == "<class 'bottle.HTTPResponse'>":
           raise exception
        else:
           return bottle.HTTPResponse(status=500,body="Error")
    time.sleep(1)
    return {'status':'Success'}        

@bottle.route('/configure_api')
@authorize()
def configure_api():
    # Python code to configure api service
    try:
        if config_data['nodetype'] == 'controller':
            command = ['sudo', 'rm', "/etc/init/wlm-api.override"];
            #shell=FALSE for sudo to work.
            subprocess.call(command, shell=False)
            
        else:
            command = ['sudo', 'service', 'wlm-api', 'stop'];
            subprocess.call(command, shell=False)
            
            command = ['sudo', 'sh', '-c', "echo manual > /etc/init/wlm-api.override"]
            subprocess.call(command, shell=False)

        #configure tvault-gui
        command = ['sudo', 'rm', "/etc/init/tvault-gui.override"];
        subprocess.call(command, shell=False) 
        #command = ['sudo', 'rm', "/etc/init/tvault-gui-worker.override"];
        #subprocess.call(command, shell=False)         
        #command = ['sudo', 'rm', "/etc/init/tvault-gui-worker-1.override"];
        #subprocess.call(command, shell=False)        
        command = ['sudo', 'rm', "/etc/init/tvault-gui-web.override"];
        subprocess.call(command, shell=False)         
        command = ['sudo', 'rm', "/etc/init/tvault-gui-web-1.override"];
        subprocess.call(command, shell=False)
                                
        replace_line('/opt/tvault-gui/config/tvault-gui.yml', '    ip: ', '    ip: ' + config_data['keystone_host'])
        replace_line('/opt/tvault-gui/config/tvault-gui.yml', '    port: ', '    port: ' + str(config_data['keystone_public_port']))
        if 'vcenter' in config_data and config_data['vcenter']:
            replace_line('/opt/tvault-gui/config/tvault-gui.yml', '    name: ', '    name: vCenter')
            replace_line('/opt/tvault-gui/config/tvault-gui.yml', '    value: ', '    value: ' + config_data['vcenter'])                 
        else:
            replace_line('/opt/tvault-gui/config/tvault-gui.yml', '    name: ', '    name: Region')
            replace_line('/opt/tvault-gui/config/tvault-gui.yml', '    value: ', '    value: ' + config_data['region_name'])                 
        
        #configure tvault-gui
        #command = ['sudo', 'service', 'tvault-gui', 'stop'];
        #subprocess.call(command, shell=False)
        #command = ['sudo', 'service', 'tvault-gui-worker', 'stop'];
        #subprocess.call(command, shell=False)
        #command = ['sudo', 'service', 'tvault-gui-worker-1', 'stop'];
        #subprocess.call(command, shell=False)
        #command = ['sudo', 'service', 'tvault-gui-web', 'stop'];
        #subprocess.call(command, shell=False)
        #command = ['sudo', 'service', 'tvault-gui-web-1', 'stop'];
        #subprocess.call(command, shell=False)   
                                                     
        #command = ['sudo', 'sh', '-c', "echo manual > /etc/init/tvault-gui.override"];
        #subprocess.call(command, shell=False) 
        #command = ['sudo', 'sh', '-c', "echo manual > /etc/init/tvault-gui-worker.override"];
        #subprocess.call(command, shell=False)         
        #command = ['sudo', 'sh', '-c', "echo manual > /etc/init/tvault-gui-worker-1.override"];
        #subprocess.call(command, shell=False)        
        #command = ['sudo', 'sh', '-c', "echo manual > /etc/init/tvault-gui-web.override"];
        #subprocess.call(command, shell=False)         
        #command = ['sudo', 'sh', '-c', "echo manual > /etc/init/tvault-gui-web-1.override"];
        #subprocess.call(command, shell=False)        
            
    except Exception as exception:
        bottle.request.environ['beaker.session']['error_message'] = "Error: %(exception)s" %{'exception': exception,}
        return bottle.HTTPResponse(status=500,body="Error")
    time.sleep(1)
    return {'status':'Success'}

@bottle.route('/configure_scheduler')
@authorize()
def configure_scheduler():
    # Python code here to configure scheduler
    try:
        if config_data['nodetype'] == 'controller':
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
        return bottle.HTTPResponse(status=500,body="Error")
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

        replace_line('/etc/workloadmgr/workloadmgr.conf', 'keystone_endpoint_url = ', 'keystone_endpoint_url = ' + config_data['keystone_admin_url'])
        
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'glance_production_host = ', 'glance_production_host = ' + config_data['glance_production_host'])
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'glance_production_port = ', 'glance_production_port = ' + str(config_data['glance_production_port']))
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'glance_production_api_servers = ', 'glance_production_api_servers = ' + str(config_data['glance_production_api_servers']))
        
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'neutron_admin_auth_url = ', 'neutron_admin_auth_url = ' + config_data['neutron_admin_auth_url'])
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'neutron_production_url = ', 'neutron_production_url = ' + config_data['neutron_production_url'])
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'neutron_admin_username = ', 'neutron_admin_username = ' + config_data['neutron_admin_username'])
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'neutron_admin_password = ', 'neutron_admin_password = ' + config_data['neutron_admin_password'])
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'neutron_admin_tenant_name = ', 'neutron_admin_tenant_name = ' + config_data['neutron_admin_tenant_name'])
        
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'nova_admin_auth_url = ', 'nova_admin_auth_url = ' + config_data['nova_admin_auth_url'])
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'nova_production_endpoint_template = ', 'nova_production_endpoint_template = ' + config_data['nova_production_endpoint_template'])

        replace_line('/etc/workloadmgr/workloadmgr.conf', 'nova_admin_username = ', 'nova_admin_username = ' + config_data['nova_admin_username'])
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'nova_admin_password = ', 'nova_admin_password = ' + config_data['nova_admin_password'])
        
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'cinder_production_endpoint_template = ', 'cinder_production_endpoint_template = ' + config_data['cinder_production_endpoint_template'])
        
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'vault_swift_url = ', 'vault_swift_url = ' + config_data['vault_swift_url'])

        replace_line('/etc/workloadmgr/workloadmgr.conf', 'vault_storage_type = ', 'vault_storage_type = nfs')
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'vault_data_directory = ', 'vault_data_directory = ' + config_data['vault_data_directory'])
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'vault_data_directory_old = ', 'vault_data_directory_old = ' + config_data['vault_data_directory_old'])
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'vault_storage_nfs_export = ', 'vault_storage_nfs_export = ' + config_data['storage_nfs_export'])
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'vault_storage_nfs_options = ', 'vault_storage_nfs_options = ' + config_data['storage_nfs_options'])
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'cloud_unique_id = ', 'cloud_unique_id = ' + config_data['cloud_unique_id'])
       
        if  config_data['swift_auth_url'] and len(config_data['swift_auth_url']) > 0:
            replace_line('/etc/workloadmgr/workloadmgr.conf', 'vault_storage_nfs_export = ', 'vault_storage_nfs_export = TrilioVault')
            replace_line('/etc/workloadmgr/workloadmgr.conf', 'vault_storage_type = ', 'vault_storage_type = swift-s')
            replace_line('/etc/workloadmgr/workloadmgr.conf', 'vault_swift_url = ', 'vault_swift_url = ' + config_data['swift_auth_url'])
            replace_line('/etc/workloadmgr/workloadmgr.conf', 'vault_swift_auth_version = ', 'vault_swift_auth_version = ' + config_data['swift_auth_version'])
            replace_line('/etc/workloadmgr/workloadmgr.conf', 'vault_swift_auth_url = ', 'vault_swift_auth_url = ' + config_data['swift_auth_url'])
            if config_data['swift_auth_version'] == 'TEMPAUTH':
               replace_line('/etc/workloadmgr/workloadmgr.conf', 'vault_swift_username = ', 'vault_swift_username = ' + config_data['swift_username'])
               replace_line('/etc/workloadmgr/workloadmgr.conf', 'vault_swift_password = ', 'vault_swift_password = ' + config_data['swift_password'])            
               replace_line('/etc/workloadmgr/workloadmgr.conf', 'vault_swift_tenant = ', 'vault_swift_tenant = ' + config_data['swift_tenantname'])
               replace_line('/etc/workloadmgr/workloadmgr.conf', 'vault_swift_domain_id = ', 'vault_swift_domain_id = ' + config_data['swift_domain_id'])
            else:
                 replace_line('/etc/workloadmgr/workloadmgr.conf', 'vault_swift_username = ', 'vault_swift_username = ' + config_data['workloadmgr_user'])
                 replace_line('/etc/workloadmgr/workloadmgr.conf', 'vault_swift_password = ', 'vault_swift_password = ' + config_data['workloadmgr_user_password'])
                 replace_line('/etc/workloadmgr/workloadmgr.conf', 'vault_swift_tenant = ', 'vault_swift_tenant = ' + config_data['service_tenant_name'])
                 replace_line('/etc/workloadmgr/workloadmgr.conf', 'vault_swift_domain_id = ', 'vault_swift_domain_id = ' + config_data['triliovault_user_domain_id'])


                        
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'sql_connection = ', 'sql_connection = ' + config_data['sql_connection'])
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'rabbit_host = ', 'rabbit_host = ' + config_data['rabbit_host'])
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'rabbit_password = ', 'rabbit_password = ' + config_data['rabbit_password'])
        
        if 'vcenter_password' in config_data:
            replace_line('/etc/workloadmgr/workloadmgr.conf', 'host_password = ', 'host_password = ' + config_data['vcenter_password'])               
        if 'vcenter_username' in config_data:
            replace_line('/etc/workloadmgr/workloadmgr.conf', 'host_username = ', 'host_username = ' + config_data['vcenter_username'])
        if 'vcenter' in config_data:               
            replace_line('/etc/workloadmgr/workloadmgr.conf', 'host_ip = ', 'host_ip = ' + config_data['vcenter']) 
            
        if 'vcenter_username' in config_data:
            replace_line('/etc/workloadmgr/workloadmgr.conf', 'auditlog_admin_user = ', 'auditlog_admin_user = ' + config_data['vcenter_username'])
               
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'nova_api_insecure = ', 'nova_api_insecure = True')
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'cinder_api_insecure = ', 'cinder_api_insecure = True')
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'glance_api_insecure = ', 'glance_api_insecure = True')
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'neutron_api_insecure = ', 'neutron_api_insecure = True')

        replace_line('/etc/workloadmgr/workloadmgr.conf', 'auth_url = ',
                     'auth_url = ' + config_data['keystone_admin_url'].\
                     strip("v3").strip("v2.0"),
                     starts_with=True)
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'auth_uri = ',
                     'auth_uri = ' + config_data['keystone_public_url'],
                     starts_with=True)
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'admin_tenant_name = ',
                     'admin_tenant_name = ' + config_data['service_tenant_name'],
                     starts_with=True)
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'trustee_role = ',
                     'trustee_role = ' + config_data.get('trustee_role', '_member_'),
                     starts_with=True)
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'region_name_for_services = ',
                     'region_name_for_services = ' + config_data.get('region_name', 'RegionOne'),
                     starts_with=True)        
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'domain_name = ',
                     'domain_name = ' + config_data.get('domain_name'),
                     starts_with=True)
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'triliovault_user_domain_id = ',
                     'triliovault_user_domain_id = ' + config_data['triliovault_user_domain_id'],
                     starts_with=True)
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'user_domain_id = ',
                     'user_domain_id = ' + config_data['triliovault_user_domain_id'],
                     starts_with=True)
        replace_line('/etc/workloadmgr/workloadmgr.conf', 'project_domain_id = ',
                     'project_domain_id = ' + config_data['service_tenant_domain_id'],
                     starts_with=True)

        replace_line('/etc/workloadmgr/workloadmgr.conf', 'endpoint_type = ',
                     'endpoint_type = ' + config_data['endpoint_type'],
                     starts_with=True)

        #configure api-paste
        replace_line('/etc/workloadmgr/api-paste.ini', 'auth_host = ', 'auth_host = ' + config_data['keystone_host'])
        replace_line('/etc/workloadmgr/api-paste.ini', 'auth_port = ', 'auth_port = ' + str(config_data['keystone_admin_port']))
        replace_line('/etc/workloadmgr/api-paste.ini', 'auth_protocol = ', 'auth_protocol = ' + config_data['keystone_admin_protocol'])
        replace_line('/etc/workloadmgr/api-paste.ini', 'admin_user = ', 'admin_user = ' + config_data['workloadmgr_user'])
        replace_line('/etc/workloadmgr/api-paste.ini', 'admin_password = ', 'admin_password = ' + config_data['workloadmgr_user_password'])
        replace_line('/etc/workloadmgr/api-paste.ini', 'admin_tenant_name = ', 'admin_tenant_name = ' + config_data['service_tenant_name'])
        replace_line('/etc/workloadmgr/api-paste.ini', 'admin_user_domain_id = ', 'admin_user_domain_id = ' + config_data['triliovault_user_domain_id'])
        replace_line('/etc/workloadmgr/api-paste.ini', 'insecure = ', 'insecure = True')
        
    except Exception as exception:
        bottle.request.environ['beaker.session']['error_message'] = "Error: %(exception)s" %{'exception': exception,}
        return bottle.HTTPResponse(status=500,body="Error")
    time.sleep(1)
    return {'status':'Success'}

@bottle.route('/start_api')
@authorize()
def start_api():
    # Python code to configure api service
    try:
        if config_data['nodetype'] == 'controller':
            command = ['sudo', 'service', 'wlm-api', 'restart'];
            subprocess.call(command, shell=False)

        #configure tvault-gui
        command = ['sudo', 'service', 'tvault-gui', 'restart'];
        subprocess.call(command, shell=False)
        #command = ['sudo', 'service', 'tvault-gui-worker', 'restart'];
        #subprocess.call(command, shell=False)
        #command = ['sudo', 'service', 'tvault-gui-worker-1', 'restart'];
        #subprocess.call(command, shell=False)
        command = ['sudo', 'service', 'tvault-gui-web', 'restart'];
        subprocess.call(command, shell=False)
        command = ['sudo', 'service', 'tvault-gui-web-1', 'restart'];
        subprocess.call(command, shell=False) 
            
    except Exception as exception:
        bottle.request.environ['beaker.session']['error_message'] = "Error: %(exception)s" %{'exception': exception,}
        return bottle.HTTPResponse(status=500,body="Error")
    time.sleep(2)
    return {'status':'Success'}

@bottle.route('/start_scheduler')
@authorize()
def start_scheduler():
    # Python code here to configure scheduler
    try:
        if config_data['nodetype'] == 'controller':        
            command = ['sudo', 'service', 'wlm-scheduler', 'restart'];
            #shell=FALSE for sudo to work.
            subprocess.call(command, shell=False)
    except Exception as exception:
        bottle.request.environ['beaker.session']['error_message'] = "Error: %(exception)s" %{'exception': exception,}
        return bottle.HTTPResponse(status=500,body="Error")
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
        return bottle.HTTPResponse(status=500,body="Error")
    time.sleep(2)
    return {'status':'Success'}

@bottle.route('/start_swift_service')
@authorize()
def start_swift_service():
    try:
        try:
            command = ['sudo', 'service', 'tvault-swift', 'stop'];
            subprocess.call(command, shell=False)
        except:
               pass
        try:
            shutil.rmtree(config_data['vault_data_directory'])
        except:
               pass
        try:
            shutil.rmtree(config_data['vault_data_directory_old'])
        except:
               pass
        try:
            os.stat(config_data['vault_data_directory_old'])
            os.mkdir(config_data['vault_data_directory_old'])
        except:
               os.mkdir(config_data['vault_data_directory_old'])   
        try:
            os.stat(config_data['vault_data_directory'])
        except:
               os.mkdir(config_data['vault_data_directory'])
        command = ['sudo', 'chown', WLM_USER+':'+WLM_USER, config_data['vault_data_directory']];
        subprocess.call(command, shell=False)
        command = ['sudo', 'chown', WLM_USER+':'+WLM_USER, config_data['vault_data_directory_old']];
        subprocess.call(command, shell=False)
        command = ['sudo', 'chown', WLM_USER+':'+WLM_USER, '/etc/fuse.conf'];
        subprocess.call(command, shell=False)
        command = ['sudo', 'service', 'tvault-swift', 'restart'];
        subprocess.call(command, shell=False)
    except Exception as exception:
        bottle.request.environ['beaker.session']['error_message'] = "Error: %(exception)s" %{'exception': exception,}
        return bottle.HTTPResponse(status=500,body="Error")
    time.sleep(2)
    return {'status':'Success'}

@bottle.route('/register_workloadtypes')
@authorize()
def register_workloadtypes():
    # Python code here to register workload types
    for i in range(0,1):
        try:
            _register_workloadtypes()
            time.sleep(1)
            return {'status':'Success'}            
        except Exception as exception:
            pass    
    try:
        _register_workloadtypes()
    except Exception as exception:
        bottle.request.environ['beaker.session']['error_message'] = "Error: %(exception)s" %{'exception': exception,}
        if str(exception.__class__) == "<class 'bottle.HTTPResponse'>":
           raise exception
        else:
           return bottle.HTTPResponse(status=500,body="Error")
    time.sleep(1)
    return {'status':'Success'}  

@bottle.route('/workloads_import')
@authorize()
def workloads_import():
    # Python code here to register workload types
    for i in range(0,1):
        try:
            _workloads_import()
            time.sleep(1)
            return {'status':'Success'}            
        except Exception as exception:
            pass    
    try:
        _workloads_import()
    except Exception as exception:
        bottle.request.environ['beaker.session']['error_message'] = "Error: %(exception)s" %{'exception': exception,}
        if str(exception.__class__) == "<class 'bottle.HTTPResponse'>":
           raise exception
        else:
           return bottle.HTTPResponse(status=500,body="Error")
    time.sleep(1)
    return {'status':'Success'}        

@bottle.route('/discover_vcenter')
@authorize()
def discover_vcenter():
    # Python code here to configure workloadmgr
    try:    
        if config_data['nodetype'] == 'controller':
                time.sleep(5)
                client = nova.novaclient2(config_data['keystone_public_url'], 
                                          config_data['admin_username'], 
                                          config_data['admin_password'], 
                                          config_data['admin_tenant_name'],
                                          config_data['nova_production_endpoint_template'])
                search_opts = {}
                search_opts['deep_discover'] = '1'
                client.servers.list(True, search_opts)
        config_data['config_status'] = 'success'
        persist_config()

    except Exception as exception:
        bottle.request.environ['beaker.session']['error_message'] = "Error: %(exception)s" %{'exception': exception,}
        config_data['config_status'] = 'failed'
        persist_config()
        return bottle.HTTPResponse(status=500,body="Error")
    time.sleep(1)
    return {'status':'Success'}

@authorize()
def persist_config():
    try:
        Config = ConfigParser.RawConfigParser()
        Config.read('/etc/tvault-config/tvault-config.conf')
        for key, value in config_data.iteritems():
            Config.set(None, key, value)           
            if config_data['nodetype'] == 'controller':
               engine = create_engine(config_data['sql_connection'])
               name_found = False
               for persisted_setting in engine.execute(select([models.Settings.__table__])):
                   row_dict = dict(persisted_setting.items())
                   k1 = row_dict.get("name",None)             
                   if k1 == key:
                      update = models.Settings.__table__.update().where(models.Settings.__table__.columns.name == key).\
                      values({'value' : value})
                      engine.execute(update)
                      name_found = True
                      break
               if name_found == False:
                  result = engine.execute(models.Settings.__table__.insert().values({'name' : key,
                                            'value' : value,
                                            'user_id': 'Configurator',
                                            'project_id': 'Configurator',   
                                            'status': 'available',
                                            'hidden': True }))

        if not os.path.exists('/etc/tvault-config/'):
            os.makedirs('/etc/tvault-config/')
        with open('/etc/tvault-config/tvault-config.conf', 'wb') as configfile:
            Config.write(configfile)
    except Exception as exception:
        bottle.request.environ['beaker.session']['error_message'] = "Error: %(exception)s" %{'exception': exception,}
        raise exception                    
    time.sleep(1)
    return {'status':'Success'}    

def ntp_setup():    
    try:
        ntps = config_data['ntp_servers']
        reachable_ntps = []
        for ntp in ntps.strip(",").split(","):
            if os.system("ping -c 1 " + ntp.strip()) == 0: 
                command = ['sudo', 'ntpdate', '-s', ntp.strip()]
                subprocess.call(command, shell=False)
                reachable_ntps.append(ntp)
        
        if len(reachable_ntps) == 0:
           error_msg = "NTP servers unavailable to update time instantly  Enter valid servers "

        if len(reachable_ntps) > 5:
           errro_msg = "Maximum 5 servers allowed  Suppressed rest "

        if 'error_msg' in vars():
           raise Exception(error_msg)
        else:
           contents = open('/etc/ntp.conf', 'r').read()
           new_contents = ""
           detect = 0
           for line in contents.splitlines():
               line = line.strip()
               if (line.find('#server ') != -1 or line.find('server ') != -1) and (detect == 0 or detect == 1):
                    detect = 1
               else:
                    if line.find('fallback') != -1 and detect == 1:
                        detect = 2
                        new_contents += "\n".join(["server %s" % ntp for ntp in reachable_ntps[0:5]])
                    elif detect == 1:
                        detect = 3
                        new_contents += "\n".join(["server %s" % ntp for ntp in reachable_ntps[0:5]])

                    new_contents += line+"\n"

           conf_file = open('/etc/ntp.conf', 'w')
           conf_file.write(new_contents)
           conf_file.close()
            #timezone_file = open('/etc/timezone', 'w')
            #timezone_file.write(config_data['timezone']+"\n")
            #timezone_file.close()
            #command = ['sudo', 'dpkg-reconfigure', '-f', 'noninteractive', 'tzdata']
           command = ['sudo', 'timedatectl', 'set-timezone', config_data['timezone']]
           subprocess.call(command, shell=False)

           command = ['sudo', 'service', 'ntp', 'stop']
           subprocess.call(command, shell=False)
           command = ['sudo', 'service', 'ntp', 'restart']
           subprocess.call(command, shell=False)
    except Exception as exception:
        bottle.request.environ['beaker.session']['error_message'] = "Error: %(exception)s" %{'exception': exception,}
        config_data['config_status'] = 'failed'
        raise exception
    time.sleep(1)
    return {'status':'Success'}
    
@bottle.post('/configure_vmware')
@authorize()
def configure_vmware():
    global config_data
    config_data = {}
    bottle.request.environ['beaker.session']['error_message'] = ''
    try: 
        config_inputs = bottle.request.POST
        if config_inputs['refresh'] == '1':
           config_data['sql_connection'] = 'mysql://root:' + TVAULT_SERVICE_PASSWORD + '@' + config_inputs['tvault-primary-node'] + '/workloadmgr?charset=utf8' 
           engine = create_engine(config_data['sql_connection'])
           for row in engine.execute(select([models.Settings.__table__]).where(models.Settings.__table__.columns.project_id=='Configurator')):
               items = dict(row.items())
               if config_inputs['nodetype'] == 'additional' and items['name'] == 'nodetype':
                  items['value'] = 'additional'
               config_data[items['name']] = items['value']  
               config_inputs[items['name'].replace('_','-')] = items['value']
           config_data['refresh'] = 0
           config_data['nodetype'] = config_inputs['nodetype']
           persist_config()
           if 'from' not in config_inputs.keys():
              bottle.redirect("/configure_vmware")

        config_data['configuration_type'] = 'vmware'
        config_data['nodetype'] = config_inputs['nodetype']
        config_data['tvault_primary_node'] = config_inputs['tvault-primary-node']
        config_data['tvault_ipaddress'] = get_lan_ip()
        config_data['floating_ipaddress'] = config_data['tvault_ipaddress']
        config_data['name_server'] = config_inputs['name-server']
        config_data['domain_search_order'] = config_inputs['domain-search-order']        
        
        config_data['vcenter'] = config_inputs['vcenter']
        config_data['vcenter_username'] = config_inputs['vcenter-username']
        config_data['vcenter_password'] = config_inputs['vcenter-password']

        if 'ntp-enabled' in config_inputs:
            config_data['ntp_enabled'] = config_inputs['ntp-enabled']
            config_data['ntp_servers'] = config_inputs['ntp-servers'].replace(" ","")
            config_data['timezone'] = config_inputs['timezone']
        else:
            config_data['ntp_enabled'] = 'off'
        
        config_data['storage_nfs_export'] = config_inputs['storage-nfs-export']
        
        config_data['swift_auth_version'] = config_inputs['swift-auth-version']
        config_data['swift_auth_url'] = config_inputs['swift-auth-url']
        config_data['swift_username'] = config_inputs['swift-username']
        config_data['swift_password'] = config_inputs['swift-password']
        config_data['swift_tenantname'] = config_inputs['swift-tenantname']
        config_data['swift_container_prefix'] = config_inputs['swift-container-prefix']
        config_data['swift_url_template'] = ''        
        
               
        config_data['ldap_server_url'] = config_inputs['ldap-server-url']
        if not config_data['ldap_server_url'] or  config_data['ldap_server_url'] == "ldap://localhost":
            config_data['ldap_server_url'] = "ldap://localhost"
            config_data['ldap_domain_name_suffix'] = "dc=openstack,dc=org"
            config_data['ldap_user_tree_dn'] = "ou=Users,dc=openstack,dc=org"
            config_data['ldap_user_dn'] = "dc=Manager,dc=openstack,dc=org"
            config_data['ldap_user_password'] = "52T8FVYZJse"
            config_data['ldap_use_dumb_member'] = True
            config_data['ldap_user_allow_create'] = True
            config_data['ldap_user_allow_update'] = True
            config_data['ldap_user_allow_delete'] = True
            config_data['ldap_tenant_allow_create'] = True
            config_data['ldap_tenant_allow_update'] = True
            config_data['ldap_tenant_allow_delete'] = True
            config_data['ldap_role_allow_create'] = True
            config_data['ldap_role_allow_update'] = True
            config_data['ldap_role_allow_delete'] = True
            config_data['ldap_user_objectclass'] = "inetOrgPerson" 
            config_data['ldap_user_name_attribute'] = "sn"                       
        else:
            config_data['ldap_domain_name_suffix'] = config_inputs['ldap-domain-name-suffix']
            config_data['ldap_user_tree_dn'] = config_inputs['ldap-user-tree-dn']
            config_data['ldap_user_dn'] = config_inputs['ldap-user-dn']
            config_data['ldap_user_password'] = config_data['vcenter_password'] 
            config_data['ldap_use_dumb_member'] = False
            config_data['ldap_user_allow_create'] = False
            config_data['ldap_user_allow_update'] = False
            config_data['ldap_user_allow_delete'] = False
            config_data['ldap_tenant_allow_create'] = False
            config_data['ldap_tenant_allow_update'] = False
            config_data['ldap_tenant_allow_delete'] = False
            config_data['ldap_role_allow_create'] = False
            config_data['ldap_role_allow_update'] = False
            config_data['ldap_role_allow_delete'] = False
            config_data['ldap_user_objectclass'] = config_inputs['ldap-user-objectclass']
            config_data['ldap_user_name_attribute'] = config_inputs['ldap-user-name-attribute']
                       

        config_data['keystone_admin_url'] = "http://" + config_data['tvault_primary_node'] + ":35357/v2.0"
        config_data['keystone_public_url'] = "http://" + config_data['tvault_primary_node'] + ":5000/v2.0"
        config_data['admin_username'] = config_data['vcenter_username']
        config_data['admin_password'] = config_data['vcenter_password']        
        config_data['admin_tenant_name'] = 'admin'
        config_data['region_name'] = 'RegionOne'
        
        parse_result = urlparse(config_data['keystone_admin_url'])
        config_data['keystone_host'] = parse_result.hostname
        config_data['keystone_admin_port'] = parse_result.port
        config_data['keystone_admin_protocol'] = parse_result.scheme
        
        parse_result = urlparse(config_data['keystone_public_url'])
        config_data['keystone_public_port'] = parse_result.port
        config_data['keystone_public_protocol'] = parse_result.scheme
        
        config_data['workloadmgr_user'] = config_data['vcenter_username']
        config_data['workloadmgr_user_password'] = config_data['vcenter_password']

        if 'workloads-import' in config_inputs:
            config_data['workloads_import'] = config_inputs['workloads-import']
        else:
            config_data['import_workloads'] = 'off'
        bottle.redirect("/task_status_vmware")
    except Exception as exception:
        bottle.request.environ['beaker.session']['error_message'] = "Error: %(exception)s" %{'exception': exception,}
        if str(exception.__class__) == "<class 'bottle.HTTPResponse'>":
           raise exception
        else:
           bottle.redirect("/configure_vmware")
           
@bottle.post('/configure_openstack')
@authorize()
def configure_openstack():
    global config_data
    config_data = {}
    bottle.request.environ['beaker.session']['error_message'] = ''
    try:
        config_inputs = bottle.request.POST

        config_data['configuration_type'] = 'openstack'
        config_data['nodetype'] = config_inputs['nodetype']
        config_data['tvault_ipaddress'] = get_lan_ip()
        config_data['floating_ipaddress'] = config_inputs['floating-ipaddress'].strip()
        if config_data['nodetype'] == 'controller':
            config_data['tvault_primary_node'] = config_data['floating_ipaddress'].strip()
        elif config_data['nodetype'] == 'additional':
             sql_connection = 'mysql://root:' + TVAULT_SERVICE_PASSWORD + '@' + config_data['floating_ipaddress'] + '/workloadmgr?charset=utf8'
             engine = create_engine(sql_connection)
             rows = engine.execute(select([models.Settings.__table__]).where(models.Settings.__table__.columns.project_id=='Configurator'))
             if not int(rows.rowcount) >= 0:
                raise Exception("Invalid controller node")
             for row in rows:
                 items = dict(row.items())
                 if items['name'] == 'tvault_ipaddress':
                    if items['value'] == config_data['tvault_ipaddress']:
                       raise Exception("Additional node IP address cannot be Controller node, Enter Controller node Ip address")
        config_data['name_server'] = config_inputs['name-server'].strip()
        config_data['domain_search_order'] = config_inputs['domain-search-order'].strip()        
        
        config_data['keystone_admin_url'] = config_inputs['keystone-admin-url'].strip()
        config_data['keystone_public_url'] = config_inputs['keystone-public-url'].strip()
        
        config_data['admin_username'] = config_inputs['admin-username'].strip()
        config_data['admin_password'] = config_inputs['admin-password']
        config_data['admin_tenant_name'] = config_inputs['admin-tenant-name'].strip()
        config_data['region_name'] = config_inputs['region-name'].strip()

        if 'domain-name' in config_inputs and config_inputs['domain-name'].strip() != '':
           config_data['domain_name'] = config_inputs['domain-name'].strip()
        else:
             config_data['domain_name'] = 'default'
           
        if 'trustee-role' in config_inputs:
            config_data['trustee_role'] = config_inputs['trustee-role'].strip()
        else:
             config_data['trustee_role'] = None
        config_data['guest_name'] = config_inputs['guest-name'].strip()
        
        parse_result = urlparse(config_data['keystone_admin_url'])
        config_data['keystone_host'] = parse_result.hostname
        config_data['keystone_admin_port'] = parse_result.port
        config_data['keystone_admin_protocol'] = parse_result.scheme
        #getting ntp and timezones        
        if 'ntp-enabled' in config_inputs:
            config_data['ntp_enabled'] = config_inputs['ntp-enabled']
        else:
            config_data['ntp_enabled'] = 'off'
        config_data['ntp_servers'] = config_inputs['ntp-servers'].replace(" ","")
        config_data['timezone'] = config_inputs['timezone']

        parse_result = urlparse(config_data['keystone_public_url'])
        config_data['keystone_public_port'] = parse_result.port
        config_data['keystone_public_protocol'] = parse_result.scheme
        
        config_data['workloadmgr_user'] = 'triliovault'
        config_data['workloadmgr_user_password'] = TVAULT_SERVICE_PASSWORD       

        config_data['vault_data_directory'] = '/var/triliovault-mounts'
        config_data['vault_data_directory_old'] = '/var/triliovault'

        config_data['storage_nfs_options'] = 'nolock,soft,timeo=180,intr'
        config_data['storage_nfs_export'] = ''
        config_data['swift_auth_url'] = ''
        config_data['swift_username'] = ''
        config_data['swift_password'] = ''
        config_data['swift_tenantname'] = ''
        config_data['swift_domain_id'] = ''
        config_data['swift_auth_version'] = 'NONE'

        config_data['backup_target_type'] = config_inputs['backup_target_type']
        if config_data['backup_target_type'] == 'NFS':
            config_data['storage_nfs_export'] = config_inputs['storage-nfs-export'].strip()

            if 'storage-nfs-options' in config_inputs:
                config_data['storage_nfs_options'] = config_inputs['storage-nfs-options'].strip()

        else:
            config_data['swift_auth_version'] = config_inputs['swift-auth-version']

            if config_data['swift_auth_version'] == 'TEMPAUTH':
                config_data['swift_auth_url'] = config_inputs['swift-auth-url'].strip()
                config_data['swift_username'] = config_inputs['swift-username'].strip()
                config_data['swift_password'] = config_inputs['swift-password'].strip()
                config_data['swift_tenantname'] = ''
                config_data['swift_domain_id'] = ''
            elif config_data['swift_auth_version'] == 'KEYSTONE':
                config_data['swift_auth_url'] = config_data['keystone_public_url']
                config_data['swift_username'] = config_data['admin_username']
                config_data['swift_password'] = config_data['admin_password']
                config_data['swift_tenantname'] = config_data['admin_tenant_name']
                config_data['swift_domain_id'] = config_data['domain_name']

        config_data['workloads_import'] = config_inputs.get('workloads-import', "off").strip().rstrip() == 'on'
        
        bottle.redirect("/task_status_openstack")
    except Exception as exception:
        bottle.request.environ['beaker.session']['error_message'] = "Error: %(exception)s" %{'exception': exception,}
        if str(exception.__class__) == "<class 'bottle.HTTPResponse'>":
           raise exception
        else:
           bottle.redirect("/configure_openstack")

@bottle.post('/configure')
@authorize()
def configure():
    bottle.request.environ['beaker.session']['error_message'] = ''
    try:
        config_inputs = bottle.request.POST
        bottle.redirect("/configure_" + config_inputs['configuration-type'])
    except Exception as exception:
        bottle.request.environ['beaker.session']['error_message'] = "Error: %(exception)s" %{'exception': exception,}
        if str(exception.__class__) == "<class 'bottle.HTTPResponse'>":
           raise exception
        else:
           bottle.redirect("/configure")
           
@bottle.route('/home')
@bottle.view('home')
@authorize()
def home():
    if not 'error_message' in bottle.request.environ['beaker.session']:
       bottle.request.environ['beaker.session']['error_message'] = '' 
    if not 'success_message' in bottle.request.environ['beaker.session']:
       bottle.request.environ['beaker.session']['success_message'] = '' 
     
    msgs =  dict(error_message = bottle.request.environ['beaker.session']['error_message'],success_message = bottle.request.environ['beaker.session']['success_message'])
    bottle.request.environ['beaker.session']['error_message'] = ''
    bottle.request.environ['beaker.session']['success_message'] = ''
    return msgs
  
@bottle.route('/reinitialize')
@authorize()
def reinitialize():
    try:
        bottle.request.environ['beaker.session']['error_message'] = ''
        Config = ConfigParser.RawConfigParser()
        Config.read('/etc/tvault-config/tvault-config.conf')
        config_data = dict(Config._defaults)

        if 'sql_connection' in config_data:
           engine = create_engine(config_data['sql_connection'])
           connection = engine.connect()
           trans = connection.begin()
           tables = engine.table_names() 
           connection.execute("SET FOREIGN_KEY_CHECKS=0")
           for table in tables:
               if table != 'workload_types':
                  connection.execute("TRUNCATE TABLE "+str(table))
           connection.execute("SET FOREIGN_KEY_CHECKS=1") 
           trans.commit()
           bottle.request.environ['beaker.session']['success_message'] = 'Reinitialized successfully'
           try:
                context = bottle.request.environ['beaker.session']
                context.user = 'System'
                context.tenant = 'System'
                context.user_id = 'System'
                context.project_id = 'System'
                context.vault_storage_nfs_export = ''
                if config_data['backup_target_type'] == 'NFS':
                   context.vault_storage_nfs_export = config_data['storage_nfs_export']
                context.cloud_unique_id = config_data['cloud_unique_id']
                AUDITLOG = auditlog.getAuditLogger(CONF1=context)
                AUDITLOG.log(context,'Reinitialized database', None)
           except Exception as ex:
                  pass               
        else:
             bottle.request.environ['beaker.session']['error_message'] = 'No database found'
    except Exception as exception:
           trans.rollback()
           bottle.request.environ['beaker.session']['error_message'] = "Error: %(exception)s" %{'exception': exception,}

    bottle.redirect("/home")


@bottle.route('/validate_keystone_url')
@authorize()
def validate_keystone_url():
    import urllib
    # Validate keystone url
    for i in range(0,1):
        try:
            urllib.urlopen(bottle.request.query['url']).read()
            time.sleep(1)
            return {'status':'Success'}            
        except Exception as exception:
            pass    
    try:
        urllib.urlopen(bottle.request.query['url']).read()
    except Exception as exception:
        bottle.request.environ['beaker.session']['error_message'] = "Error: %(exception)s" %{'exception': exception,}
        if str(exception.__class__) == "<class 'bottle.HTTPResponse'>":
           raise exception
        else:
           return bottle.HTTPResponse(status=500, body=str(exception))
    time.sleep(1)

    return {'status':'Success'}        


@bottle.route('/validate_swift_credentials')
@authorize()
def validate_swift_credentials():
    data = {}
    public_url = bottle.request.query['public_url']
    swift_auth_version = bottle.request.query['swift_auth_version']
    data['configuration_type'] = 'openstack'
    data['swift_auth_version'] = swift_auth_version
    data['keystone_auth_version'] = bottle.request.query['keystone_auth_version']
    data['keystone_auth_version'] = 2
    if data['keystone_auth_version'] == 'true':
       data['keystone_auth_version'] = 3
    if swift_auth_version == 'KEYSTONE':
       data['swift_auth_url'] = public_url
       data['swift_username'] =  bottle.request.query['username']
       data['swift_password'] =  bottle.request.query['password']
       data['swift_tenantname'] =  bottle.request.query['project_name']
       data['swift_domain_id'] = bottle.request.query['domain_id']
       data['region_name'] = bottle.request.query['region_name']
    elif swift_auth_version == 'TEMPAUTH':
         data['swift_auth_url'] = bottle.request.query['swift_auth_url']
         data['swift_username'] = bottle.request.query['swift_username']
         data['swift_password'] = bottle.request.query['swift_password']

    try:
        _authenticate_with_swift(data)
    except Exception as exception:
        bottle.request.environ['beaker.session']['error_message'] = "Error: %(exception)s" %{'exception': exception,}
        if str(exception.__class__) == "<class 'bottle.HTTPResponse'>":
           raise exception
        else:
           return bottle.HTTPResponse(status=500, body=str(exception))

    return {'status':'Success'}


@bottle.route('/validate_keystone_credentials')
@authorize()
def validate_keystone_credentials():
    data = {}
    data['admin_username'] = bottle.request.query['username']
    data['admin_password'] = bottle.request.query['password']
    data['admin_tenant_name'] = bottle.request.query['project_name']
    data['keystone_admin_url'] = bottle.request.query['admin_url']
    data['keystone_public_url'] = bottle.request.query['public_url']
    data['domain_name'] = bottle.request.query['domain_id']

    #test public url
    try:
        global config_data
        config_data = data
        keystone, tenants =  _validate_keystone_client_and_version(admin_url=False)
    except Exception as exception:
        bottle.request.environ['beaker.session']['error_message'] = "Error: %(exception)s" %{'exception': exception,}
        if str(exception.__class__) == "<class 'bottle.HTTPResponse'>":
           raise exception
        else:
           return bottle.HTTPResponse(status=500, body=str(exception))

    try:
        keystone, tenants =  _validate_keystone_client_and_version()
    except Exception as exception:
        bottle.request.environ['beaker.session']['error_message'] = "Error: %(exception)s" %{'exception': exception,}
        if str(exception.__class__) == "<class 'bottle.HTTPResponse'>":
           raise exception
        else:
           return bottle.HTTPResponse(status=500, body=str(exception))

    # populate roles list
    try:
        roles = [role.name for role in keystone.roles.list()]
    except Exception as exception:
        bottle.request.environ['beaker.session']['error_message'] = "Error: %(exception)s" %{'exception': exception,}
        if str(exception.__class__) == "<class 'bottle.HTTPResponse'>":
           raise exception
        else:
           return bottle.HTTPResponse(status=500, body=str(exception))

    return {'status':'Success', 'roles': roles, 'keystone_version': keystone.version}


@bottle.route('/validate_nfs_share')
@authorize()
def validate_nfs_share():
    try:
        from workloadmgr import utils
        nfsshare = bottle.request.query['nfsshare']
        nfsserver = nfsshare.split(":")[0]
        sharepath = nfsshare.split(":")[1]
        rpcinfo = utils.execute("rpcinfo", "-s", nfsserver)

        for i in rpcinfo[0].split("\n")[1:]:
            if len(i.split()) and i.split()[3] == 'mountd':
                mounts = utils.execute("showmount", "-e", "--no-headers", nfsserver)
                if sharepath not in mounts[0]:
                    return bottle.HTTPResponse(status=500,
                        body=str("'%s' is not found in %s export list" % (nfsshare, nfsserver)))
                return {'status': 'Success'}
        return bottle.HTTPResponse(status=500,
            body=str("NFS Daemon is not running on the server '%s'" % nfsserver))

    except Exception as exception:
        body=str("NFS Daemon is not running on the server '%s'" % nfsserver)
        return bottle.HTTPResponse(status=500, body=body)


def findXmlSection(dom, sectionName):
    sections = dom.getElementsByTagName(sectionName)
    return sections[0]
 

def getPropertyMap(ovfEnv):
    dom = parseString(ovfEnv)
    section = findXmlSection(dom, "PropertySection")
    propertyMap = {}
    for property in section.getElementsByTagName("Property"):
        key   = property.getAttribute("oe:key")
        value = property.getAttribute("oe:value")
        propertyMap[key] = value
    dom.unlink()
    return propertyMap    


def set_network_interfaces(propertyMap):
    
    ip1          = propertyMap["ip1"]
    netmask1     = propertyMap["netmask1"]
    gateway1     = propertyMap["gateway1"]
    ip2          = propertyMap.get('ip2', '192.168.3.100')
    netmask2     = propertyMap.get('netmask2', '255.255.255.0')
                
    fh, abs_path = mkstemp()
    new_file = open(abs_path,'w')
    new_file.write('# This file describes the network interfaces available on your system\n')
    new_file.write('# and how to activate them. For more information, see interfaces(5).\n')
    new_file.write('\n')
    new_file.write('# The loopback network interface\n')
    new_file.write('auto lo\n')
    new_file.write('iface lo inet loopback\n')
    new_file.write('\n')
    new_file.write('# The primary network interface\n')
    new_file.write('# Management Interface\n')
    new_file.write('auto eth0\n')
    new_file.write('        iface eth0 inet manual\n')
    new_file.write('        up ifconfig $IFACE 0.0.0.0 up\n')
    new_file.write('        up ip link set $IFACE promisc on\n')
    new_file.write('        down ip link set $IFACE promisc off\n')
    new_file.write('        down ifconfig $IFACE down\n')
    new_file.write('\n')
    new_file.write('auto br-eth0\n')
    new_file.write('        iface br-eth0 inet static\n')
    new_file.write('        address ' + ip1 + '\n')
    new_file.write('        netmask ' + netmask1 + '\n')
    new_file.write('        gateway ' + gateway1 + '\n')
    new_file.write('        up ip link set $IFACE promisc on\n')
    new_file.write('        down ip link set $IFACE promisc off\n')
    new_file.write('\n')
    new_file.write('# Additional Interface for application access\n')
    new_file.write('auto eth1\n')
    new_file.write('        iface eth1 inet static\n')
    new_file.write('        address ' + ip2 + '\n')
    new_file.write('        netmask ' + netmask2 + '\n')
    new_file.write('        up ip link set $IFACE promisc on\n')
    new_file.write('        down ip link set $IFACE promisc off\n')

    #close temp file
    new_file.close()
    close(fh)
        
    #Move new file
    command = ['sudo', 'mv', abs_path, "/etc/network/interfaces"];
    subprocess.call(command, shell=False)
    os.chmod('/etc/hostname', 0644)
    command = ['sudo', 'chown', 'root:root', "/etc/network/interfaces"];
    subprocess.call(command, shell=False)

    command = ['sudo', 'ifdown', 'br-eth0']
    subprocess.call(command, shell=False)
    command = ['sudo', 'ifup', 'br-eth0']
    subprocess.call(command, shell=False)  
    
    command = ['sudo', 'ifdown', 'eth1']
    subprocess.call(command, shell=False)
    command = ['sudo', 'ifup', 'eth1']
    subprocess.call(command, shell=False)            

# #  Web application main  # #
def main_http():
    # Start the Bottle webapp
    bottle.debug(True)
    bottle.TEMPLATE_PATH.insert(0, '/opt/stack/workloadmgr/workloadmgr/tvault-config/views')
    bottle.run(host='0.0.0.0', port=80, reloader=False)
    
def main():
    #configure the networking
    try:
        try:
            ovfEnv = subprocess.Popen("echo `vmtoolsd --cmd \"info-get guestinfo.ovfenv\"`", shell=True, stdout=subprocess.PIPE).stdout.read()
            propertyMap = getPropertyMap(ovfEnv)
            
            ip1 = propertyMap["ip1"]
            ip2 = propertyMap.get('ip2', '192.168.3.100')
            hostname    = propertyMap["hostname"]
            
            #adjust hostname       
            fh, abs_path = mkstemp()
            new_file = open(abs_path,'w')
            new_file.write(hostname)
            #close temp file
            new_file.close()
            close(fh)
            #Move new file
            command = ['sudo', 'mv', abs_path, "/etc/hostname"];
            subprocess.call(command, shell=False)
            os.chmod('/etc/hostname', 0644)
            command = ['sudo', 'chown', 'root:root', "/etc/hostname"];
            subprocess.call(command, shell=False)
    
            command = ['sudo', 'hostname', hostname];
            subprocess.call(command, shell=False)        
                    
            # adjust hosts file
            fh, abs_path = mkstemp()
            new_file = open(abs_path,'w')
            new_file.write('127.0.0.1 localhost\n')
            new_file.write('127.0.0.1 ' + hostname + '\n')
            new_file.write(ip1 + ' ' + hostname + '\n')
            new_file.write(ip2 + ' ' + hostname + '\n')
            
            #close temp file
            new_file.close()
            close(fh)
            #Move new file
            command = ['sudo', 'mv', abs_path, "/etc/hosts"];
            subprocess.call(command, shell=False)
            os.chmod('/etc/hosts', 0644)
            command = ['sudo', 'chown', 'root:root', "/etc/hosts"];
            subprocess.call(command, shell=False)
            
            set_network_interfaces(propertyMap)
        except Exception as ex:
            pass
        
        command = ['sudo', 'rabbitmqctl', 'change_password', 'guest', TVAULT_SERVICE_PASSWORD]
        subprocess.call(command, shell=False)

        
        #SSL regeneration     
        prev_hostname = 'none'
        Config = ConfigParser.RawConfigParser()
        try:
            Config.read('/etc/tvault-config/tvault-config.conf')
            config_data = dict(Config._defaults)
            prev_hostname = config_data.get('hostname', 'none')
        except Exception as exception:
            prev_hostname = 'none'

        if prev_hostname != socket.gethostname():
            if os.path.exists("/opt/stack/workloadmgr/etc/gen-cer"):
                command = ['sudo', 'mv', "/opt/stack/workloadmgr/etc/gen-cer", "/etc/tvault/ssl/"];
                subprocess.call(command, shell=False, cwd="/etc/tvault/ssl")
                os.chmod('/etc/tvault/ssl/gen-cer',0554)
                command = ['sudo', 'sh','gen-cer',socket.gethostname()];
                subprocess.call(command, shell=False, cwd="/etc/tvault/ssl")
                command = ['sudo', 'rm', '-rf',"/etc/tvault/ssl/"+socket.gethostname()+".csr"];
                subprocess.call(command, shell=False, cwd="/etc/tvault/ssl")
                command = ['sudo', 'mv', "gen-cer","/opt/stack/workloadmgr/etc/"];
                subprocess.call(command, shell=False, cwd="/etc/tvault/ssl") 
                Config.set(None, 'hostname', socket.gethostname())
               
                command = ['sudo', 'mv', "/etc/tvault/ssl/localhost.crt", "/etc/tvault/ssl/localhost_bak.crt"];
                subprocess.call(command, shell=False)
                command = ['sudo', 'mv', "/etc/tvault/ssl/localhost.key", "/etc/tvault/ssl/localhost_bak.key"];
                subprocess.call(command, shell=False)
                command = ['sudo', 'mv', "/etc/tvault/ssl/"+socket.gethostname()+".crt", "/etc/tvault/ssl/localhost.crt"];
                subprocess.call(command, shell=False)
                command = ['sudo', 'mv', "/etc/tvault/ssl/"+socket.gethostname()+".key", "/etc/tvault/ssl/localhost.key"];
                subprocess.call(command, shell=False)
                
                #create hostkeys
                command = ['sudo', 'rm', "/etc/ssh/ssh_host_rsa_key"];
                subprocess.call(command, shell=False)               
                command = ['sudo', 'ssh-keygen', '-f', "/etc/ssh/ssh_host_rsa_key", '-b', '4096', '-t', 'rsa', '-q', '-N', ""];
                subprocess.call(command, shell=False)  
                
                with open('/etc/tvault-config/tvault-config.conf', 'wb') as configfile:
                    Config.write(configfile)
                                   
    except Exception as exception:
        #TODO: implement logging
        pass
    
    http_thread = Thread(target=main_http)
    http_thread.daemon = True # thread dies with the program
    http_thread.start()

    bottle.debug(True)
    srv = SSLWSGIRefServer(host='0.0.0.0', port=443)
    bottle.run(server=srv, app=app, quiet=False, reloader=False)          

if __name__ == "__main__":
    main()
