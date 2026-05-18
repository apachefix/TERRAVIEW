import base64
import jwt
import json 

# Define the encryption key

#ENCRYPTION_KEY = json.load(open("C:\\NRN\\TERRAMAR-CAMIONES\\encription_key.json"))
ENCRYPTION_KEY = {
    "ENCRYPTION_KEY": "1234567890"
}
def encrypt_string(input_string):
    """Encrypt the input string using base64 encoding and a key."""
    # Encode the input string and key into bytes
    input_bytes = input_string.encode('utf-8')
    key_bytes = ENCRYPTION_KEY["ENCRYPTION_KEY"].encode('utf-8')
    
    # XOR the input bytes with the key bytes
    encrypted_bytes = bytearray(a ^ b for a, b in zip(input_bytes, key_bytes))
    
    # Encode the result using base64
    base64_bytes = base64.b64encode(encrypted_bytes)
    return base64_bytes.decode('utf-8')

def decrypt_string(encrypted_string):
    """Decrypt the encrypted string using base64 decoding and a key."""
    # Decode the base64 encoded string
    encrypted_bytes = base64.b64decode(encrypted_string)
    
    # Decode the key into bytes
    key_bytes = ENCRYPTION_KEY["ENCRYPTION_KEY"].encode('utf-8')
    
    # XOR the encrypted bytes with the key bytes to get the original bytes
    decrypted_bytes = bytearray(a ^ b for a, b in zip(encrypted_bytes, key_bytes))
    
    # Decode the bytes to get the original string
    return decrypted_bytes.decode('utf-8')

def encrypt_payload(payload):
    token = jwt.encode(payload, ENCRYPTION_KEY["ENCRYPTION_KEY"], algorithm='HS256')
    return token
