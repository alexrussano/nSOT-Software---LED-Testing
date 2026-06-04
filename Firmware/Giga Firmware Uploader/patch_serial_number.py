#!/usr/bin/env python3
import re
import serial
import serial.tools.list_ports
import subprocess
import time
import argparse
import os
import sys

SERIAL_MARKER = b'__SERIAL_NUMBER__'
SERIAL_FIELD_LENGTH = 12

DFU_ADDRESS_READ = "0x08100000:"
DFU_ADDRESS_WRITE = "0x08100000:leave"

TEMP_FIRMWARE = "temp_firmware.bin"


def find_giga_port():
    """Locate the Arduino GIGA based on its description and manufacturer."""
    ports = serial.tools.list_ports.comports()
    for port in ports:
        if port.description and port.manufacturer:
            if "Giga" in port.description and "Arduino" in port.manufacturer:
                return port.device
    return None


def trigger_dfu_mode(port):
    """
    Trigger DFU mode by opening the serial port at 1200 baud.
    This is a common trick on Arduino boards to signal a bootloader reset.
    """
    try:
        with serial.Serial(port, 1200, timeout=1) as ser:
            pass
        print(f"Triggered DFU mode on port {port}.")
        time.sleep(2)
    except Exception as e:
        print(f"Error triggering DFU mode on port {port}: {e}")


def read_firmware_from_board(output_path):
    """
    Uses dfu-util to download (read) the current M4 firmware from the device.
    
    Parameters:
      output_path (str): Temporary filename to store the firmware binary.
    """
    print("Reading current M4 firmware from board using dfu-util...")
    cmd = [
        "dfu-util",
        "-a", "0",
        "-s", DFU_ADDRESS_READ,
        "-U", output_path
    ]
    subprocess.run(cmd, check=True)
    print(f"Firmware successfully read and saved to '{output_path}'.")


def read_serial_from_file(bin_path, marker=SERIAL_MARKER, field_length=SERIAL_FIELD_LENGTH):
    """
    Reads the serial number embedded in the firmware binary.
    
    The function searches for the marker (e.g., '__SERIAL_NUMBER__') and then reads
    the following fixed-length field for the serial number. Trailing NUL bytes are removed.
    
    Parameters:
      bin_path (str): Path to the binary firmware file.
      marker (bytes): Marker indicating the start of the serial number.
      field_length (int): The fixed length allocated for the serial number.
    
    Returns:
      A tuple (serial_str, marker_index) where:
        - serial_str is the serial number (string) or None if not found.
        - marker_index is the starting index of the marker, or None if not found.
    """
    with open(bin_path, "rb") as f:
        data = f.read()
    index = data.find(marker)
    if index == -1:
        print("Serial number marker not found in firmware!")
        return None, None
    serial_start = index + len(marker)
    serial_end = serial_start + field_length
    serial_bytes = data[serial_start:serial_end]
    serial_str = serial_bytes.rstrip(b'\x00').decode("ascii")
    return serial_str, index


def update_serial_in_file(bin_path, new_serial, marker=SERIAL_MARKER, field_length=SERIAL_FIELD_LENGTH):
    """
    Replaces the serial number in the firmware binary with the new serial number.
    
    The serial number field is updated in place: the new serial number (prepended with the marker)
    is padded with NUL bytes to maintain the same length.
    
    Parameters:
      bin_path (str): Path to the firmware binary file.
      new_serial (str): The new serial number string (e.g., 'DA_2025_123').
      marker (bytes): Marker that prefixes the serial number in the binary.
      field_length (int): Fixed length for the serial number field.
    
    Returns:
      True if patching was successful, False otherwise.
    """
    with open(bin_path, "rb") as f:
        data = f.read()

    current_serial, marker_index = read_serial_from_file(bin_path, marker, field_length)
    if current_serial is None:
        print("No serial number found to update in firmware!")
        return False
    
    print(f"Current serial number in firmware: '{current_serial}'")

    old_serial_field = marker + current_serial.encode("ascii")
    old_serial_field = old_serial_field.ljust(len(marker) + field_length, b'\x00')

    new_serial_field = marker + new_serial.encode("ascii")
    new_serial_field = new_serial_field.ljust(len(marker) + field_length, b'\x00')

    if old_serial_field not in data:
        print("Old serial field not found in the firmware data!")
        return False

    new_data = data.replace(old_serial_field, new_serial_field, 1)
    with open(bin_path, "wb") as f:
        f.write(new_data)
    print(f"Firmware serial number updated to '{new_serial}'.")
    return True


