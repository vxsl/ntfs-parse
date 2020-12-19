# recoverability

A Windows application to determine whether there is any hope of recovering data from a corrupt disk. Requires a copy of some file that you know *used to* exist on the disk. `recoverability` will attempt to rebuild this file using only blocks from the disk in question, even if the data is far from contiguous. 

The source file is broken up into 512-byte sectors and the chosen disk is searched to find matching sectors. "Express Mode" skims the disk at an interval dependent on the size of the source file, and when a single match has been found, a new thread begins a forward-backward serial reading of the area around the address. As a result, the searching process is greatly expedited, and a 12 TB disk (with a 3 MB source file) can be fully searched and parsed with high accuracy in as little as 4 hours.

If you already have an idea of the general location of your data of interest, you can choose a hexadecimal address at which to begin your search.

Note that this program currently relies on a multithreaded approach. Performance on systems with low thread counts has not yet been tested. 
