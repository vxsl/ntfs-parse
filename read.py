import sys, time, gzip
import io
import zlib


def parseAls(startAddr):
    print("\n\ntrying to parse a .als file at ", startAddr, " ...")
    disk.seek(startAddr)
    try:
        unzipper = zlib.decompressobj(32 + zlib.MAX_WBITS)
        unzipped = unzipper.decompress(disk.read(500000))        
        f = open(hex(startAddr)+".als", "wb")    
        f.write(unzipped)
        f.close()
        print("Success. [", hex(startAddr), " -> ", hex(disk.tell()), "]" )
    except Exception as e: 
        print("Something went wrong. Guess this wasn't a .als file.")
    


#disk = open("\\\\.\\PhysicalDrive1", 'r+b')
#disk = open(r"\\.\PhysicalDrive1", 'rb')
disk = open(r"\\.\E:", 'rb')

startFlag = False

disk.seek(int("3e600", 16))
print(disk.tell())

while True:
    #print (hex(disk.tell()))
    seq = disk.read(8).hex()
    if seq == "1f8b080000000000":        
        print("gzip signature found at address ", disk.tell(), " -- possible .als file")
        if startFlag == False:
            startFlag = True
            startPos = seq            
            #thread.start_new_thread(parseAls(disk.tell() - 8))
            parseAls(disk.tell() - 8)
            print(hex(disk.tell()))
            startFlag = False
        else:
            print("overlap")
    
