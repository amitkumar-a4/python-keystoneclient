<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN" "http://www.w3.org/TR/html4/loose.dtd">
<html>
<head>
<!-- Latest compiled and minified CSS -->
<link rel="stylesheet" href="css/bootstrap.min.css">

<!-- Optional theme -->
<link rel="stylesheet" href="css/bootstrap-theme.min.css">

<script src="js/jquery-1.11.0.min.js"></script>
<!-- Latest compiled and minified JavaScript -->
<script src="js/bootstrap.min.js"></script>
</head>

<body>
<meta content="text/html; charset=utf-8" http-equiv="content-type">
<nav class="navbar navbar-default" role="navigation">
  <div class="container-fluid">
    <!-- Brand and toggle get grouped for better mobile display -->
    <div class="navbar-header">
      <button type="button" class="navbar-toggle" data-toggle="collapse" data-target="#bs-example-navbar-collapse-1">
        <span class="sr-only">Toggle navigation</span>
        <span class="icon-bar"></span>
        <span class="icon-bar"></span>
        <span class="icon-bar"></span>
      </button>
      <a class="navbar-brand" href="#"><img src="images/triliodata-144x36.png" alt="Trilio Data, Inc" height="36" width="144"></a>
    </div>
    <div id="bs-example-navbar-collapse-3" class="collapse navbar-collapse navbar-right">
       <button class="btn btn-default navbar-btn" type="button" onClick="parent.location='/logout'">Sign Out</button>
    </div>
  </div><!-- /.container-fluid -->
</nav>

