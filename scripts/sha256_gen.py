#!/usr/bin/env python3
import hashlib
import hmac
import sys

def simple_concat_hash(device_id, secret):
    """Simple concatenation: SHA256(device_id + secret)"""
    combined = device_id + secret
    return hashlib.sha256(combined.encode('utf-8')).hexdigest()

def hmac_hash(device_id, secret):
    """HMAC-SHA256 using secret as key and device_id as message"""
    return hmac.new(secret.encode('utf-8'), device_id.encode('utf-8'), hashlib.sha256).hexdigest()

def salted_hash(device_id, secret):
    """Salted hash: SHA256(secret + device_id + secret)"""
    combined = secret + device_id + secret
    return hashlib.sha256(combined.encode('utf-8')).hexdigest()

def main():
    # Default values
    device_id = "123456789"
    secret = "7JijoHPvHXyHjajDK00V"
    
    # Check for command line arguments
    if len(sys.argv) >= 3:
        device_id = sys.argv[1]
        secret = sys.argv[2]
    elif len(sys.argv) == 2:
        print("Usage: python3 sha256_gen.py <device_id> <secret>")
        print("Or run without arguments to use defaults")
        return
    
    print(f"Device ID: {device_id}")
    print(f"Secret: {secret}")
    print("-" * 60)
    
    # Generate different types of hashes
    concat_hash = simple_concat_hash(device_id, secret)
    hmac_result = hmac_hash(device_id, secret)
    salt_hash = salted_hash(device_id, secret)
    
    print(f"Simple Concat: {concat_hash}")
    print(f"HMAC-SHA256:   {hmac_result}")
    print(f"Salted Hash:   {salt_hash}")
    
    # Generate sample data format
    print("\n" + "="*60)
    print("SAMPLE DATA FORMAT:")
    print("="*60)
    print(f"{device_id}, {concat_hash}")
    print("1669734897, 1669734897, 46.123456, 8.654321, 1250, 15.5, 180")
    print("1669734897, 1669734898, 46.123457, 8.654322, 1251, 16.2, 181")
    print("1669734897, 1669734899, 46.123458, 8.654323, 1252, 16.8, 182")

if __name__ == "__main__":
    main()