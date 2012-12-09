from fabric.api import run, sudo
from fabric.context_managers import cd
from fabric.operations import sudo, prompt, get
from fabric.api import run, env, settings
from fabric.utils import puts, warn, abort
from fabric.contrib import files
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
  global config

  # Prepare yum dependencies
  sudo('yum update --assumeyes');
  sudo('yum remove postgresql9-libs --assumeyes');
  sudo('''yum install -y 
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

  if (not files.exists('.fab-pg')):
    puts("Creating packages directory..")
    run("mkdir %s" % config['main_dir'])
    run("mkdir %s/packages" % config['main_dir'])
    run("mkdir %s/configs" % config['main_dir'])

def install():
  # Prepare system
  prepare()

  # Ask user for PostgreSQL version
  version = prompt('PostgreSQL version to install [9.2]:').strip();
  if not version:
    version = '9.2';

  # Verify valid selection
  active_package = None
  if version not in config['versions']:
    abort('Invalid choice')
  else:
    active_package = config['versions'][version]

  # Download YUM package
  package_path = "./.fab-pg/packages/%s.rpm" % active_package['alias']
  should_download = True
  if (files.exists("./packages/%s" % package_path)):
    should_download = confirm("Using existing RPM package? [Y/n]")

  puts("Downloading %s RPM package \ninto: %s \nfrom: %s" 
      % (version, package_path, active_package['RPM']));
  sudo("curl %s > %s" % (active_package['RPM'], package_path))

  # Add YUM repository
  sudo("yum install %s" % package_path, warn_only=True)
  
  # Install necessary PostgreSQL packages
  sudo('''yum install --assumeyes
    postgresql92-contrib.x86_64
    postgresql92-devel.x86_64
    postgresql92-server.x86_64
    postgresql92-test.x86_64'''.replace('\n', ' '))
  
  
