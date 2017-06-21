<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN" "http://www.w3.org/TR/html4/loose.dtd">
<html>
<head>

<link rel="stylesheet" href="css/bootstrap.min.css">
<link rel="stylesheet" href="css/spinner.css">

<!-- Optional theme -->
<link rel="stylesheet" href="css/bootstrap-theme.min.css">

<script src="js/jquery-1.11.0.min.js"></script>
<!-- Latest compiled and minified JavaScript -->
<script src="js/bootstrap.min.js"></script>

<script>
var xmlhttp;
var ntp_note = "";
function redirectToConf(xmlhttp)
{
  if(xmlhttp.status==500 &&  xmlhttp.responseText =="Error"  )
 {
 window.location.href="/configure_form_vmware"
 return;
 }
}
function loadXMLDoc(url, callback)
{
        flag = $('#'+url).css('display')
        if (flag == 'block')
        {
          if (window.XMLHttpRequest)
          {// code for IE7+, Firefox, Chrome, Opera, Safari
             xmlhttp=new XMLHttpRequest();
          }
          else
          {// code for IE6, IE5
            xmlhttp=new ActiveXObject("Microsoft.XMLHTTP");
          }
          xmlhttp.onreadystatechange=callback;
          xmlhttp.open("GET",url,true);
          xmlhttp.send();
        }
        else
        {
          callback()
        }
}

