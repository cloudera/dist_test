Master, slave, and client for submitting and running Isolate tasks distributed on a cluster.

The server exposes a set of webpages for viewing jobs and task results. A public dist test server is available: http://dist-test.cloudera.org

The server is also the API end point for submitting tests and coordinates running test tasks on slaves. Task state is kept in a MySQL database.

The server distributes JSON isolate task descriptions to slaves via [beanstalk](http://kr.github.io/beanstalkd/), a simple pub/sub system.

To run the server and slave locally (useful for testing), you need a configuration file at `~/.dist_test.cnf` that looks like the following:

        [isolate]
        home=/home/andrew/dev/swarming/client
        server=http://dist-test.cloudera.org:4242
        cache_dir=/tmp/isolate-cache

        [aws]
        access_key=<FILL IN HERE>
        secret_key=<FILL IN HERE>
        test_result_bucket=<FILL IN HERE>

        [mysql]
        host=localhost
        user=<FILL IN HERE>
        password=<FILL IN HERE>
        database=<FILL IN HERE>

        [beanstalk]
        host=localhost

        [dist_test]
        master=http://localhost:8081/

Note that as part of this, you need to setup an AWS account to store test results, and also a MySQL instance running with a configured user/password and database.

Start beanstalk:

        $ beanstalkd

Once you have the config file setup, do the following to run the master:

        # Set up virtualenv for server
        $ ./make-env-server.sh
        # Activate the server's virtualenv
        $ source server-env/bin/activate
        # Start the server
        $ ./server.py

Do the same to run a slave:

        $ ./make-env-slave.sh
        $ source slave-env/bin/activate
        $ ./slave.py

# Authentication and authorization (server side)

The distributed test master has a very basic authentication and authorization system.
The master allows read-only access from anywhere, but requires authentication to
submit or cancel jobs. The authentication is done either by an IP whitelist or by
a username/password pair.

For example, to configure the server:

        [dist_test]
        allowed_ip_ranges=172.16.0.0/16
        accounts={"user1":"password", "user2":"pass"}

If a request originates from a host in the specified subnet, it will be allowed without
any user-based authentication. Otherwise, HTTP Digest authentication will be employed.

NOTE: slaves sometimes make requests back to the dist-test master. Thus, the slaves
must be configured with a username and password if they do not run from within an
allowed IP range.

# Authentication and authorization (client side)

If a client is not within an authorized IP range, its username and password can be
configured as follows:

        [dist_test]
        user=foo
        password=bar

Alternatively, the `DIST_TEST_USER` and `DIST_TEST_PASSWORD` environment variables may
be used to specify the credentials.
