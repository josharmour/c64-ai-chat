#!/usr/bin/env python3
"""
bas2prg - C64 BASIC Tokenizer
Converts ASCII BASIC text files to authentic C64 PRG binary format.
"""

import sys
import struct

# C64 BASIC V2 load address
LOAD_ADDRESS = 0x0801

# BASIC V2 keyword tokens - order matters: longer keywords first
BASIC_TOKENS = [
    # Statements
    ("PRINT#", 0x98),
    ("CMD", 0x9D),
    ("SYS", 0x9E),
    ("OPEN", 0x9F),
    ("CLOSE", 0xA0),
    ("GET", 0xA1),
    ("INPUT#", 0x84),
    ("INPUT", 0x85),
    ("READ", 0x87),
    ("RESTORE", 0x8C),
    ("DIM", 0x86),
    ("DATA", 0x83),
    ("PRINT", 0x99),
    ("LIST", 0x9B),
    ("CLR", 0x9C),
    ("FOR", 0x81),
    ("NEXT", 0x82),
    ("GOTO", 0x89),
    ("GOSUB", 0x8D),
    ("RETURN", 0x8E),
    ("REM", 0x8F),
    ("STOP", 0x90),
    ("ON", 0x91),
    ("WAIT", 0x92),
    ("LOAD", 0x93),
    ("SAVE", 0x94),
    ("VERIFY", 0x95),
    ("DEF", 0x96),
    ("POKE", 0x97),
    ("NEW", 0xA2),
    ("TAB(", 0xA3),
    ("TO", 0xA4),
    ("FN", 0xA5),
    ("SPC(", 0xA6),
    ("THEN", 0xA7),
    ("NOT", 0xA8),
    ("STEP", 0xA9),
    ("IF", 0x8B),
    ("LET", 0x88),
    ("RUN", 0x8A),
    ("END", 0x80),
    ("CONT", 0x9A),
    # Operators
    ("+", 0xAA),
    ("-", 0xAB),
    ("*", 0xAC),
    ("/", 0xAD),
    ("^", 0xAE),
    ("AND", 0xAF),
    ("OR", 0xB0),
    (">", 0xB1),
    ("=", 0xB2),
    ("<", 0xB3),
    # Functions
    ("SGN", 0xB4),
    ("INT", 0xB5),
    ("ABS", 0xB6),
    ("USR", 0xB7),
    ("FRE", 0xB8),
    ("POS", 0xB9),
    ("SQR", 0xBA),
    ("RND", 0xBB),
    ("LOG", 0xBC),
    ("EXP", 0xBD),
    ("COS", 0xBE),
    ("SIN", 0xBF),
    ("TAN", 0xC0),
    ("ATN", 0xC1),
    ("PEEK", 0xC2),
    ("LEN", 0xC3),
    ("STR$", 0xC4),
    ("VAL", 0xC5),
    ("ASC", 0xC6),
    ("CHR$", 0xC7),
    ("LEFT$", 0xC8),
    ("RIGHT$", 0xC9),
    ("MID$", 0xCA),
    ("GO", 0xCB),
]


def tokenize_line(text):
    """Convert a single BASIC line (without line number) to tokenized bytes."""
    result = bytearray()
    i = 0
    in_quotes = False
    in_rem = False
    in_data = False

    while i < len(text):
        ch = text[i]

        # Inside a quoted string - copy verbatim
        if in_quotes:
            result.append(ord(ch))
            if ch == '"':
                in_quotes = False
            i += 1
            continue

        # After REM token - copy entire rest of line verbatim
        if in_rem:
            result.append(ord(ch))
            i += 1
            continue

        # After DATA token - copy verbatim until colon or EOL
        if in_data:
            if ch == ':':
                in_data = False
                # Don't append colon yet - fall through to tokenizer
            else:
                result.append(ord(ch))
                i += 1
                continue

        # Check for start of quoted string
        if ch == '"':
            in_quotes = True
            result.append(ord(ch))
            i += 1
            continue

        # ? is shorthand for PRINT
        if ch == '?':
            result.append(0x99)
            i += 1
            continue

        # Try to match keywords (case-insensitive)
        upper_rest = text[i:].upper()
        matched = False
        for keyword, token in BASIC_TOKENS:
            if upper_rest.startswith(keyword):
                result.append(token)
                i += len(keyword)
                matched = True
                # Check for special tokens
                if token == 0x8F:  # REM
                    in_rem = True
                elif token == 0x83:  # DATA
                    in_data = True
                break

        if not matched:
            result.append(ord(ch))
            i += 1

    return bytes(result)