function taskfunction()
{
	var r = confirm("Continuing will configure the appliance.\nWould you like to proceed?");
	if (r == false) {
		window.history.back()
		return
	}

	$("#alert").hide();
	document.getElementById("final_status").innerHTML = "Final Status";
   	loadXMLDoc("configure_host", function() {
   	   document.getElementById("configure_host").children[0].classList.add("glyphicon-refresh");
	   if (xmlhttp.readyState != 4) return;
	   document.getElementById("configure_host").children[0].classList.remove("glyphicon-refresh");
	   if (xmlhttp.readyState==4 && xmlhttp.status==200)
	   {
		  document.getElementById("configure_host").classList.add("list-group-item-success");
		  document.getElementById("configure_host").children[0].classList.add("glyphicon-ok");
	   }
	   else
	   {
		  return redirectToConf(xmlhttp);
	   }
	   // Call authenticate with keystone
	   loadXMLDoc("authenticate_with_vcenter", function() {
   	   	  document.getElementById("authenticate_with_vcenter").children[0].classList.add("glyphicon-refresh");
	      if (xmlhttp.readyState != 4) return;
	      document.getElementById("authenticate_with_vcenter").children[0].classList.remove("glyphicon-refresh");
	      if (xmlhttp.readyState != 4) return;
	      if (xmlhttp.readyState==4 && xmlhttp.status==200)
	      {
	         document.getElementById("authenticate_with_vcenter").classList.add("list-group-item-success");
	         document.getElementById("authenticate_with_vcenter").children[0].classList.add("glyphicon-ok");
	      }
	      else
	      {
			 return redirectToConf(xmlhttp);
	      }
		  // Call authenticate with swift
		  loadXMLDoc("authenticate_with_swift", function() {
		   	  document.getElementById("authenticate_with_swift").children[0].classList.add("glyphicon-refresh");
		      if (xmlhttp.readyState != 4) return;
		      document.getElementById("authenticate_with_swift").children[0].classList.remove("glyphicon-refresh");
		      if (xmlhttp.readyState != 4) return;
		      if (xmlhttp.readyState==4 && xmlhttp.status==200)
		      {
		         document.getElementById("authenticate_with_swift").classList.add("list-group-item-success");
		         document.getElementById("authenticate_with_swift").children[0].classList.add("glyphicon-ok");
		      }
		      else
		      {
				 return redirectToConf(xmlhttp);
		      }
			  // Call register_service api
			  loadXMLDoc("register_service", function() {
		   	   	 document.getElementById("register_service").children[0].classList.add("glyphicon-refresh");
		      	 if (xmlhttp.readyState != 4) return;
		      	 document.getElementById("register_service").children[0].classList.remove("glyphicon-refresh");
			     if (xmlhttp.readyState==4 && xmlhttp.status==200)
			     {
			        document.getElementById("register_service").classList.add("list-group-item-success");
			        document.getElementById("register_service").children[0].classList.add("glyphicon-ok");
			     }
			     else
			     {
				 	return redirectToConf(xmlhttp);
			     }
			     // Call configure_api
			     loadXMLDoc("configure_api",function() {
			   	   	document.getElementById("configure_api").children[0].classList.add("glyphicon-refresh");
			      	if (xmlhttp.readyState != 4) return;
			      	document.getElementById("configure_api").children[0].classList.remove("glyphicon-refresh");
			        if (xmlhttp.readyState==4 && xmlhttp.status==200)
			        {
			           document.getElementById("configure_api").classList.add("list-group-item-success");
			           document.getElementById("configure_api").children[0].classList.add("glyphicon-ok");
			        }
			        else
			        {
				 	   return redirectToConf(xmlhttp);
			        }
			        // Call configure_scheduler
			        loadXMLDoc("configure_scheduler",function() {
			   	   	   document.getElementById("configure_scheduler").children[0].classList.add("glyphicon-refresh");
			      	   if (xmlhttp.readyState != 4) return;
			      	   document.getElementById("configure_scheduler").children[0].classList.remove("glyphicon-refresh");
			           if (xmlhttp.readyState==4 && xmlhttp.status==200)
			           {
			              document.getElementById("configure_scheduler").classList.add("list-group-item-success");
			              document.getElementById("configure_scheduler").children[0].classList.add("glyphicon-ok");
			           }
			           else
			           {
				 		  return redirectToConf(xmlhttp);
			           }
			           // Call configure_service
			           loadXMLDoc("configure_service",function() {
			   	   	      document.getElementById("configure_service").children[0].classList.add("glyphicon-refresh");
			      	      if (xmlhttp.readyState != 4) return;
			      	      document.getElementById("configure_service").children[0].classList.remove("glyphicon-refresh");
			              if (xmlhttp.readyState==4 && xmlhttp.status==200)
			              {
			                 document.getElementById("configure_service").classList.add("list-group-item-success");
			                 document.getElementById("configure_service").children[0].classList.add("glyphicon-ok");
			              }
			              else
			              {
							 return redirectToConf(xmlhttp);
			              }
			              // Call start_api
			              loadXMLDoc("start_api",function() {
			   	   	         document.getElementById("start_api").children[0].classList.add("glyphicon-refresh");
			      	         if (xmlhttp.readyState != 4) return;
			      	         document.getElementById("start_api").children[0].classList.remove("glyphicon-refresh");
			                 if (xmlhttp.readyState==4 && xmlhttp.status==200)
			                 {
			                    document.getElementById("start_api").classList.add("list-group-item-success");
			                    document.getElementById("start_api").children[0].classList.add("glyphicon-ok");
			                 }
			                 else
			                 {
				 				return redirectToConf(xmlhttp);
			                 }
			                 // Call start_scheduler
			                 loadXMLDoc("start_scheduler",function() {
			   	   	            document.getElementById("start_scheduler").children[0].classList.add("glyphicon-refresh");
			      	            if (xmlhttp.readyState != 4) return;
			      	            document.getElementById("start_scheduler").children[0].classList.remove("glyphicon-refresh");
			                    if (xmlhttp.readyState==4 && xmlhttp.status==200)
			                    {
			                       document.getElementById("start_scheduler").classList.add("list-group-item-success");
			                       document.getElementById("start_scheduler").children[0].classList.add("glyphicon-ok");
			                    }
			                    else
			                    {
				 				  return redirectToConf(xmlhttp);
			                    }
			                    // Call start_service
			                    loadXMLDoc("start_service",function() {
									document.getElementById("start_service").children[0].classList.add("glyphicon-refresh");
									if (xmlhttp.readyState != 4) return;
									document.getElementById("start_service").children[0].classList.remove("glyphicon-refresh");
									if (xmlhttp.readyState==4 && xmlhttp.status==200)
									{
										document.getElementById("start_service").classList.add("list-group-item-success");
										document.getElementById("start_service").children[0].classList.add("glyphicon-ok");
									}
									else
									{
										return redirectToConf(xmlhttp);
									}
			                       	loadXMLDoc("register_workloadtypes",function() {
										document.getElementById("register_workloadtypes").children[0].classList.add("glyphicon-refresh");
										if (xmlhttp.readyState != 4) return;
										document.getElementById("register_workloadtypes").children[0].classList.remove("glyphicon-refresh");
										if (xmlhttp.readyState==4 && xmlhttp.status==200)
										{
											document.getElementById("register_workloadtypes").classList.add("list-group-item-success");
											document.getElementById("register_workloadtypes").children[0].classList.add("glyphicon-ok");
										}
										else
										{
											return redirectToConf(xmlhttp);
										}
				                       	loadXMLDoc("workloads_import",function() {
											document.getElementById("workloads_import").children[0].classList.add("glyphicon-refresh");
											if (xmlhttp.readyState != 4) return;
											document.getElementById("workloads_import").children[0].classList.remove("glyphicon-refresh");
											if (xmlhttp.readyState==4 && xmlhttp.status==200)
											{
												document.getElementById("workloads_import").classList.add("list-group-item-success");
												document.getElementById("workloads_import").children[0].classList.add("glyphicon-ok");
											}
											else
											{
												return redirectToConf(xmlhttp);
											}
					                       	loadXMLDoc("discover_vcenter",function() {
												document.getElementById("discover_vcenter").children[0].classList.add("glyphicon-refresh");
												if (xmlhttp.readyState != 4) return;
												document.getElementById("discover_vcenter").children[0].classList.remove("glyphicon-refresh");
												if (xmlhttp.readyState==4 && xmlhttp.status==200)
												{
													document.getElementById("discover_vcenter").classList.add("list-group-item-success");
													document.getElementById("discover_vcenter").children[0].classList.add("glyphicon-ok");
												}
												else
												{
													return redirectToConf(xmlhttp);
												}

                                  //ntp code

						                   });
						               });
					           	   });
		                       });
		                    });
		                 });
		              });
		           });
		        });
		     });
		  });
	   });
	});
}

