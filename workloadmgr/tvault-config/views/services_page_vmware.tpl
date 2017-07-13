<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN" "http://www.w3.org/TR/html4/loose.dtd">
<html>

<head>
	<!-- Latest compiled and minified CSS -->
	<link rel="stylesheet" href="css/bootstrap.min.css">
	
	<!-- Optional theme -->
	<link rel="stylesheet" href="css/bootstrap-theme.min.css">
        <link href="css/paper-bootstrap-wizard.css" rel="stylesheet" />
	
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
	      <a class="navbar-brand" href="/home"><img src="images/triliodata-144x36.png" alt="Trilio Data, Inc" height="32" width="134"></a>
	    </div>
	    <div id="bs-example-navbar-collapse-3" class="collapse navbar-collapse navbar-right">
	       <button class="btn btn-default navbar-btn" type="button" onClick="parent.location='/logout'">Sign Out</button>
	    </div>
	  </div><!-- /.container-fluid -->
	</nav>
	<div class="panel panel-primary" style="width:70%;text-align:left;margin-left:auto; margin-right:auto;margin-top:100px">
	  <!-- Default panel contents -->
	  <div class="panel-heading"><h3 class="panel-title">TrilioVault Services</h3></div>
	  % if len(error_message) > 0:
		  	<div class="alert alert-danger alert-dismissible" role="alert">
			  <button type="button" class="close" data-dismiss="alert">
			  <span aria-hidden="true">&times;</span><span class="sr-only">Close</span></button>
			  <strong>{{error_message}}</strong>
	 		</div>
	  % end
  	<div style="margin-left:auto; margin-right:auto; padding:20px">	
  	
	<table class="table table-hover">
	    <thead>
	      <tr>
	        <th>Name</th>
	        <th>Status</th>
	        <th>Action</th>
	      </tr>
	    </thead>
	    <tbody>
	      <tr>
	        <td>tVault API Service</td>
			%if 'api_service' in locals() and api_service == 'Running':
		        <td style="color:green">Running</td>
		        <td><a href="/services/api_service/stop">Stop</a></td>			
			%elif 'api_service' in locals() and api_service == 'Stopped':
		        <td style="color:red">Stopped</td>
		        <td><a href="/services/api_service/start">Start</a></td>	
			%elif 'api_service' in locals():
		        <td>{{api_service}}</td>
		        <td>None</td>
			%else:
		        <td>Not Applicable</td>
		        <td>None</td>		        
	        %end  	        
	      </tr>
	      <tr>
	        <td>tVault Scheduler Service</td>
			%if 'scheduler_service' in locals() and scheduler_service == 'Running':
		        <td style="color:green">Running</td>
		        <td><a href="/services/scheduler_service/stop">Stop</a></td>			
			%elif 'scheduler_service' in locals() and scheduler_service == 'Stopped':
		        <td style="color:red">Stopped</td>
		        <td><a href="/services/scheduler_service/start">Start</a></td>	
			%elif 'scheduler_service' in locals():
		        <td>{{scheduler_service}}</td>
		        <td>None</td>
			%else:
		        <td>Not Applicable</td>
		        <td>None</td>		        
	        %end
	      </tr>
	      <tr>
	        <td>tVault Workload Service</td>
			%if 'workloads_service' in locals() and workloads_service == 'Running':
		        <td style="color:green">Running</td>
		        <td><a href="/services/workloads_service/stop">Stop</a></td>			
			%elif 'workloads_service' in locals() and workloads_service == 'Stopped':
		        <td style="color:red">Stopped</td>
		        <td><a href="/services/workloads_service/start">Start</a></td>	
			%elif 'workloads_service' in locals():
		        <td>{{workloads_service}}</td>
		        <td>None</td>
			%else:
		        <td>Not Applicable</td>
		        <td>None</td>		        
	        %end
	      </tr>
	      <!--tr>
	        <td>tVault Inventory Service</td>
			%if 'inventory_service' in locals() and inventory_service == 'Running':
		        <td style="color:green">Running</td>
		        <td><a href="/services/inventory_service/stop">Stop</a></td>			
			%elif 'inventory_service' in locals() and inventory_service == 'Stopped':
		        <td style="color:red">Stopped</td>
		        <td><a href="/services/inventory_service/start">Start</a></td>	
			%elif 'inventory_service' in locals():
		        <td>{{inventory_service}}</td>
		        <td>None</td>
			%else:
		        <td>Not Applicable</td>
		        <td>None</td>		        
	        %end
	      </tr>	
	      <tr>
	        <td>tVault GUI Service</td>
			%if 'tvault_gui_service' in locals() and tvault_gui_service == 'Running':
		        <td style="color:green">Running</td>
		        <td><a href="/services/tvault_gui_service/stop">Stop</a></td>			
			%elif 'tvault_gui_service' in locals() and tvault_gui_service == 'Stopped':
		        <td style="color:red">Stopped</td>
		        <td><a href="/services/tvault_gui_service/start">Start</a></td>	
			%elif 'tvault_gui_service' in locals():
		        <td>{{tvault_gui_service}}</td>
		        <td>None</td>
			%else:
		        <td>Not Applicable</td>
		        <td>None</td>		        
	        %end
	      </tr-->			      			      
	    </tbody>
	  </table>
	<br>
	<br>				
</body>
</html>
