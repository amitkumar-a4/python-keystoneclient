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

<!-- 
<script>
$(function() {
  var $storagetype = $("input[name='storage-type']");
  $storagetype.each(function() {
    $(this).on("click",function() {
      $storagetype.each(function() {
        var textField = $(this).nextAll("input").first();
        if (textField) textField.prop("disabled",!this.checked);
      });    
    });    
  });
});  
</script>  
-->   

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
  <form role="form" class="form-configure" action="/configure_vmware" method="post">
    <input name = "nodetype" type="radio"  value="controller" checked>  Controller Node
    <input name = "nodetype" type="radio"  value="additional">   Additional Node <br> <br>

    <div class="input-group">
    	<label class="input-group-addon">Controller Node&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</label>
    	<input name="tvault-primary-node" type="text" required placeholder="192.168.2.216" class="form-control"><br>
    </div><br>
   
    <div class="input-group">
    	<label class="input-group-addon">vCenter&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</label>
    	<input name="vcenter" type="text" required placeholder="vcenter.local" class="form-control"><br>
    </div><br>
    <div class="input-group">
    	<label class="input-group-addon">vCenter User&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</label>
    	<input name="vcenter-username" type="text" required placeholder="administrator@vsphere.local" class="form-control"> <br>
    </div><br>
    <div class="input-group">
    	<label class="input-group-addon">vCenter Password&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp</label>
    	<input name="vcenter-password" type="password" required placeholder="" class="form-control"> <br>
    </div><br>
    
	<div class="panel-group" id="accordion">
	  <div class="panel panel-default" id="panel3">
	    <div class="panel-heading">
	      <h4 class="panel-title">
	        <a data-toggle="collapse" data-target="#collapseThree" href="#collapseThree">
	          Storage
	        </a>
	      </h4>
	    </div>
	    <div id="collapseThree" class="panel-collapse collapse in">
	      <div class="panel-body">
    		<div class="input-group" >
    			<input name="storage-type" id="storage-type-local" type="radio"  value="local" checked> Local Device 
    			<input name="storage-local-device" id="storage-local-device" type="text" required placeholder="/dev/sdb" value="/dev/sdb" class="form-control" /> <br/>
    			<input name="storage-type" id="storage-type-nfs" type="radio"  value="nfs"> NFS Export 
    			<input name="storage-nfs-export" id="storage-nfs-export" type="text" required placeholder="server:/var/nfs" value="server:/var/nfs" class="form-control" /> <br/>
 		    	<!---   			
    			<input name="storage-type" id="storage-type-object" type="radio"  value="object" disabled> Object Store 
    			<input name="storage-object-url" id="storage-object-url" type="text" required placeholder="" class="form-control">	<br/>
		    	-->	    	
    		</div><br>   	      
	      </div>
	    </div>
	  </div>
	</div>
    
    
	<div class="panel-group" id="accordion">
	  <div class="panel panel-default" id="panel1">
	    <div class="panel-heading">
	      <h4 class="panel-title">
	        <a data-toggle="collapse" data-target="#collapseOne" href="#collapseOne">
	          LDAP (Optional)
	        </a>
	      </h4>
	    </div>
	    <div id="collapseOne" class="panel-collapse collapse">
	      <div class="panel-body">
			<div class="input-group">
				<label class="input-group-addon">Server URL&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</label>
				<input name="ldap-server-url" type="text" placeholder="ldap://example.com" class="form-control"><br>
			</div><br>
			<div class="input-group">
				<label class="input-group-addon">DN for domain name</label>
				<input name="ldap-domain-name-suffix" type="text" placeholder="dc=example,dc=com" class="form-control"> <br>
			</div><br>
			<div class="input-group">
				<label class="input-group-addon">Base DN for users&nbsp;&nbsp;&nbsp;</label>
				<input name="ldap-user-tree-dn" type="text" placeholder="cn=users,dc=example,dc=com" class="form-control"><br>
			</div><br>
			<div class="input-group">
				<label class="input-group-addon">Username(DN)&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</label>
				<input name="ldap-user-dn" type="text" placeholder="cn=triliovault,cn=users,dc=example,dc=com" class="form-control"> <br>
			</div><br>						
	      </div>
	    </div>
	  </div>
	</div>    
    
	<div class="panel-group" id="accordion">
	  <div class="panel panel-default" id="panel2">
	    <div class="panel-heading">
	      <h4 class="panel-title">
	        <a data-toggle="collapse" data-target="#collapseTwo" href="#collapseTwo">
	          NameServer (Optional)
	        </a>
	      </h4>
	    </div>
	    <div id="collapseTwo" class="panel-collapse collapse">
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