$( document ).ready(function() {
    taskfunction();
});

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
  <div class="panel-heading">Configuring TrilioVault Appliance </div>
  <!-- List group -->
  <ul class="list-group">
    <li id="configure_host" class="list-group-item"><span class="glyphicon"></span>
                Configuring TrilioVault host</li>
    <li id="authenticate_with_vcenter" class="list-group-item"><span class="glyphicon"></span>
                Authenticating with vCenter</li>
	%if 'swift_auth_url' in locals() and len(swift_auth_url) > 0:
    	<li id="authenticate_with_swift" class="list-group-item"><span class="glyphicon"></span>
                Authenticating with Swift Object Store</li>
	%else:
    	<li id="authenticate_with_swift" class="list-group-item" style="display:None"><span class="glyphicon"></span>
                Authenticating with Swift Object Store</li>
    %end
    <li id="register_service" class="list-group-item"><span class="glyphicon"></span>
                Registering TrilioVault service</li>
    <li id="configure_api" class="list-group-item"><span class="glyphicon"></span>
                Configuring TrilioVault API service</li>
    <li id="configure_scheduler" class="list-group-item"><span class="glyphicon"></span>
                Configuring TrilioVault scheduler service </li>
    <li id="configure_service" class="list-group-item"><span class="glyphicon"></span>
                Configuring TrilioVault service </li>
    <li id="start_api" class="list-group-item"><span class="glyphicon"></span>
                Starting TrilioVault API service</li>
    <li id="start_scheduler" class="list-group-item"><span class="glyphicon"></span>
                Starting TrilioVault scheduler service</li>
    <li id="start_service" class="list-group-item"><span class="glyphicon"></span>
                Starting TrilioVault service</li>
    <li id="register_workloadtypes" class="list-group-item"><span class="glyphicon"></span>
                Registering workload types</li>
	%if 'import_workloads' in locals() and import_workloads == 'on':
    	<li id="workloads_import" class="list-group-item"><span class="glyphicon"></span>
                Importing workloads</li>
	%else:
    	<li id="workloads_import" class="list-group-item" style="display:None"><span class="glyphicon"></span>
                Importing workloads</li>
    %end
    <li id="discover_vcenter" class="list-group-item"><span class="glyphicon"></span>
                Discover vCenter inventory</li>
     %#if 'ntp_enabled' in locals() and ntp_enabled == 'on':
        <li id="ntp_setup" class="list-group-item"><span class="glyphicon"></span>
        NTP setup</li>
    %#else:
        <li id="ntp_setup" class="list-group-item" style="display:None"><span class="glyphicon"></span>
        NTP setup</li>
    %#end
    <li id="final_status" class="list-group-item"><span class="glyphicon"></span>
                Final Status</li>
  </ul>
  <div id="alert" class="alert alert-danger" role="alert" style="display:none">
	  <p id="error_message"> Error Message </p>
  </div>
</div>

</body>
</html>
