-- MySQL dump 10.13  Distrib 5.5.44, for debian-linux-gnu (x86_64)
--
-- Host: localhost    Database: workloadmgr
-- ------------------------------------------------------
-- Server version	5.5.44-0ubuntu0.14.04.1

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `alembic_version`
--

DROP TABLE IF EXISTS `alembic_version`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `alembic_version` (
  `version_num` varchar(32) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `apscheduler_jobs`
--

DROP TABLE IF EXISTS `apscheduler_jobs`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `apscheduler_jobs` (
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `user_id` varchar(255) NOT NULL,
  `project_id` varchar(255) NOT NULL,
  `workload_id` varchar(255) NOT NULL,
  `trigger` blob NOT NULL,
  `func_ref` varchar(1024) NOT NULL,
  `args` blob NOT NULL,
  `kwargs` blob NOT NULL,
  `name` varchar(1024) DEFAULT NULL,
  `misfire_grace_time` int(11) NOT NULL,
  `coalesce` tinyint(1) NOT NULL,
  `max_runs` int(11) DEFAULT NULL,
  `max_instances` int(11) DEFAULT NULL,
  `next_run_time` datetime NOT NULL,
  `runs` bigint(20) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=14 DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `config_backup_metadata`
--

DROP TABLE IF EXISTS `config_backup_metadata`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `config_backup_metadata` (
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  `id` varchar(255) NOT NULL,
  `config_backup_id` varchar(255) NOT NULL,
  `key` varchar(255) NOT NULL,
  `value` text,
  PRIMARY KEY (`id`),
  UNIQUE KEY `config_backup_id` (`config_backup_id`,`key`),
  KEY `ix_config_backup_metadata_backup_id` (`config_backup_id`),
  CONSTRAINT `config_backup_metadata_ibfk_1` FOREIGN KEY (`config_backup_id`) REFERENCES `config_backups` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `config_backups`
--

DROP TABLE IF EXISTS `config_backups`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `config_backups` (
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `finished_at` datetime DEFAULT NULL,
  `scheduled_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  `id` varchar(255) NOT NULL,
  `user_id` varchar(255) DEFAULT NULL,
  `project_id` varchar(255) DEFAULT NULL,
  `config_workload_id` varchar(255) NOT NULL,
  `display_name` varchar(255) DEFAULT NULL,
  `display_description` varchar(255) DEFAULT NULL,
  `size` bigint(20) DEFAULT NULL,
  `host` varchar(255) DEFAULT NULL,
  `progress_msg` varchar(255) DEFAULT NULL,
  `warning_msg` varchar(4096) DEFAULT NULL,
  `error_msg` varchar(4096) DEFAULT NULL,
  `time_taken` bigint(20) DEFAULT NULL,
  `vault_storage_path` varchar(255) DEFAULT NULL,
  `status` varchar(32) NOT NULL,
  `data_deleted` tinyint(1) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `config_workload_id` (`config_workload_id`),
  CONSTRAINT `config_backup_ibfk_1` FOREIGN KEY (`config_workload_id`) REFERENCES `config_workloads` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `config_workload_metadata`
--

DROP TABLE IF EXISTS `config_workload_metadata`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `config_workload_metadata` (
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  `id` varchar(255) NOT NULL,
  `config_workload_id` varchar(255) NOT NULL,
  `key` varchar(255) NOT NULL,
  `value` text,
  PRIMARY KEY (`id`),
  UNIQUE KEY `config_workload_id` (`config_workload_id`,`key`),
  KEY `ix_config_workload_metadata_workload_id` (`config_workload_id`),
  CONSTRAINT `config_workload_metadata_ibfk_1` FOREIGN KEY (`config_workload_id`) REFERENCES `config_workloads` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `config_workloads`
--

DROP TABLE IF EXISTS `config_workloads`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `config_workloads` (
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  `id` varchar(255) NOT NULL,
  `user_id` varchar(255) DEFAULT NULL,
  `project_id` varchar(255) DEFAULT NULL,
  `status` varchar(255) NOT NULL,
  `jobschedule` varchar(4096) DEFAULT NULL,
  `backup_media_target` varchar(2048) DEFAULT NULL,
  `host` varchar(255) DEFAULT NULL,
  `error_msg` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `file_search`
--

DROP TABLE IF EXISTS `file_search`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `file_search` (
  `id` int(255) NOT NULL AUTO_INCREMENT,
  `vm_id` varchar(100) NOT NULL,
  `project_id` varchar(255) DEFAULT NULL,
  `user_id` varchar(255) DEFAULT NULL,
  `filepath` varchar(255) NOT NULL,
  `snapshot_ids` text,
  `json_resp` longtext,
  `start` int(10) DEFAULT NULL,
  `end` int(10) DEFAULT NULL,
  `date_from` varchar(50) DEFAULT NULL,
  `date_to` varchar(50) DEFAULT NULL,
  `host` varchar(100) DEFAULT NULL,
  `error_msg` varchar(255) DEFAULT NULL,
  `status` varchar(10) NOT NULL,
  `scheduled_at` datetime DEFAULT NULL,
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=latin1;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `flowdetails`
--

DROP TABLE IF EXISTS `flowdetails`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `flowdetails` (
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `parent_uuid` varchar(64) DEFAULT NULL,
  `meta` text,
  `state` varchar(255) DEFAULT NULL,
  `name` varchar(255) DEFAULT NULL,
  `uuid` varchar(64) NOT NULL,
  PRIMARY KEY (`uuid`),
  KEY `flowdetails_ibfk_1` (`parent_uuid`),
  KEY `flowdetails_uuid_idx` (`uuid`),
  CONSTRAINT `flowdetails_ibfk_1` FOREIGN KEY (`parent_uuid`) REFERENCES `logbooks` (`uuid`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `logbooks`
--

DROP TABLE IF EXISTS `logbooks`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `logbooks` (
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `meta` text,
  `name` varchar(255) DEFAULT NULL,
  `uuid` varchar(64) NOT NULL,
  PRIMARY KEY (`uuid`),
  KEY `logbook_uuid_idx` (`uuid`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `migrate_version`
--

DROP TABLE IF EXISTS `migrate_version`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `migrate_version` (
  `repository_id` varchar(250) NOT NULL,
  `repository_path` text,
  `version` int(11) DEFAULT NULL,
  PRIMARY KEY (`repository_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `restore_metadata`
--

DROP TABLE IF EXISTS `restore_metadata`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `restore_metadata` (
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  `id` varchar(255) NOT NULL,
  `restore_id` varchar(255) NOT NULL,
  `key` varchar(255) NOT NULL,
  `value` text,
  PRIMARY KEY (`id`),
  UNIQUE KEY `restore_id` (`restore_id`,`key`),
  KEY `ix_restore_metadata_restore_id` (`restore_id`),
  CONSTRAINT `restore_metadata_ibfk_1` FOREIGN KEY (`restore_id`) REFERENCES `restores` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `restored_vm_metadata`
--

DROP TABLE IF EXISTS `restored_vm_metadata`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `restored_vm_metadata` (
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  `id` varchar(255) NOT NULL,
  `restored_vm_id` varchar(255) NOT NULL,
  `key` varchar(255) NOT NULL,
  `value` text,
  PRIMARY KEY (`id`),
  UNIQUE KEY `restored_vm_id` (`restored_vm_id`,`key`),
  KEY `ix_restored_vm_metadata_restored_vm_id` (`restored_vm_id`),
  CONSTRAINT `restored_vm_metadata_ibfk_1` FOREIGN KEY (`restored_vm_id`) REFERENCES `restored_vms` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `restored_vm_resource_metadata`
--

DROP TABLE IF EXISTS `restored_vm_resource_metadata`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `restored_vm_resource_metadata` (
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  `id` varchar(255) NOT NULL,
  `restored_vm_resource_id` varchar(255) NOT NULL,
  `key` varchar(255) NOT NULL,
  `value` text,
  PRIMARY KEY (`id`),
  UNIQUE KEY `restored_vm_resource_id` (`restored_vm_resource_id`,`key`),
  KEY `ix_restored_vm_resource_metadata_restored_vm_resource_id` (`restored_vm_resource_id`),
  CONSTRAINT `restored_vm_resource_metadata_ibfk_1` FOREIGN KEY (`restored_vm_resource_id`) REFERENCES `restored_vm_resources` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `restored_vm_resources`
--

DROP TABLE IF EXISTS `restored_vm_resources`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `restored_vm_resources` (
  `created_at` datetime DEFAULT NULL,
  `finished_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  `id` varchar(255) NOT NULL,
  `vm_id` varchar(255) NOT NULL,
  `restore_id` varchar(255) DEFAULT NULL,
  `resource_type` varchar(255) DEFAULT NULL,
  `resource_name` varchar(255) DEFAULT NULL,
  `status` varchar(32) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `id` (`id`,`vm_id`,`restore_id`,`resource_name`),
  KEY `restore_id` (`restore_id`),
  CONSTRAINT `restored_vm_resources_ibfk_1` FOREIGN KEY (`restore_id`) REFERENCES `restores` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `restored_vms`
--

DROP TABLE IF EXISTS `restored_vms`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `restored_vms` (
  `created_at` datetime DEFAULT NULL,
  `finished_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  `id` varchar(255) NOT NULL,
  `vm_id` varchar(255) NOT NULL,
  `vm_name` varchar(255) NOT NULL,
  `restore_id` varchar(255) DEFAULT NULL,
  `size` bigint(20) NOT NULL,
  `restore_type` varchar(32) DEFAULT NULL,
  `status` varchar(32) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `restore_id` (`restore_id`),
  CONSTRAINT `restored_vms_ibfk_1` FOREIGN KEY (`restore_id`) REFERENCES `restores` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `restores`
--

DROP TABLE IF EXISTS `restores`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `restores` (
  `created_at` datetime DEFAULT NULL,
  `finished_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  `id` varchar(255) NOT NULL,
  `snapshot_id` varchar(255) DEFAULT NULL,
  `user_id` varchar(255) DEFAULT NULL,
  `project_id` varchar(255) DEFAULT NULL,
  `restore_type` varchar(32) NOT NULL,
  `display_name` varchar(255) DEFAULT NULL,
  `display_description` varchar(255) DEFAULT NULL,
  `pickle` mediumtext,
  `size` bigint(20) NOT NULL,
  `uploaded_size` bigint(20) NOT NULL,
  `progress_percent` int(11) NOT NULL,
  `progress_msg` varchar(255) DEFAULT NULL,
  `warning_msg` varchar(4096) DEFAULT NULL,
  `error_msg` varchar(4096) DEFAULT NULL,
  `host` varchar(255) DEFAULT NULL,
  `target_platform` varchar(255) DEFAULT NULL,
  `time_taken` bigint(20) DEFAULT NULL,
  `status` varchar(32) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `snapshot_id` (`snapshot_id`),
  CONSTRAINT `restores_ibfk_1` FOREIGN KEY (`snapshot_id`) REFERENCES `snapshots` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `scheduled_jobs`
--

DROP TABLE IF EXISTS `scheduled_jobs`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `scheduled_jobs` (
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  `id` varchar(255) NOT NULL,
  `workload_id` varchar(255) DEFAULT NULL,
  `trigger` varchar(4096) NOT NULL,
  `func_ref` varchar(1024) NOT NULL,
  `args` varchar(1024) NOT NULL,
  `kwargs` varchar(1024) NOT NULL,
  `name` varchar(1024) DEFAULT NULL,
  `misfire_grace_time` int(11) NOT NULL,
  `coalesce` tinyint(1) NOT NULL,
  `max_runs` int(11) DEFAULT NULL,
  `max_instances` int(11) DEFAULT NULL,
  `next_run_time` datetime NOT NULL,
  `runs` int(11) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `workload_id` (`workload_id`),
  CONSTRAINT `scheduled_jobs_ibfk_1` FOREIGN KEY (`workload_id`) REFERENCES `workloads` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `services`
--

DROP TABLE IF EXISTS `services`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `services` (
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `host` varchar(255) DEFAULT NULL,
  `ip_addresses` varchar(255) DEFAULT NULL,
  `binary` varchar(255) DEFAULT NULL,
  `topic` varchar(255) DEFAULT NULL,
  `report_count` int(11) NOT NULL,
  `disabled` tinyint(1) DEFAULT NULL,
  `availability_zone` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `unique_index` (`host`,`topic`,`binary`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `setting_metadata`
--

DROP TABLE IF EXISTS `setting_metadata`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `setting_metadata` (
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  `id` varchar(255) NOT NULL,
  `settings_name` varchar(255) NOT NULL,
  `settings_project_id` varchar(255) NOT NULL,
  `key` varchar(255) NOT NULL,
  `value` text,
  PRIMARY KEY (`id`),
  UNIQUE KEY `settings_name` (`settings_name`,`settings_project_id`,`key`),
  CONSTRAINT `setting_metadata_settings` FOREIGN KEY (`settings_name`, `settings_project_id`) REFERENCES `settings` (`name`, `project_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `settings`
--

DROP TABLE IF EXISTS `settings`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `settings` (
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  `user_id` varchar(255) DEFAULT NULL,
  `project_id` varchar(255) NOT NULL,
  `name` varchar(255) NOT NULL,
  `value` text,
  `description` varchar(255) DEFAULT NULL,
  `category` varchar(32) DEFAULT NULL,
  `type` varchar(32) DEFAULT NULL,
  `public` tinyint(1) DEFAULT NULL,
  `hidden` tinyint(1) DEFAULT NULL,
  `status` varchar(32) NOT NULL,
  PRIMARY KEY (`project_id`,`name`),
  UNIQUE KEY `name` (`name`,`project_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `snapshot_metadata`
--

DROP TABLE IF EXISTS `snapshot_metadata`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `snapshot_metadata` (
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  `id` varchar(255) NOT NULL,
  `snapshot_id` varchar(255) NOT NULL,
  `key` varchar(255) NOT NULL,
  `value` text,
  PRIMARY KEY (`id`),
  UNIQUE KEY `snapshot_id` (`snapshot_id`,`key`),
  KEY `ix_snapshot_metadata_snapshot_id` (`snapshot_id`),
  CONSTRAINT `snapshot_metadata_ibfk_1` FOREIGN KEY (`snapshot_id`) REFERENCES `snapshots` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `snapshot_vm_metadata`
--

DROP TABLE IF EXISTS `snapshot_vm_metadata`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `snapshot_vm_metadata` (
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  `id` varchar(255) NOT NULL,
  `snapshot_vm_id` varchar(255) NOT NULL,
  `key` varchar(255) NOT NULL,
  `value` text,
  PRIMARY KEY (`id`),
  UNIQUE KEY `snapshot_vm_id` (`snapshot_vm_id`,`key`),
  KEY `ix_snapshot_vm_metadata_snapshot_vm_id` (`snapshot_vm_id`),
  CONSTRAINT `snapshot_vm_metadata_ibfk_1` FOREIGN KEY (`snapshot_vm_id`) REFERENCES `snapshot_vms` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `snapshot_vm_resource_metadata`
--

DROP TABLE IF EXISTS `snapshot_vm_resource_metadata`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `snapshot_vm_resource_metadata` (
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  `id` varchar(255) NOT NULL,
  `snapshot_vm_resource_id` varchar(255) NOT NULL,
  `key` varchar(255) NOT NULL,
  `value` text,
  PRIMARY KEY (`id`),
  UNIQUE KEY `snapshot_vm_resource_id` (`snapshot_vm_resource_id`,`key`),
  KEY `ix_snapshot_vm_resource_metadata_snapshot_vm_resource_id` (`snapshot_vm_resource_id`),
  CONSTRAINT `snapshot_vm_resource_metadata_ibfk_1` FOREIGN KEY (`snapshot_vm_resource_id`) REFERENCES `snapshot_vm_resources` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `snapshot_vm_resources`
--

DROP TABLE IF EXISTS `snapshot_vm_resources`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `snapshot_vm_resources` (
  `created_at` datetime DEFAULT NULL,
  `finished_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  `id` varchar(255) NOT NULL,
  `vm_id` varchar(255) NOT NULL,
  `snapshot_id` varchar(255) DEFAULT NULL,
  `resource_type` varchar(255) DEFAULT NULL,
  `resource_name` varchar(255) DEFAULT NULL,
  `resource_pit_id` varchar(255) DEFAULT NULL,
  `size` bigint(20) NOT NULL,
  `restore_size` bigint(20) NOT NULL,
  `snapshot_type` varchar(32) DEFAULT NULL,
  `data_deleted` tinyint(1) DEFAULT NULL,
  `time_taken` bigint(20) DEFAULT NULL,
  `status` varchar(32) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `vm_id` (`vm_id`,`snapshot_id`,`resource_name`,`resource_pit_id`),
  KEY `snapshot_id` (`snapshot_id`),
  CONSTRAINT `snapshot_vm_resources_ibfk_1` FOREIGN KEY (`snapshot_id`) REFERENCES `snapshots` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `snapshot_vms`
--

DROP TABLE IF EXISTS `snapshot_vms`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `snapshot_vms` (
  `created_at` datetime DEFAULT NULL,
  `finished_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  `id` varchar(255) NOT NULL,
  `vm_id` varchar(255) NOT NULL,
  `vm_name` varchar(255) NOT NULL,
  `snapshot_id` varchar(255) DEFAULT NULL,
  `size` bigint(20) NOT NULL,
  `restore_size` bigint(20) NOT NULL,
  `snapshot_type` varchar(32) DEFAULT NULL,
  `status` varchar(32) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `snapshot_id` (`snapshot_id`),
  CONSTRAINT `snapshot_vms_ibfk_1` FOREIGN KEY (`snapshot_id`) REFERENCES `snapshots` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `snapshots`
--

DROP TABLE IF EXISTS `snapshots`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `snapshots` (
  `created_at` datetime DEFAULT NULL,
  `finished_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  `id` varchar(255) NOT NULL,
  `workload_id` varchar(255) DEFAULT NULL,
  `user_id` varchar(255) DEFAULT NULL,
  `project_id` varchar(255) DEFAULT NULL,
  `snapshot_type` varchar(32) NOT NULL,
  `display_name` varchar(255) DEFAULT NULL,
  `display_description` varchar(255) DEFAULT NULL,
  `size` bigint(20) NOT NULL,
  `restore_size` bigint(20) NOT NULL,
  `uploaded_size` bigint(20) NOT NULL,
  `progress_percent` int(11) NOT NULL,
  `progress_msg` varchar(255) DEFAULT NULL,
  `warning_msg` varchar(4096) DEFAULT NULL,
  `error_msg` varchar(4096) DEFAULT NULL,
  `host` varchar(255) DEFAULT NULL,
  `data_deleted` tinyint(1) DEFAULT NULL,
  `pinned` tinyint(1) DEFAULT NULL,
  `time_taken` bigint(20) DEFAULT NULL,
  `vault_storage_id` varchar(255) DEFAULT NULL,
  `status` varchar(32) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `workload_id` (`workload_id`),
  KEY `vault_storage_id` (`vault_storage_id`),
  CONSTRAINT `snapshots_ibfk_1` FOREIGN KEY (`workload_id`) REFERENCES `workloads` (`id`),
  CONSTRAINT `snapshots_ibfk_2` FOREIGN KEY (`vault_storage_id`) REFERENCES `vault_storages` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `task_status_messages`
--

DROP TABLE IF EXISTS `task_status_messages`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `task_status_messages` (
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  `id` varchar(255) NOT NULL,
  `task_id` varchar(255) NOT NULL,
  `status_message` text,
  PRIMARY KEY (`id`),
  KEY `ix_task_status_messages_task_id` (`task_id`),
  CONSTRAINT `task_status_messages_ibfk_1` FOREIGN KEY (`task_id`) REFERENCES `tasks` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `taskdetails`
--

DROP TABLE IF EXISTS `taskdetails`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `taskdetails` (
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `parent_uuid` varchar(64) DEFAULT NULL,
  `meta` text,
  `name` varchar(255) DEFAULT NULL,
  `results` mediumtext,
  `version` varchar(64) DEFAULT NULL,
  `state` varchar(255) DEFAULT NULL,
  `uuid` varchar(64) NOT NULL,
  `failure` text,
  PRIMARY KEY (`uuid`),
  KEY `taskdetails_ibfk_1` (`parent_uuid`),
  KEY `taskdetails_uuid_idx` (`uuid`),
  CONSTRAINT `taskdetails_ibfk_1` FOREIGN KEY (`parent_uuid`) REFERENCES `flowdetails` (`uuid`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `tasks`
--

DROP TABLE IF EXISTS `tasks`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `tasks` (
  `created_at` datetime DEFAULT NULL,
  `finished_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  `id` varchar(255) NOT NULL,
  `display_name` varchar(255) DEFAULT NULL,
  `display_description` varchar(255) DEFAULT NULL,
  `result` mediumtext,
  `status` varchar(32) NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `vault_storage_metadata`
--

DROP TABLE IF EXISTS `vault_storage_metadata`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `vault_storage_metadata` (
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  `id` varchar(255) NOT NULL,
  `vault_storage_id` varchar(255) NOT NULL,
  `key` varchar(255) NOT NULL,
  `value` text,
  PRIMARY KEY (`id`),
  UNIQUE KEY `vault_storage_id` (`vault_storage_id`,`key`),
  KEY `ix_vault_storage_metadata_vault_storage_id` (`vault_storage_id`),
  CONSTRAINT `vault_storage_metadata_ibfk_1` FOREIGN KEY (`vault_storage_id`) REFERENCES `vault_storages` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `vault_storages`
--

DROP TABLE IF EXISTS `vault_storages`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `vault_storages` (
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  `id` varchar(255) NOT NULL,
  `user_id` varchar(255) DEFAULT NULL,
  `project_id` varchar(255) DEFAULT NULL,
  `type` varchar(32) NOT NULL,
  `display_name` varchar(255) DEFAULT NULL,
  `display_description` varchar(255) DEFAULT NULL,
  `capacity` bigint(20) NOT NULL,
  `used` bigint(20) NOT NULL,
  `status` varchar(32) NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `vm_disk_resource_snap_metadata`
--

DROP TABLE IF EXISTS `vm_disk_resource_snap_metadata`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `vm_disk_resource_snap_metadata` (
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  `id` varchar(255) NOT NULL,
  `vm_disk_resource_snap_id` varchar(255) NOT NULL,
  `key` varchar(255) NOT NULL,
  `value` text,
  PRIMARY KEY (`id`),
  UNIQUE KEY `vm_disk_resource_snap_id` (`vm_disk_resource_snap_id`,`key`),
  KEY `ix_vm_disk_resource_snap_metadata_vm_disk_resource_snap_id` (`vm_disk_resource_snap_id`),
  CONSTRAINT `vm_disk_resource_snap_metadata_ibfk_1` FOREIGN KEY (`vm_disk_resource_snap_id`) REFERENCES `vm_disk_resource_snaps` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `vm_disk_resource_snaps`
--

DROP TABLE IF EXISTS `vm_disk_resource_snaps`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `vm_disk_resource_snaps` (
  `created_at` datetime DEFAULT NULL,
  `finished_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  `id` varchar(255) NOT NULL,
  `snapshot_vm_resource_id` varchar(255) DEFAULT NULL,
  `vm_disk_resource_snap_backing_id` varchar(255) DEFAULT NULL,
  `vm_disk_resource_snap_child_id` varchar(255) DEFAULT NULL,
  `top` tinyint(1) DEFAULT NULL,
  `vault_url` varchar(4096) DEFAULT NULL,
  `vault_metadata` varchar(4096) DEFAULT NULL,
  `size` bigint(20) NOT NULL,
  `restore_size` bigint(20) NOT NULL,
  `data_deleted` tinyint(1) DEFAULT NULL,
  `time_taken` bigint(20) DEFAULT NULL,
  `status` varchar(32) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `snapshot_vm_resource_id` (`snapshot_vm_resource_id`),
  CONSTRAINT `vm_disk_resource_snaps_ibfk_1` FOREIGN KEY (`snapshot_vm_resource_id`) REFERENCES `snapshot_vm_resources` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `vm_network_resource_snap_metadata`
--

DROP TABLE IF EXISTS `vm_network_resource_snap_metadata`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `vm_network_resource_snap_metadata` (
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  `id` varchar(255) NOT NULL,
  `vm_network_resource_snap_id` varchar(255) NOT NULL,
  `key` varchar(255) NOT NULL,
  `value` text,
  PRIMARY KEY (`id`),
  UNIQUE KEY `vm_network_resource_snap_id` (`vm_network_resource_snap_id`,`key`),
  KEY `ix_vm_network_resource_snap_metadata_vm_network_resource_snap_id` (`vm_network_resource_snap_id`),
  CONSTRAINT `vm_network_resource_snap_metadata_ibfk_1` FOREIGN KEY (`vm_network_resource_snap_id`) REFERENCES `vm_network_resource_snaps` (`vm_network_resource_snap_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `vm_network_resource_snaps`
--

DROP TABLE IF EXISTS `vm_network_resource_snaps`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `vm_network_resource_snaps` (
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  `vm_network_resource_snap_id` varchar(255) NOT NULL,
  `pickle` mediumtext,
  `status` varchar(32) NOT NULL,
  PRIMARY KEY (`vm_network_resource_snap_id`),
  CONSTRAINT `vm_network_resource_snaps_ibfk_1` FOREIGN KEY (`vm_network_resource_snap_id`) REFERENCES `snapshot_vm_resources` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `vm_recent_snapshot`
--

DROP TABLE IF EXISTS `vm_recent_snapshot`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `vm_recent_snapshot` (
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  `vm_id` varchar(255) NOT NULL,
  `snapshot_id` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`vm_id`),
  KEY `snapshot_id` (`snapshot_id`),
  CONSTRAINT `vm_recent_snapshot_ibfk_1` FOREIGN KEY (`snapshot_id`) REFERENCES `snapshots` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `vm_security_group_rule_snap_metadata`
--

DROP TABLE IF EXISTS `vm_security_group_rule_snap_metadata`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `vm_security_group_rule_snap_metadata` (
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  `id` varchar(255) NOT NULL,
  `vm_security_group_rule_snap_id` varchar(255) NOT NULL,
  `key` varchar(255) NOT NULL,
  `value` text,
  PRIMARY KEY (`id`),
  UNIQUE KEY `vm_security_group_rule_snap_id` (`vm_security_group_rule_snap_id`,`key`),
  KEY `ix_vm_security_group_rule_snap_metadata_vm_security_grou_d8ef` (`vm_security_group_rule_snap_id`),
  CONSTRAINT `vm_security_group_rule_snap_metadata_ibfk_1` FOREIGN KEY (`vm_security_group_rule_snap_id`) REFERENCES `vm_security_group_rule_snaps` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `vm_security_group_rule_snaps`
--

DROP TABLE IF EXISTS `vm_security_group_rule_snaps`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `vm_security_group_rule_snaps` (
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  `id` varchar(255) NOT NULL,
  `vm_security_group_snap_id` varchar(255) NOT NULL,
  `pickle` mediumtext,
  `status` varchar(32) NOT NULL,
  PRIMARY KEY (`id`,`vm_security_group_snap_id`),
  KEY `vm_security_group_snap_id` (`vm_security_group_snap_id`),
  CONSTRAINT `vm_security_group_rule_snaps_ibfk_1` FOREIGN KEY (`vm_security_group_snap_id`) REFERENCES `snapshot_vm_resources` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `workload_metadata`
--

DROP TABLE IF EXISTS `workload_metadata`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `workload_metadata` (
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  `id` varchar(255) NOT NULL,
  `workload_id` varchar(255) NOT NULL,
  `key` varchar(255) NOT NULL,
  `value` text,
  PRIMARY KEY (`id`),
  UNIQUE KEY `workload_id` (`workload_id`,`key`),
  KEY `ix_workload_metadata_workload_id` (`workload_id`),
  CONSTRAINT `workload_metadata_ibfk_1` FOREIGN KEY (`workload_id`) REFERENCES `workloads` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `workload_type_metadata`
--

DROP TABLE IF EXISTS `workload_type_metadata`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `workload_type_metadata` (
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  `id` varchar(255) NOT NULL,
  `workload_type_id` varchar(255) NOT NULL,
  `key` varchar(255) NOT NULL,
  `value` text,
  PRIMARY KEY (`id`),
  UNIQUE KEY `workload_type_id` (`workload_type_id`,`key`),
  KEY `ix_workload_type_metadata_workload_type_id` (`workload_type_id`),
  CONSTRAINT `workload_type_metadata_ibfk_1` FOREIGN KEY (`workload_type_id`) REFERENCES `workload_types` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `workload_types`
--

DROP TABLE IF EXISTS `workload_types`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `workload_types` (
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  `id` varchar(255) NOT NULL,
  `user_id` varchar(255) DEFAULT NULL,
  `project_id` varchar(255) DEFAULT NULL,
  `display_name` varchar(255) DEFAULT NULL,
  `display_description` varchar(255) DEFAULT NULL,
  `is_public` tinyint(1) DEFAULT NULL,
  `status` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `workload_vm_metadata`
--

DROP TABLE IF EXISTS `workload_vm_metadata`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `workload_vm_metadata` (
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  `id` varchar(255) NOT NULL,
  `workload_vm_id` varchar(255) NOT NULL,
  `key` varchar(255) NOT NULL,
  `value` text,
  PRIMARY KEY (`id`),
  UNIQUE KEY `workload_vm_id` (`workload_vm_id`,`key`),
  KEY `ix_workload_vm_metadata_workload_vm_id` (`workload_vm_id`),
  CONSTRAINT `workload_vm_metadata_ibfk_1` FOREIGN KEY (`workload_vm_id`) REFERENCES `workload_vms` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `workload_vms`
--

DROP TABLE IF EXISTS `workload_vms`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `workload_vms` (
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  `id` varchar(255) NOT NULL,
  `vm_id` varchar(255) NOT NULL,
  `vm_name` varchar(255) NOT NULL,
  `workload_id` varchar(255) DEFAULT NULL,
  `status` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `workload_id` (`workload_id`),
  CONSTRAINT `workload_vms_ibfk_1` FOREIGN KEY (`workload_id`) REFERENCES `workloads` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Table structure for table `workloads`
--

DROP TABLE IF EXISTS `workloads`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `workloads` (
  `created_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  `id` varchar(255) NOT NULL,
  `user_id` varchar(255) DEFAULT NULL,
  `project_id` varchar(255) DEFAULT NULL,
  `host` varchar(255) DEFAULT NULL,
  `error_msg` varchar(4096) DEFAULT NULL,
  `availability_zone` varchar(255) DEFAULT NULL,
  `display_name` varchar(255) DEFAULT NULL,
  `display_description` varchar(255) DEFAULT NULL,
  `source_platform` varchar(255) DEFAULT NULL,
  `workload_type_id` varchar(255) DEFAULT NULL,
  `jobschedule` varchar(4096) DEFAULT NULL,
  `vault_storage_id` varchar(255) DEFAULT NULL,
  `status` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `workload_type_id` (`workload_type_id`),
  KEY `vault_storage_id` (`vault_storage_id`),
  CONSTRAINT `workloads_ibfk_1` FOREIGN KEY (`workload_type_id`) REFERENCES `workload_types` (`id`),
  CONSTRAINT `workloads_ibfk_2` FOREIGN KEY (`vault_storage_id`) REFERENCES `vault_storages` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;


--
-- Table structure for table `workload_policy`
--

DROP TABLE IF EXISTS `workload_policy`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `workload_policy` (
  `created_at` datetime DEFAULT NULL,
  `finished_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  `id` varchar(255) NOT NULL,
  `user_id` varchar(255) NOT NULL,
  `project_id` varchar(255) NOT NULL,
  `display_name` varchar(255) NOT NULL,
  `display_description` varchar(255) NOT NULL,
  `status` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;


--
-- Table structure for table `workload_policy_assignments`
--

DROP TABLE IF EXISTS `workload_policy_assignments`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `workload_policy_assignments` (
  `created_at` datetime DEFAULT NULL,
  `finished_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  `id` varchar(255) NOT NULL,
  `policy_id` varchar(255) NOT NULL,
  `project_id` varchar(255) NOT NULL,
  `policy_name` varchar(255) NOT NULL,
  `project_name` varchar(255) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `workload_policy_assignments_workload_policy` (`policy_id`),
  CONSTRAINT `workload_policy_assignmnents_workload_policy` FOREIGN KEY (`policy_id`) REFERENCES `workload_policy` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;


--
-- Table structure for table `workload_policy_fields`
--

DROP TABLE IF EXISTS `workload_policy_fields`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `workload_policy_fields` (
  `created_at` datetime DEFAULT NULL,
  `finished_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  `id` varchar(255) NOT NULL,
  `field_name` varchar(255) NOT NULL,
  `type` varchar(255) NOT NULL,
  PRIMARY KEY (`field_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `workload_policy_fields`
--
LOCK TABLES `workload_policy_fields` WRITE;
/*!40000 ALTER TABLE `workload_policy_fields` DISABLE KEYS */;
INSERT INTO `workload_policy_fields` VALUES  (current_timestamp(),NULL,NULL,NULL,0,NULL,'5b2314a2-df38-495a-a2e0-9f16be1d7c3c','fullbackup_interval','text'),(current_timestamp(),NULL,NULL,NULL,0,NULL,'4b61711f-1110-4e5d-9976-5216a8c7eb85','interval','text'),(current_timestamp(),NULL,NULL,NULL,0,NULL,'22beaf15-d593-4774-a41f-af2ac5070238','retention_policy_type','text'),(current_timestamp(),NULL,NULL,NULL,0,NULL,'a3d67e8a-33b5-4f6e-8ac7-9583be4147b8','retention_policy_value','text');
/*!40000 ALTER TABLE `workload_policy_fields` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `workload_policy_metadata`
--

DROP TABLE IF EXISTS `workload_policy_metadata`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `workload_policy_metadata` (
  `created_at` datetime DEFAULT NULL,
  `finished_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  `id` varchar(255) NOT NULL,
  `policy_id` varchar(255) NOT NULL,
  `key` varchar(255) NOT NULL,
  `value` text,
  PRIMARY KEY (`id`),
  KEY `workload_policy_metadata_workload_policy` (`policy_id`),
  CONSTRAINT `workload_policy_metadata_workload_policy` FOREIGN KEY (`policy_id`) REFERENCES `workload_policy` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;


--
-- Table structure for table `workload_policy_values`
--

DROP TABLE IF EXISTS `workload_policy_values`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8 */;
CREATE TABLE `workload_policy_values` (
  `created_at` datetime DEFAULT NULL,
  `finished_at` datetime DEFAULT NULL,
  `updated_at` datetime DEFAULT NULL,
  `deleted_at` datetime DEFAULT NULL,
  `deleted` tinyint(1) DEFAULT NULL,
  `version` varchar(255) DEFAULT NULL,
  `id` varchar(255) NOT NULL,
  `policy_id` varchar(255) NOT NULL,
  `policy_field_name` varchar(255) NOT NULL,
  `value` varchar(255) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `workload_policy_values_workload_policy_fields` (`policy_field_name`),
  KEY `workload_policy_values_workload_policy` (`policy_id`),
  CONSTRAINT `workload_policy_values_workload_policy` FOREIGN KEY (`policy_id`) REFERENCES `workload_policy` (`id`),
  CONSTRAINT `workload_policy_values_workload_policy_fields` FOREIGN KEY (`policy_field_name`) REFERENCES `workload_policy_fields` (`field_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;
/*!40101 SET character_set_client = @saved_cs_client */;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;
/*!40101 SET GLOBAL SQL_MODE="" */;
/*!40101 SET SESSION SQL_MODE="" */;
-- Dump completed on 2017-11-02  5:41:36
