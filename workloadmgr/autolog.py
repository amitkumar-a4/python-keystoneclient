# Copyright 2014 TrilioData Inc.
# All Rights Reserved.


import logging
import random
import re
import types
import inspect

"""This file has been *heavily* modified to remove the use of global variables, implement
a logging class instead of relying on sys.stdout, remove the function log decorator, remove
the module log decorator, allow color changing on any log call,
allow indentation level changing on any log call, and PEP-8 formatting.

Copyright (C) 2013 Ben Gelb
"""


BLACK = "\033[0;30m"
BLUE = "\033[0;34m"
GREEN = "\033[0;32m"
CYAN = "\033[0;36m"
RED = "\033[0;31m"
PURPLE = "\033[0;35m"
BROWN = "\033[0;33m"
GRAY = "\033[0;37m"
BOLDGRAY = "\033[1;30m"
BOLDBLUE = "\033[1;34m"
BOLDGREEN = "\033[1;32m"
BOLDCYAN = "\033[1;36m"
BOLDRED = "\033[1;31m"
BOLDPURPLE = "\033[1;35m"
BOLDYELLOW = "\033[1;33m"
WHITE = "\033[1;37m"
NORMAL = "\033[0m"


class Logger(object):
    def __init__(self, log=None, indent_string='    ',
                 indent_level=0, *args, **kwargs):
        self.__log = log
        self.indent_string = indent_string
        self.indent_level = indent_level

    @property
    def __logger(self):
        if not self.__log:
            FORMAT = '%(asctime)s - %(levelname)s - %(message)s'
            self.__log = logging.getLogger(__name__)
            self.__log.setLevel(logging.INFO)
            handler = logging.StreamHandler()
            handler.setLevel(logging.INFO)
            handler.setFormatter(logging.Formatter(FORMAT))
            self.__log.addHandler(handler)
        return self.__log

    def _log_levels(self, level):
        return {
            'debug': 10,
            'info': 20,
            'warning': 30,
            'critical': 40,
            'error': 50
        }.get(level, 'info')

    def update_indent_level(self, val):
        self.indent_level = val

    def log(self, message, color=None, log_level='info',
            indent_level=None, *args, **kwargs):
        msg_params = {
            'color': color or NORMAL,
            'indent': self.indent_string * (indent_level or self.indent_level),
            'msg': message
        }
        _message = "{color} {indent}{msg}".format(**msg_params)
        self.__logger.log(self._log_levels(log_level), _message)


def format_args(args, kwargs, password_arg=None):
    """
    makes a nice string representation of all the arguments
    """
    allargs = []
    for idx, item in enumerate(args):
        if password_arg and password_arg == idx + 1:
            allargs.append('%s' % '******')
        elif 'password' in str(item).lower():
            allargs.append('%s' % '******')
        else:
            arg_str = '%s' % str(item)
            if len(arg_str) > 100:
                arg_str = arg_str[:96] + " ..."
            allargs.append(arg_str)

    for key, item in kwargs.items():
        if 'password' in key.lower():
            allargs.append('%s=%s' % (key, '******'))
        elif 'password' in str(item).lower():
            allargs.append('%s=%s' % (key, '******'))
        else:
            arg_str = '%s=%s' % (key, str(item))
            if len(arg_str) > 100:
                arg_str = arg_str[:96] + " ..."
            allargs.append(arg_str)

    formattedArgs = ', '.join(allargs)

    if len(formattedArgs) > 1000:
        return formattedArgs[:996] + " ..."
    return formattedArgs


def log_method(logger, method_name=None, log_args=True,
               log_retval=True, password_arg=None):
    """use this for class or instance methods, it formats with the object out front."""
    def _real_log_method(method):
        def _wrapper(*args, **kwargs):
            if log_args:
                arg_str = format_args(args, kwargs, password_arg)
            else:
                arg_str = ''
            message_enter = "{method_color}{method_name}{message_color} ENTER {normal_color}({arg_str}) {file_name} {line_num}".format(**{
                'method_color': BROWN,
                'method_name': "{0}".format(method_name or method.__name__),
                'message_color': PURPLE,
                'normal_color': NORMAL,
                'arg_str': arg_str,
                'file_name': method.func_code.co_filename,
                'line_num': method.func_code.co_firstlineno,
            })

            logger.log(message_enter)
            ret_val = method(*args, **kwargs)

            ret_val_to_log = None
            if not log_retval:
                ret_val_to_log = ' '
            elif 'password' in str(ret_val).lower():
                ret_val_to_log = "******"

            message_exit = "{method_color}{method_name}{message_color} EXIT {normal_color}(Return Value(s):{ret_val}) {file_name} {line_num}".format(**{
                'method_color': BROWN,
                'method_name': "{0}".format(method_name or method.__name__),
                'message_color': BLUE,
                'normal_color': NORMAL,
                'ret_val': ret_val_to_log or ret_val,
                'file_name': method.func_code.co_filename,
                'line_num': method.func_code.co_firstlineno,
            })
            logger.log(message_exit)

            return ret_val
        return _wrapper
    return _real_log_method
