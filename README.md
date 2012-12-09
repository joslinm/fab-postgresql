fab-postgresql
=============
A small fab file to get postgresql installed on a RHES Linux system. 

Commands
========
* install
* benchmark(scale=10, clients=10, transactions=10, threads=1)
* mount_data(dev='/dev/xvdf', fs='xfs') <-- **CHANGE DEVICE**

Usage
=======
`fab mount_data:dev=/dev/xvd, fs=ext4`