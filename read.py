import sys, time, gzip
import io
import zlib
import gzip
import re
import os, time
import config
from PerformanceCalc import PerformanceCalc
import shutil


def parseAls(tmpFileName):
    print("trying to parse a .als file in ", tmpFileName, " ...")
    tmpFile = open(tmpFileName, "rb")

    try:

        unzipper = zlib.decompressobj(32 + zlib.MAX_WBITS)
        unzipped = unzipper.decompress(tmpFile.read())   
        split = unzipped.split(b'<')
        if split[1][0:4] != b'?xml':
            #print("not an XML file")
            tmpFile.close()
            os.remove(tmpFileName)
            return
        else:            
            if split[2][0:7] != b"Ableton":
                #print("not a .als file")
                os.remove(tmpFileName)
                return
            else:                
                als = open(tmpFileName.split(".")[0]+".als", "wb")    
                als.write(unzipped)
                als.close()
                tmpFile.close()            
                os.remove(tmpFileName)
                print("Success: " + als.name)
    
    except Exception as e:
        tmpFile.close()            
        os.remove(tmpFileName)
        print("Decompression failed: " + e.args[0])
        return
    
#diskPath = r"\\."
#diskPath += "\\" + config.LOGICAL_VOLUME + ":"
diskPath = r"\\.\D:"

disk = os.open(diskPath, os.O_RDONLY | os.O_BINARY)
fileObj = os.fdopen(disk, 'rb')

perf = PerformanceCalc(disk, fileObj)

blockInProgress = -1

while True:
    start = time.perf_counter()
    #data = os.read(disk, 512)    
    data = fileObj.read(512)
    stop = time.perf_counter()
    perf.iteration(stop - start)

    if data.hex()[0:16] == "1f8b080000000000":
        if blockInProgress != -1:
            f.close()
            parseAls(f.name)
            #print("\ngzip signature found at address ", hex(disk.tell() - 8), " -- possible .als file")        
        f = open("block" + hex(fileObj.tell() - 512)+".tmp", "wb")    
        blockInProgress = fileObj.tell() - 512
            

    if blockInProgress != -1:
        f.write(data)
            
    #print(data.hex())
    #print(hex(fileObj.tell()))


