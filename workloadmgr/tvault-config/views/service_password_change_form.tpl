<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01 Transitional//EN" "http://www.w3.org/TR/html4/loose.dtd">
<html>
<head>
<link rel="stylesheet" href="css/bootstrap.min.css">

<!-- Optional theme -->
<link rel="stylesheet" href="css/bootstrap-theme.min.css">


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
      <a class="navbar-brand" href="#"><img src="images/triliodata-144x36.png" alt="Trilio Data, Inc" height="32" width="134"></a>
    </div>
  </div><!-- /.container-fluid -->
</nav>

<div class="panel panel-default" style="width:400px;text-align:center;margin-left:auto; margin-right:auto;margin-top:100px">
<div class="panel-body">
<div class="container" style="width:370px">
 <img width="350" height="50" src="images/triliovault.png" alt="trilio-splash" id="tdmini">
 <form role="form" class="form-signin" action="/update_service_account_password" onsubmit="return validatepasswords()" method="post">
  <h5 class="form-signin-heading">Update Service Account Credentials</h5><br><br>
      <div>
        <input id="oldpassword" name="oldpassword" type="password" autofocus="" required="" placeholder="triliovault Current Password" class="form-control"><span style="align:left;color:#ff6666">{{error}}</span><br>
        <input id="newpassword" name="newpassword" type="password" autofocus="" required="" placeholder="triliovault New Password" class="form-control" onkeyup="validatestrongpassword(); return false;"><br>
        <input id="confirmpassword" name="confirmpassword" type="password" required="" placeholder="Confirm New Password" class="form-control" onkeyup="validatepasswords(); return false;"><br>
        <span id="confirmMessage" class="confirmMessage"></span>
        <button type="submit" class="btn btn-lg btn-primary btn-block">Submit</button>
      </div>
 </form>
</div>
</div>
</div>
</body>
<script src="js/jquery-1.11.0.min.js"></script>
<!-- Latest compiled and minified JavaScript -->
<script src="js/bootstrap.min.js"></script>
<script src="js/passwordvalidation.js"></script>
</html>
