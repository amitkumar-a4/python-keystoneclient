# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.
"""Policy Engine For Workloadmgr"""


from oslo_config import cfg
from oslo_policy import opts as policy_opts
from oslo_policy import policy

from workloadmgr import exception

CONF = cfg.CONF
policy_opts.set_defaults(cfg.CONF, 'policy.json')

_ENFORCER = None


def init():
    global _ENFORCER
    if not _ENFORCER:
        _ENFORCER = policy.Enforcer(CONF)


def enforce_action(context, action):
    """Checks that the action can be done by the given context.

    Applies a check to ensure the context's project_id and user_id can be
    applied to the given action using the policy enforcement api.
    """

    return enforce(context, action, {'project_id': context.project_id,
                                     'user_id': context.user_id})


def enforce(context, action, target):
    """Verifies that the action is valid on the target in this context.

       :param context: workloadmgr context
       :param action: string representing the action to be checked
           this should be colon separated for clarity.
           i.e. ``workload:workload_get``,
           ``workload:workload_show``,
           ``workload:workload_get_all``
       :param object: dictionary representing the object of the action
           for object creation this should be a dictionary representing the
           location of the object e.g. ``{'project_id': context.project_id}``

       :raises PolicyNotAuthorized: if verification fails.

    """
    init()

    return _ENFORCER.enforce(action, target, context.to_dict(),
                             do_raise=True,
                             exc=exception.PolicyNotAuthorized,
                             action=action)


def check_is_admin(roles, context=None):
    """Whether or not user is admin according to policy setting.

    """
    init()

    # include project_id on target to avoid KeyError if context_is_admin
    # policy definition is missing, and default admin_or_owner rule
    # attempts to apply.
    target = {'project_id': ''}
    if context is None:
        credentials = {'roles': roles}
    else:
        credentials = context.to_dict()

    return _ENFORCER.enforce('context_is_admin', target, credentials)
