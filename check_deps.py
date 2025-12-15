import sys
print(f"Python version: {sys.version}")

try:
    import nacl
    print("PyNaCl is installed and importable.")
except ImportError as e:
    print(f"PyNaCl is NOT installed: {e}")

try:
    import audioop
    print("audioop is available.")
except ImportError as e:
    print(f"audioop is NOT available: {e}")
