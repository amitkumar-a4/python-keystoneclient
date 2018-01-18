<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN" "http://www.w3.org/TR/html4/loose.dtd">
<html>
<head>
<!-- Latest compiled and minified CSS -->
<link rel="stylesheet" href="css/bootstrap.min.css">

<!-- Optional theme -->
<link rel="stylesheet" href="css/bootstrap-theme.min.css">
<link rel="stylesheet" href="css/font-awesome.min.css">
<link rel="stylesheet" href="css/bootstrap-tagsinput.css">

<!-- CSS Files -->
<link href="css/paper-bootstrap-wizard.css" rel="stylesheet" />

<!-- Fonts and Icons -->
<link href="css/themify-icons.css" rel="stylesheet">

<!--   Core JS Files   -->
<script src="js/jquery-2.2.4.min.js" type="text/javascript"></script>
<script src="js/bootstrap.min.js" type="text/javascript"></script>
<script src="js/jquery.bootstrap.wizard.js" type="text/javascript"></script>
<script src="js/passwordvalidation.js"></script>

<!--  Plugin for the Wizard -->
<script src="js/paper-bootstrap-wizard.js" type="text/javascript"></script>

<!--  More information about jquery.validate here: http://jqueryvalidation.org/     -->
<script src="js/jquery.validate.min.js" type="text/javascript"></script>

<script src="js/bootstrap-tagsinput.min.js"></script>

<style>
.bootstrap-tagsinput > span {
text-transform: initial;
}
</style>

<script type="text/javascript">
IsV3 = false
Invalid = true
function validate_swift_credentials(inputelement) {
    public_url = $('[name="keystone-public-url"]')[0].value
    project_name = $('[name="admin-tenant-name"]')[0].value
    username = $('[name="admin-username"]')[0].value
    password = $('[name="admin-password"]')[0].value
    domain_id = $('[name="domain-name"]')[0].value
    region_name = $('[name="region-name"]')[0].value
    swift_auth_url = $('[name="swift-auth-url"]')[0].value
    swift_username = $('[name="swift-username"]')[0].value
    swift_password = $('[name="swift-password"]')[0].value
    obj = $("#configure_openstack input[name='swift-auth-version']:checked")
    inputelement = obj
    /*if (inputelement.name != 'swift-auth-version' || inputelement == 'custom') {
       inputelement = obj
    }*/
    swift_auth_version = obj.val()
    $.ajax({
        url: "validate_swift_credentials?public_url="+public_url+"&project_name="+project_name+"&username="+username+"&password="+password+"&domain_id="+domain_id+
             "&swift_auth_url="+swift_auth_url+"&swift_username="+swift_username+"&swift_password="+swift_password+"&region_name="+region_name+
             "&swift_auth_version="+swift_auth_version+"&keystone_auth_version="+IsV3,
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
           Invalid = false
           $('[name="next"]').trigger( "click" );
        }
    });
}


function setRequired() {
    if(IsV3) {
       $('[name="domain-name"]').attr("required", "true");
    }
    else {
         $('[name="domain-name"]').removeAttr('required')
    }
}
function findForm() {
  hideshowstorages()
}

function hideshowstorages() {
  backup_target_type = $('[name="backup_target_type"]:checked').val()
  if (typeof backup_target_type == "undefined") {
     $($('#swiftstorage-panel')[0]).addClass('hidden');
     $($('#nfsstorage-panel')[0]).addClass('hidden');
  }
  if (backup_target_type == 'NFS') {
     $($('#swiftstorage-panel')[0]).addClass('hidden');$($('#nfsstorage-panel')[0]).removeClass('hidden');
     setSwiftRequired(true, 'NFS')
  }
  if (backup_target_type == 'SWIFT') {
     $($('#nfsstorage-panel')[0]).addClass('hidden');$($('#swiftstorage-panel')[0]).removeClass('hidden');
     obj = $("#configure_openstack input[name='swift-auth-version']:checked")
     setSwiftRequired(obj.attr('checked'), obj.val())
     //validate_swift_credentials('custom')
  }
}

