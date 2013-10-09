#!/usr/bin/env python

# Copyright (c) 2013 TrilioData
# All Rights Reserved.

# THIS FILE IS MANAGED BY THE GLOBAL REQUIREMENTS REPO - DO NOT EDIT
import setuptools

from workloadmanager.openstack.common import setup as common_setup

requires = common_setup.parse_requirements()
depend_links = common_setup.parse_dependency_links()
project = 'workloadmanager'

filters = [
    "AvailabilityZoneFilter = "
    "workloadmanager.openstack.common.scheduler.filters."
    "availability_zone_filter:AvailabilityZoneFilter",
    "CapabilitiesFilter = "
    "workloadmanager.openstack.common.scheduler.filters."
    "capabilities_filter:CapabilitiesFilter",
    "CapacityFilter = "
    "workloadmanager.scheduler.filters.capacity_filter:CapacityFilter",
    "JsonFilter = "
    "workloadmanager.openstack.common.scheduler.filters.json_filter:JsonFilter",
    "RetryFilter = "
    "workloadmanager.scheduler.filters.retry_filter:RetryFilter",
]

weights = [
    "CapacityWeigher = workloadmanager.scheduler.weights.capacity:CapacityWeigher",
]

setuptools.setup(
    name=project,
    version= common_setup.get_version(project, '2013.1.3'),
    description='WorkloadManager',
    author='TrilioData',
    author_email='info@triliodata.com',
    url='http://www.triliodata.com/',
    classifiers=[
        'Environment :: TrilioData',
        'Intended Audience :: Information Technology',
        'Intended Audience :: System Administrators',
        'License :: TrilioData',
        'Operating System :: POSIX :: Linux',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
    ],
    cmdclass=common_setup.get_cmdclass(),
    packages=setuptools.find_packages(exclude=['bin', 'smoketests']),
    install_requires=requires,
    dependency_links=depend_links,
    entry_points={
        'workloadmanager.scheduler.filters': filters,
        'workloadmanager.scheduler.weights': weights,
    },
    include_package_data=True,
    test_suite='nose.collector',
    setup_requires=['setuptools_git>=0.4'],
    scripts=['bin/workloadmanager-all',
             'bin/workloadmanager-api',
             'bin/workloadmanager-clear-rabbit-queues',
             'bin/workloadmanager-manage',
             'bin/workloadmanager-rootwrap',
             'bin/workloadmanager-rpc-zmq-receiver',
             'bin/workloadmanager-scheduler',
             'bin/workloadmanager-workloads'],
    py_modules=[])
