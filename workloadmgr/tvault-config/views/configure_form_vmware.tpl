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

	<script>
	function warnCreateFileSystem(cb) {
	  if(cb.checked == true){
	   var r = confirm("Creating a new file system will erase the previous contents permanently.\nDo you want to create a new file system?");
	   if (r == true) {
		   cb.checked = true;
	   } else {
	     cb.checked = false;
	   }
	  }
	}

        function refreshData() {
            nodes = document.getElementsByName('nodetype')
            var refresh = document.getElementById('refresh').value
            var val
            for(i=0;i<nodes.length;i++) {
              if(nodes[i].checked) {
                val = nodes[i].value
              } 
            }
            if (val == 'additional' && refresh == 1) {
               url = window.location.href
               form = document.forms[0]
               form.action = url
               form.submit()
            }
            else {
               document.getElementById('refresh').value = 0;                
            }

        } 
	</script>  
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
	      <a class="navbar-brand" href="/home"><img src="images/triliodata-144x36.png" alt="Trilio Data, Inc" height="32" width="134"></a>
	    </div>
	    <div id="bs-example-navbar-collapse-3" class="collapse navbar-collapse navbar-right">
	       <button class="btn btn-default navbar-btn" type="button" onClick="parent.location='/logout'">Sign Out</button>
	    </div>
	  </div><!-- /.container-fluid -->
	</nav>
	<div class="panel panel-primary" style="width:70%;text-align:left;margin-left:auto; margin-right:auto;margin-top:100px">
	  <!-- Default panel contents -->
	  <div class="panel-heading"><h3 class="panel-title">TrilioVault Configuration</h3></div>
	  % if len(error_message) > 0:
		  	<div class="alert alert-danger alert-dismissible" role="alert">
			  <button type="button" class="close" data-dismiss="alert">
			  <span aria-hidden="true">&times;</span><span class="sr-only">Close</span></button>
			  <strong>{{error_message}}</strong>
	 		</div>
	  % end
  	<div style="margin-left:auto; margin-right:auto; padding:20px">	
	<form role="form" class="form-configure" action="/configure_vmware" method="post">
		%if 'nodetype' in locals() and nodetype == 'additional':
			<input name = "nodetype" type="radio"  value="controller" >  Controller Node&nbsp;&nbsp;
			<input name = "nodetype" type="radio"  value="additional" checked>   Additional Node <br> <br>		
		%else:
			<input name = "nodetype" type="radio"  value="controller" checked>  Controller Node&nbsp;&nbsp;
			<input name = "nodetype" type="radio"  value="additional" >   Additional Node <br> <br>		
		%end  
	      
            %if refresh == 1:
            	<input type="hidden" id="refresh" name="refresh" value="1"/>
            %else:
                 <input type="hidden" id="refresh" name="refresh" value="0"/>
            %end
	    <div class="input-group">
	    	<label class="input-group-addon">Controller Node&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</label>
	    	<input name="tvault-primary-node" {{'value=' + tvault_primary_node if defined('tvault_primary_node') else ''}} type="text" required placeholder="192.168.2.216" class="form-control" onblur="refreshData()"><br>
	    </div><br>
	   
	    <div class="input-group">
	    	<label class="input-group-addon">vCenter&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</label>
	    	<input name="vcenter" {{'value=' + vcenter if defined('vcenter') else ''}} type="text" required placeholder="vcenter.local" class="form-control"><br>
	    </div><br>
	    <div class="input-group">
	    	<label class="input-group-addon">vCenter User&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</label>
	    	<input name="vcenter-username" {{'value=' + vcenter_username if defined('vcenter_username') else ''}} type="text" required placeholder="administrator@vsphere.local" class="form-control"> <br>
	    </div><br>
	    <div class="input-group">
	    	<label class="input-group-addon">vCenter Password&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp</label>
	    	<input name="vcenter-password" type="password" required placeholder="" class="form-control"> <br>
	    </div><br>
		<div class="input-group" >
	    	<label class="input-group-addon">Name Server&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp</label>
	    	<input name="name-server" {{'value=' + name_server if (defined('name_server') and len(name_server)) else ''}} type="text" placeholder="192.168.2.1" class="form-control">
	    	
	    	<label class="input-group-addon">Domain Search Order</label>
	    	<input name="domain-search-order" {{'value=' + domain_search_order if (defined('domain_search_order') and len(domain_search_order)) else ''}} type="text" placeholder="example.com example.net" class="form-control">
		</div><br>   	      

               <div class="panel-group" id="accordion">
		  <div class="panel panel-default" id="panel9">
		    <div class="panel-heading">
		      <h4 class="panel-title">
		        <a data-toggle="collapse" data-target="#collapseNine" href="#collapseNine">
		          NTP
		        </a>
		      </h4>
		    </div>
		    <div id="collapseNine" class="panel-collapse collapse in">
		      <div class="panel-body">
                        <div class="input-group">
                             %if 'ntp_enabled' in locals() and ntp_enabled == 'on':
								<input name="ntp-enabled" checked id="ntp-enabled" type="checkbox"> NTP <span style="font-size:11px;">(List ntp servers separated by comma) </span>
							%else:
								<input name="ntp-enabled" id="ntp-enabled" type="checkbox"> NTP <span style="font-size:11px">(List ntp servers separated by comma) </span>
							%end    		
                        </div>
                        <br />
	    		<div class="input-group" >                                        
					<label class="input-group-addon">NTP servers&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp</label>
	    			        <input name="ntp-servers" {{'value=' + ntp_servers if defined('ntp_servers') else ''}} id="ntp-servers" type="text" required placeholder="0.pool.ntp.org,1.pool.ntp.org" class="form-control" />
	    		</div>
                        <br />
                        <div class="input-group">
	                     <label class="input-group-addon">Timezone&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</label>
                             <select name="timezone" id="timezone" class="form-control">
                             %for tz in timezones:
                                   %if tz==timezone:
                                       <option value="{{tz}}" selected>{{tz}}</option>
                                   %else:
                                        <option value="{{tz}}">{{tz}}</option>
                                   %end
                            %end
                            </select>
                        </div>
	 	      </div>
		    </div>
		  </div>
		</div> 
	    
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
	    					<input name="storage-local-device" {{'value=' + storage_local_device if defined('storage_local_device') else ''}} id="storage-local-device" type="text" required placeholder="/dev/sdb" value="/dev/sdb" class="form-control" />
							%if 'create_file_system' in locals() and create_file_system == 'on':
								<input name="create-file-system" checked id="create-file-system" type="checkbox" onclick='warnCreateFileSystem(this)';> Create File System
							%else:
								<input name="create-file-system" id="create-file-system" type="checkbox" onclick='warnCreateFileSystem(this)';> Create File System
							%end    					
	    				</div>
	    			</div>
	    			<br/>
					%if 'storage_type' in locals() and storage_type == 'nfs':
						<input name="storage-type" id="storage-type-nfs" type="radio"  value="nfs" checked> NFS Export
					%else:
						<input name="storage-type" id="storage-type-nfs" type="radio"  value="nfs" > NFS Export
					%end      			
	    			<input name="storage-nfs-export" {{'value=' + storage_nfs_export if defined('storage_nfs_export') else ''}} id="storage-nfs-export" type="text" required placeholder="server:/var/nfs" value="server:/var/nfs" class="form-control" /> <br/>
	 		    	<!---
					%if 'storage_type' in locals() and storage_type == 'object':
						<input name="storage-type" id="storage-type-object" type="radio"  value="object" disabled checked> Object Store
					%else:
						<input name="storage-type" id="storage-type-object" type="radio"  value="object" disabled> Object Store
					%end      			
	    			<input name="storage-object-url" {{'value=' + storage_object_url if defined('storage_object_url') else ''}} id="storage-object-url" type="text" required placeholder="" class="form-control">	<br/>
			    	-->
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
		    <div id="collapseFive" class="panel-collapse collapse">
		      <div class="panel-body">
                %if 'swift_auth_version' in locals() and swift_auth_version == 'TEMPAUTH':
                    <input name = "swift-auth-version" type="radio"  value="KEYSTONE_V2" >  KEYSTONE_V2 &nbsp;&nbsp;
                    <input name = "swift-auth-version" type="radio"  value="KEYSTONE_V3" >  KEYSTONE_V3 &nbsp;&nbsp;
                    <input name = "swift-auth-version" type="radio"  value="TEMPAUTH" checked>  TEMPAUTH <br> <br>                       
                %elif 'swift_auth_version' in locals() and swift_auth_version == 'KEYSTONE_V3':
                    <input name = "swift-auth-version" type="radio"  value="KEYSTONE_V2" >  KEYSTONE_V2 &nbsp;&nbsp;
                    <input name = "swift-auth-version" type="radio"  value="KEYSTONE_V3" checked>  KEYSTONE_V3 &nbsp;&nbsp;
                    <input name = "swift-auth-version" type="radio"  value="TEMPAUTH" >  TEMPAUTH <br> <br>                                
                %else:
                    <input name = "swift-auth-version" type="radio"  value="KEYSTONE_V2" checked>  KEYSTONE_V2 &nbsp;&nbsp;
                    <input name = "swift-auth-version" type="radio"  value="KEYSTONE_V3" >  KEYSTONE_V3 &nbsp;&nbsp;
                    <input name = "swift-auth-version" type="radio"  value="TEMPAUTH" >  TEMPAUTH <br> <br>      	
                %end  
                <div class="input-group">
                    <label class="input-group-addon">Auth Url&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</label>
                    <input name="swift-auth-url" {{'value=' + swift_auth_url if (defined('swift_auth_url') and len(swift_auth_url)) else ''}} type="text" placeholder="http://keystonehost:5000/v2.0" class="form-control"><br>
                </div><br>
                <div class="input-group">
                    <label class="input-group-addon">Username&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</label>
                    <input name="swift-username" {{'value=' + swift_username if (defined('swift_username') and len(swift_username)) else ''}} type="text" placeholder="admin" class="form-control"> <br>
                </div><br>
                <div class="input-group">
                    <label class="input-group-addon">Password&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp</label>
                    <input name="swift-password" type="password" class="form-control"> <br>
                </div><br>
                <div class="input-group">
                    <label class="input-group-addon">Tenant&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</label>
                    <input name="swift-tenantname" {{'value=' + swift_tenantname if (defined('swift_tenantname') and len(swift_tenantname)) else ''}} type="text" placeholder="admin" class="form-control"> <br>
                </div><br>
                <div class="input-group">
                    <label class="input-group-addon">Container Prefix&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</label>
                    <input name="swift-container-prefix" type="text" {{'value=' + swift_container_prefix if (defined('swift_container_prefix') and len(swift_container_prefix)) else ''}} placeholder="TrilioVault" class="form-control"> <br>
                </div><br>                    
	 	      </div>
		    </div>
		  </div>
		</div>
		
		<div class="panel-group" id="accordion">
		  <div class="panel panel-default" id="panel1">
		    <div class="panel-heading">
		      <h4 class="panel-title">
		        <a data-toggle="collapse" data-target="#collapseOne" href="#collapseOne">
		          LDAP (Optional)
		        </a>
		      </h4>
		    </div>
		    <div id="collapseOne" class="panel-collapse collapse">
		      <div class="panel-body">
				%if 'ldap_server_url' in locals() and ldap_server_url != 'ldap://localhost':
					<div class="input-group">
						<label class="input-group-addon">Server URL&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</label>
						<input name="ldap-server-url" {{'value=' + ldap_server_url if defined('ldap_server_url') else ''}} type="text" placeholder="ldap://example.com" class="form-control"><br>
					</div><br>
					<div class="input-group">
						<label class="input-group-addon">DN for domain name</label>
						<input name="ldap-domain-name-suffix" {{'value=' + ldap_domain_name_suffix if defined('ldap_domain_name_suffix') else ''}} type="text" placeholder="dc=example,dc=com" class="form-control"> <br>
					</div><br>
					<div class="input-group">
						<label class="input-group-addon">Base DN for users&nbsp;&nbsp;&nbsp;&nbsp;</label>
						<input name="ldap-user-tree-dn" {{'value=' + ldap_user_tree_dn if defined('ldap_user_tree_dn') else ''}} type="text" placeholder="cn=users,dc=example,dc=com" class="form-control"><br>
					</div><br>
					<div class="input-group">
						<label class="input-group-addon">Username(DN)&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</label>
						<input name="ldap-user-dn" {{'value=' + ldap_user_dn if defined('ldap_user_dn') else ''}} type="text" placeholder="cn=triliovault,cn=users,dc=example,dc=com" class="form-control"> <br>
					</div><br>
					<div class="input-group">
						<label class="input-group-addon">User Object Class&nbsp;&nbsp;&nbsp;&nbsp;</label>
						<input name="ldap-user-objectclass" {{'value=' + ldap_user_objectclass if defined('ldap_user_objectclass') else ''}} type="text" placeholder="inetOrgPerson OR Person" class="form-control"> <br>
					</div><br>	
					<div class="input-group">
						<label class="input-group-addon">Username Attribute&nbsp;&nbsp;</label>
						<input name="ldap-user-name-attribute" {{'value=' + ldap_user_name_attribute if defined('ldap_user_name_attribute') else ''}} type="text" placeholder="sn OR cn" class="form-control"> <br>
					</div><br>
				%else:
					<div class="input-group">
						<label class="input-group-addon">Server URL&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</label>
						<input name="ldap-server-url" type="text" placeholder="ldap://example.com" class="form-control"><br>
					</div><br>
					<div class="input-group">
						<label class="input-group-addon">DN for domain name</label>
						<input name="ldap-domain-name-suffix" type="text" placeholder="dc=example,dc=com" class="form-control"> <br>
					</div><br>
					<div class="input-group">
						<label class="input-group-addon">Base DN for users&nbsp;&nbsp;&nbsp;&nbsp;</label>
						<input name="ldap-user-tree-dn" type="text" placeholder="cn=users,dc=example,dc=com" class="form-control"><br>
					</div><br>
					<div class="input-group">
						<label class="input-group-addon">Username(DN)&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</label>
						<input name="ldap-user-dn" type="text" placeholder="cn=triliovault,cn=users,dc=example,dc=com" class="form-control"> <br>
					</div><br>
					<div class="input-group">
						<label class="input-group-addon">User Object Class&nbsp;&nbsp;&nbsp;&nbsp;</label>
						<input name="ldap-user-objectclass" type="text" placeholder="inetOrgPerson OR Person" class="form-control"> <br>
					</div><br>	
					<div class="input-group">
						<label class="input-group-addon">Username Attribute&nbsp;&nbsp;</label>
						<input name="ldap-user-name-attribute" type="text" placeholder="sn OR cn" class="form-control"> <br>
					</div><br>			
				%end  																	
		      </div>
		    </div>
		  </div>
		</div>    

		<div class="panel-group" id="accordion">
		  <div class="panel panel-default" id="panel4">
		    <div class="panel-heading">
		      <h4 class="panel-title">
		        <a data-toggle="collapse" data-target="#collapseFour" href="#collapseFour">
		          Imports
		        </a>
		      </h4>
		    </div>
		    <div id="collapseFour" class="panel-collapse collapse in">
		      <div class="panel-body">
				%if 'import_workloads' in locals() and import_workloads == 'on':
					<input name="import-workloads" id="import-workloads" type="checkbox" checked> Import Existing Workloads
				%elif 'import_workloads' not in locals():
					<input name="import-workloads" id="import-workloads" type="checkbox" checked> Import Existing Workloads
				%else:
					<input name="import-workloads" id="import-workloads" type="checkbox" > Import Existing Workloads
				%end    					
	 	      </div>
		    </div>
		  </div>
		</div>
	    
	    <button type="submit" class="btn btn-lg btn-primary btn-block">Submit</button>
	</form>
  </div>
</body>
</html>
