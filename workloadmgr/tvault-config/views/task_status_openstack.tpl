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
function loadXMLDoc(url, callback)
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

function taskfunction()
{
	$("#alert").hide();
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
		  $("#error_message").html(xmlhttp.responseText);
		  $("#alert").show();
		  document.getElementById("configure_host").classList.add("list-group-item-danger");
		  document.getElementById("configure_host").children[0].classList.add("glyphicon-remove");
		  document.getElementById("final_status").classList.add("list-group-item-danger");
		  document.getElementById("final_status").children[0].classList.add("glyphicon-remove");
		  return;
	   }
	   // Call authenticate with keystone
	   loadXMLDoc("authenticate_with_keystone", function() {
   	   	  document.getElementById("authenticate_with_keystone").children[0].classList.add("glyphicon-refresh");
	      if (xmlhttp.readyState != 4) return;
	      document.getElementById("authenticate_with_keystone").children[0].classList.remove("glyphicon-refresh");
	      if (xmlhttp.readyState != 4) return;
	      if (xmlhttp.readyState==4 && xmlhttp.status==200)
	      {
	         document.getElementById("authenticate_with_keystone").classList.add("list-group-item-success");
	         document.getElementById("authenticate_with_keystone").children[0].classList.add("glyphicon-ok");
	      }
	      else
	      {
			 //$("#error_message").html(xmlhttp.responseText);
			 $("#error_message").html(xmlhttp.responseText);
			 $("#alert").show();	      
	         document.getElementById("authenticate_with_keystone").classList.add("list-group-item-danger");
	         document.getElementById("authenticate_with_keystone").children[0].classList.add("glyphicon-remove");
	         document.getElementById("final_status").classList.add("list-group-item-danger");
	         document.getElementById("final_status").children[0].classList.add("glyphicon-remove");
	         return;
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
			 	$("#error_message").html(xmlhttp.responseText);
			 	$("#alert").show();		     
		        document.getElementById("register_service").classList.add("list-group-item-danger");
		        document.getElementById("register_service").children[0].classList.add("glyphicon-remove");
		        document.getElementById("final_status").classList.add("list-group-item-danger");
		        document.getElementById("final_status").children[0].classList.add("glyphicon-remove");
		        return;
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
			 	   $("#error_message").html(xmlhttp.responseText);
			 	   $("#alert").show();		        
		           document.getElementById("configure_api").classList.add("list-group-item-danger");
		           document.getElementById("configure_api").children[0].classList.add("glyphicon-remove");
		           document.getElementById("final_status").classList.add("list-group-item-danger");
		           document.getElementById("final_status").children[0].classList.add("glyphicon-remove");
		           return;
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
			 		  $("#error_message").html(xmlhttp.responseText);
			 		  $("#alert").show();		           
		              document.getElementById("configure_scheduler").classList.add("list-group-item-danger");
		              document.getElementById("configure_scheduler").children[0].classList.add("glyphicon-remove");
		              document.getElementById("final_status").classList.add("list-group-item-danger");
		              document.getElementById("final_status").children[0].classList.add("glyphicon-remove");
		              return;
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
						 $("#error_message").html(xmlhttp.responseText);
						 $("#alert").show();		              
		                 document.getElementById("configure_service").classList.add("list-group-item-danger");
		                 document.getElementById("configure_service").children[0].classList.add("glyphicon-remove");
		                 document.getElementById("final_status").classList.add("list-group-item-danger");
		                 document.getElementById("final_status").children[0].classList.add("glyphicon-remove");
		                 return;
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
			 				$("#error_message").html(xmlhttp.responseText);
			 				$("#alert").show();		                 
		                    document.getElementById("start_api").classList.add("list-group-item-danger");
		                    document.getElementById("start_api").children[0].classList.add("glyphicon-remove");
		                    document.getElementById("final_status").classList.add("list-group-item-danger");
		                    document.getElementById("final_status").children[0].classList.add("glyphicon-remove");
		                    return;
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
			 				   $("#error_message").html(xmlhttp.responseText);
			 				   $("#alert").show();		                    
		                       document.getElementById("start_scheduler").classList.add("list-group-item-danger");
		                       document.getElementById("start_scheduler").children[0].classList.add("glyphicon-remove");
		                       document.getElementById("final_status").classList.add("list-group-item-danger");
		                       document.getElementById("final_status").children[0].classList.add("glyphicon-remove");
		                       return;
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
								  $("#error_message").html(xmlhttp.responseText);
								  $("#alert").show();		                       
		                          document.getElementById("start_service").classList.add("list-group-item-danger");
		                          document.getElementById("start_service").children[0].classList.add("glyphicon-remove");
		                          document.getElementById("final_status").classList.add("list-group-item-danger");
		                          document.getElementById("final_status").children[0].classList.add("glyphicon-remove");
		                          return;
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
			 						 $("#error_message").html(xmlhttp.responseText);
			 						 $("#alert").show();		                          
		                             document.getElementById("register_workloadtypes").classList.add("list-group-item-danger");
		                             document.getElementById("register_workloadtypes").children[0].classList.add("glyphicon-remove");
		                             document.getElementById("final_status").classList.add("list-group-item-danger");
		                             document.getElementById("final_status").children[0].classList.add("glyphicon-remove");
		                             return;
		                          }
		                          document.getElementById("final_status").classList.add("list-group-item-success");
		                          document.getElementById("final_status").children[0].classList.add("glyphicon-ok");
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
      <a class="navbar-brand" href="#"><img src="images/triliodata-144x36.png" alt="Trilio Data, Inc" height="36" width="144"></a>
    </div>
    <div id="bs-example-navbar-collapse-3" class="collapse navbar-collapse navbar-right">
       <button class="btn btn-default navbar-btn" type="button" onClick="parent.location='/logout'">Sign Out</button>
    </div>
  </div><!-- /.container-fluid -->
</nav>

<div class="panel panel-primary" style="width:70%;text-align:left;margin-left:auto; margin-right:auto;margin-top:100px">
  <!-- Default panel contents -->
  <div class="panel-heading">Configuring trilioVault Appliance </div>
  <!-- List group -->
  <ul class="list-group">
    <li id="configure_host" class="list-group-item"><span class="glyphicon"></span>
                Configuring tVault host</li>  
    <li id="authenticate_with_keystone" class="list-group-item"><span class="glyphicon"></span>
                Authenticating with keystone</li>                 
    <li id="register_service" class="list-group-item"><span class="glyphicon"></span>
                Registering tVault service with keystone</li>
    <li id="configure_api" class="list-group-item"><span class="glyphicon"></span>
                Configuring tVault API service</li>
    <li id="configure_scheduler" class="list-group-item"><span class="glyphicon"></span>
                Configuring tVault scheduler service </li>
    <li id="configure_service" class="list-group-item"><span class="glyphicon"></span>
                Configuring tVault service </li>
    <li id="start_api" class="list-group-item"><span class="glyphicon"></span>
                Starting tVault API service</li>
    <li id="start_scheduler" class="list-group-item"><span class="glyphicon"></span>
                Starting tVault scheduler service</li>
    <li id="start_service" class="list-group-item"><span class="glyphicon"></span>
                Starting tVault service</li>
    <li id="register_workloadtypes" class="list-group-item"><span class="glyphicon"></span>
                Registering workload types</li>
    <li id="final_status" class="list-group-item"><span class="glyphicon"></span>
                Final Status</li>
  </ul>
  <div id="alert" class="alert alert-danger" role="alert" style="display:none">
	  <p id="error_message"> Error Message </p>
  </div>    
</div>

</body>
</html>