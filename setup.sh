#!/usr/bin/env bash

set -eu

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

ENV="$DIR/env"
mkdir -p "$ENV"

cat > "$ENV/grind.cfg" << EOF
[grind]
isolate_server = http://isolate.cloudera.org:4242
dist_test_client_path = $DIR/bin/client
dist_test_master = http://dist-test.cloudera.org:80
grind_cache_dir = $ENV/.grind/cache
grind_temp_dir = $ENV/.grind/temp
isolate_path = $DIR/bin/isolate
EOF

echo "Wrote grind.cfg to $ENV"

cat > "$ENV/env.source" << EOF
export DIST_TEST_MASTER=http://dist-test.cloudera.org:80
EOF

echo "Wrote env.source to $ENV"
