import urllib.request
import urllib.error

urls = [
    "https://github.com/discord-net/Discord.Net/raw/main/src/Discord.Net.Core/opus.dll",
    "https://github.com/Thalhammer/discord-opus/raw/main/libopus-0.x64.dll",
    "https://raw.githubusercontent.com/telegramdesktop/tdesktop/dev/Telegram/ThirdParty/libopus/win64/libopus-0.dll",
    "https://github.com/bwmarrin/discordgo/raw/master/examples/airhorn/libopus-0.dll",
    "https://github.com/Rapptz/discord.py/raw/master/discord/bin/libopus-0.x64.dll",
    "https://github.com/Rapptz/discord.py/raw/v1.7.3/discord/bin/libopus-0.x64.dll",
    "https://github.com/discordjs/opus/raw/master/prebuild/win32-x64/node.napi.opus.node"
]

print("Checking URLs...")
for url in urls:
    try:
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            print(f"URL: {url} - Status: {response.status}")
    except urllib.error.HTTPError as e:
        print(f"URL: {url} - Failed: {e.code}")
    except Exception as e:
        print(f"URL: {url} - Error: {e}")
