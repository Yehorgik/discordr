import discord
import sys

print(f"Python: {sys.version}")
print(f"Discord.py: {discord.__version__}")

try:
    print(f"VoiceClient attributes: {dir(discord.VoiceClient)}")
    if 'start_recording' in dir(discord.VoiceClient):
        print("VoiceClient has start_recording")
    else:
        print("VoiceClient DOES NOT have start_recording")
except Exception as e:
    print(f"Error checking VoiceClient: {e}")
