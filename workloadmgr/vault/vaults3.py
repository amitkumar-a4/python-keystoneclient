# vim: tabstop=4 shiftwidth=4 softtabstop=4
# Copyright (c) 2017 Trilio Data, Inc.
# All Rights Reserved.
""" Trilio S3 Backend implimentation

    This module contains the back end implimentation of all of all S3 specific
    support.
"""

# Disable pylint unused-argument checking because this is an interface
# implimentation file and not all method arguments would be used.
# pylint: disable=unused-argument
from __future__ import print_function, unicode_literals

import datetime
import time
import json
import os

# AWS S3 API... why we're doing all this.
import boto3
import botocore
from botocore.exceptions import ClientError

BASENAME = 's3'


def _make_timestamp(modified_time):
    """ Utility function used to convert a datetime to an OS timestamp.

    Args:
        modified_time (datetime): Datatime object to convert to a Unix Epoc timestamp.

    Returns:
        The value of modified_time as a timestamp.
    """
    naive_time = modified_time.replace(tzinfo=None)
    delta_seconds = (naive_time - datetime.datetime(1970, 1, 1)).total_seconds()
    return delta_seconds


class S3Backend(object):
    """ S3 Backend implimentation.

    A Wrapper for the AWS S3 boto3 and botocore API. This class encapsulates all S3
    operations and exposes them as a backend storage instance.
    """
    def __init__(self, options):
        config_object = None
        if options['s3_signature'] != 'default':
            config_object = botocore.client.Config(signature_version=options['s3_signature'])

        self.__client = boto3.client('s3',
                                     region_name=options['os_options']['region_name'],
                                     use_ssl=options['s3_ssl'],
                                     aws_access_key_id=options['user'],
                                     aws_secret_access_key=options['key'],
                                     endpoint_url=options['os_options']['object_storage_url'],
                                     config=config_object)

        self.__bucket_name = options['bucket']
        # Keep the TransferConfig here for future performance tweaking.
        # I'm not sure if 3rd Party (Not AWS) S3 APIs will support this.
        # self.__transfer_config = boto3.s3.transfer.TransferConfig(multipart_threshold=10485760,
        #                                                           max_concurrency=10,
        #                                                           multipart_chunksize=5242880,
        #                                                           num_download_attempts=5,
        #                                                           max_io_queue=100,
        #                                                           io_chunksize=1024 * 1024,
        #                                                           use_threads=True)
        # self.__transfer_config = boto3.s3.transfer.TransferConfig(multipart_threshold=3355443,
        #                                                    max_concurrency=10,
        #                                                    multipart_chunksize=3355443,
        #                                                    num_download_attempts=5,
        #                                                    max_io_queue=100,
        #                                                    io_chunksize=262144,
        #                                                    use_threads=True)

    def __delete_object_list(self, object_list):
        """ Utility method that takes a list of objects and puts it in the correct format
            for the S3 delete_objects() API.

        Args:
            object_list (list): A list of objects with the correct S3 path.
        """
        try:
            object_delete_list = []
            for obj in object_list:
                object_delete_list.append({'Key': obj})

            self.__client.delete_objects(Bucket=self.__bucket_name,
                                         Delete={'Objects': object_delete_list})
        except ClientError:
            raise

    def __delete_object_tree(self, object_tree):
        """ Utility method used to perform a rmdir operation on an object hierarchy

        Args:
            object_tree (str): Object/Tree path.
        """
        try:
            object_list = []
            # The list_objects_v2 API is limited to 1,000 objects so we need to
            # use a paginator.
            list_paginator = self.__client.get_paginator('list_objects_v2')
            page_iterator = list_paginator.paginate(Bucket=self.__bucket_name, Prefix=object_tree)
            for objects in page_iterator:
                if 'Contents' in objects and objects.get('KeyCount', len(objects['Contents'])) > 0:
                    for obj in objects['Contents']:
                        object_list.append(obj['Key'])

                    self.__delete_object_list(object_list)
        except ClientError:
            raise

    def delete_object_list(self, object_list, options):
        """ Delete a list of objects.

        Args:
            object_list (list): List of objects. Each with a full object path
                                in correct format.
            options (dic): Dictionary of configuration options.
        """
        self.__delete_object_list(object_list)

    def delete_object(self, args, options):
        """ Delete an object from the S3 object store.

        The object and any segments stored in the segment directory will be
        removed.

        Args:
            args (list): List of object name parts.
            options (dic): Dictionary of configuration options.
        """
        try:
            if not args:
                return

            object_name = '/'.join(args)

            if '-segments' in object_name:
                # Just delete a single segment.
                self.__client.delete_object(Bucket=self.__bucket_name,
                                            Key=object_name)
            else:
                # Delete the segmented object
                if not options['leave_segments']:
                    object_tree = object_name + '-segments/'
                    self.__delete_object_tree(object_tree)

                # if is_folder == True:
                #     object_name = object_name + '/'
                self.__client.delete_object(Bucket=self.__bucket_name,
                                            Key=object_name + ".manifest")

        except ClientError:
            raise

    def __wait_for_object(self, object_name, retries=1):
        """ Utility method used to wait for a S3 object to become available.

        This routine will keep performing a head_object() request every second
        for "retries" number of times. This was added to work around any potential
        eventual consistancey issues when uploading to AWS.

        Args:
            object_name (str): Name of the object.
            retries (int): Optional parameter that defaults to 1.

        Returns:
            Returns when the object is available or ClientError not found exception.
        """
        # Make sure retries is at least 1
        retries = max(1, retries)
        try:
            for retry in range(0, retries):
                try:
                    self.__client.head_object(Bucket=self.__bucket_name,
                                              Key=object_name)
                    return
                except ClientError as error:
                    if (error.response['ResponseMetadata']['HTTPStatusCode'] == 404 and
                            retry + 1 != retries):
                        time.sleep(1)
                        continue
                    raise
        except ClientError:
            raise

    def get_object_manifest(self, object_name):
        """ Download and return the object manifest as a json array.

            Args:
                object_name (str): Name of the object.

            Returns:
                Object manifest as a dictionary.
        """
        manifest_name = object_name.strip('/') + ".manifest"
        try:
            resp = self.__client.get_object(Bucket=self.__bucket_name, Key=manifest_name)
            return json.loads(resp['Body'].read(resp['ContentLength']))
        except ClientError as error:
            if error.response['ResponseMetadata']['HTTPStatusCode'] != 404:
                raise
            else:
                try:
                    self.__wait_for_object(manifest_name, 10)
                    resp = self.__client.get_object(Bucket=self.__bucket_name,
                                                    Key=manifest_name)
                    return json.loads(resp['Body'].read(resp['ContentLength']))
                except ClientError:
                    raise

    def download_object(self, args, options):
        """ Download a file from the S3 object store.

        Args:
            args (list): List of object name parts.
            options (dic): Dictionary of configuration options.

        Returns:
            On success, the contents of the object are downloaded to file identidfied
            by options.out_file.
        """
        try:
            object_name = '/'.join(args)
            # err = self.__client.download_fileobj(Bucket=self.__bucket_name, Key=object_name,
            #                                      Fileobj=fileHandle)
            self.__client.download_file(self.__bucket_name, object_name, options.out_file)

        except ClientError:
            raise
        except Exception:
            raise

    def list_objects(self, args, options):
        """ Return a list of objects based on the provided prefix.

        Used to generate a directory listing based on a prefix path
        constructed from the object parts in args[] and the options.prefix.

        Args:
            args (list): List of prefix keyParts
            options (dic): Dictionary of configuration options

        Returns:
            On success a list of unique items to be used as a directory listing.
        """
        object_set = set()
        prefix = '/'.join(args)
        if options['prefix'] is not None:
            prefix = prefix + '/' + options['prefix']
            if prefix.endswith('/'):
                prefix = prefix[:-1]

        try:
            # The list_objects_v2 API is limited to 1,000 objects so we need to
            # use a paginator.
            list_paginator = self.__client.get_paginator('list_objects_v2')
            if not args:
                page_iterator = list_paginator.paginate(Bucket=self.__bucket_name,  # Prefix='',
                                                        Delimiter='/')
            else:
                page_iterator = list_paginator.paginate(Bucket=self.__bucket_name,
                                                        Prefix=prefix)
            for objects in page_iterator:
                if 'Contents' in objects and objects.get('KeyCount', len(objects['Contents'])) > 0:
                    split_token = prefix + '/'
                    for item in objects['Contents']:
                        path, object_name = os.path.split(item['Key'].rstrip('/'))

                        # If this a S3 backend that does not support empty directory
                        # objects we need to hide the "hidden" file and return the
                        # directory that it is in.
                        if object_name == 'x.hidden':
                            root_path, sub_dir = os.path.split(path)
                            if len(sub_dir) > 0 and root_path != '' and path != prefix:
                                object_set.add(sub_dir)
                            continue
                        root_path, _ = os.path.split(prefix)
                        if ((root_path != path and path != prefix) or object_name == '' or
                                item['Key'] == split_token):
                            continue

                        # Keep this code here for now. I might need to go back to this
                        # detailed parsing. - cjk
                        # key_parts = string.split(item['Key'], split_token)
                        # if key_parts[0] == '.':
                        #     continue
                        #
                        # if split_token == '/' and key_parts[0] != '':
                        #     object_name = key_parts[0]
                        # else:
                        #     if len(key_parts) > 1 and key_parts[0] == '' and key_parts[1] != '':
                        #         sub_part = string.split(key_parts[1], '/')
                        #         object_name = sub_part[0]
                        #     else:
                        #         continue

                        if path == prefix:
                            # Trim ".manifest" and everything after it if that is in the name.
                            object_set.add(object_name.split(".manifest", 1)[0])

                if 'CommonPrefixes' in objects:
                    for object_prefix in objects['CommonPrefixes']:
                        object_set.add(object_prefix['Prefix'])

            return list(object_set)

        except ClientError:
            raise

    def list_segments(self, args, options):
        """ Returns a list of object segments based on a prefix.

        Args:
            args (list): List of object name parts.
            options (dic): Dictionary of configuration options.

        Returns:
            A list of segments in the object store that match the supplied prefix.
        """
        try:
            segment_list = []
            segments_path, _ = os.path.split(options.prefix)
            object_list = self.list_objects(args, options)
            for item in object_list:
                segment_list.append(segments_path + '/' + item)

            return segment_list

        except ClientError:
            raise

    def __get_object_headers(self, object_name, retries=1):
        """ Utility method that gets an object head from the repository with retry support.

        The default is to try once. Admittedly, this is ugly because the
        provided object name might be a terminal object or a "directory" so
        we need to try both cases for each retry attempt. When retry > 1, there is
        a 1 second delay between attempts.

        Args:
            object_name (str): Name of the object.
            retries (int): Optional parameter, default is 1 attempt.

        Returns:
            Object head dictionary or Boto3 exception.
        """
        # Prevent retries from being set to less than 1.
        retries = max(1, retries)
        try:
            for retry in range(0, retries):
                try:
                    obj_headers = self.__client.head_object(Bucket=self.__bucket_name,
                                                            Key=object_name)
                    return obj_headers
                except ClientError as error:
                    if error.response['ResponseMetadata']['HTTPStatusCode'] == 404:
                        try:
                            obj_headers = self.__client.head_object(Bucket=self.__bucket_name,
                                                                    Key=object_name + '/')
                            return obj_headers
                        except ClientError as error:
                            if error.response['ResponseMetadata']['HTTPStatusCode'] == 404:
                                if '-segments' not in object_name:
                                    try:
                                        obj_headers = self.__client.head_object(Bucket=self.__bucket_name,
                                                                                Key=object_name + '.manifest')
                                        return obj_headers
                                    except ClientError as error:
                                        if (error.response['ResponseMetadata']['HTTPStatusCode'] == 404 and
                                                retry + 1 != retries):
                                            time.sleep(1)
                                            continue
                                        raise
                                if retry + 1 != retries:
                                    time.sleep(1)
                                    continue
                            raise
                    raise
        except ClientError:
            raise

    def stat_object(self, args, options):
        """ Get "operating system like" stat data for the given object.

        Args:
            args (list): List of object name parts.
            options (dic): Dictionary of configuration options.

        Returns:
            A stat structure containing object information required by caller.
        """
        stat_data = {'timestamp': 0, 'size': 0, 'etag': "", 'directory': False}
        stat_data['headers'] = {}
        stat_data['headers']['Metadata'] = {}
        object_name = '/'.join(args)
        try:
            if not args:
                stat_data['timestamp'] = _make_timestamp(datetime.datetime.now())
                return stat_data
            else:
                obj_header = self.__get_object_headers(object_name)
                stat_data['timestamp'] = _make_timestamp(obj_header['LastModified'])
                stat_data['headers'] = obj_header
                if (obj_header['ContentType'] == 'application/x-directory' or
                        obj_header['ContentLength'] == 0):
                    stat_data['directory'] = True

                # Copy the Metadata sub values into the stat structure in order to conform
                # to our API.
                for key, value in stat_data['headers']['Metadata'].iteritems():
                    if 'x-object-meta' in key:
                        stat_data['headers'][key] = value

                if stat_data['headers']['Metadata'].get('x-object-meta-segments', 0) > 0:
                    stat_data['size'] = stat_data['headers']['Metadata'].get(
                        'x-object-meta-total-size', 0)
                else:
                    stat_data['size'] = obj_header['ContentLength']

                stat_data['x-account-bytes-used'] = stat_data['size']
                return stat_data

        except ClientError:
            raise

    def mkdir_object(self, args, options):
        """ Create an object that represents a directory in the object store.

        Args:
            args (list): List of object name parts.
            options (dic): Dictionary of configuration options.
        """
        new_folder = '/'.join(args)
        self.__create_folder(new_folder, options)
        return

    def rmdir_object(self, args, options):
        """ Remove an object that represents a directory in the object store.

        Args:
            args (list): List of object name parts.
            options (dic): Dictionary of configuration options.
        """
        object_tree = '/'.join(args) + '/'
        self.__delete_object_tree(object_tree)
        return

    def upload_object_manifest(self, object_name, put_headers, manifest_data):
        """ Upload a new object manifest to the object store.

        Args:
            object_name (str): Name of the object. A ".manifest" will be added.
            put_headers (dic): Dictionary of meta data to be added to the object.
            manifest_data (dic): The manifest data which becomes the body of file.
        """
        try:
            # A workaround to make the S3 manifest behave like the original Swift one.
            for segment_data in manifest_data:
                segment_data['name'] = segment_data.pop('path')
                segment_data['hash'] = segment_data.pop('etag', 0)
            manifest = json.dumps(manifest_data)
            manifest_name = object_name.strip('/') + ".manifest"
            self.__client.put_object(Bucket=self.__bucket_name,
                                     Key=manifest_name,
                                     Metadata=put_headers,
                                     Body=manifest)
        except ClientError:
            raise
        return

    def __create_folder(self, folder_name, options):
        """ Utility method used to create a object directory structure.

        The entire path is split and each directory level is created as an object
        if it does not exist.

        Args:
            folder_name (str): The entire folder name.
            options (dic): Dictionary of configuration options.
        """
        try:
            self.__client.head_object(Bucket=self.__bucket_name, Key=folder_name)  # + '/')
        except ClientError as error:
            if error.response['ResponseMetadata']['HTTPStatusCode'] == 404:
                path_parts = folder_name.split('/')
                new_path = ''
                for part in path_parts:
                    if part == '':
                        break
                    new_path = new_path + part + '/'
                    try:
                        #obj_head =
                        self.__client.head_object(Bucket=self.__bucket_name, Key=new_path)
                    except ClientError as error:
                        if error.response['ResponseMetadata']['HTTPStatusCode'] == 404:
                            if options['support_empty_dir'] is True:
                                # For S3 backends (Minio) that do not return a directory
                                # if it is empty, we need to actually create an object that
                                # we will keep hidden.
                                self.__client.put_object(Bucket=self.__bucket_name,
                                                         Key=new_path + 'x.hidden',
                                                         Body='Do Not Remove')
                            else:
                                self.__client.put_object(Bucket=self.__bucket_name, Key=new_path,
                                                         Body='',
                                                         ContentType='application/x-directory')
                        continue

    def upload_object(self, args, options):
        """ Upload an object to the S3 object store.

        Args:
            args (list): List of object name parts.
            options (dic): Dictionary of configuration options.
        """
        files = args[1:]
        try:
            # First check the path_valid flag to see if this is not the first segment.
            # Note - Added this for performance reasons when I was tuning.  Might be overkill
            # if it becomes problematic.
            if options.path_valid is False:
                self.__create_folder(os.path.dirname(args[0] + '/' + options['object_name']),
                                     options)
            if options.object_name is not None:
                with open(files[0], 'rb') as data:
                    self.__client.upload_fileobj(data, Bucket=self.__bucket_name,
                                                 Key=args[0] + '/' + options['object_name'],
                                                 ExtraArgs={
                                                     'ContentType': 'application/octet-stream'
                                                 })
                    # If experimenting with transfer config settings (a.k.a AWS chunking)
                    # include the argument below as the last argument in the upload_fileobj()
                    # call above. - cjk
                    # Config=__transfer_config
        except ClientError:
            raise
