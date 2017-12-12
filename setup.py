# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 TrilioData, Inc.
# All Rights Reserved.


import setuptools

from workloadmgr.openstack.common import setup as common_setup

requires = common_setup.parse_requirements()
depend_links = common_setup.parse_dependency_links()
project = 'workloadmgr'

filters = [
    "AvailabilityZoneFilter = "
    "workloadmgr.openstack.common.scheduler.filters."
    "availability_zone_filter:AvailabilityZoneFilter",
    "CapabilitiesFilter = "
    "workloadmgr.openstack.common.scheduler.filters."
    "capabilities_filter:CapabilitiesFilter",
    "CapacityFilter = "
    "workloadmgr.scheduler.filters.capacity_filter:CapacityFilter",
    "JsonFilter = "
    "workloadmgr.openstack.common.scheduler.filters.json_filter:JsonFilter",
    "RetryFilter = "
    "workloadmgr.scheduler.filters.retry_filter:RetryFilter",
]

weights = [
    "CapacityWeigher = workloadmgr.scheduler.weights.capacity:CapacityWeigher",
]

setuptools.setup(
    name=project,
    version=common_setup.get_version(project, '2013.1.3'),
    description='Data Protection As a Service',
    author='OpenStack',
    author_email='workloadmgr@lists.launchpad.net',
    url='http://www.openstack.org/',
    classifiers=[
        'Environment :: OpenStack',
        'Intended Audience :: Information Technology',
        'Intended Audience :: System Administrators',
        'License :: OSI Approved :: Apache Software License',
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
        'workloadmgr.scheduler.filters': filters,
        'workloadmgr.scheduler.weights': weights,
    },
    include_package_data=True,
    test_suite='nose.collector',
    setup_requires=['setuptools_git>=0.4'],
    scripts=['bin/workloadmgr-all',
             'bin/workloadmgr-api',
             'bin/workloadmgr-workloads',
             'bin/workloadmgr-clear-rabbit-queues',
             'bin/workloadmgr-manage',
             'bin/workloadmgr-rootwrap',
             'bin/workloadmgr-scheduler',
             'bin/workloadmgr-rpc-zmq-receiver'],
    py_modules=[])
