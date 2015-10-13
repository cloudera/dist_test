import os
import sys

def du(path):
    """Return the size of the file or directory."""

    if not os.path.exists(path):
        raise Exception("Path does not exist: " + path)
    if os.path.isfile(path):
        return os.path.getsize(path)
    else:
        total = 0
        for root, dirs, files in os.walk(path):
            total += sum([os.path.getsize(os.path.join(root, f)) for f in files])
        return total

def sizeof_fmt(num, suffix='B'):
    for unit in ['','Ki','Mi','Gi','Ti','Pi','Ei','Zi']:
        if abs(num) < 1024.0:
            return "%3.1f%s%s" % (num, unit, suffix)
        num /= 1024.0
    return "%.1f%s%s" % (num, 'Yi', suffix)

def prompt_confirmation(msg):
    """Prompt user for confirmation. Returns True if yes, False if no. Defaults to no."""
    sys.stdout.write("%s (y/N): " % msg)
    choice = raw_input().lower()
    if choice == "y":
        return True
    return False

def prompt_confirm_or_exit(msg):
    if not prompt_confirmation(msg):
        print "Aborted"
        sys.exit(1)
