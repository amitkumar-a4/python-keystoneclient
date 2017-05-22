# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.


from keystoneclient import exceptions

from workloadmgr import exception
from workloadmgr.common import workloadmgr_keystoneclient as wkc
from workloadmgr.common.clients import client_plugin

CLIENT_NAME = 'keystone'


class KeystoneClientPlugin(client_plugin.ClientPlugin):

    exceptions_module = exceptions

    service_types = [IDENTITY] = ['identity']

    def _create(self):
        client = wkc.KeystoneClient(self.context)
        keystone_client = client.client
        return keystone_client

    def is_not_found(self, ex):
        return isinstance(ex, exceptions.NotFound)

    def is_over_limit(self, ex):
        return isinstance(ex, exceptions.RequestEntityTooLarge)

    def is_conflict(self, ex):
        return isinstance(ex, exceptions.Conflict)

    def get_role_id(self, role):
        try:
            role_obj = self.client().client.roles.get(role)
            return role_obj.id
        except exceptions.NotFound:
            role_list = self.client().client.roles.list(name=role)
            for role_obj in role_list:
                if role_obj.name == role:
                    return role_obj.id

        raise exception.EntityNotFound(entity='KeystoneRole', name=role)

    def get_project_id(self, project):
        if project is None:
            return None
        try:
            project_obj = self.client().client.projects.get(project)
            return project_obj.id
        except exceptions.NotFound:
            project_list = self.client().client.projects.list(name=project)
            for project_obj in project_list:
                if project_obj.name == project:
                    return project_obj.id

        raise exception.EntityNotFound(entity='KeystoneProject',
                                       name=project)

    def get_domain_id(self, domain):
        if domain is None:
            return None
        try:
            domain_obj = self.client().client.domains.get(domain)
            return domain_obj.id
        except exceptions.NotFound:
            domain_list = self.client().client.domains.list(name=domain)
            for domain_obj in domain_list:
                if domain_obj.name == domain:
                    return domain_obj.id

        raise exception.EntityNotFound(entity='KeystoneDomain', name=domain)

    def get_group_id(self, group):
        if group is None:
            return None
        try:
            group_obj = self.client().client.groups.get(group)
            return group_obj.id
        except exceptions.NotFound:
            group_list = self.client().client.groups.list(name=group)
            for group_obj in group_list:
                if group_obj.name == group:
                    return group_obj.id

        raise exception.EntityNotFound(entity='KeystoneGroup', name=group)

    def get_service_id(self, service):
        if service is None:
            return None
        try:
            service_obj = self.client().client.services.get(service)
            return service_obj.id
        except exceptions.NotFound:
            service_list = self.client().client.services.list(name=service)

            if len(service_list) == 1:
                return service_list[0].id
            elif len(service_list) > 1:
                raise exception.KeystoneServiceNameConflict(service=service)
            else:
                raise exception.EntityNotFound(entity='KeystoneService',
                                               name=service)

    def get_user_id(self, user):
        if user is None:
            return None
        try:
            user_obj = self.client().client.users.get(user)
            return user_obj.id
        except exceptions.NotFound:
            user_list = self.client().client.users.list(name=user)
            for user_obj in user_list:
                if user_obj.name == user:
                    return user_obj.id

        raise exception.EntityNotFound(entity='KeystoneUser', name=user)

    def get_region_id(self, region):
        try:
            region_obj = self.client().client.regions.get(region)
            return region_obj.id
        except exceptions.NotFound:
            raise exception.EntityNotFound(entity='KeystoneRegion',
                                           name=region)
