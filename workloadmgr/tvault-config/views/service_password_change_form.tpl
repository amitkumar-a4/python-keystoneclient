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
function validatepasswords()
{
    //Store the password field objects into variables ...
    var pass1 = document.getElementById('newpassword');
    var pass2 = document.getElementById('confirmpassword');

    //Store the Confimation Message Object ...
    var message = document.getElementById('confirmMessage');

    //Set the colors we will be using ...
    var goodColor = "#66cc66";
    var badColor = "#ff6666";

    //Compare the values in the password field 
    //and the confirmation field
    if(pass1.value == pass2.value){
        //The passwords match. 
        //Set the color to the good color and inform
        //the user that they have entered the correct password 
        pass2.style.backgroundColor = goodColor;
        message.style.color = goodColor;
        message.innerHTML = "Passwords Match!"
    }else{
        //The passwords do not match.
        //Set the color to the bad color and
        //notify the user.
        pass2.style.backgroundColor = badColor;
        message.style.color = badColor;
        message.innerHTML = "Passwords Do Not Match!"
        return false;
    }
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
      <a class="navbar-brand" href="#"><img src="images/triliodata-144x36.png" alt="Trilio Data, Inc" height="32" width="134"></a>
    </div>
  </div><!-- /.container-fluid -->
</nav>

<div class="panel panel-default" style="width:400px;text-align:center;margin-left:auto; margin-right:auto;margin-top:100px">
<div class="panel-body">
<div class="container" style="width:370px">
 <img width="350" height="50" src="images/triliovault.png" alt="trilio-splash" id="tdmini">
 <form role="form" class="form-signin" action="/update_service_account_password" onsubmit="return validatepasswords()" method="post">
  <h2 class="form-signin-heading">Update Service Account Credentials</h2><br><br>
      <div>
        <input id="newpassword" name="newpassword" type="password" autofocus="" required="" placeholder="New Password" class="form-control"><br>
        <input id="confirmpassword" name="confirmpassword" type="password" required="" placeholder="Confirm Password" class="form-control" onkeyup="validatepasswords(); return false;"><br>
        <span id="confirmMessage" class="confirmMessage"></span>
        <button type="submit" class="btn btn-lg btn-primary btn-block">Submit</button>
      </div>
 </form>
</div>
</div>
</div>
</body>
</html>
