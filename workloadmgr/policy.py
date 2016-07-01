# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.

"""Policy Engine For WorkloadMgr"""

from oslo.config import cfg

from workloadmgr.openstack.common.gettextutils import _
from workloadmgr import exception
from workloadmgr import flags
from workloadmgr.openstack.common import policy
from workloadmgr import utils

policy_opts = [
    cfg.StrOpt('policy_file',
               default='policy.json',
               help=_('JSON file representing policy')),
    cfg.StrOpt('policy_default_rule',
               default='default',
               help=_('Rule checked when requested rule is not found')), ]

FLAGS = flags.FLAGS
FLAGS.register_opts(policy_opts)

_POLICY_PATH = None
_POLICY_CACHE = {}


def reset():
    global _POLICY_PATH
    global _POLICY_CACHE
    _POLICY_PATH = None
    _POLICY_CACHE = {}
    policy.reset()


def init():
    global _POLICY_PATH
    global _POLICY_CACHE
    if not _POLICY_PATH:
        _POLICY_PATH = utils.find_config(FLAGS.policy_file)
    utils.read_cached_file(_POLICY_PATH, _POLICY_CACHE,
                           reload_func=_set_brain)


def _set_brain(data):
    default_rule = FLAGS.policy_default_rule
    policy.set_brain(policy.HttpBrain.load_json(data, default_rule))


def enforce(context, action, target):
    """Verifies that the action is valid on the target in this context.

       :param context: workloadmgr context
       :param action: string representing the action to be checked
           this should be colon separated for clarity.
           i.e. ``compute:create_instance``,
           ``compute:attach_volume``,
           ``volume:attach_volume``

       :param object: dictionary representing the object of the action
           for object creation this should be a dictionary representing the
           location of the object e.g. ``{'project_id': context.project_id}``

       :raises workloadmgr.exception.PolicyNotAuthorized: if verification fails.

    """
    init()

    match_list = ('rule:%s' % action,)
    credentials = context.to_dict()

    policy.enforce(match_list, target, credentials,
                   exception.PolicyNotAuthorized, action=action)


def check_is_admin(roles):
    """Whether or not roles contains 'admin' role according to policy setting.

    """
    init()

    action = 'context_is_admin'
    match_list = ('rule:%s' % action,)
    # include project_id on target to avoid KeyError if context_is_admin
    # policy definition is missing, and default admin_or_owner rule
    # attempts to apply.  Since our credentials dict does not include a
    # project_id, this target can never match as a generic rule.
    target = {'project_id': ''}
    credentials = {'roles': roles}

    return policy.enforce(match_list, target, credentials)
