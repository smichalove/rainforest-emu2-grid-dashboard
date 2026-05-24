import serial
import xml.etree.ElementTree as ET
import time
import sys

def hex_to_signed_int(hex_str, bits=32):
    val = int(hex_str, 16)
    if (val & (1 << (bits - 1))) != 0:
        val = val - (1 << bits)
    return val

def process_chunk(xml_data):
    try:
        root = ET.fromstring(xml_data)
        if root.tag == 'InstantaneousDemand':
            demand_hex = root.find('Demand').text
            multiplier_hex = root.find('Multiplier').text
            divisor_hex = root.find('Divisor').text
            
            demand = hex_to_signed_int(demand_hex)
            multiplier = int(multiplier_hex, 16)
            divisor = int(divisor_hex, 16)
            
            if divisor == 0:
                return
                
            actual_kw = (demand * multiplier) / divisor
            
            status = "Exporting (Solar)" if actual_kw < 0 else "Importing (Grid)"
            # Print with flush so it appears immediately
            print(f"[{time.strftime('%H:%M:%S')}] Grid Usage: {actual_kw:.3f} kW | {status}")
            sys.stdout.flush()
    except Exception as e:
        pass

def main():
    print("Starting EMU-2 Grid Usage Monitor...")
    sys.stdout.flush()
    try:
        ser = serial.Serial('/dev/ttyACM0', 115200, timeout=1)
    except Exception as e:
        print(f"Failed to open port: {e}")
        return

    buffer = ""
    while True:
        try:
            data = ser.read(ser.in_waiting or 1)
            if data:
                buffer += data.decode('utf-8', errors='ignore')
                
                while '<InstantaneousDemand>' in buffer and '</InstantaneousDemand>' in buffer:
                    start = buffer.find('<InstantaneousDemand>')
                    end = buffer.find('</InstantaneousDemand>') + len('</InstantaneousDemand>')
                    
                    chunk = buffer[start:end]
                    process_chunk(chunk)
                    
                    buffer = buffer[end:]
        except KeyboardInterrupt:
            break
        except Exception as e:
            break

if __name__ == "__main__":
    main()
