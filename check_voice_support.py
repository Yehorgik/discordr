import discord
import nacl.secret
import nacl.utils

print(f"Discord lib: {discord.__name__} v{discord.__version__}")
print(f"PyNaCl version: {nacl.__version__}")

try:
    # Check if discord detects encryption support
    # In py-cord, this might be checked differently, but let's try to instantiate a VoiceClient (mock) or check internal flags
    from discord.voice_client import VoiceClient
    print(f"VoiceClient supported modes: {VoiceClient.supported_modes}")
except Exception as e:
    print(f"Error checking supported modes: {e}")