def parse_basic_lines(input_path):
    """Read a BASIC text file and return list of (line_number, text) tuples."""
    lines = []
    with open(input_path, 'r') as f:
        for raw_line in f:
            raw_line = raw_line.rstrip('\n').rstrip('\r')
            if not raw_line.strip():
                continue

            # Extract line number
            stripped = raw_line.lstrip()
            num_str = ""
            idx = 0
            while idx < len(stripped) and stripped[idx].isdigit():
                num_str += stripped[idx]
                idx += 1

            if not num_str:
                continue  # Skip lines without a line number

            line_num = int(num_str)
            # Skip whitespace after line number
            while idx < len(stripped) and stripped[idx] == ' ':
                idx += 1
            code = stripped[idx:]
            lines.append((line_num, code))

    return lines


def build_prg(basic_lines):
    """
    Build a complete PRG binary from parsed BASIC lines.
    Format:
      - 2-byte load address (little-endian, $0801)
      - For each line:
        - 2-byte pointer to next line (absolute address, little-endian)
        - 2-byte line number (little-endian)
        - N bytes: tokenized BASIC text
        - 1-byte: 0x00 (line terminator)
      - 2-byte end marker: 0x00 0x00
    """
    prg = bytearray()
    # Load address header
    prg += struct.pack('<H', LOAD_ADDRESS)

    current_addr = LOAD_ADDRESS

    tokenized_lines = []
    for line_num, code in basic_lines:
        tokens = tokenize_line(code)
        tokenized_lines.append((line_num, tokens))

    for i, (line_num, tokens) in enumerate(tokenized_lines):
        # Calculate next line address:
        # 2 (next ptr) + 2 (line num) + len(tokens) + 1 (null terminator)
        line_size = 2 + 2 + len(tokens) + 1
        next_addr = current_addr + line_size

        # Next line pointer
        prg += struct.pack('<H', next_addr)
        # Line number
        prg += struct.pack('<H', line_num)
        # Tokenized code
        prg += tokens
        # Null terminator
        prg.append(0x00)

        current_addr = next_addr

    # End-of-program marker
    prg += struct.pack('<H', 0x0000)

    return bytes(prg)


def bas_to_prg(input_path, output_path):
    """Main entry point: convert .bas file to .prg file."""
    basic_lines = parse_basic_lines(input_path)
    if not basic_lines:
        print("Error: No BASIC lines found in input file.")
        sys.exit(1)

    prg_data = build_prg(basic_lines)

    with open(output_path, 'wb') as f:
        f.write(prg_data)

    print(f"=== bas2prg - C64 BASIC Tokenizer ===")
    print(f"Input:  {input_path}")
    print(f"Output: {output_path}")
    print(f"Lines:  {len(basic_lines)}")
    print(f"Size:   {len(prg_data)} bytes (including 2-byte load address)")
    print(f"Load address: ${LOAD_ADDRESS:04X}")
    print()

    # Show tokenization details
    for line_num, code in basic_lines:
        tokens = tokenize_line(code)
        hex_str = ' '.join(f'{b:02X}' for b in tokens)
        print(f"  {line_num:>5}: {code}")
        print(f"         [{hex_str}]")

    print()
    print(f"Done! Transfer {output_path} to your Ultimate 64")
    print(f"and use: LOAD \"{output_path.replace('.prg','').upper()}\",8,1")
    print(f"then:    RUN")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python3 bas2prg.py input.bas output.prg")
        sys.exit(1)
    bas_to_prg(sys.argv[1], sys.argv[2])
