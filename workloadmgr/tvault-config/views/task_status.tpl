<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN" "http://www.w3.org/TR/html4/loose.dtd">
<html>
<head>

<link rel="stylesheet" href="css/bootstrap.min.css">

<!-- Optional theme -->
<link rel="stylesheet" href="css/bootstrap-theme.min.css">

<script src="js/jquery-1.11.0.min.js"></script>
<!-- Latest compiled and minified JavaScript -->
<script src="js/bootstrap.min.js"></script>

<script>
var xmlhttp;
function loadXMLDoc(url,cfunc)
{
  if (window.XMLHttpRequest)
  {// code for IE7+, Firefox, Chrome, Opera, Safari
     xmlhttp=new XMLHttpRequest();
  }
  else
  {// code for IE6, IE5
     xmlhttp=new ActiveXObject("Microsoft.XMLHTTP");
  }
  xmlhttp.onreadystatechange=cfunc;
  xmlhttp.open("GET",url,true);
  xmlhttp.send();
}

function taskfunction()
{
   loadXMLDoc("configure_storage", function() {
      if (xmlhttp.readyState != 4) return;
      if (xmlhttp.readyState==4 && xmlhttp.status==200)
      {
         document.getElementById("configure-storage").classList.add("list-group-item-success");
         document.getElementById("configure-storage").children[0].classList.add("glyphicon-ok");
      }
      else
      {
         document.getElementById("configure-storage").classList.add("list-group-item-danger");
         document.getElementById("configure-storage").children[0].classList.add("glyphicon-remove");
         document.getElementById("final-status").classList.add("list-group-item-danger");
         document.getElementById("final-status").children[0].classList.add("glyphicon-remove");
         return;
      }
	  // Call register_service api
	  loadXMLDoc("register_service", function() {
	     if (xmlhttp.readyState != 4) return;
	     if (xmlhttp.readyState==4 && xmlhttp.status==200)
	     {
	        document.getElementById("register-service").classList.add("list-group-item-success");
	        document.getElementById("register-service").children[0].classList.add("glyphicon-ok");
	     }
	     else
	     {
	        document.getElementById("register-service").classList.add("list-group-item-danger");
	        document.getElementById("register-service").children[0].classList.add("glyphicon-remove");
	        document.getElementById("final-status").classList.add("list-group-item-danger");
	        document.getElementById("final-status").children[0].classList.add("glyphicon-remove");
	        return;
	     }
	     // Call configure_api
	     loadXMLDoc("configure_api",function() {
	        if (xmlhttp.readyState != 4) return;
	        if (xmlhttp.readyState==4 && xmlhttp.status==200)
	        {
	           document.getElementById("configure-api").classList.add("list-group-item-success")
	           document.getElementById("configure-api").children[0].classList.add("glyphicon-ok")
	        }
	        else
	        {
	           document.getElementById("configure-api").classList.add("list-group-item-danger")
	           document.getElementById("configure-api").children[0].classList.add("glyphicon-remove")
	           document.getElementById("final-status").classList.add("list-group-item-danger");
	           document.getElementById("final-status").children[0].classList.add("glyphicon-remove");
	           return;
	        }
	        // Call configure_scheduler
	        loadXMLDoc("configure_scheduler",function() {
	           if (xmlhttp.readyState != 4) return;
	           if (xmlhttp.readyState==4 && xmlhttp.status==200)
	           {
	              document.getElementById("configure-scheduler").classList.add("list-group-item-success")
	              document.getElementById("configure-scheduler").children[0].classList.add("glyphicon-ok")
	           }
	           else
	           {
	              document.getElementById("configure-scheduler").classList.add("list-group-item-danger")
	              document.getElementById("configure-scheduler").children[0].classList.add("glyphicon-remove")
	              document.getElementById("final-status").classList.add("list-group-item-danger");
	              document.getElementById("final-status").children[0].classList.add("glyphicon-remove");
	              return;
	           }
	           // Call configure_service
	           loadXMLDoc("configure_service",function() {
	               if (xmlhttp.readyState != 4) return;
	              if (xmlhttp.readyState==4 && xmlhttp.status==200)
	              {
	                 document.getElementById("configure-service").classList.add("list-group-item-success")
	                 document.getElementById("configure-service").children[0].classList.add("glyphicon-ok")
	              }
	              else
	              {
	                 document.getElementById("configure-service").classList.add("list-group-item-danger")
	                 document.getElementById("configure-service").children[0].classList.add("glyphicon-remove")
	                 document.getElementById("final-status").classList.add("list-group-item-danger");
	                 document.getElementById("final-status").children[0].classList.add("glyphicon-remove");
	                 return;
	              }
	              // Call start_api
	              loadXMLDoc("start_api",function() {
	                 if (xmlhttp.readyState != 4) return;
	                 if (xmlhttp.readyState==4 && xmlhttp.status==200)
	                 {
	                    document.getElementById("start-api").classList.add("list-group-item-success")
	                    document.getElementById("start-api").children[0].classList.add("glyphicon-ok")
	                 }
	                 else
	                 {
	                    document.getElementById("start-api").classList.add("list-group-item-danger")
	                    document.getElementById("start-api").children[0].classList.add("glyphicon-remove")
	                    document.getElementById("final-status").classList.add("list-group-item-danger");
	                    document.getElementById("final-status").children[0].classList.add("glyphicon-remove");
	                    return;
	                 }
	                 // Call start_scheduler
	                 loadXMLDoc("start_scheduler",function() {
	                    if (xmlhttp.readyState != 4) return;
	                    if (xmlhttp.readyState==4 && xmlhttp.status==200)
	                    {
	                       document.getElementById("start-scheduler").classList.add("list-group-item-success")
	                       document.getElementById("start-scheduler").children[0].classList.add("glyphicon-ok")
	                    }
	                    else
	                    {
	                       document.getElementById("start-scheduler").classList.add("list-group-item-danger")
	                       document.getElementById("start-scheduler").children[0].classList.add("glyphicon-remove")
	                       document.getElementById("final-status").classList.add("list-group-item-danger");
	                       document.getElementById("final-status").children[0].classList.add("glyphicon-remove");
	                       return;
	                    }
	                    // Call start_service
	                    loadXMLDoc("start_service",function() {
	                       if (xmlhttp.readyState != 4) return;
	                       if (xmlhttp.readyState==4 && xmlhttp.status==200)
	                       {
	                          document.getElementById("start-service").classList.add("list-group-item-success")
	                          document.getElementById("start-service").children[0].classList.add("glyphicon-ok")
	                       }
	                       else
	                       {
	                          document.getElementById("start-service").classList.add("list-group-item-danger")
	                          document.getElementById("start-service").children[0].classList.add("glyphicon-remove")
	                          document.getElementById("final-status").classList.add("list-group-item-danger");
	                          document.getElementById("final-status").children[0].classList.add("glyphicon-remove");
	                          return;
	                       }
	                       loadXMLDoc("register_workloadtypes",function() {
	                          if (xmlhttp.readyState != 4) return;
	                          if (xmlhttp.readyState==4 && xmlhttp.status==200)
	                          {
	                             document.getElementById("register-workloadtypes").classList.add("list-group-item-success")
	                             document.getElementById("register-workloadtypes").children[0].classList.add("glyphicon-ok")
	                          }
	                          else
	                          {
	                             document.getElementById("register-workloadtypes").classList.add("list-group-item-danger")
	                             document.getElementById("register-workloadtypes").children[0].classList.add("glyphicon-remove")
	                             document.getElementById("final-status").classList.add("list-group-item-danger");
	                             document.getElementById("final-status").children[0].classList.add("glyphicon-remove");
	                             return;
	                          }
	                          document.getElementById("final-status").classList.add("list-group-item-success");
	                          document.getElementById("final-status").children[0].classList.add("glyphicon-ok");
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
      <a class="navbar-brand" href="#"><img src="triliodata-144x36.png" alt="Trilio Data, Inc" height="36" width="144"></a>
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
    <li id="configure-storage" class="list-group-item"><span class="glyphicon"></span>
                Configuring storage at /dev/vdb</li>  
    <li id="register-service" class="list-group-item"><span class="glyphicon"></span>
                Registering tvault service with keystone</li>
    <li id="configure-api" class="list-group-item"><span class="glyphicon"></span>
                Configuring tvault API service</li>
    <li id="configure-scheduler" class="list-group-item"><span class="glyphicon"></span>
                Configuring tvault scheduler service </li>
    <li id="configure-service" class="list-group-item"><span class="glyphicon"></span>
                Configuring tvault service </li>
    <li id="start-api" class="list-group-item"><span class="glyphicon"></span>
                Starting tvault API service</li>
    <li id="start-scheduler" class="list-group-item"><span class="glyphicon"></span>
                Starting tvault scheduler service</li>
    <li id="start-service" class="list-group-item"><span class="glyphicon"></span>
                Starting tvault service</li>
    <li id="register-workloadtypes" class="list-group-item"><span class="glyphicon"></span>
                Registering workload types</li>
    <li id="final-status" class="list-group-item"><span class="glyphicon"></span>
                Final Status</li>
  </ul>
</div>

</body>
</html>