function setSwiftRequired(checked, val) {
     storage_nfs_export  = $('#storage-nfs-export').val()
     val_length = storage_nfs_export.split(",").length
     if (val == "decide") {
         obj = $("#configure_openstack input[name='swift-auth-version']:checked")
         if (typeof obj == "undefined") {
             $('[placeholder="server:/var/nfs"]').first().removeAttr('required')
             return
         }
         val = obj.val()
     }
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
       $('[placeholder="server:/var/nfs"]').first().removeAttr('required')
     }
     else {
       if(storage_nfs_export == "")
         $('[placeholder="server:/var/nfs"]').first().attr("required", "true");
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
      <a class="navbar-brand" href="#"><img src="images/triliodata-144x36.png" alt="Trilio Data, Inc" height="32" width="134"></a>
    </div>
    <div id="bs-example-navbar-collapse-3" class="collapse navbar-collapse navbar-right">
       <button class="btn btn-default navbar-btn" type="button" onClick="parent.location='/logout'">Sign Out</button>
    </div>
  </div><!-- /.container-fluid -->
</nav>

<div style="text-align:left;margin-left:auto; margin-right:auto;">
  <!-- Default panel contents -->
  % if len(error_message) > 0:
	  	<div class="alert alert-danger alert-dismissible" role="alert">
		  <button type="button" class="close" data-dismiss="alert">
		  <span aria-hidden="true">&times;</span><span class="sr-only">Close</span></button>
		  <strong>{{error_message}}</strong>
 		</div>
  % end
  <div style="margin-left:auto; margin-right:auto;">
  <div ><!--role="form"  id="configure_openstack" class="form-configure" action="/configure_openstack" method="post"-->  <!-- form-->
    <div class="image-container set-full-height" style="background-image: url('images/triliobackground.png')">

        <!--   Big container   -->
        <div class="container">
            <div class="row">
                <div class="col-sm-8 col-sm-offset-1">

                    <!--      Wizard container        -->
                    <div class="wizard-container">
                        <div class="card wizard-card" data-color="green" id="wizard">
                        <form role="form"  id="configure_openstack" class="form-configure" action="/configure_openstack" method="post">  <!-- form-->
                        <!--        You can switch " data-color="green" "  with one of the next bright colors: "blue", "azure", "orange", "red"       -->

                                <div class="wizard-header">
                                    <h3 class="wizard-title"><img src="images/triliovault.png" width="200" height="25"> Configuration</h3>
                                    <p class="category">Please enter all the information to configure the appliance.</p>
                                </div>
                                <div class="wizard-navigation">
                                    <div class="progress-with-circle">
                                        <div class="progress-bar" role="progressbar" aria-valuenow="1" aria-valuemin="1" aria-valuemax="4" style="width: 15%;"></div>
                                    </div>
                                    <ul>
                                        <li>
                                            <a href="#triliovault" data-toggle="tab">
                                                <div class="icon-circle">
                                                    <i class="ti-view-list"></i>
                                                </div>
                                                TrilioVault
                                            </a>
                                        </li>
                                        <li>
                                            <a href="#oscredentials" data-toggle="tab">
                                                <div class="icon-circle">
                                                    <i class="ti-lock"></i>
                                                </div>
                                                OpenStack Credentials
                                            </a>
                                        </li>
                                        <li>
                                            <a href="#triliovaultcredentials" data-toggle="tab">
                                                <div class="icon-circle">
                                                    <i class="ti-ticket"></i>
                                                </div>
                                                TrilioVault Trustee Role
                                            </a>
                                        </li>
                                        <li>
                                            <a href="#ntpservers" data-toggle="tab">
                                                <div class="icon-circle">
                                                    <i class="ti-timer"></i>
                                                </div>
                                                NTP Servers
                                            </a>
                                        </li>
                                        <li>
                                            <a href="#storage" data-toggle="tab">
                                                <div class="icon-circle">
                                                    <i class="ti-server"></i>
                                                </div>
                                                Backend Storage
                                            </a>
                                        </li>
                                        <li id='import-tab'>
                                            <a href="#import" data-toggle="tab">
                                                <div class="icon-circle">
                                                    <i class="ti-download"></i>
                                                </div>
                                                Import Workloads
                                            </a>
                                        </li>
                                        <li id='certificate-tab'>
                                            <a href="#certificate" data-toggle="tab">
                                                <div class="icon-circle">
                                                    <i class="ti-key"></i>
                                                </div>
                                                Certificate
                                            </a>
                                        </li>
                                    </ul>
                                </div><br>
                                <div class="tab-content">
                                    <div class="tab-pane" id="triliovault">
                                        <div class="row">
                                            <div class="col-sm-12">
                                                <h5 class="info-text"> Let's start with TrilioVault configuration</h5>
                                            </div>
                                            <div class="col-sm-12">
                                                <div class="form-group">
	                                        %if 'nodetype' in locals() and nodetype == 'additional':
		                                    <input name = "nodetype" type="radio"  value="controller" onclick='$("#import-tab")[0].style.display="";$("#certificate-tab")[0].style.display="";$("#import")[0].style.display="";$("#certificate")[0].style.display=""';>  Controller Node
		                                    <input name = "nodetype" type="radio"  value="additional" checked onclick='$("#import-tab")[0].style.display="none";$("#certificate-tab")[0].style.display="none";$("#import")[0].style.display="none";$("#certificate")[0].style.display="none";'>   Additional Node <br><br>
	                                        %else:
		                                    <input name = "nodetype" type="radio"  value="controller" checked onclick='$("#import-tab")[0].style.display="";$("#certificate-tab")[0].style.display="";$("#import")[0].style.display="";$("#certificate")[0].style.display=""'>  Controller Node
		                                    <input name = "nodetype" type="radio"  value="additional" onclick='$("#import-tab")[0].style.display="none";$("#certificate-tab")[0].style.display="none";$("#import")[0].style.display="none";$("#certificate")[0].style.display="none";'>   Additional Node <br><br>
	                                        %end  
                                                </div>
                                            </div>
                                            <div class="col-sm-5">
                                                <div class="form-group">
    	                                            <label class="control-label">TrilioVault Controller IP Address<i class="fa fa-spinner fa-spin hidden" id="floatingip-spinner" style="font-size:15px"></i></label>
    	                                            <input name="floating-ipaddress" {{'value=' + floating_ipaddress if defined('floating_ipaddress') else ''}} type="text" required="" placeholder="192.168.2.200" class="form-control">
                                                </div>
                                            </div>
                                            <div class="col-sm-5">
                                                <div class="form-group">
                                                    <label class="control-label">Hostname</label>
                                                    <input name="guest-name" {{'value=' + guest_name if defined('guest_name') else ''}} type="text" required="" placeholder="Hostname" class="form-control">
                                                </div>
                                            </div>
                                            <div class="col-sm-5">
                                                <div class="form-group" >
	                                            <label class="control-label">Name Server</label>
	                                            <input name="name-server" {{'value=' + name_server if (defined('name_server') and len(name_server)) else ''}} type="text" placeholder="192.168.2.1" class="form-control">
                                                </div>
                                            </div>
                                            <div class="col-sm-5">
                                                <div class="form-group" >
	                                            <label class="control-label">Domain Search Order</label>
	                                            <input name="domain-search-order" {{'value=' + domain_search_order if (defined('domain_search_order') and len(domain_search_order)) else ''}} type="text" placeholder="example.com example.net" class="form-control">
                                                 </div>
                                            </div>
                                        </div>
                                    </div>
                                    <div class="tab-pane" id="oscredentials">
                                        <h5 class="info-text"> OpenStack Credentials </h5>
                                        <div class="row">
                                            <div class="col-sm-12">
                                                <div class="col-sm-5">
                                                    <div class="form-group">
    	                                                <label class="control-label">Keystone Admin Url<i class="fa fa-spinner fa-spin hidden" id="adminurl-spinner" style="font-size:15px"></i></label>
    	                                                <input name="keystone-admin-url" {{'value=' + keystone_admin_url if defined('keystone_admin_url') else ''}} onblur='setRequired(this.value);' type="text" required="" placeholder="http://keystonehost:35357/v2.0" class="form-control" aria-describedby="adminurl_helpblock">
                                                        <span id="adminurl_helpblock" class="help-block hidden">A block of help text that breaks onto a new line and may extend beyond one line.</span>
                                                    </div>
                                                </div>
                                                <div class="col-sm-5">
                                                    <div class="form-group">
    	                                                <label class="control-label">Keystone Url (Public/Internal)<i class="fa fa-spinner fa-spin hidden" id="publicurl-spinner" style="font-size:15px"></i></label>
    	                                                <input name="keystone-public-url" {{'value=' + keystone_public_url if defined('keystone_public_url') else ''}} onblur='setRequired(this.value);' type="text" required="" placeholder="http://keystonehost:5000/v2.0" class="form-control" aria-describedby="publicurl_helpblock">
                                                        <span id="publicurl_helpblock" class="help-block hidden">A block of help text that breaks onto a new line and may extend beyond one line.</span>
                                                    </div>
                                                </div>
                                                <div class="col-sm-5">
                                                    <div class="form-group">
    	                                                <label class="control-label">Administrator</label>
    	                                                <input name="admin-username" {{'value=' + admin_username if defined('admin_username') else ''}} type="text" required="" placeholder="admin" class="form-control"> 
                                                    </div>
                                                </div>
                                                <div class="col-sm-5">
                                                    <div class="form-group">
    	                                                <label class="control-label">Password</label>
    	                                                <input name="admin-password" type="password" required="" placeholder="" class="form-control">
                                                    </div>
                                                </div>
                                                <div class="col-sm-5">
    	                                            <div class="form-group">
    	                                                <label class="control-label">Admin Tenant<i class="fa fa-spinner fa-spin hidden" id="password-spinner" style="font-size:15px"></i></label>
    	                                                <input name="admin-tenant-name" {{'value=' + admin_tenant_name if defined('admin_tenant_name') else ''}} type="text" required="" placeholder="admin" class="form-control" onblur=''  aria-describedby="cred_helpblock">
                                                        <span id="cred_helpblock" class="help-block hidden">A block of help text that breaks onto a new line and may extend beyond one line.</span>
                                                    </div>
                                                </div>
                                                <div class="col-sm-5">
                                                    <div class="form-group">
    	                                                <label class="control-label">Region</label>
    	                                                <input name="region-name" {{'value=' + region_name if defined('region_name') else ''}} type="text" required="" placeholder="RegionOne" class="form-control">
                                                    </div>
                                                </div>
                                                <div class="col-sm-5">
                                                    <div class="form-group">
                                                        <label class="control-label">Domain ID</label>
                                                        <input name="domain-name" {{'value=' + domain_name if defined('domain_name') else ''}} type="text" placeholder="default" class="form-control" onblur=''>
                                                        <span id="cred_helpblock" class="help-block hidden">A block of help text that breaks onto a new line and may extend beyond one line.</span>
                                                    </div>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                    <div class="tab-pane" id="triliovaultcredentials">
                                        <h5 class="info-text"> TrilioVault Trustee Role </h5>
                                        <div class="row">
                                            <!--div class="col-sm-12">
                                                <div class="col-sm-5">
                                                    <div class="form-group">
    	                                                <label class="control-label">Password</label>
    	                                                <input id='newpassword' name="triliovault-password1" type="password" required="" placeholder="" class="form-control" onkeyup="validatestrongpassword(); return false;">
                                                    </div>
                                                </div>
                                                <div class="col-sm-5">
                                                    <div class="form-group">
    	                                                <label class="control-label">Retype Password</label>
    	                                                <input id='confirmpassword' name="triliovault-password2" type="password" required="" placeholder="" class="form-control" onkeyup="validatepasswords(); return false;">
                                                    </div>
                                                </div>
                                            </div-->
                                            <div class="col-sm-12">
                                            <div class="col-sm-5">
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
                                            </div>
                                            </div>
                                            <div class="col-sm-12">
                                                <span id="confirmMessage" class="confirmMessage"></span>
                                            </div>
                                        </div>
                                    </div>
                                    <div class="tab-pane" id="ntpservers">
                                        <h5 class="info-text">Tell us more about NTP servers. </h5>
                                        <div class="row">
                                            <div class="col-sm-12">
	                                        <div class="form-group">
			                            %if 'ntp_enabled' in locals() and ntp_enabled == 'on':
				                        <input name="ntp-enabled" checked id="ntp-enabled" type="checkbox"> NTP <span style="font-size:11px;">(List ntp servers separated by comma) </span>
			                            %else:
				                        <input name="ntp-enabled" id="ntp-enabled" type="checkbox"> NTP <span style="font-size:11px">(List ntp servers separated by comma) </span>
			                            %end
	                                        </div>
                                            </div>
                                            <div class="col-sm-5">
		                                <div class="form-group" >
			                            <label class="control-label">NTP servers</label>
			                            %if 'ntp_servers' in locals():
			                               <input name="ntp-servers" value="{{locals()['ntp_servers']}}" id="ntp-servers" type="text" placeholder="0.pool.ntp.org,1.pool.ntp.org" class="form-control" />
                                                    %else:
			                               <input name="ntp-servers" id="ntp-servers" value="" type="text" placeholder="0.pool.ntp.org,1.pool.ntp.org" class="form-control" />
                                                    %end
		                                </div>
		                            </div>
                                            <div class="col-sm-5">
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
                                    <div class="tab-pane" id="storage">
                                        <div class="row">
                                            <h5 class="info-text"> Enter backup storage details. </h5>
                                            <div class="col-sm-12">
                                                <label class="radio-inline">
                                                %if 'backup_target_type' in locals() and backup_target_type == 'NFS':
                                                    <input type="radio" name="backup_target_type" aria-describedby="backup_target_helpblock" checked value="NFS" onchange="$($('#swiftstorage-panel')[0]).addClass('hidden');$($('#nfsstorage-panel')[0]).removeClass('hidden');" onclick="setSwiftRequired(true, 'NFS')">NFS
                                                %else:
                                                    <input type="radio" name="backup_target_type" aria-describedby="backup_target_helpblock" value="NFS" onchange="$($('#swiftstorage-panel')[0]).addClass('hidden');$($('#nfsstorage-panel')[0]).removeClass('hidden');" onclick="setSwiftRequired(true, 'NFS')" required>NFS
                                                %end 
                                                </label>
                                                <label class="radio-inline">
                                                %if 'backup_target_type' in locals() and backup_target_type == 'SWIFT':
                                                    <input type="radio" name="backup_target_type" aria-describedby="backup_target_helpblock"  checked value="SWIFT" onchange="$($('#nfsstorage-panel')[0]).addClass('hidden');$($('#swiftstorage-panel')[0]).removeClass('hidden');" onclick="setSwiftRequired(true, 'decide');">SWIFT
                                                %else:
                                                    <input type="radio" name="backup_target_type" aria-describedby="backup_target_helpblock" value="SWIFT" onchange="$($('#nfsstorage-panel')[0]).addClass('hidden');$($('#swiftstorage-panel')[0]).removeClass('hidden');" onclick="setSwiftRequired(true, 'decide');">SWIFT
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
		                                                  <label class="control-label">NFS Export<i class="fa fa-spinner fa-spin hidden" id="nfs-spinner" style="font-size:15px"></i></label>
			                                          <input name="storage-nfs-export" {{'value='+storage_nfs_export if (defined('storage_nfs_export') and len(storage_nfs_export)) else ''}} id="storage-nfs-export" type="text" placeholder="server:/var/nfs" class="form-control"  aria-describedby="nfs_helpblock" data-role="tagsinput">
                                                                  <span id="nfs_helpblock" class="help-block">Please enter list of NFS shares separated by commas</span>
			                                      </div>
                                                              <div class="form-group">
                                                                  <label class="control-label">NFS Options<i class="fa fa-spinner fa-spin hidden" id="nfs-spinner" style="font-size:15px"></i></label>
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
                                                                    <input name = "swift-auth-version" type="radio"  aria-describedby="swiftsel_helpblock" value="KEYSTONE" onchange="setSwiftRequired(this.checked, this.value);">  KEYSTONE &nbsp;&nbsp;
                                                                    <input name = "swift-auth-version" type="radio"  aria-describedby="swiftsel_helpblock" value="TEMPAUTH" checked onchange="setSwiftRequired(this.checked, this.value)">  TEMPAUTH <br> <br>                       
                                                                    %elif 'swift_auth_version' in locals() and swift_auth_version == 'KEYSTONE':
                                                                    <input name = "swift-auth-version" type="radio"  aria-describedby="swiftsel_helpblock" value="KEYSTONE" checked onchange="setSwiftRequired(this.checked, this.value);">  KEYSTONE &nbsp;&nbsp;
                                                                    <input name = "swift-auth-version" type="radio"  aria-describedby="swiftsel_helpblock" value="TEMPAUTH" onchange="setSwiftRequired(this.checked, this.value)">  TEMPAUTH <br> <br>                                
                                                                    %else:
                                                                    <input name = "swift-auth-version" type="radio"  aria-describedby="swiftsel_helpblock" value="KEYSTONE" checked onchange="setSwiftRequired(this.checked, this.value);">  KEYSTONE &nbsp;&nbsp;
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
                                                                     <input name="swift-password" type="password" class="form-control" aria-describedby="swifturl_helpblock" onblur="">
                                                                     <span id="swifturl_helpblock" class="help-block hidden">A block of help text that breaks onto a new line and may extend beyond one line.</span>
                                                                 </div><br>
	 	                                             </div>
		                                        </div>
	                                            </div>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                    <div class="tab-pane" id="import">
                                        <div class="row">
                                            <h5 class="info-text"> Import Workloads </h5>
                                            <div class="col-sm-12">
                                                <div id="collapseFour" class="panel-collapse collapse in">
                                                  <div class="panel-body">
                                                      <div class="form-group">
                                                        %if 'workloads_import' in locals() and workloads_import == 'on':
                                                            <input name="workloads-import" checked id="workloads-import" type="checkbox"> Import workloads metadata from backup media. <span style="font-size:11px;">Choose this option if you are upgrading TrilioVault VM.</span>
                                                        %else:
                                                            <a data-toggle="collapse" data-target="#collapseFour" href="#collapseFour"> Import Workloads </a>
                                                      </div>
                                                  </div>
                                                </div>
                                            </div>
                                            <div class="col-sm-12">
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
                                    <div class="tab-pane" id="certificate">
                                        <div class="row">
                                            <div class="col-sm-12">
                                                <div id="collapseFour" class="panel-collapse collapse in">
                                                  <div class="panel-body">
                                                      <div class="form-group">
                                                        %if 'enable_tls' in locals() and enable_tls == 'on':
                                                             <input name="enable_tls" checked id="enable_tls" checked type="checkbox"> Enable TLS. <span style="font-size:11px;">Choose this option if you are enabling TLS endpoint.</span>
                                                             <div class="form-group" id='cert-group'><br>
                                                                 <label for="cert">Certificate:</label>
                                                                 <textarea name='cert' class="form-control" required rows="5" id="cert">{{cert}}</textarea>
                                                               </div>
                                                             <div class="form-group" id='privatekey-group'>
                                                                 <label for="privatekey">Private Key:</label>
                                                                 <textarea name='privatekey' class="form-control" required rows="5" id="privatekey">{{privatekey}}</textarea>
                                                             </div>
                                                        %else:
                                                             <input name="enable_tls" id="enable_tls" type="checkbox"> Enable TLS. <span style="font-size:11px;">Choose this option if you are enabling TLS endpoint.</span>
                                                             <div class="form-group disabled" id='cert-group'><br>
                                                                 <label for="cert">Certificate:</label>
                                                                 <textarea name='cert' class="form-control" required rows="5" id="cert"></textarea>
                                                               </div>
                                                             <div class="form-group disabled" id='privatekey-group'>
                                                                 <label for="privatekey">Private Key:</label>
                                                                 <textarea name='privatekey' class="form-control" required rows="5" id="privatekey"></textarea>
                                                             </div>
                                                        %end
                                                      </div>
                                                      <br />
                                                  </div>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                                <div class="wizard-footer">
                                    <div class="pull-right">
                                        <input type='button' class='btn btn-next btn-fill btn-success btn-wd' name='next' value='Next' />
                                        <input type='submit' class='btn btn-finish btn-fill btn-success btn-wd' name='finish' value='Finish' />
                                    </div>

                                    <div class="pull-left">
                                        <input type='button' class='btn btn-previous btn-default btn-wd' name='previous' value='Previous' />
                                    </div>
                                    <div class="clearfix"></div>
                                </div>
                             </div>
                            </div>  <!--form-->
                        </div>
                    </div> <!-- wizard container -->
                </div>
            </div> <!-- row -->
        </div> <!--  big container -->
    </div>
  </form>

<script>
//$(document).ready(function(){
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

$('#enable_tls').click(function(){
if($(this).is(':checked'))
{
    $('#cert-group').removeClass('disabled')
    $('#privatekey-group').removeClass('disabled')
}
else
{
    $('#cert-group').addClass('disabled')
    $('#privatekey-group').addClass('disabled')
}
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
           IsV3 = false
           if(result.keystone_version == 'v3') {
              IsV3 = true
           }
           setRequired()
           $.each(result.roles, function( index, value ) {
               options += "<option value="+ value +" selected>"+ value + "</option>"
           });
           document.getElementsByName("trustee-role")[0].innerHTML = options
           Invalid = false
           $('[name="next"]').trigger( "click" );
        }
    });
}

/*$('[name="storage-nfs-options"]').tagsinput({
  allowDuplicates: true
});*/

$('[name="storage-nfs-export"]').on('itemRemoved', function(event) {
  storage_nfs_export = $('#storage-nfs-export').val()
  val_length = storage_nfs_export.split(",").length
  if(val_length >= 1 && storage_nfs_export != "") {
      $('[placeholder="server:/var/nfs"]').first().removeAttr('required')
  }
  if(storage_nfs_export == "") {
    $('[placeholder="server:/var/nfs"]').first().attr("required", "true");
  }
});

$('[name="storage-nfs-export"]').on('itemAdded', function(event) {
//function validate_nfsshare(inputelement) {
//}
    //nfsshare = $('[name="storage-nfs-export"]')[0].value
    storage_nfs_export = $('#storage-nfs-export').val()
    val_length = storage_nfs_export.split(",").length
    if(val_length >= 1 && storage_nfs_export != "") {
      $('[placeholder="server:/var/nfs"]').first().removeAttr('required')
    }
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
    //$("#panel4")[0].hidden=true
}
//});
</script>
</body>
</html>
