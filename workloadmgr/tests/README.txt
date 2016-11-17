Steps to run unit test cases:
1. Clone workloadmanager repository from https://github.com/trilioData/workloadmanager.git
    $ git clone https://github.com/trilioData/workloadmanager.git

2. Go inside workloadmanager directory.
    $ cd workloadmanager
    
    All the unit cases for worloadmanager module are inside "workloadmanager/workloadmgr/tests/" folder.

3. Install required packages for running test cases.
   $ ./install_dependencies.sh
   $ pip install -r requirements.txt
   $ pip install -r test-requirements.txt
    
4. To run only single test case:
    $  python -m testtools.run workloadmgr.tests.<FILE_NAME>.<CLASS_NAME>.<TEST_CASE_NAME>
    
    Ex: $ python -m testtools.run workloadmgr.tests.unit.test_wsgi.TestLoaderNormalFilesystem.test_app_not_found

5. To run all test cases of a class:
    $  python -m testtools.run workloadmgr.tests.<FILE_NAME>.<CLASS_NAME>.
    
    Ex: $ python -m testtools.run workloadmgr.tests.unit.test_wsgi.TestLoaderNormalFilesystem
    
6. To run all test cases of a file:
    $  python -m testtools.run workloadmgr.tests.<FILE_NAME>
    
    Ex: $ python -m testtools.run workloadmgr.tests.unit.test_wsgi
    
          or
          
        $ python -m testtools.run workloadmgr/tests/unit/test_wsgi.py
        
7. To run all test cases inside a folder:
    $  python -m testtools.run discover <FOLDER_NAME>
    
    Ex: $python -m testtools.run discover workloadmgr/tests/unit/
    
    NOTE: Discovery of unit test cases is not recursive for folders.
    
    
##########################################################################
There is another way to run these test cases using "testr" library.
For this you can run the script "run_tests.sh" located at workloadmanager/run_tests.sh

   
###########################
Steps to execute the script.

1.  Go inside workloadmanager directory.
    $ cd workloadmanager

2.  To see the help run:
    $ ./run_tests.sh --help
  
    
    Here are the available options with this script.
    
   -V, --virtual-env           Always use virtualenv.  Install automatically if not present"
   -N, --no-virtual-env        Don't use virtualenv.  Run tests in local environment"
   -s, --no-site-packages      Isolate the virtualenv from the global Python environment"
   -r, --recreate-db           Recreate the test database (deprecated, as this is now the default)."
   -n, --no-recreate-db        Don't recreate the test database."
   -f, --force                 Force a clean re-build of the virtual environment. Useful when dependencies have been added."
   -u, --update                Update the virtual environment with any newer package versions"
   -p, --pep8                  Just run PEP8 and HACKING compliance check"
   -8, --pep8-only-changed Just run PEP8 and HACKING compliance check on files changed since HEAD~1"
   -P, --no-pep8               Don't run static code checks"
   -c, --coverage              Generate coverage report"
   -d, --debug                 Run tests with testtools instead of testr. This allows you to use the debugger."
   -h, --help                  Print this usage message"
   --hide-elapsed              Don't print the elapsed time for each test along with slow test list"
   --virtual-env-path <path>   Location of the virtualenv directory"
                                Default: \$(pwd)"
   --virtual-env-name <name>   Name of the virtualenv directory"
                                Default: .venv"
   --tools-path <dir>          Location of the tools directory"
                                Default: \$(pwd)"
   --concurrency <concurrency> How many processes to use when running the tests. A value of 0 autodetects concurrency from your CPU count"
                                Default: 1"
 
 Note: with no options specified, the script will try to run the tests in a virtual environment,"
       If no virtualenv is found, the script will ask if you would like to create one.  If you "
       prefer to run tests NOT in a virtual environment, simply pass the -N option."

3. To run all the test cases run:
    $ ./run_tests.sh

   
 Sample Output:
 -------------------------------------------------------------------------------------------------------
{1} workloadmgr.tests.test_wsgi.TestWSGIServer.test_no_app [0.003957s] ... ok
{2} workloadmgr.tests.test_wsgi.TestLoaderNormalFilesystem.test_app_not_found [0.012344s] ... ok
{3} workloadmgr.tests.test_utils.AuditPeriodTest.test_year [0.021220s] ... ok
{0} workloadmgr.tests.test_wsgi.TestWSGIServer.test_app_using_ssl [0.032697s] ... FAILED

Captured traceback:
~~~~~~~~~~~~~~~~~~~
    Traceback (most recent call last):
      File "workloadmgr/tests/test_wsgi.py", line 157, in test_app_using_ssl
        self.assertEqual("test", response.read())
      File "/usr/local/lib/python2.7/dist-packages/testtools/testcase.py", line 411, in assertEqual
        self.assertThat(observed, matcher, message)
      File "/usr/local/lib/python2.7/dist-packages/testtools/testcase.py", line 498, in assertThat
        raise mismatch_error
    testtools.matchers._impl.MismatchError: 'test' != 'Hello, World!!!'


Captured pythonlogging:
~~~~~~~~~~~~~~~~~~~~~~~
    140084120178768 Started test_app on 0.0.0.0:49429
    140084041271248 140084041271248 (22015) wsgi starting up on https://0.0.0.0:49429

    140084041271248 140084041271248 (22015) accepted ('127.0.0.1', 59400)

    140084041270288 140084041270288 127.0.0.1 - - [02/Aug/2016 07:19:03] "GET / HTTP/1.1" 200 150 0.000345

======
Totals
======
Ran: 54 tests in 2.0000 sec.
 - Passed: 51
 - Skipped: 2
 - Expected Fail: 0
 - Unexpected Success: 0
 - Failed: 1
Sum of execute time for each test: 0.8712 sec.

#####################################################################
For CI you can use "tox". 
Steps to run test cases using tox:

1. Go inside workloadmanager directory.
    $ cd workloadmanager

2. For tox help:
    $ tox -help
   
3. To run test cases using tox:
    $ tox -e py27 
  
