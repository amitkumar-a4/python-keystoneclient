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

	<script>
	function warnCreateFileSystem(cb) {
	  if(cb.checked == true){
	   var r = confirm("Creating a new file system will erase the previous contents permanently.\nDo you want to create a new file system?");
	   if (r == true) {
		   cb.checked = true;
	   } else {
	     cb.checked = false;
	   }
	  }
	}
	</script>  
	
	<style>
		.form-inline .form-group input {
	    width:348px;
		}
	</style>	
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
	  <div class="panel-heading"><h3 class="panel-title">TrilioVault Troubleshooting</h3></div>
	  % if len(error_message) > 0:
		  	<div class="alert alert-danger alert-dismissible" role="alert">
			  <button type="button" class="close" data-dismiss="alert">
			  <span aria-hidden="true">&times;</span><span class="sr-only">Close</span></button>
			  <strong>{{error_message}}</strong>
	 		</div>
	  % end
  	<div style="margin-left:auto; margin-right:auto; padding:20px">	
	<form class="form-inline" action="/troubleshooting_ping" method="post">
		<div class="form-group">
			<label >Hostname/IPAddress </label>
			<input {{'value=' + ping_address if defined('ping_address') else ''}} class="form-control" name="ping_address" type="text" required>
		</div>
	   	<button type="submit" class="btn btn-primary">Ping</button>
	</form>
	<br>
	<textarea name=ping_output_textarea" rows="10" cols="75" readonly>
{{ping_output if defined('ping_output') else ''}}
	</textarea>		
  	</div>
  	
  	<div style="margin-left:auto; margin-right:auto; padding:20px">	
	<form  class="form-inline" action="/troubleshooting_vmware_reset_cbt" method="post">
		<div class="form-group">
			<label >Virtual Machines(s) </label>
			<input {{'value=' + reset_cbt_vms if defined('reset_cbt_vms') else ''}} class="form-control" name="reset_cbt_vms" type="text" required>
		</div>
		<button type="submit" class="btn btn-primary">Reset</button>
	</form>
	<br>
	<textarea name=reset_cbt_vms_output_textarea" rows="11" cols="75" readonly>
{{reset_cbt_output if defined('reset_cbt_output') else ''}}
	</textarea>		
  	</div>  	
</body>
</html>
