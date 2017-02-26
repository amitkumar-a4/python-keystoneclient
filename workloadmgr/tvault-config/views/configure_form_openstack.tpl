<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN" "http://www.w3.org/TR/html4/loose.dtd">
<html>
<head>
<!-- Latest compiled and minified CSS -->
<link rel="stylesheet" href="css/bootstrap.min.css">

<!-- Optional theme -->
<link rel="stylesheet" href="css/bootstrap-theme.min.css">
<link rel="stylesheet" href="css/font-awesome.min.css">
<link rel="stylesheet" href="css/bootstrap-tagsinput.css">

<script src="js/jquery-1.11.0.min.js"></script>
<!-- Latest compiled and minified JavaScript -->
<script src="js/bootstrap.min.js"></script>
<script src="js/bootstrap-tagsinput.min.js"></script>
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
  obj = $("#configure_openstack input[name='swift-auth-version']:checked")
  setSwiftRequired(obj.attr('checked'), obj.val())
}

function setSwiftRequired(checked, val) {
     if((checked==true || checked=='checked') && val=='TEMPAUTH') {
        $('[name="swift-auth-url"]').attr("required", "true");
        $('[name="swift-username"]').attr("required", "true");
        $('[name="swift-password"]').attr("required", "true");
        $('#swift-auth-url-div').toggle(true)
        $('#swift-username-div').toggle(true)
        $('#swift-password-div').toggle(true)
     }
     if(val != 'TEMPAUTH') {
        $('#swift-auth-url-div').toggle(false)
        $('#swift-username-div').toggle(false)
        $('#swift-password-div').toggle(false)
        $('[name="swift-auth-url"]').removeAttr('required')
        $('[name="swift-username"]').removeAttr('required')
        $('[name="swift-password"]').removeAttr('required')
     }
     if(val == 'TEMPAUTH' || val == 'KEYSTONE') {
       $('[name="storage-nfs-export"]').removeAttr('required')
       $('[name="storage-nfs-options"]').removeAttr('required')        
     }
     else {
       $('[name="storage-nfs-export"]').attr("required", "true");
       $('[name="storage-nfs-options"]').attr("required", "true");
     }

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
    	<input name="keystone-public-url" {{'value=' + keystone_public_url if defined('keystone_public_url') else ''}} onblur='setRequired(this.value);if (validate_url_versions()) validate_keystone_url("validate_keystone_url?url="+this.value, this)' type="url" required="" placeholder="http://keystonehost:5000/v2.0" class="form-control" aria-describedby="publicurl_helpblock">
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

	<div class="panel-group" id="backend-choice">
	  <div class="panel panel-default" id="panel9">
             <div class="panel-heading">
                <h4 class="panel-title">
                  <a data-toggle="collapse" data-target="#collapseThree" href="#collapseThree"> Choose Backup Target </a>
                </h4>
             </div>
          </div>
          <div id="collapsebackendtype" class="panel-collapse collapse in">
            <div class="panel-body">
             <label class="radio-inline">
             %if 'backup_target_type' in locals() and backup_target_type == 'NFS':
                <input type="radio" name="backup_target_type" aria-describedby="backup_target_helpblock" checked value="NFS" onchange="$($('#swiftstorage-panel')[0]).addClass('hidden');$($('#nfsstorage-panel')[0]).removeClass('hidden')">NFS
             %else:
                <input type="radio" name="backup_target_type" aria-describedby="backup_target_helpblock" value="NFS" onchange="$($('#swiftstorage-panel')[0]).addClass('hidden');$($('#nfsstorage-panel')[0]).removeClass('hidden')">NFS
             %end 
             </label>
             <label class="radio-inline">
             %if 'backup_target_type' in locals() and backup_target_type == 'SWIFT':
                <input type="radio" name="backup_target_type" aria-describedby="backup_target_helpblock" checked value="SWIFT" onchange="$($('#nfsstorage-panel')[0]).addClass('hidden');$($('#swiftstorage-panel')[0]).removeClass('hidden')">SWIFT
             %else:
                <input type="radio" name="backup_target_type" aria-describedby="backup_target_helpblock" value="SWIFT" onchange="$($('#nfsstorage-panel')[0]).addClass('hidden');$($('#swiftstorage-panel')[0]).removeClass('hidden')">SWIFT
             %end 
             </label>
             <span id="backup_target_helpblock" class="help-block">Choose the backend for storing backup images.</span> 

            %if 'backup_target_type' in locals() and backup_target_type == 'NFS':
	    <div class="panel-group" id="nfsstorage-panel">
             %else:
	    <div class="panel-group hidden" id="nfsstorage-panel">
             %end 
	       <div class="panel panel-default" id="panel3">
		<div class="panel-heading">
		  <h4 class="panel-title">
                     <a data-toggle="collapse" data-target="#collapseThree" href="#collapseThree"> NFS Storage </a>
		  </h4>
		</div>
		<div id="collapseThree" class="panel-collapse collapse in">
		  <div class="panel-body">
			<div class="form-group" >
		        <label class="control-label">NFS Export<i class="fa fa-spinner fa-spin hidden" id="nfs-spinner" style="font-size:20px"></i></label>
			<input name="storage-nfs-export" {{'value=' + storage_nfs_export if defined('storage_nfs_export') else ''}} id="storage-nfs-export" type="text" required placeholder="server:/var/nfs" class="form-control"  aria-describedby="nfs_helpblock" data-role="tagsinput">
                        <span id="nfs_helpblock" class="help-block">Please enter list of NFS shares separated by commas</span>
			</div>
                        <div class="form-group">
                        <label class="control-label">NFS Options<i class="fa fa-spinner fa-spin hidden" id="nfs-spinner" style="font-size:20px"></i></label>
                        <input name="storage-nfs-options" {{'value=' + storage_nfs_options if defined('storage_nfs_options') else ''}} id="storage-nfs-options" type="text" required placeholder="" class="form-control"  aria-describedby="nfs_options_helpblock" data-role="tagsinput">
                        <span id="nfs_options_helpblock" class="help-block">Please enter list of NFS options separated by commas</span>
                        </div>
		  </div>
		</div>
	      </div>
	    </div>

            %if 'backup_target_type' in locals() and backup_target_type == 'SWIFT':
            <div class="panel-group" id="swiftstorage-panel">
            %else:
            <div class="panel-group hidden" id="swiftstorage-panel">
            %end 
               <div class="panel panel-default" id="panel5">
                  <div class="panel-heading">
                     <h4 class="panel-title">
		        <a data-toggle="collapse" data-target="#collapseFive" href="#collapseFive"> Swift Object Storage </a>
		     </h4>
		  </div>
		  <div id="collapseFive" class="panel-collapse collapse in">
		     <div class="panel-body">
                       <div class="input-group">
                %if 'swift_auth_version' in locals() and swift_auth_version == 'TEMPAUTH':
                         <input name = "swift-auth-version" type="radio"  aria-describedby="swiftsel_helpblock" value="KEYSTONE" onchange="setSwiftRequired(this.checked, this.value);validate_swift_credentials(this)">  KEYSTONE &nbsp;&nbsp;
                         <input name = "swift-auth-version" type="radio"  aria-describedby="swiftsel_helpblock" value="TEMPAUTH" checked onchange="setSwiftRequired(this.checked, this.value)">  TEMPAUTH <br> <br>                       
                %elif 'swift_auth_version' in locals() and swift_auth_version == 'KEYSTONE':
                         <input name = "swift-auth-version" type="radio"  aria-describedby="swiftsel_helpblock" value="KEYSTONE" checked onchange="setSwiftRequired(this.checked, this.value);validate_swift_credentials(this)">  KEYSTONE &nbsp;&nbsp;
                         <input name = "swift-auth-version" type="radio"  aria-describedby="swiftsel_helpblock" value="TEMPAUTH" onchange="setSwiftRequired(this.checked, this.value)">  TEMPAUTH <br> <br>                                
                %else:
                         <input name = "swift-auth-version" type="radio"  aria-describedby="swiftsel_helpblock" value="KEYSTONE" checked onchange="setSwiftRequired(this.checked, this.value);validate_swift_credentials(this)">  KEYSTONE &nbsp;&nbsp;
                         <input name = "swift-auth-version" type="radio" aria-describedby="swiftsel_helpblock"  value="TEMPAUTH" onchange="setSwiftRequired(this.checked, this.value)">  TEMPAUTH <br> <br>      	
                %end 
                         <span id="swiftsel_helpblock" class="help-block hidden">A block of help text that breaks onto a new line and may extend beyond one line.</span> 
                       </div>
                       <div class="input-group" id="swift-auth-url-div">
                         <label class="control-label">Auth Url&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</label>
                         <input name="swift-auth-url" {{'value=' + swift_auth_url if (defined('swift_auth_url') and len(swift_auth_url)) else ''}} type="text" placeholder="" class="form-control"><br>
                       </div><br>
                       <div class="input-group" id="swift-username-div">
                          <label class="control-label">Username&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</label>
                          <input name="swift-username" {{'value=' + swift_username if (defined('swift_username') and len(swift_username)) else ''}} type="text" placeholder="" class="form-control"> <br>
                       </div><br>
                       <div class="input-group" id="swift-password-div">
                         <label class="control-label">Password&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp</label>
                         <input name="swift-password" type="password" class="form-control" aria-describedby="swifturl_helpblock" onblur="validate_swift_credentials(this)">
                         <span id="swifturl_helpblock" class="help-block hidden">A block of help text that breaks onto a new line and may extend beyond one line.</span>
                       </div><br>
	 	     </div>
		  </div>
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
    </div>
    </div>
    <div>
    <button type="submit" class="btn btn-lg btn-primary btn-block">Submit</button>
    </div>
  </form>

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

function validate_url_versions() {
   if ($( "input[name='keystone-admin-url']" )[0].value.split('v')[1] !=
       $( "input[name='keystone-public-url']" )[0].value.split('v')[1]) {
       $($($("input[name='keystone-public-url']")[0]).parent().find(".help-block")[0]).removeClass("hidden")
       $($("input[name='keystone-public-url']")[0]).parent().find(".help-block")[0].innerHTML = "Keystone URL versions don't match"
       $($($("input[name='keystone-public-url']")[0]).parent()).addClass("has-error")
       return false
   } else {
       $($($("input[name='keystone-public-url']")[0]).parent().find(".help-block")[0]).addClass("hidden")
       $($($("input[name='keystone-public-url']")[0]).parent()).removeClass("has-error")
   }
   return true
}

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
   })
}

