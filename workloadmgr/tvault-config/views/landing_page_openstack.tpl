<head>
	<!-- Latest compiled and minified CSS -->
	<link rel="stylesheet" href="css/bootstrap.min.css">
	<link rel="stylesheet" href="css/jumbotron.css" type="text/css">
		
	<!-- Optional theme -->
	<link rel="stylesheet" href="css/bootstrap-theme.min.css">
        <link href="css/paper-bootstrap-wizard.css" rel="stylesheet" />
	
	<script src="js/jquery-1.11.0.min.js"></script>
	<!-- Latest compiled and minified JavaScript -->
	<script src="js/bootstrap.min.js"></script>
</head>

<body>
<style>

.fixed {
    position: fixed;
}

/* sidebar */
.bs-docs-sidebar {
    padding-left: 20px;
    margin-top: 40px;
    margin-bottom: 20px;
}

/* all links */
.bs-docs-sidebar .nav>li>a {
    color: #999;
    border-left: 2px solid transparent;
    padding: 4px 20px;
    font-size: 13px;
    font-weight: 400;
}

/* nested links */
.bs-docs-sidebar .nav .nav>li>a {
    padding-top: 1px;
    padding-bottom: 1px;
    padding-left: 30px;
    font-size: 12px;
}

/* active & hover links */
.bs-docs-sidebar .nav>.active>a, 
.bs-docs-sidebar .nav>li>a:hover, 
.bs-docs-sidebar .nav>li>a:focus {
    color: #563d7c;                 
    text-decoration: none;          
    background-color: transparent;  
    border-left-color: #563d7c; 
}
/* all active links */
.bs-docs-sidebar .nav>.active>a, 
.bs-docs-sidebar .nav>.active:hover>a,
.bs-docs-sidebar .nav>.active:focus>a {
    font-weight: 700;
}
/* nested active links */
.bs-docs-sidebar .nav .nav>.active>a, 
.bs-docs-sidebar .nav .nav>.active:hover>a,
.bs-docs-sidebar .nav .nav>.active:focus>a {
    font-weight: 500;
}
</style>

<div class="navbar navbar-default navbar-fixed-top">
    <div class="container-fluid">
        <div class="navbar-header">
            <a class="navbar-brand" href="http://www.trilio.io">
                <img height="35" width="150" src="images/triliovault-logo2.png">
            </a>
        </div>
    </div>