def flash_firmware_to_board(firmware_path):
    """
    Uses dfu-util to flash the firmware binary back to the M4.
    
    Parameters:
      firmware_path (str): Path to the firmware file to flash.
    """
    print("Flashing updated firmware back to the board...")
    cmd = [
        "dfu-util",
        "-a", "0",
        "-s", DFU_ADDRESS_WRITE,
        "-D", firmware_path
    ]
    subprocess.run(cmd, check=True)
    print("Firmware flashed successfully.")


def nop_test(port, expected_serial_number):
  try:
      with serial.Serial(port, 115200, timeout=2) as ser:
          print()
          print(f"Testing NOP on {ser.port}...")
          
          ser.write("NOP\r\n".encode())
          
          response = ser.readline().decode().strip()
          
          if response == "NOP":
              print("NOP test passed: Correct response received.")
          else:
              print(f"NOP test failed: Expected 'nop', but received '{response}'")
              return
          
          ser.write("*IDN?\r\n".encode())
          id = ser.readline().decode().strip()
          
          ser.write("SERIAL_NUMBER\r\n".encode())
          serial_number = ser.readline().decode().strip()
          
          print()
          print(f"ID: {id}, Serial Number: {serial_number}")
          if serial_number != expected_serial_number:
              print(f"Serial number mismatch: Expected {expected_serial_number}, but got {serial_number}")
              return
          print(f"Firmware successfully uploaded.")
          
  except Exception as e:
      print(f"Error during NOP test: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Read the current M4 firmware from Arduino GIGA, update its serial number, and flash it back."
    )
    parser.add_argument(
        "serial_number",
        type=str,
        help="New serial number to patch into the firmware (format e.g., 123)"
    )
    args = parser.parse_args()

    if not re.fullmatch('.{0,3}', args.serial_number):
        print("Error: Invalid serial number format. Expected format is up to three characters.")
        sys.exit(1)
    
    serial_number = str(args.serial_number)
    while len(serial_number) < 3:
      serial_number = "0" + serial_number
    serial_number = f"DA_2025_{serial_number}"

    port = find_giga_port()
    if port is None:
        print("Arduino GIGA not found. Make sure it is connected.")
        sys.exit(1)
    print(f"Found Arduino GIGA on port: {port}")
    
    if os.path.exists(TEMP_FIRMWARE):
      print(f"Temporary firmware file '{TEMP_FIRMWARE}' already exists. Deleting it.")
      os.remove(TEMP_FIRMWARE)

    trigger_dfu_mode(port)

    try:
        read_firmware_from_board(TEMP_FIRMWARE)
    except subprocess.CalledProcessError as e:
        print(f"Error reading firmware: {e}")
        sys.exit(1)

    current_serial, _ = read_serial_from_file(TEMP_FIRMWARE)
    if current_serial:
        print(f"Firmware currently contains serial number: '{current_serial}'")
    else:
        print("No serial number found in firmware; proceeding with update anyway.")
 
    if not update_serial_in_file(TEMP_FIRMWARE, serial_number):
        print("Failed to update the serial number in firmware.")
        sys.exit(1)

    try:
        flash_firmware_to_board(TEMP_FIRMWARE)
    except subprocess.CalledProcessError as e:
        print(f"Error flashing firmware: {e}")
        sys.exit(1)

    print("Validating...")
    nop_test(port, serial_number)
    
    try:
        if os.path.exists(TEMP_FIRMWARE):
            os.remove(TEMP_FIRMWARE)
    except OSError as e:
        print(f"Error deleting temporary file {TEMP_FIRMWARE}: {e}")


if __name__ == "__main__":
    main()