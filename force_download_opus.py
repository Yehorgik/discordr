import os
import sys
import urllib.request
import urllib.error
import shutil

# List of mirrors to try
MIRRORS = [
    {
        "url": "https://github.com/discord-net/Discord.Net/raw/dev/src/Discord.Net.Core/opus.dll",
        "filename": "opus.dll"
    },
    {
        "url": "https://github.com/Thalhammer/discord-opus/raw/master/libopus-0.x64.dll",
        "filename": "opus.dll"
    },
    {
        "url": "https://raw.githubusercontent.com/telegramdesktop/tdesktop/dev/Telegram/ThirdParty/libopus/win64/libopus-0.dll",
        "filename": "opus.dll"
    }
]

def download_file(url, dest_path):
    print(f"Trying to download from: {url}")
    try:
        # Create a request with a User-Agent to avoid 403 Forbidden
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        )
        
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                with open(dest_path, 'wb') as out_file:
                    shutil.copyfileobj(response, out_file)
                print(f"Successfully downloaded to {dest_path}")
                return True
            else:
                print(f"Failed with status code: {response.status}")
    except urllib.error.HTTPError as e:
        print(f"HTTP Error: {e.code} - {e.reason}")
    except urllib.error.URLError as e:
        print(f"URL Error: {e.reason}")
    except Exception as e:
        print(f"Error: {e}")
    return False

def main():
    dest_dir = os.path.dirname(os.path.abspath(__file__))
    dest_path = os.path.join(dest_dir, "opus.dll")
    
    print(f"Target destination: {dest_path}")
    
    success = False
    for mirror in MIRRORS:
        if download_file(mirror["url"], dest_path):
            success = True
            break
    
    if success:
        # Verify file size (DLLs are usually > 100KB)
        size = os.path.getsize(dest_path)
        print(f"Downloaded file size: {size} bytes")
        if size < 1000:
            print("WARNING: File seems too small. It might be a corrupt file or an HTML error page.")
        else:
            print("Download complete! You can now run the bot.")
    else:
        print("All download attempts failed.")
        print("Please download manually from: https://github.com/discord-net/Discord.Net/raw/dev/src/Discord.Net.Core/opus.dll")
        print(f"And save it as: {dest_path}")

if __name__ == "__main__":
    main()
