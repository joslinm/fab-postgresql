from fabric.api import run, sudo
from fabric.context_managers import cd
from fabric.operations import sudo, prompt, get, put
from fabric.api import run, env, settings
from fabric.utils import puts, warn, abort
from fabric.contrib import files
from fabric.contrib.console import confirm
import os
import yaml
import tempfile

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
    run("mkdir %s" % config['main_dir'])
  if (not files.exists("%s/packages" % config['main_dir'])):
    run("mkdir %s/packages" % config['main_dir'])
  if (not files.exists("%s/configs" % config['main_dir'])):
    run("mkdir %s/configs" % config['main_dir'])
  if (not files.exists("%s/wals" % config['main_dir'])):
    run("mkdir %s/wals" % config['main_dir'])

  # Prepare system
  if (not files.contains('/etc/sysctl.conf', 'vm.swappiness=0')):
    # Shrink filesystem cache rather than swap out pages
    files.append('/etc/sysctl.conf', 'vm.swappiness=0', use_sudo=True)


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
  init()
  if confirm("Do you want to start the database now?"):
    start()

def init():
  version = read_remote_file(config['main_dir'] + '/version')
  data_dir = "/var/lib/pgsql/%s/data" % version
  if confirm("Do you want to initialize the database now?"):
    sudo("rm -r %s" % data_dir, warn_only=True)
    # sudo("mkdir %s" % data_dir)

    # # Hand control of data + log directory to postgres user
    # data_dir = "/var/lib/pgsql/%s/data" % version
    # sudo("chown postgres %s" % data_dir)
    if (not files.exists(config['log_dir'])):
      sudo("touch %s" % config['log_dir'])
    sudo("chown postgres %s" % config['log_dir'])
    run("sudo su postgres -c '/usr/pgsql-%s/bin/pg_ctl initdb -D %s'" %
        (version, data_dir), warn_only=True)

def start():
  version = read_remote_file(config['main_dir'] + '/version')
  data_dir = "/var/lib/pgsql/%s/data" % version
  run("sudo su postgres -c '/usr/pgsql-%s/bin/pg_ctl start -D %s -l %s'" %
        (version, data_dir, config['log_dir']))

def stop():
  version = read_remote_file(config['main_dir'] + '/version')
  data_dir = "/var/lib/pgsql/%s/data" % version
  run("sudo su postgres -c '/usr/pgsql-%s/bin/pg_ctl stop -D %s'" %
        (version, data_dir), warn_only=True)

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

def read_remote_file(filename):
  f = open(get(filename, "%(host)s-tmp-%(basename)s")[0], 'r')
  data = f.readline().strip()
  os.remove(f.name)
  return data

def write_remote_file(remote_path, data):
  fh = tempfile.NamedTemporaryFile(mode='w+b')
  fh.write(data)
  fh.flush()
  put(fh.name, remote_path, use_sudo=True)
  fh.close()

def delete_value(namespace, key):
  path = "%s/config/%s.yml" % (config['main_dir'], namespace)
  data = read_remote_file(path)
  values = yaml.load(data)
  if key in values:
    del values[key]
    write_remote_file(path, yaml.dump(values))

def persist_value(namespace, key, value):
  path = "%s/configs/%s.yml" % (config['main_dir'], namespace)
  if not files.exists(path):
    values = { key: value }
    write_remote_file(path, yaml.dump(values))
  else:
    # Get values
    data = read_remote_file(path)
    values = yaml.load(data)
    
    # Alter/create values dictionary
    if (values):
      values[key] = value
    else:
      values = { key: value }

    # Write out to server
    yml = yaml.dump(values)
    write_remote_file(path, yml)

def create_volume(size, avail_zone='us-east-1d', fs='ext4'):
   output = run("ec2-create-volume --size %s --availability-zone %s -O %s -W %s"
        % (size, avail_zone, config['access_key'], config['secret_key']));

   pattern = re.compile(r"(?P<name>vol-\d+)")
   match = pattern.match(output)
   volume = None
   if match:
     volume = match.groupdict()['name']
     puts("Got volume: %s" % volume)
   else:
     abort("Couldn't find volume in\n%s" % output)

   return volume

def attach_volume(vol, dev):
  # Get instance ID
  instance_id = run('wget -q -O -'
      ' http://169.254.169.254/latest/meta-data/instance-id')

  # Attach via ec2 cmd line tools
  puts("Instance ID: '%s'" % instance_id)
  run("ec2-attach-volume %s -i %s -d %s -O %s -W %s"
      % (vol, instance_id, dev, config['access_key'], config['secret_key']))

  # Append a dictionary entry of new device
  persist_value('volumes', dev, vol)

def mount(dev, path, fs_type, no_atime=True):
  # Make sure we got XFS package
  prepare()

  # Turn up the sequential read-ahead value (defaults 256)
  sudo("blockdev --setra 4096 %s" % dev)

  # Create fresh filesystem on dev
  if (not confirm("*WARNING* This WILL ERASE ALL DATA ON %s. Ok?" % path)):
    abort("Aborting")

  # Create filesystem for device
  puts ("Creating %s filesystem on %s" % (fs_type, path))
  sudo("umount %s" % dev, warn_only=True)
  if (fs_type == 'xfs'):
    # Need to append -f to force
    sudo("mkfs.%s %s -f" % (fs_type, dev))
  else:
    sudo("mkfs.%s %s" % (fs_type, dev))

  # Mount the path on device
  if (no_atime):
    sudo("mount %s %s -o noatime" % (dev, path))
  else:
    sudo("mount %s %s" % (dev, path))

  # Put in fstab entry
  fstab_line = "%s  %s  %s  noatime  0  0" % (dev, path, fs_type)
  if (not files.contains('/etc/fstab', fstab_line, exact=True, use_sudo=True)):
    puts("Appending new filesystem to /etc/fstab")
    files.comment('/etc/fstab', r"^%s" % dev, use_sudo=True)
    files.append('/etc/fstab', fstab_line, use_sudo=True)
  else:
    puts("Fstab already contains entry for %s" % dev)

  # Append a dictionary entry of new device
  persist_value('mounts', dev, mount)

def mount_wal(dev, fs='ext4'):
  stop()

  # Get active version 
  version = read_remote_file("%s/version" % config['main_dir'])

  # Turn up the sequential read-ahead value (defaults 256)
  sudo("blockdev --setra 4096 %s" % dev)

  # Backup
  dest_dir = "/var/lib/pgsql/%s/data/pg_xlog" % version
  sudo("cp -r %s %s.bak" % (dest_dir, dest_dir))
  mount(dev, dest_dir, fs)
  sudo("chown postgres %s" % dest_dir)
  sudo("mv %s.bak/* %s" % (dest_dir, dest_dir))
  start()

def mount_data(dev, fs='ext4'):
  # Get active version 
  v_file = open(get("%s/version" % config['main_dir'], 'version')[0], 'r')
  version = v_file.readline().strip()
  data_dir = "/var/lib/pgsql/%s/data" % version
  os.remove(v_file.name)
  puts("Using PostgreSQL %s" % version)
  puts("Using PostgreSQL Data Directory %s" % data_dir)

  # Mount dev with fs type to data_dir
  mount(dev, data_dir, fs)
