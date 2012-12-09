from fabric.api import run, sudo
from fabric.context_managers import cd
from fabric.operations import sudo
from fabric.api import run, env
import os

HOME = os.getenv('HOME')

env.user = 'ec2-user'
env.key_filename = [
    '%s/key.pem'%HOME
] #assuming key

def hello():
  print "HI!";

def install(config='standard'):
  sudo('echo hi');
