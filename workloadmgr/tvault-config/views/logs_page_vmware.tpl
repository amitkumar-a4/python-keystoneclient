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
	  <div class="panel-heading"><h3 class="panel-title">TrilioVault Logs</h3></div>
	  % if len(error_message) > 0:
		  	<div class="alert alert-danger alert-dismissible" role="alert">
			  <button type="button" class="close" data-dismiss="alert">
			  <span aria-hidden="true">&times;</span><span class="sr-only">Close</span></button>
			  <strong>{{error_message}}</strong>
	 		</div>
	  % end
  	<div style="margin-left:auto; margin-right:auto; padding:20px">	
    <div class="container">
        <!-- Example row of columns -->
        <!--div class="row">
            <div style="margin-left:auto; margin-right:auto; padding:20px; text-align:left;">
                <a href="/tvault/tvaultlogs">Basic</a>
            </div>
        </div-->
        <div class="row">
	        <div style="margin-left:auto; margin-right:auto; padding:20px; text-align:left;">
	                <a href="/tvault/tvaultlogs_all">Download Complete Zip</a>
	        </div>
	    </div>        
    </div>
    <div style="margin-left:auto; margin-right:auto; padding:20px">
	<div class="panel-group" id="accordion">
		<div class="panel panel-default" id="panel1">
		    <div class="panel-heading">
		      <h4 class="panel-title">
		        <a data-toggle="collapse" data-target="#collapseOne" href="#collapseOne">Download Service Logs</a>
		      </h4>
		    </div>
	 	    <div id="collapseOne" class="panel-collapse collapse in">
		      <div class="panel-body">
				<a href="tvault/workloadmgr/workloadmgr-api.log">workloadmgr-api.log</a>
				<br><br>   
				<a href="tvault/workloadmgr/workloadmgr-scheduler.log">workloadmgr-scheduler.log</a>
				<br><br>
				<a href="tvault/workloadmgr/workloadmgr-workloads.log">workloadmgr-workloads.log</a>
				<br><br>
                                <a href="upstart/tvault-config.log">tvault-config.log</a>
                                <br><br>
				<!--a href="tvault/nova/nova-api.log">inventory-service.log</a>
				<br><br>
				<a href="tvault/tvault-gui/web-1.log">tvault-gui-web-1.log</a>
				<br><br-->															    
		      </div>
		    </div>
		</div>
	</div>
	
</body>
</html>
