# Written by Brendan O'Connor, brenocon@gmail.com, www.anyall.org
#  * Originally written Aug. 2005
#  * Posted to gist.github.com/16173 on Oct. 2008
 
#   Copyright (c) 2003-2006 Open Source Applications Foundation
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
 
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
    def __init__(self, log=None, indent_string='    ', indent_level=0, *args, **kwargs):
        self.__log = log
        self.indent_string = indent_string
        self.indent_level = indent_level
 
    @property
    def __logger(self):
        if not self.__log:
            FORMAT = '%(asctime)s - %(levelname)s - %(message)s'
            self.__log = logging.getLogger(__name__)
            self.__log.setLevel(logging.DEBUG)
            handler = logging.StreamHandler()
            handler.setLevel(logging.DEBUG)
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
 
    def log(self, message, color=None, log_level='info', indent_level=None, *args, **kwargs):
        msg_params = {
            'color': color or NORMAL,
            'indent': self.indent_string * (indent_level or self.indent_level),
            'msg': message
        }
        _message = "{color} {indent}{msg}".format(**msg_params)
        self.__logger.log(self._log_levels(log_level), _message)
 
 
def format_args(args, kwargs):
    """
    makes a nice string representation of all the arguments
    """
    allargs = []
    for item in args:
        allargs.append('%s' % str(item))
 
    for key, item in kwargs.items():
        allargs.append('%s=%s' % (key, str(item)))
 
    formattedArgs = ', '.join(allargs)
 
    if len(formattedArgs) > 500:
        return formattedArgs[:496] + " ..."
    return formattedArgs
 
 
def log_method(logger, method_name=None):
    """use this for class or instance methods, it formats with the object out front."""
    def _real_log_method(method):
        def _wrapper(*args, **kwargs):
            arg_str = format_args(args, kwargs)
            message_enter = "{method_color}{method_name}{message_color} ENTER {normal_color}({arg_str})".format(**{
                'method_color': BROWN,
                'method_name': "{}".format(method_name or method.__name__),
                'message_color': PURPLE,
                'normal_color': NORMAL,
                'arg_str': arg_str,
            })

            logger.log(message_enter)
            ret_val = method(*args, **kwargs)
            
            message_exit = "{method_color}{method_name}{message_color} EXIT {normal_color}(Return Value(s):{ret_val})".format(**{
                'method_color': BROWN,
                'method_name': "{}".format(method_name or method.__name__),
                'message_color': BLUE,
                'normal_color': NORMAL,
                'ret_val': ret_val,
            })             
            logger.log(message_exit)
            
            return ret_val
        return _wrapper
    return _real_log_method

