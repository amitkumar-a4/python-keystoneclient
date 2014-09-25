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
  <div class="panel-heading"><h3 class="panel-title">trilioVault Appliance Configuration</h3></div>
  % if len(error_message) > 0:
	  	<div class="alert alert-danger alert-dismissible" role="alert">
		  <button type="button" class="close" data-dismiss="alert">
		  <span aria-hidden="true">&times;</span><span class="sr-only">Close</span></button>
		  <strong>{{error_message}}</strong>
 		</div>
  % end
  <div style="margin-left:auto; margin-right:auto; padding:20px">
  <form role="form" class="form-configure" action="/configure" method="post">
    <input name = "nodetype" type="radio"  value="controller" checked>  Controller Node
    <input name = "nodetype" type="radio"  value="additional">   Additional Node <br> <br>

    <div class="input-group">
    	<label class="input-group-addon">Primary Node&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</label>
    	<input name="tvault-primary-node" type="text" required="" placeholder="192.168.2.203" class="form-control"><br>
    </div><br>
   
    <div class="input-group">
    	<label class="input-group-addon">vCenter&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</label>
    	<input name="vcenter" type="text" required="" placeholder="vcenter.local" class="form-control"><br>
    </div><br>
    <div class="input-group">
    	<label class="input-group-addon">vCenter Administrator</label>
    	<input name="vcenter-admin-username" type="text" required="" placeholder="administrator" class="form-control"> <br>
    </div><br>
    <div class="input-group">
    	<label class="input-group-addon">vCenter Password&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp</label>
    	<input name="vcenter-admin-password" type="password" required="" placeholder="password" class="form-control"> <br>
    </div><br>
    
	<div class="panel-group" id="accordion">
	  <div class="panel panel-default" id="panel1">
	    <div class="panel-heading">
	      <h4 class="panel-title">
	        <a data-toggle="collapse" data-target="#collapseOne" href="#collapseOne">
	          Optional
	        </a>
	      </h4>
	    </div>
	    <div id="collapseOne" class="panel-collapse collapse">
	      <div class="panel-body">
    		<div class="input-group" >
		    	<label class="input-group-addon">Name Server&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp</label>
		    	<input name="name-server" type="text" placeholder="192.168.2.1" class="form-control">
		    	
		    	<label class="input-group-addon">Domain Search Order</label>
		    	<input name="domain-search-order" type="text" placeholder="example.com example.net" class="form-control">
    		</div><br>   	      
	      </div>
	    </div>
	  </div>
	</div>
    
    <button type="submit" class="btn btn-lg btn-primary btn-block">Submit</button>
  </form>
  </div>
</div>
</body>
</html>
