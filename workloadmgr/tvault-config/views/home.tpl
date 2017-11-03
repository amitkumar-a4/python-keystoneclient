<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN" "http://www.w3.org/TR/html4/loose.dtd">
<html>
	<head>
	<!-- Latest compiled and minified CSS -->
	<link rel="stylesheet" href="css/bootstrap.min.css">
	
	<!-- Optional theme -->
	<link rel="stylesheet" href="css/bootstrap-theme.min.css">
        <link href="css/paper-bootstrap-wizard.css" rel="stylesheet" />
	
	<script>
	function warnReinitialize() {
	   return confirm("Reinitializing will erase the backup metadata from the the appliance. \nThis operation can't be undone. Proceed to reinitialize?");
	}
	function warnResetPassword() {
	   return confirm("Do you want to reset password?");
	}
	function warnUpdateServiceAccount() {
	   return confirm("Do you want to update TrilioVault service account password?");
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
	  <div class="panel-heading"><h3 class="panel-title">TrilioVault</h3></div>
	  % if 'error_message' in locals() and len(error_message) > 0:
		  	<div class="alert alert-danger alert-dismissible" role="alert">
			  <button type="button" class="close" data-dismiss="alert">
			  <span aria-hidden="true">&times;</span><span class="sr-only">Close</span></button>
			  <strong>{{error_message}}</strong>
	 		</div>
	  % end

          % if 'success_message' in locals() and len(success_message) > 0:
                        <div class="alert alert-success alert-dismissible" role="alert">
                          <button type="button" class="close" data-dismiss="alert">
                          <span aria-hidden="true">&times;</span><span class="sr-only">Close</span></button>
                          <strong>{{success_message}}</strong>
                        </div>
          % end
  	<div style="margin-left:auto; margin-right:auto; padding:20px">	
    <div class="container">
        <!-- Example row of columns -->
        <div class="row">
            <div>
                <a href="/configure" data-toggle="tooltip" title="Configure TrilioVault appliance">Configure Appliance</a>
            	<br><br>
            	<a href="/reinitialize" onclick='return warnReinitialize(this)'; data-toggle="tooltip" title="Reinitialize TriliVault mysql database">Reinitialize TrilioVault Database</a>
                <br><br>
            	<a href="/reset_password" onclick='return warnResetPassword(this)'; data-toggle="tooltip" title="Reset TrilioVault configurator password">Reset Configurator Password</a>
                <br><br>
            	<a href="/update_service_account_password" onclick='return warnUpdateServiceAccount(this)'; data-toggle="tooltip" title="Reset TrilioVault service account password in Keystone">Update TrilioVault Service Password</a>
                <br><br>
                <a href="/services" data-toggle="tooltip" title="Workloadmgr services running on TrilioVault appliance">Workloadmgr Services</a>
            	<br><br>
                <a href="/logs" data-toggle="tooltip" title="Download Logs on TrilioVault appliance ">TrilioVault Logs</a>
            	<br><br>
                <a href="/troubleshooting">Troubleshooting</a>
            	<br>              	                
            </div>
        </div>
    </div>
</body>

<script src="js/jquery-1.11.0.min.js"></script>
<!-- Latest compiled and minified JavaScript -->
<script src="js/bootstrap.min.js"></script>

</html>
