import re
import serial
import time
import os
import subprocess
import serial.tools.list_ports
import argparse

def read_serial(bin_path, marker=b'__SERIAL_NUMBER__'):
    with open(bin_path, 'rb') as f:
        data = f.read()

    index = data.find(marker)
    if index == -1:
        print("Serial number not found.")
        return None

    serial_bytes = data[index + 17:index + 29]

    serial = serial_bytes.rstrip(b'\x00').decode('ascii')

    return serial


def patch_serial(bin_path, new_serial, output_path):
    with open(bin_path, 'rb') as f:
        data = f.read()
    
    new_serial = "__SERIAL_NUMBER__" + new_serial
    
    old_serial = read_serial(bin_path)
    
    print(f"Found old serial number: {old_serial}")

    old_serial = ("__SERIAL_NUMBER__" + old_serial).encode('ascii')
    
    if old_serial is None:
        print("No serial number found to patch.")
        return
    
    new_serial_bytes = new_serial.encode('ascii')
    new_serial_bytes = new_serial_bytes.ljust(len(old_serial), b'\x00')

    if old_serial not in data:
        print("Placeholder not found.")
        return

    data = data.replace(old_serial, new_serial_bytes, 1)

    with open(output_path, 'wb') as f:
        f.write(data)

    print(f"Patched and saved to {output_path}")

def find_giga_port():
    ports = serial.tools.list_ports.comports()
    for port in ports:
        if port.description is not None and port.manufacturer is not None and "Giga" in port.description and "Arduino" in port.manufacturer:
            return port.device
    return None

def trigger_dfu_mode(port):
    try:
        with serial.Serial(port, 1200, timeout=1) as ser:
            ser.close()
            print(f"Triggered DFU mode on {port}.")
        time.sleep(2)
    except Exception as e:
        print(f"Error triggering DFU mode: {e}")

def upload_firmwareM4(firmware_name, serial_number):
    try:
        script_dir = os.path.dirname(os.path.realpath(__file__))
        firmware_path = os.path.join(script_dir, 'firmware', firmware_name)
        
        if serial_number is None:
            print("No serial number provided!")
            return
        if not re.fullmatch('DA_2025_.{3}', serial_number):
            print("Invalid serial number format!")
            print("Expected format: DA_2025_XXX")
            return
        
        patch_serial(firmware_path, serial_number, firmware_path)
        
        subprocess.run([
            "dfu-util",
            "-a", "0",
            "-s", "0x08100000:leave",
            "-D", firmware_path
        ], check=True)
        print(f"M{firmware_name[9]} firmware uploaded successfully!")
    except subprocess.CalledProcessError as e:
        print(f"Error uploading firmware: {e}")

def upload_firmwareM7(firmware_name):
    try:
        script_dir = os.path.dirname(os.path.realpath(__file__))
        firmware_path = os.path.join(script_dir, 'firmware', firmware_name)
        subprocess.run([
            "dfu-util",
            "-a", "0",
            "-s", "0x08040000:leave",
            "-D", firmware_path
        ], check=True)
        print(f"M{firmware_name[9]} firmware uploaded successfully!")
    except subprocess.CalledProcessError as e:
        print(f"Error uploading firmware: {e}")

def nop_test(expected_serial_number):
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

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Upload firmware to Arduino GIGA.')
    
    parser.add_argument('target', type=str, help='The target firmware to upload.', choices=['new_hardware', 'old_hardware', 'new_shield_old_dac_adc'], default='new_hardware')
    
    parser.add_argument('serial_number', type=str, help='Serial number to patch in the firmware.', default=None)
    
    args = parser.parse_args()
    
    script_dir = os.path.dirname(os.path.realpath(__file__))
    firmware_path_m7 = os.path.join(script_dir, 'firmware', "firmwareM7.bin")
    firmware_path_m4 = os.path.join(script_dir, 'firmware', f"firmwareM4_{args.target}.bin")
    if not os.path.exists(firmware_path_m4):
        print(f"Error: Firmware file '{firmware_path_m4}' not found.")
        exit(1)
    if not os.path.exists(firmware_path_m7):
        print(f"Error: Firmware file '{firmware_path_m7}' not found.")
        exit(1)
    if args.serial_number is None:
        print("Error: Serial number is required.")
        exit(1)
    if not re.fullmatch('.{3}', args.serial_number):
        print("Error: Invalid serial number format.")
        print("Expected format is 3 characters!")
        exit(1)
    
    port = find_giga_port()
    if port:
        print()
        print(f"Found Arduino GIGA on {port}")
        print("Uploading M7 firmware...")
        trigger_dfu_mode(port)
        time.sleep(0.5)
        upload_firmwareM7('firmwareM7.bin')
        
        print()
        print("Waiting for M7 firmware to boot...")
        time.sleep(2)
        print("Uploading M4 firmware...")
        trigger_dfu_mode(port)
        time.sleep(0.5)
        upload_firmwareM4(f'firmwareM4_{args.target}.bin', f"DA_2025_{args.serial_number}")
        print()
        print("Waiting for M4 firmware to boot...")
        time.sleep(2)
        
        nop_test(f"DA_2025_{args.serial_number}")
    else:
        print("Arduino GIGA not found. Make sure it is connected.")
