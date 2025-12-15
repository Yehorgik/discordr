#!/usr/bin/env python3
"""
Скачивает opus.dll из разных источников
"""
import urllib.request
import os
import sys

# Альтернативные зеркала с ПРЯМЫМИ ссылками (не GitHub)
SOURCES = [
    # Discord.py github
    ("Discord.Net dev", "https://github.com/discord-net/Discord.Net/raw/dev/src/Discord.Net.Core/opus.dll"),
    # Backup от других проектов
    ("discord.py labs", "https://github.com/Rapptz/discord.py-stubs/raw/main/discord/opus.dll"),
]

def download_with_retry(url, output):
    """Скачивает файл с повторами"""
    print(f"📥 Скачиваю: {url}")
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Accept': '*/*',
    }
    
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as response:
            data = response.read()
            
        # Проверяем, что это не HTML ошибка
        if data.startswith(b'<'):
            print(f"❌ Получил HTML вместо DLL")
            return False
            
        if len(data) < 100000:  # Opus.dll обычно > 100KB
            print(f"⚠️ Файл слишком маленький: {len(data)} байт")
            return False
        
        with open(output, 'wb') as f:
            f.write(data)
        
        print(f"✅ Скачано: {len(data)} байт")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return False

if __name__ == '__main__':
    output = 'opus.dll'
    
    for name, url in SOURCES:
        print(f"\n🔍 Пробую {name}...")
        if download_with_retry(url, output):
            print(f"\n✅ opus.dll готов!")
            sys.exit(0)
    
    print("\n❌ Все источники исчерпаны")
    print("Попробуйте скачать вручную или установите VLC (он содержит opus.dll)")
