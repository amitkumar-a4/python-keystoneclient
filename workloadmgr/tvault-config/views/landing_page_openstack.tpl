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
            <h1 class="center-block text-center">Welcome to TrilioVault landing page. TrilioVault provides tenant driven data protection for the OpenStack Cloud.</h1>
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
                            <b>Download <a href="/tvault-contego-install.sh">tvault-contego-install.sh</a>, set the following values and run as sudo...</b><br>
                            <br>
							####### IP Address of Trilio Vault Appliance ################################<br>
							TVAULT_APPLIANCE_NODE=192.168.1.XXX<br>
							TVAULT_CONTEGO_VERSION=1.0.158<br>
							<br>
							####### Nova Configuration Files ########################################<br> 
							NOVA_CONF_FILE=/etc/nova/nova.conf<br>
							#Nova distribution specific configuration file path<br>
							NOVA_DIST_CONF_FILE=/usr/share/nova/nova-dist.conf<br>
							#Nova compute.filters file path<br> 
							NOVA_COMPUTE_FILTERS_FILE=/usr/share/nova/rootwrap/compute.filters<br>
							<br>
							####### OpenStack Controller Node: Set TVAULT_CONTEGO_API as True #######<br>
							TVAULT_CONTEGO_API=False<br>
							<br>
							####### OpenStack Compute Node: Set TVAULT_CONTEGO_API as True ########<br>
							TVAULT_CONTEGO_EXT=False<br>
							TVAULT_CONTEGO_EXT_USER=nova<br>
							<br>
							VAULT_STORAGE_TYPE=nfs<br>
							VAULT_DATA_DIR=/var/triliovault<br>
							<br>                 
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
                    <li>Horizon Dashboard
                        <br>
                        <br>
                        <div class="well">
                        	<script>document.write('<a href="http://' + window.location.host + ':3001" target="_blank"> http://floating-ipaddress-of-tvault-vm:3001 </a>')</script>
                        </div>
                    </li>

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