</div>

    <div class="container">
        <!-- Example row of columns -->
        <div class="row">
            <!--Nav Bar -->
            <nav class="col-xs-3 bs-docs-sidebar">
                <ul id="sidebar" class="nav nav-stacked fixed">
                    <li class='active'>
                        <a href="#GroupA">Deployment</a>
                    </li>
                    <li>
                        <a href="#GroupB">Configuration</a>
                        <ul class="nav nav-stacked">
                            <li><a href="#GroupBSub1">Appliance</a></li>
                            <li><a href="#GroupBSub2">Controller and Compute Nodes</a></li>
                        </ul>
                    </li>
                    <li>
                        <a href="#GroupC">Horizon Plugin</a>
                    </li>
                    <li>
                        <a href="#GroupD">TrilioVault CLI</a>
                    </li>
                    <li>
                        <a href="#GroupE">Ansible Scripts</a>
                    </li>
                    <li>
                        <a href="#GroupF">Documentation</a>
                    </li>
                </ul>
            </nav>
            <div class="col-xs-9">
                <h3 id="GroupA">Deployment</h3>
                <p>Welcome to TrilioVault landing page. TrilioVault provides tenant driven data protection for OpenStack Clouds. <br /> Version {{ version }}</p>
                <ol>
                    <img src="images/triliovault-overview-openstack-thumb.png" width=80%  height=40% style="padding-top:23px;" onmouseover="showtrail('auto','auto','images/triliovault-overview-openstack.png');" onmouseout="hidetrail();" />
                    <br>
                </ol>
                <h3 id="GroupB">Configuration</h3>
                <ol>
                    <li id="GroupBSub1">Configure TrilioVault Appliance (Controller or Additional Node)
                        <br>
                        <br>
                        <div class="well">
                            <a href="/home" target="_blank">http://floating-ipaddress-of-triliovault-vm/home</a>
                        </div>
                    </li>
                    
                    <li"GroupBSub2">Configure OS Controller and Compute Nodes
                        <br>
                        <br>
                        <div class="well">
                            <b>Download <a href="/tvault-contego-install.sh">tvault-contego-install.sh</a> and run as sudo...</b><br>
                            <b>Download <a href="/tvault-contego-install.answers">tvault-contego-install.answers</a></b><br>
                        </div>                    
                    </li>
                   
                    <!-- Enable deb and rpm packages later on 
                    <li>Configure OS Controller</li>
                    <br>
                    <div class="well">
                        <code># sudo sh -c "echo 'deb http://floating-ipaddress-of-tvault-vm/debs/ amd64/' &gt;&gt; /etc/apt/sources.list"</code>
                        <br>
                        <code># sudo apt-get update</code>
                        <br>
                        <code># sudo apt-get install tvault-contego-api</code>
                        <br>
                    </div>

                    <li>Configure Compute Nodes</li>
                    <br>
                    <div class="well">
                        <code># sudo sh -c "echo 'deb http://floating-ipaddress-of-tvault-vm/debs/ amd64/' &gt;&gt; /etc/apt/sources.list"</code>
                        <br>
                        <code># sudo apt-get update</code>
                        <br>
                        <code># sudo apt-get install tvault-contego</code>
                        <br>
                    </div>
                    -->
                    
                </ol>
                <h3 id="GroupC">Dashboard</h3>
                <ol>
                    <li>Configure Horizon Plugin
                        <br>
                        <br>
                        <div class="well">
                            <b>Download <a href="/tvault-horizon-plugin-install.sh">tvault-horizon-plugin-install.sh</a> and run as sudo...</b><br>
                        </div>                    
                    </li>
               
                    <!--li>Horizon Dashboard on Appliance
                        <br>
                        <br>
                        <div class="well">
                        	<script>document.write('<a href="http://' + window.location.host + ':3001" target="_blank"> http://floating-ipaddress-of-tvault-vm:3001 </a>')</script>
                        </div>
                    </li-->

                    <!-- Enable deb and rpm packages later on 
                    <li>Horizon Dashboard Plugin</li>
                    <br>
                    <div class="well">
                        <code># sudo sh -c "echo 'deb http://floating-ipaddress-of-tvault-vm/debs/ amd64/' &gt;&gt; /etc/apt/sources.list"</code>
                        <br>
                        <code># sudo apt-get update</code>
                        <br>
                        <code># sudo apt-get install tvault-horizon-plugin</code>
                        <br>
                    </div>
                    -->
                </ol>
                <h3 id="GroupD">Cli</h3>
                <ol>
                    <div class="well">
                        <script>document.write("easy_install http://" + window.location.host + ":8081/packages/pip-7.1.2.tar.gz")</script>
                         <br>
                        <script>document.write("pip install http://" + window.location.host + ":8081/packages/python-workloadmgrclient-")</script>{{version}}<script>document.write(".tar.gz")</script>
                    </div>
                </ol>                
                
                <h3 id="GroupE">Ansible Scripts</h3>
                <ol>
                    <div class="well">
                        <b>Download Ansible Scripts <a href="/tvault-ansible-scripts.tar.gz">tvault-ansible-scripts-{{version}}.tar.gz</a></b><br>
                         <br>
                    </div>
                </ol>

                <h3 id="GroupF">TrilioVault Documentation</h3>
                <ol>
                    <div class="well">
                        <b>Product Documentation Portal 
                           <script>document.write("<a href=http://" + window.location.host + ":8181/doc/index.php/Main_Page>")</script>
                           {{version}}</a></b><br>
                         <br>
                    </div>
                </ol>

                <h3 id="GroupH">Support</h3>
                <ol>
                    <div class="well"><a>support@triliodata.com</a>
                    </div>
                </ol>
            </div>
        </div>
    </div>
    <hr>
    <!-- /container -->
</body>

<script>
$('body').scrollspy({
    target: '.bs-docs-sidebar',
    offset: 40
});
</script>
