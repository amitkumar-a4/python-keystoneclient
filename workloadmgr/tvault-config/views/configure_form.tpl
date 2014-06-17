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
      <a class="navbar-brand" href="#"><img src="triliodata-144x36.png" alt="Trilio Data, Inc" height="36" width="144"></a>
    </div>
    <div id="bs-example-navbar-collapse-3" class="collapse navbar-collapse navbar-right">
       <button class="btn btn-default navbar-btn" type="button" onClick="parent.location='/logout'">Sign Out</button>
    </div>
  </div><!-- /.container-fluid -->
</nav>

<div class="panel panel-primary" style="width:70%;text-align:left;margin-left:auto; margin-right:auto;margin-top:100px">
  <!-- Default panel contents -->
  <div class="panel-heading"><h3 class="panel-title">trilioVault Appliance Configuration</h3></div>
  <div style="margin-left:auto; margin-right:auto; padding:20px">


  <form role="form" class="form-configure" action="/configure" method="post">
    <input name = "nodetype" type="radio"  value="controller" checked>  Controller Node
    <input name = "nodetype" type="radio"  value="additional">   Additional Node <br> <br>
    <div class="input-group">
    <label class="input-group-addon">Floating IP Address	</label>
    <input name="floating-ipaddress" type="text" required="" placeholder="192.168.2.200" class="form-control"><br>
    </div><br>
    <div class="input-group">    
    <label class="input-group-addon">Keystone Admin Url</label>
    <input name="keystone-admin-url" type="url" required="" placeholder="http://keystonehost:35357/v2.0" class="form-control"><br>
    </div><br>
    <div class="input-group">
    <label class="input-group-addon">Keystone Public Url</label>
    <input name="keystone-public-url" type="url" required="" placeholder="http://keystonehost:5000/v2.0" class="form-control"><br>
    </div><br>
    <div class="input-group">
    <label class="input-group-addon">Administrator&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp</label>
    <input name="admin-username" type="text" required="" placeholder="admin" class="form-control"> <br>
    </div><br>
    <div class="input-group">
    <label class="input-group-addon">Password&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp</label>
    <input name="admin-password" type="password" required="" placeholder="password" class="form-control"> <br>
    </div><br>
    <div class="input-group">
    <label class="input-group-addon">Admin Tenant&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp</label>
    <input name="admin-tenant-name" type="text" required="" placeholder="admin" class="form-control">
    </div><br>
    <div class="input-group">
    <label class="input-group-addon">Region&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp</label>
    <input name="region-name" type="text" required="" placeholder="RegionOne" class="form-control">
    </div><br>    
    <button type="submit" class="btn btn-lg btn-primary btn-block">Submit</button>
  </form>
  </div>
</div>
</body>
</html>
