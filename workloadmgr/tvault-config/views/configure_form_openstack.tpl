<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN" "http://www.w3.org/TR/html4/loose.dtd">
<html>
<head>
<!-- Latest compiled and minified CSS -->
<link rel="stylesheet" href="css/bootstrap.min.css">

<!-- Optional theme -->
<link rel="stylesheet" href="css/bootstrap-theme.min.css">
<link rel="stylesheet" href="css/font-awesome.min.css">

<script src="js/jquery-1.11.0.min.js"></script>
<!-- Latest compiled and minified JavaScript -->
<script src="js/bootstrap.min.js"></script>
<script type="text/javascript">
IsV3 = false
function setRequired(val) {
    if(val.includes('v3')) {
       IsV3 = true
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
		<input name = "nodetype" type="radio"  value="controller" onclick='$("#panel4")[0].hidden=false'>  Controller Node
		<input name = "nodetype" type="radio"  value="additional" checked onclick='$("#panel4")[0].hidden=true'>   Additional Node <br><br>
	%else:
		<input name = "nodetype" type="radio"  value="controller" checked onclick='$("#panel4")[0].hidden=false'>  Controller Node
		<input name = "nodetype" type="radio"  value="additional" onclick='$("#panel4")[0].hidden=true'>   Additional Node <br><br>
	%end  
		   
    <div class="form-group">
    	<label class="control-label">Floating IP Address	<i class="fa fa-spinner fa-spin hidden" id="floatingip-spinner" style="font-size:20px"></i></label>
    	<input name="floating-ipaddress" {{'value=' + floating_ipaddress if defined('floating_ipaddress') else ''}} type="text" required="" placeholder="192.168.2.200" class="form-control">
    </div>
    <div class="form-group">
    	<label class="control-label">Keystone Admin Url<i class="fa fa-spinner fa-spin hidden" id="adminurl-spinner" style="font-size:20px"></i></label>
    	<input name="keystone-admin-url" {{'value=' + keystone_admin_url if defined('keystone_admin_url') else ''}} onblur='setRequired(this.value);validate_keystone_url("validate_keystone_url?url="+this.value, this)' type="url" required="" placeholder="http://keystonehost:35357/v2.0" class="form-control" aria-describedby="adminurl_helpblock">
        <span id="adminurl_helpblock" class="help-block hidden">A block of help text that breaks onto a new line and may extend beyond one line.</span>
    </div>
    <div class="form-group">
    	<label class="control-label">Keystone Public Url<i class="fa fa-spinner fa-spin hidden" id="publicurl-spinner" style="font-size:20px"></i></label>
    	<input name="keystone-public-url" {{'value=' + keystone_public_url if defined('keystone_public_url') else ''}} onblur='setRequired(this.value);validate_keystone_url("validate_keystone_url?url="+this.value, this)' type="url" required="" placeholder="http://keystonehost:5000/v2.0" class="form-control" aria-describedby="publicurl_helpblock">
        <span id="publicurl_helpblock" class="help-block hidden">A block of help text that breaks onto a new line and may extend beyond one line.</span>
    </div>
    <div class="form-group">
    	<label class="control-label">Administrator</label>
    	<input name="admin-username" {{'value=' + admin_username if defined('admin_username') else ''}} type="text" required="" placeholder="admin" class="form-control"> 
    </div>
    <div class="form-group">
    	<label class="control-label">Password</label>
    	<input name="admin-password" type="password" required="" placeholder="" class="form-control">
    </div>
    	<div class="form-group">
    	<label class="control-label">Admin Tenant<i class="fa fa-spinner fa-spin hidden" id="password-spinner" style="font-size:20px"></i></label>
    	<input name="admin-tenant-name" {{'value=' + admin_tenant_name if defined('admin_tenant_name') else ''}} type="text" required="" placeholder="admin" class="form-control" onblur='validate_keystone_credentials(this)'  aria-describedby="cred_helpblock">
        <span id="cred_helpblock" class="help-block hidden">A block of help text that breaks onto a new line and may extend beyond one line.</span>
    </div>
    <div class="form-group">
    	<label class="control-label">Region</label>
    	<input name="region-name" {{'value=' + region_name if defined('region_name') else ''}} type="text" required="" placeholder="RegionOne" class="form-control">
    </div>
    <div class="form-group">
        <label class="control-label">Domain ID</label>
        <input name="domain-name" {{'value=' + domain_name if defined('domain_name') else ''}} type="text" placeholder="default" class="form-control" onblur='validate_keystone_credentials(this)'>
        <span id="cred_helpblock" class="help-block hidden">A block of help text that breaks onto a new line and may extend beyond one line.</span>
    </div>
    <div class="form-group">
         <label class="control-label">Trustee Role</label>
                    <select name="trustee-role" id="trustee-role" class="form-control">
                    %for role in roles:
                         %if role==trustee_role:
                             <option value="{{role}}" selected>{{role}}</option>
                         %else:
                              <option value="{{role}}">{{role}}</option>
                         %end
                    %end
                    </select>
    </div>
    <div class="form-group">
        <label class="control-label">Hostname</label>
        <input name="guest-name" {{'value=' + guest_name if defined('guest_name') else ''}} type="text" required="" placeholder="Hostname" class="form-control">
    </div>
    <div class="form-group" >
	<label class="control-label">Name Server</label>
	<input name="name-server" {{'value=' + name_server if (defined('name_server') and len(name_server)) else ''}} type="text" placeholder="192.168.2.1" class="form-control">
    </div>
    <div class="form-group" >
	<label class="control-label">Domain Search Order</label>
	<input name="domain-search-order" {{'value=' + domain_search_order if (defined('domain_search_order') and len(domain_search_order)) else ''}} type="text" placeholder="example.com example.net" class="form-control">
     </div>
     <div class="panel-group" id="accordion" >
	  <div class="panel panel-default" id="panel9">
	    <div class="panel-heading">
	      <h4 class="panel-title">
	        <a data-toggle="collapse" data-target="#collapseNine" href="#collapseNine"> NTP </a>
	      </h4>
	    </div>
	    <div id="collapseNine" class="panel-collapse collapse in">
	      <div class="panel-body">
	        <div class="form-group">
			%if 'ntp_enabled' in locals() and ntp_enabled == 'on':
				<input name="ntp-enabled" checked id="ntp-enabled" type="checkbox"> NTP <span style="font-size:11px;">(List ntp servers separated by comma) </span>
			%else:
				<input name="ntp-enabled" id="ntp-enabled" type="checkbox"> NTP <span style="font-size:11px">(List ntp servers separated by comma) </span>
			%end    		
	        </div>
		<div class="form-group" >                                        
			<label class="control-label">NTP servers</label>
			<input name="ntp-servers" {{'value=' + ntp_servers if defined('ntp_servers') else ''}} id="ntp-servers" type="text" placeholder="0.pool.ntp.org,1.pool.ntp.org" class="form-control" />
		</div>
	        <div class="form-group">
	         <label class="control-label">Timezone</label>
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
			<div class="form-group" >
		        <label class="control-label">NFS Export<i class="fa fa-spinner fa-spin hidden" id="nfs-spinner" style="font-size:20px"></i></label>
			<input name="storage-nfs-export" {{'value=' + storage_nfs_export if defined('storage_nfs_export') else ''}} id="storage-nfs-export" type="text" required placeholder="server:/var/nfs" class="form-control" onblur='validate_nfsshare(this)'  aria-describedby="nfs_helpblock">
                        <span id="nfs_helpblock" class="help-block hidden">A block of help text that breaks onto a new line and may extend beyond one line.</span>
			</div>
		  </div>
		</div>
	  </div>
	</div>

	<div class="panel-group" id="accordion">
	  <div class="panel panel-default" id="panel4">
		<div class="panel-heading">
		  <h4 class="panel-title">
			<a data-toggle="collapse" data-target="#collapseFour" href="#collapseFour"> Import Workloads </a>
		  </h4>
		</div>
		<div id="collapseFour" class="panel-collapse collapse in">
		  <div class="panel-body">
	              <div class="form-group">
			%if 'workloads_import' in locals() and workloads_import == 'on':
				<input name="workloads-import" checked id="workloads-import" type="checkbox"> Import workloads metadata from backup media. <span style="font-size:11px;">Choose this option if you are upgrading TrilioVault VM.</span>
			%else:
				<input name="workloads-import" id="workloads-import" type="checkbox"> Import workloads metadata from backup media. <span style="font-size:11px;">Choose this option if you are upgrading TrilioVault VM.</span>
			%end
	              </div>
	              <br />
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
			<div class="form-group">
				<label class="control-label">URL Template</label>
				<input name="swift-url-template" {{'value=' + swift_url_template if (defined('swift_url_template') and len(swift_url_template)) else ''}} type="text" placeholder="http://swifthost:8080/v1/AUTH_%(project_id)s" class="form-control"><br>
			</div><br>
			<div class="form-group">
				<label class="control-label">Container Prefix</label>
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

function validate_keystone_url(url, inputelement) {
    $.ajax({url: url,
            beforeSend: function() {
             spinelement = $($($(inputelement).parent()[0])[0]).find(".fa-spinner")
             $(spinelement[0]).removeClass("hidden")
             $($($($(inputelement).parent()[0]).find(".help-block")[0])[0]).addClass("hidden")
             $($(inputelement).parent()[0]).removeClass("has-error")
             $($(inputelement).parent()[0]).removeClass("has-success")
            },
            complete: function(result) {
             spinelement = $($($(inputelement).parent()[0])[0]).find(".fa-spinner")
             $(spinelement[0]).addClass("hidden")
            },
            error: function(result) {
             $($(inputelement).parent()[0]).addClass("has-error")
             $($($($(inputelement).parent()[0]).find(".help-block")[0])[0]).removeClass("hidden")
             $($($(inputelement).parent()[0]).find(".help-block")[0])[0].innerHTML = result.responseText
            },
            success: function(result) {
             $($(inputelement).parent()[0]).addClass("has-success")
            }
    });
}

function validate_keystone_credentials(inputelement) {
    if(inputelement.name == 'admin-tenant-name' && IsV3 == true)
       return

    public_url = $('[name="keystone-public-url"]')[0].value
    admin_url = $('[name="keystone-admin-url"]')[0].value
    project_name = $('[name="admin-tenant-name"]')[0].value
    username = $('[name="admin-username"]')[0].value
    password = $('[name="admin-password"]')[0].value
    domain_id = $('[name="domain-name"]')[0].value
    $.ajax({
        url: "validate_keystone_credentials?public_url="+public_url+"&admin_url="+
             admin_url+"&project_name="+project_name+"&username="+username+"&password="+password+"&domain_id="+domain_id,
        beforeSend: function() {
           spinelement = $($($(inputelement).parent()[0])[0]).find(".fa-spinner")
           $(spinelement[0]).removeClass("hidden")
           $($($($(inputelement).parent()[0]).find(".help-block")[0])[0]).addClass("hidden")
           $($(inputelement).parent()[0]).removeClass("has-error")
           $($(inputelement).parent()[0]).removeClass("has-success")
        },
        complete: function(result) {
           spinelement = $($($(inputelement).parent()[0])[0]).find(".fa-spinner")
           $(spinelement[0]).addClass("hidden")
        },
        error: function(result) {
           $($(inputelement).parent()[0]).addClass("has-error")
           $($($($(inputelement).parent()[0]).find(".help-block")[0])[0]).removeClass("hidden")
           $($($(inputelement).parent()[0]).find(".help-block")[0])[0].innerHTML = result.responseText
        },
        success: function(result) {
           $($(inputelement).parent()[0]).addClass("has-success")
           options = ""
           $.each(result.roles, function( index, value ) {
               options += "<option value="+ value +" selected>"+ value + "</option>"
           });
           document.getElementsByName("trustee-role")[0].innerHTML = options
        }
    });
}

function validate_nfsshare(inputelement) {
    nfsshare = $('[name="storage-nfs-export"]')[0].value
    $.ajax({
        url: "validate_nfs_share?nfsshare="+nfsshare,
        beforeSend: function() {
           spinelement = $($($(inputelement).parent()[0])[0]).find(".fa-spinner")
           $(spinelement[0]).removeClass("hidden")
           $($($($(inputelement).parent()[0]).find(".help-block")[0])[0]).addClass("hidden")
           $($(inputelement).parent()[0]).removeClass("has-error")
           $($(inputelement).parent()[0]).removeClass("has-success")
        },
        complete: function(result) {
           spinelement = $($($(inputelement).parent()[0])[0]).find(".fa-spinner")
           $(spinelement[0]).addClass("hidden")
        },
        error: function(result) {
           $($(inputelement).parent()[0]).addClass("has-error")
           $($($($(inputelement).parent()[0]).find(".help-block")[0])[0]).removeClass("hidden")
           $($($(inputelement).parent()[0]).find(".help-block")[0])[0].innerHTML = result.responseText
        },
        success: function(result) {
           $($(inputelement).parent()[0]).addClass("has-success")
        }
    });
}

</script>
</body>
</html>
