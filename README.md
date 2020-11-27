# ntfs-toolbox

WIP

A growing collection of utilities to provide helpful information regarding diagnostics and partial recovery of raw disks containing remnants of NTFS-formatted data. Could be useful in a forensics context, or simply to assist with manual data recovery on a volume that appears 'unrecoverable' through typical means.

Each subprogram reads data from the disk at a binary level and parses for a particular goal. 

## raw_gz

Searches for .gzip signatures and unzips as much of the archive as is available serially. Saves results. There is also an option to recover .als (Ableton Live Set) files, as these are simply gzipped XML files. 

## recreate_file

This is currently the most fully-developed subprogram. A source file is broken up into 512-byte sectors and the chosen disk is searched to find matching sectors. "Express Mode" skims the disk at an interval dependent on the size of the source file, and when a single match has been found, a new thread begins a forward-backward serial reading of the area around the address. As a result, the searching process is greatly expedited, and a 12 TB disk (with a 3 MB source file) can be fully searched and parsed with high accuracy in as little as 4 hours.

If you already have an idea of the general location of your data of interest, you can choose a hexadecimal address at which to begin your search.

Note that this program currently relies on a multithreaded approach. Performance on systems with low thread counts has not yet been tested. 