function validate_keystone_credentials(inputelement) {
    if(inputelement.name == 'admin-tenant-name' && IsV3 == true)
       return

    if(inputelement.name == 'domain-name' && IsV3 == false)
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

function validate_swift_credentials(inputelement) {
    public_url = $('[name="keystone-public-url"]')[0].value
    project_name = $('[name="admin-tenant-name"]')[0].value
    username = $('[name="admin-username"]')[0].value
    password = $('[name="admin-password"]')[0].value
    domain_id = $('[name="domain-name"]')[0].value
    swift_auth_url = $('[name="swift-auth-url"]')[0].value
    swift_username = $('[name="swift-username"]')[0].value
    swift_password = $('[name="swift-password"]')[0].value
    obj = $("#configure_openstack input[name='swift-auth-version']:checked")
    swift_auth_version = obj.val()
    $.ajax({
        url: "validate_swift_credentials?public_url="+public_url+"&project_name="+project_name+"&username="+username+"&password="+password+"&domain_id="+domain_id+
              "&swift_auth_url="+swift_auth_url+"&swift_username="+swift_username+"&swift_password="+swift_password+"&swift_auth_version="+swift_auth_version,
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
        }
    });
}

/*$('[name="storage-nfs-options"]').tagsinput({
  allowDuplicates: true
});*/

$('[name="storage-nfs-export"]').on('itemAdded', function(event) {
//function validate_nfsshare(inputelement) {
//}
    //nfsshare = $('[name="storage-nfs-export"]')[0].value
    nfsshare = event.item
    inputelement = this
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
});

if ($('input:radio[name=nodetype]:checked').val() == "additional") {
    $("#panel4")[0].hidden=true
}

</script>
</body>
</html>
