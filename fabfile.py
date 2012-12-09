from fabric.api import run, sudo
from fabric.context_managers import cd
from fabric.operations import sudo, prompt, get
from fabric.api import run, env, settings
from fabric.utils import puts, warn, abort
from fabric.contrib import files
from fabric.contrib.console import confirm
import os
import yaml

# Load ec2key in
HOME = os.getenv('HOME')
env.user = 'ec2-user'
env.key_filename = [
    '%s/key.pem'%HOME
]

# Load config
f = file('config.yml', 'r')
config = yaml.load(f)

def hello():
  print "HI!";

def prepare():
  # Prepare yum dependencies
  sudo('yum update --assumeyes');
  sudo('yum remove postgresql9-libs --assumeyes');
  sudo('''yum install -y 
    xfsprogs
    gcc-c++ 
    patch 
    readline 
    readline-devel 
    zlib zlib-devel
    libyaml-devel 
    libffi-devel 
    openssl-devel 
    make 
    bzip2 
    autoconf 
    automake 
    libtool
    bison 
    iconv-devel 
    python-devel.noarch git  
    --assumeyes'''.replace('\n', ' ') # Transform into one-liner
  );

  # Prepare fab-pg directory
  if (not files.exists('.fab-pg')):
    puts("Creating packages directory..")
    run("mkdir %s" % config['main_dir'])
    run("mkdir %s/packages" % config['main_dir'])
    run("mkdir %s/configs" % config['main_dir'])

  # Prepare system
  if (not files.contains('/etc/sysctl.conf', 'vm.swappiness=0')):
    # Shrink filesystem cache rather than swap out pages
    files.append('/etc/sysctl.conf', 'vm.swappiness=0', use_sudo=True)
  if (not files.contains('/etc/sysctl.conf', 'vm.overcommit_memory=2')):
    # Don't let procs use more memory than the system owns
    files.append('/etc/sysctl.conf', 'vm.overcommit_memory=2', use_sudo=True)


def install():
  # Prepare system
  prepare()

  # Ask user for PostgreSQL version
  version = prompt('PostgreSQL version to install [9.2]:').strip();
  if not version:
    version = '9.2';

  # Verify valid selection
  pg = None
  if version not in config['versions']:
    abort('Invalid choice')
  else:
    pg = config['versions'][version]

  # Persist version to .fab-pg
  sudo('touch %s/version && echo %s > %s/version' %
      (config['main_dir'], version, config['main_dir']))

  # Download YUM package
  package_path = "./.fab-pg/packages/%s.rpm" % pg['alias']
  should_download = True
  if (files.exists(package_path)):
    should_download = confirm("Using existing RPM package?")

  if should_download:
    puts("Downloading %s RPM package \ninto: %s \nfrom: %s" 
        % (version, package_path, pg['RPM']));
  sudo("curl %s > %s" % (pg['RPM'], package_path))

  # Add YUM repository
  sudo("yum install %s" % package_path, warn_only=True)
  
  # Install necessary PostgreSQL packages
  sudo("yum install %s --assumeyes" % ' '.join(pg['packages']))

  # Hand control of data + log directory to postgres user
  data_dir = "/var/lib/pgsql/%s/data" % version
  sudo("chown postgres %s" % data_dir)
  if (not files.exists(config['log_dir'])):
    sudo("touch %s" % config['log_dir'])
  sudo("chown postgres %s" % config['log_dir'])

  # Init db
  if confirm("Do you want to initialize the database now?"):
    run("sudo su postgres -c '/usr/pgsql-%s/bin/pg_ctl initdb -D %s'" %
        (version, data_dir), warn_only=True)
  if confirm("Do you want to start the database now?"):
    run("sudo su postgres -c '/usr/pgsql-%s/bin/pg_ctl start -D %s -l %s'" %
        (version, data_dir, config['log_dir']))


def benchmark(scale=10, clients=10, transactions=10, threads=1):
  # Get active version 
  v_file = open(get("%s/version" % config['main_dir'], 'version')[0], 'r')
  version = v_file.readline().strip()
  puts("Using PostgreSQL %s" % version)
  os.remove(v_file.name)

  # Get bin directory
  bin_dir = "/usr/pgsql-%s/bin" % version
  if (not files.exists(bin_dir)):
    abort("Couldn't find bin directory: %s" % bin_dir)

  # Create benchmarking database
  output = sudo(
      "%s/psql -U postgres -c \"SELECT 1 AS result FROM pg_database" % bin_dir
      + " WHERE datname='pgbench';\"");
  if "1 row" in output:
    puts("Found pgbench database")
  else:
    puts("Creating pgbench database")
    run("sudo su postgres -c '%s/createdb pgbench'" % bin_dir)

  run("sudo su postgres -c '%s/pgbench -i -s %s pgbench'" % (bin_dir, scale))
  run("sudo su postgres -c '%s/pgbench -c %s -t %s -j %s pgbench'" 
      % (bin_dir, clients, transactions, threads))

def mount_data(dev='/dev/xvdf', fs='xfs'):
  # Make sure we got XFS package
  prepare()

  # Sequential read-ahead value
  sudo("blockdev --setra 4096 %s" % dev)

  # Get active version 
  v_file = open(get("%s/version" % config['main_dir'], 'version')[0], 'r')
  version = v_file.readline().strip()
  data_dir = "/var/lib/pgsql/%s/data" % version
  os.remove(v_file.name)
  puts("Using PostgreSQL %s" % version)
  puts("Using PostgreSQL Data Directory %s" % data_dir)

  # Create fresh filesystem on dev
  if (not confirm("*WARNING* This WILL ERASE ALL DATA ON %s. Ok?" % data_dir)):
    abort("Aborting")

  # Create filesystem for device
  puts ("Creating %s filesystem.." % fs)
  sudo("umount %s" % dev, warn_only=True)
  if (fs == 'xfs'):
    # Need to append -f to force
    sudo("mkfs.%s %s -f" % (fs, dev))
  else:
    sudo("mkfs.%s %s" % (fs, dev))
  
  # Mount the postgresql data on device
  sudo("mount %s %s -o noatime" % (dev, data_dir))

  # Put in fstab entry
  fstab_line = "%s  %s  %s  noatime  0  0" % (dev, data_dir, fs)
  if (not files.contains('/etc/fstab', fstab_line, exact=True, use_sudo=True)):
    puts("Appending new filesystem to /etc/fstab")
    files.comment('/etc/fstab', r"^%s" % dev, use_sudo=True)
    files.append('/etc/fstab', fstab_line, use_sudo=True)
  else:
    puts("Fstab already contains entry for %s" % dev)








