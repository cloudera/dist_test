import struct
import os

lines = open("classes", "r").readlines()
total = 0
count = 0
for l in lines:
    filename, flags = l.split(" ")
    flags = int(flags)
    if flags & 0x0400:
        print os.path.basename(filename), bin(flags)
        count += 1
    total += 1

print count, "of", total
