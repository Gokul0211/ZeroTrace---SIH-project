# research/telemetry_export.py
import csv
import os

def export_to_csv(dataset: list, path: str = "/mnt/usb_export/firmware_benchmarks.csv"):
    if not dataset:
        return
        
    os.makedirs(os.path.dirname(path), exist_ok=True)
    file_exists = os.path.isfile(path)
    
    with open(path, mode='a', newline='') as f:
        # Use keys from first dict
        keys = list(dataset[0].keys())
        # Make sure "error" isn't the only key
        if "error" in keys and len(keys) == 1:
             pass # skip errors
             
        writer = csv.DictWriter(f, fieldnames=keys)
        if not file_exists:
            writer.writeheader()
        writer.writerows(dataset)
