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
<script type="text/javascript">
function setRequired(val) {
    if(val.includes('v3')) {
       $('[name="domain-name"]').attr("required", "true");
    }
    else {
         $('[name="domain-name"]').removeAttr('required')
    }
}
function findForm() {
  setRequired($("#configure_openstack input[name='keystone-admin-url']").val())
  setRequired($("#configure_openstack input[name='keystone-public-url']").val())
}
</script>
</head>

<body onload="findForm()">
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
  <form role="form" id="configure_openstack" class="form-configure" action="/configure_openstack" method="post">
	%if 'nodetype' in locals() and nodetype == 'additional':
		<input name = "nodetype" type="radio"  value="controller" >  Controller Node&nbsp;&nbsp;
		<input name = "nodetype" type="radio"  value="additional" checked>   Additional Node <br> <br>		
	%else:
		<input name = "nodetype" type="radio"  value="controller" checked>  Controller Node&nbsp;&nbsp;
		<input name = "nodetype" type="radio"  value="additional" >   Additional Node <br> <br>		
	%end  
		   
    <div class="input-group">
    	<label class="input-group-addon">Floating IP Address	</label>
    	<input name="floating-ipaddress" {{'value=' + floating_ipaddress if defined('floating_ipaddress') else ''}} type="text" required="" placeholder="192.168.2.200" class="form-control"><br>
    </div><br>
    <div class="input-group">    
    	<label class="input-group-addon">Keystone Admin Url</label>
    	<input name="keystone-admin-url" {{'value=' + keystone_admin_url if defined('keystone_admin_url') else ''}} onblur="setRequired(this.value)" type="url" required="" placeholder="http://keystonehost:35357/v2.0" class="form-control"><br>
    </div><br>
    <div class="input-group">
    	<label class="input-group-addon">Keystone Public Url</label>
    	<input name="keystone-public-url" {{'value=' + keystone_public_url if defined('keystone_public_url') else ''}} onblur="setRequired(this.value)" type="url" required="" placeholder="http://keystonehost:5000/v2.0" class="form-control"><br>
    </div><br>
    <div class="input-group">
    	<label class="input-group-addon">Administrator&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp</label>
    	<input name="admin-username" {{'value=' + admin_username if defined('admin_username') else ''}} type="text" required="" placeholder="admin" class="form-control"> <br>
    </div><br>
    <div class="input-group">
    	<label class="input-group-addon">Password&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp</label>
    	<input name="admin-password" type="password" required="" placeholder="" class="form-control"> <br>
    </div><br>
    	<div class="input-group">
    	<label class="input-group-addon">Admin Tenant&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp</label>
    	<input name="admin-tenant-name" {{'value=' + admin_tenant_name if defined('admin_tenant_name') else ''}} type="text" required="" placeholder="admin" class="form-control">
    </div><br>
    <div class="input-group">
    	<label class="input-group-addon">Region&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp</label>
    	<input name="region-name" {{'value=' + region_name if defined('region_name') else ''}} type="text" required="" placeholder="RegionOne" class="form-control">
    </div><br>   
    <div class="input-group">
        <label class="input-group-addon">Domain&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp</label>
        <input name="domain-name" {{'value=' + domain_name if defined('domain_name') else ''}} type="text" placeholder="default" class="form-control">
    </div><br>
    <div class="input-group">
        <label class="input-group-addon">Hostname&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</label>
        <input name="guest-name" {{'value=' + guest_name if defined('guest_name') else ''}} type="text" required="" placeholder="Hostname" class="form-control">
    </div><br> 
	<div class="input-group" >
		<label class="input-group-addon">Name Server&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp</label>
		<input name="name-server" {{'value=' + name_server if (defined('name_server') and len(name_server)) else ''}} type="text" placeholder="192.168.2.1" class="form-control">
		
		<label class="input-group-addon">Domain Search Order</label>
		<input name="domain-search-order" {{'value=' + domain_search_order if (defined('domain_search_order') and len(domain_search_order)) else ''}} type="text" placeholder="example.com example.net" class="form-control">
	</div><br>   	      

	<div class="panel-group" id="accordion" >
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
				<input name="ntp-servers" {{'value=' + ntp_servers if defined('ntp_servers') else ''}} id="ntp-servers" type="text" placeholder="0.pool.ntp.org,1.pool.ntp.org" class="form-control" />
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
		        <label class="input-group-addon">NFS Export&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</label>
				<input name="storage-nfs-export" {{'value=' + storage_nfs_export if defined('storage_nfs_export') else ''}} id="storage-nfs-export" type="text" required placeholder="server:/var/nfs" class="form-control" />
			</div>
		  </div>
		</div>
	  </div>
	</div>

	<!-- Swift is not yet supported
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
	Swift is not yet supported -->
    
    <button type="submit" class="btn btn-lg btn-primary btn-block">Submit</button>
  </form>
  </div>
</div>

<script>
$(document).ready(function(){
$('#ntp-enabled').click(function(){
if($(this).is(':checked'))
{
$('#ntp-servers').attr('required','required')
}
else
{
$('#ntp-servers').removeAttr('required');
}
});
});
</script>
</body>
</html>