<div class="panel panel-primary" style="width:70%;text-align:left;margin-left:auto; margin-right:auto;margin-top:100px">
  <!-- Default panel contents -->
  <div class="panel-heading"><h3 class="panel-title">TrilioVault Appliance Configuration</h3></div>
  % if len(error_message) > 0:
	  	<div class="alert alert-danger alert-dismissible" role="alert">
		  <button type="button" class="close" data-dismiss="alert">
		  <span aria-hidden="true">&times;</span><span class="sr-only">Close</span></button>
		  <strong>{{error_message}}</strong>
 		</div>
  % end
  <div style="margin-left:auto; margin-right:auto; padding:20px">
  <form role="form" class="form-configure" action="/configure_openstack" method="post">
    <input name = "nodetype" type="radio"  value="controller" checked>  Controller Node
    <input name = "nodetype" type="radio"  value="additional">   Additional Node <br> <br>
   
    <div class="input-group">
    	<label class="input-group-addon">Floating IP Address	</label>
    	<input name="floating-ipaddress" type="text" required="" placeholder="192.168.2.200" class="form-control"><br>
    </div><br>
    <div class="input-group">    
    	<label class="input-group-addon">Keystone Admin Url</label>
    	<input name="keystone-admin-url" type="url" required="" placeholder="http://keystonehost:35357/v2.0" class="form-control"><br>
    </div><br>
    <div class="input-group">
    	<label class="input-group-addon">Keystone Public Url</label>
    	<input name="keystone-public-url" type="url" required="" placeholder="http://keystonehost:5000/v2.0" class="form-control"><br>
    </div><br>
    <div class="input-group">
    	<label class="input-group-addon">Administrator&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp</label>
    	<input name="admin-username" type="text" required="" placeholder="admin" class="form-control"> <br>
    </div><br>
    <div class="input-group">
    	<label class="input-group-addon">Password&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp</label>
    	<input name="admin-password" type="password" required="" placeholder="password" class="form-control"> <br>
    </div><br>
    	<div class="input-group">
    	<label class="input-group-addon">Admin Tenant&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp</label>
    	<input name="admin-tenant-name" type="text" required="" placeholder="admin" class="form-control">
    </div><br>
    <div class="input-group">
    	<label class="input-group-addon">Region&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp</label>
    	<input name="region-name" type="text" required="" placeholder="RegionOne" class="form-control">
    </div><br>    
	<div class="input-group" >
		<label class="input-group-addon">Name Server&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp</label>
		<input name="name-server" {{'value=' + name_server if (defined('name_server') and len(name_server)) else ''}} type="text" placeholder="192.168.2.1" class="form-control">
		
		<label class="input-group-addon">Domain Search Order</label>
		<input name="domain-search-order" {{'value=' + domain_search_order if (defined('domain_search_order') and len(domain_search_order)) else ''}} type="text" placeholder="example.com example.net" class="form-control">
	</div><br>   	      
	
	<div class="panel-group" id="accordion">
	  <div class="panel panel-default" id="panel3">
		<div class="panel-heading">
		  <h4 class="panel-title">
			<a data-toggle="collapse" data-target="#collapseThree" href="#collapseThree">
			  Storage
			</a>
		  </h4>
		</div>
		<div id="collapseThree" class="panel-collapse collapse in">
		  <div class="panel-body">
			<div class="input-group" >
				%if 'storage_type' in locals() and storage_type == 'local':
					<input name="storage-type" id="storage-type-local" type="radio"  value="local" checked> Local Device
				%elif 'storage_type' not in locals():
					<input name="storage-type" checked id="storage-type-local" type="radio"  value="local"> Local Device						
				%else:
					<input name="storage-type" id="storage-type-local" type="radio"  value="local"> Local Device
				%end
				<div class="row"> 
					<div class="col-md-12"> 
						<input name="storage-local-device" {{'value=' + storage_local_device if defined('storage_local_device') else ''}} id="storage-local-device" type="text" required placeholder="/dev/vdb" value="/dev/vdb" class="form-control" />
						%if 'create_file_system' in locals() and create_file_system == 'on':
							<input name="create-file-system" checked id="create-file-system" type="checkbox" onclick='warnCreateFileSystem(this)';> Create File System
						%else:
							<input name="create-file-system" id="create-file-system" type="checkbox" onclick='warnCreateFileSystem(this)';> Create File System
						%end    					
					</div>
				</div>
				<br/>
				<div class="row"> 
					<div class="col-md-12"> 				
						%if 'storage_type' in locals() and storage_type == 'nfs':
							<input name="storage-type" id="storage-type-nfs" type="radio"  value="nfs" checked> NFS Export
						%else:
							<input name="storage-type" id="storage-type-nfs" type="radio"  value="nfs" > NFS Export
						%end      			
						<input name="storage-nfs-export" {{'value=' + storage_nfs_export if defined('storage_nfs_export') else ''}} id="storage-nfs-export" type="text" required placeholder="server:/var/nfs" value="server:/var/nfs" class="form-control" />
					</div>
				</div>
				<br/>
			</div>
		  </div>
		</div>
	  </div>
	</div>

	<div class="panel-group" id="accordion">
	  <div class="panel panel-default" id="panel5">
		<div class="panel-heading">
		  <h4 class="panel-title">
			<a data-toggle="collapse" data-target="#collapseFive" href="#collapseFive">
			  Swift Object Storage (Optional)
			</a>
		  </h4>
		</div>
		<div id="collapseFive" class="panel-collapse">
		  <div class="panel-body">
			<div class="input-group">
				<label class="input-group-addon">URL Template&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</label>
				<input name="swift-url-template" {{'value=' + swift_url_template if (defined('swift_url_template') and len(swift_url_template)) else ''}} type="text" placeholder="http://swifthost:8080/v1/AUTH_%(project_id)s" class="form-control"><br>
			</div><br>
			<div class="input-group">
				<label class="input-group-addon">Container Prefix&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</label>
				<input name="swift-container-prefix" type="text" {{'value=' + swift_container_prefix if (defined('swift_container_prefix') and len(swift_container_prefix)) else ''}} placeholder="TrilioVault" class="form-control"> <br>
			</div><br>  			
		  </div>
		</div>
	  </div>
	</div>
    
    <button type="submit" class="btn btn-lg btn-primary btn-block">Submit</button>
  </form>
  </div>
</div>
</body>
</html>
