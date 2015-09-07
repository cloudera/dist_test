Master, slave, and client for submitting and running Isolate tasks distributed on a cluster.

The server exposes a set of webpages for viewing jobs and task results.
Try poking around [our internal server](http://a1228.halxg.cloudera.com:8081/).
The server keeps task state in a MySQL database which is backed up periodically.

The server and slaves communicate over beanstalk, a simple pub sub system.
The server manages a dynamic workqueue of Isolate tasks, doling them out to slaves as they become idle.

To run the server (useful for local testing), you need a configuration file at `~/.dist_test.cnf`.
See the [internal wiki page](https://wiki.cloudera.com/display/engineering/Distributed+testing+for+Kudu) for an example with the fields filled in, the format looks like this:

        [isolate]
        home=/home/andrew/dev//swarming.client
        server=<FILL IN HERE>
        cache_dir=/home/andrew/cache
        [aws]
        access_key=<FILL IN HERE>
        secret_key=<FILL IN HERE>
        test_result_bucket=<FILL IN HERE>
        [mysql]
        host=<FILL IN HERE>
        user=<FILL IN HERE>
        password=<FILL IN HERE>
        database=<FILL IN HERE>
        [beanstalk]
        host=<FILL IN HERE>

Once you have the config file setup, do the following:

        # Set up virtualenv for slave and server
        $ ./make-env.sh
        # Activate the server's virtualenv
        $ source server-env/bin/activate
        # Start the server
        $ ./server.py
        # Deactivate the virtualenv when done
        $ deactivate

