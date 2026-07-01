#!/usr/bin/env python3
import re

with open('ai_ui_utils.py', 'rb') as f:
    content = f.read()

lines = content.split(b'\n')

line_195 = lines[194]
print('Line 195 full hex dump:')
for i in range(0, len(line_195), 16):
    chunk = line_195[i:i+16]
    hex_str = ' '.join(f'{b:02x}' for b in chunk)
    ascii_str = ''.join(chr(b) if 32 <= b < 127 else '.' for b in chunk)
    print(f'{i:4d}: {hex_str}')

print()
print('Check if line ends with backslash before newline:')
print(f'Last bytes before newline: {line_195[-5:].hex()}')

# Check for literal backslash-n sequence (0x5c 0x6e)
if b'\\n' in line_195:
    print('FOUND literal backslash-n sequence!')
    for i, b in enumerate(line_195):
        if i > 0 and line_195[i-1] == 0x5c and line_195[i] == 0x6e:
            print(f'  Position {i-1}: \\n sequence')

# Check for 0x5c followed by newline
last_bytes = line_195[-3:]
print(f'Last 3 bytes: {last_bytes.hex()} = {[hex(b) for b in last_bytes]}')