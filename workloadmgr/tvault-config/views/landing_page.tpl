<head>
	<!-- Latest compiled and minified CSS -->
	<link rel="stylesheet" href="css/bootstrap.min.css">
	<link rel="stylesheet" href="css/jumbotron.css" type="text/css">
		
	<!-- Optional theme -->
	<link rel="stylesheet" href="css/bootstrap-theme.min.css">
	
	<script src="js/jquery-1.11.0.min.js"></script>
	<!-- Latest compiled and minified JavaScript -->
	<script src="js/bootstrap.min.js"></script>
	<script src="js/tooltip.js" type="text/javascript"></script>
</head>

<body>
    <div class="container">
        <img width="200" class="center-block" src="images/triliovault-logo2.png">
    </div>
    <div>
        <div class="container">
        <br>
            <h1 class="center-block text-center">Welcome to trilioVault landing page. trilioVault provides tenant driven data protection for the OpenStack Cloud.</h1>
        <br>
        </div>

    </div>

    <div class="container">
        <!-- Example row of columns -->
        <div class="row">
            <div>
                <h2>Deployment</h2>
                <ol>
                    <img src="images/triliovault-overview-thumb.png" width=auto height=auto style="padding-top:23px;" onmouseover="showtrail('auto','auto','images/triliovault-overview.png');" onmouseout="hidetrail();" />
                    <br>
                </ol>
                <h2>Configuration</h2>
                <ol>
                    <li>Configure tVault Appliance( Controller or Additional Node)
                        <br>
                        <br>
                        <div class="well">
                            <a href="/configure">http://&lt;floating-ipaddress-of-tvault-vm&gt;/configure</a>
                        </div>
                    </li>

                    <li>Configure OS Controller</li>
                    <br>
                    <div class="well">
                        <code># sudo sh -c "echo 'deb http://&lt;floating-ipaddress-of-tvault-vm&gt;/debs/ amd64/' &gt;&gt; /etc/apt/sources.list</code>
                        <br>
                        <code># sudo apt-get update</code>
                        <br>
                        <code># sudo apt-get install tvault-contego-api</code>
                        <br>
                    </div>

                    <li>Configure Compute Nodes</li>
                    <br>
                    <div class="well">
                        <code># sudo sh -c "echo 'deb http://&lt;floating-ipaddress-of-tvault-vm&gt;/debs/ amd64/' &gt;&gt; /etc/apt/sources.list</code>
                        <br>
                        <code># sudo apt-get update</code>
                        <br>
                        <code># sudo apt-get install tvault-contego</code>
                        <br>
                    </div>
                </ol>
                <h2>Dashboard</h2>
                <ol>
                    <li>trilioVault Dashboard
                        <br>
                        <br>
                        <div class="well">
                            <a>http://&lt;floating-ipaddress-of-tvault-controller&gt;:3000</a>
                        </div>
                    </li>

                    <li>Horizon Dashboard Plugin</li>
                    <br>
                    <div class="well">
                        <code># sudo sh -c "echo 'deb http://&lt;floating-ipaddress-of-tvault-vm&gt;/debs/ amd64/' &gt;&gt; /etc/apt/sources.list</code>
                        <br>
                        <code># sudo apt-get update</code>
                        <br>
                        <code># sudo apt-get install tvault-horizon-plugin</code>
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