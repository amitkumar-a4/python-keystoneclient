<head>
	<!-- Latest compiled and minified CSS -->
	<link rel="stylesheet" href="css/bootstrap.min.css">
	<link rel="stylesheet" href="css/jumbotron.css" type="text/css">
		
	<!-- Optional theme -->
	<link rel="stylesheet" href="css/bootstrap-theme.min.css">
	
	<script src="js/jquery-1.11.0.min.js"></script>
	<!-- Latest compiled and minified JavaScript -->
	<script src="js/bootstrap.min.js"></script>
</head>

<body>
    <div class="container">
        <img width="200" class="center-block" src="images/triliovault-logo2.png">
    </div>
    <div>
        <div class="container">
        <br>
            <h1 class="center-block text-center">Welcome to TrilioVault landing page. TrilioVault provides tenant driven data protection for the OpenStack Cloud. <br /> Version {{ version }}</h1>
        <br>
        </div>

    </div>

    <div class="container">
        <!-- Example row of columns -->
        <div class="row">
            <div>
                <h2>Deployment</h2>
                <ol>
                    <img src="images/triliovault-overview-openstack-thumb.png" width=auto height=auto style="padding-top:23px;" onmouseover="showtrail('auto','auto','images/triliovault-overview-openstack.png');" onmouseout="hidetrail();" />
                    <br>
                </ol>
                <h2>Configuration</h2>
                <ol>
                    <li>Configure tVault Appliance( Controller or Additional Node)
                        <br>
                        <br>
                        <div class="well">
                            <a href="/home" target="_blank">http://floating-ipaddress-of-tvault-vm/home</a>
                        </div>
                    </li>
                    
                    <li>Configure OS Controller and Compute Nodes
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
                <h2>Dashboard</h2>
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
                <h2>Cli</h2>
                <ol>
                    <div class="well">
                        <script>document.write("easy_install http://" + window.location.host + ":8081/packages/pip-7.1.2.tar.gz")</script>
                         <br>
                        <script>document.write("pip install http://" + window.location.host + ":8081/packages/python-workloadmgrclient-")</script>{{version}}<script>document.write(".tar.gz")</script>
                    </div>
                </ol>                
                
                <h2>Ansible Scripts</h2>
                <ol>
                    <div class="well">
                        <b>Download Ansible Scripts <a href="/tvault-ansible-scripts.tar.gz">tvault-ansible-scripts-{{version}}.tar.gz</a></b><br>
                         <br>
                    </div>
                </ol>

                <h2>TrilioVault Documentation</h2>
                <ol>
                    <div class="well">
                        <b>Product Documentation Portal 
                           <script>document.write("<a href=http://" + window.location.host + ":8181/doc/index.php/Main_Page>")</script>
                           {{version}}</a></b><br>
                         <br>
                    </div>
                </ol>

                <h2>Support</h2>
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
