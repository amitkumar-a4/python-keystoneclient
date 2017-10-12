options = \
    {'type': 'openstack',
     'openstack': {
         'instances':
         [
             {
                 'id': '6da5223d-6865-4c76-8551-e52f03dcca19',  # identifies the instance
                 'name': 'restored',  # new name for the new instance
                 'include': True,    # False if you want to exclude this instance from
                 'power': {          # the order in which we need to poweron the vm
                     'sequence': 1,
                 },
                 # if flavor exists, reuse the flavor or
                 # create a new flavor
                 'flavor': {         # flavor of the vm. If restore flow finds a flavor that
                     # matches these attributes, it uses the flavor id.
                     'vcpus': 1,
                     'ram': 8,       # otherwise it creates new flavor
                     'disk': 20,
                     'ephemeral': True,
                     'swap': 8,
                 },
                 # First try attaching to the following network.
                 # Each network is keyed of the mac address of the original VM.
                 # if there is no mention of mac address, then it tries to
                 # restore the VM to the original network. Otherwise it
                 # tries to find the new network from the networks_mapping
                 # stanza. If it can't find a network, restore fails
                 'nics': [
                     {
                         "mac_address": "fa:16:3e:3b:e8:dc",
                         'network': {
                             "id": "ab6a7f2e-c72b-4c8a-a5c2-ddda28973107",
                             'subnet': {
                                 "id": "bf4efb22-a40f-4a29-a830-a3ed899c7560",
                             },
                         },
                     },
                     {
                         "mac_address": "fa:16:3e:1a:fa:b8",
                         'network': {
                             "id": "9455c1f9-15b1-45cd-bdef-b47b14b075cb",
                             'subnet': {
                                 "id": "47b53ea3-0377-413c-ad11-4c4eaba41d8b",
                             },
                         },
                     },
                 ],
             },
         ],
         'networks_mapping': {
             # We only need private networking
             # workload manager need not do anything mappings to
             # router and perhaps to mapping to public networking
             # if the mapping is not found, we fail the restore?
             'private': [
                 {
                     # private
                     'snapshot_network': {
                         'id': 'd9bd4be8-2488-4bdd-8c01-e05e576228a8',
                         'subnet': {
                             "id": "9cd0b99f-6553-4707-8910-3fe345377a96",
                         },
                     },
                     # test-network
                     'target_network': {
                         'id': 'ab6a7f2e-c72b-4c8a-a5c2-ddda28973107',
                         'subnet': {
                             "id": "bf4efb22-a40f-4a29-a830-a3ed899c7560",
                         },
                     }
                 },
                 {
                     # private1
                     'snapshot_network': {
                         'id': '6f22610c-c299-40bb-a7dd-bbeb20fbd210',
                         'subnet': {
                             "id": "c7e4904f-4806-4a37-b44d-57e52b7a7828",
                         },
                     },
                     # test-network1
                     'target_network': {
                         'id': '9455c1f9-15b1-45cd-bdef-b47b14b075cb.bak',
                         'subnet': {
                             "id": "47b53ea3-0377-413c-ad11-4c4eaba41d8b",
                         },
                     }
                 }
             ],
         }
     }
     }
import os
import json
print json.dumps(options).replace("true", "True")
