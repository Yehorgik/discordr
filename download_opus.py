import requests
import zipfile
import io
import os

import requests
import os
import sys

# Список зеркал для скачивания opus.dll (x64)
urls = [
    # Зеркало 5: GitHub Raw (проверенный URL)
    {'url': 'https://github.com/discord-net/Discord.Net/blob/dev/src/Discord.Net.Core/opus.dll?raw=true', 'name': 'opus.dll'},
]

print("🔍 Начинаю поиск рабочей версии opus.dll...")

for mirror in urls:
    url = mirror.get('url')
    print(f"\n🌐 Пробую скачать с: {url}")
    
    try:
        # Делаем запрос с таймаутом
        r = requests.get(url, timeout=15, allow_redirects=True)
        
        if r.status_code == 200:
            print(f"✅ Файл найден! Размер: {len(r.content)} байт")
            
            # Проверяем, что это не HTML страница с ошибкой
            if b'<!DOCTYPE html>' in r.content[:100] or b'<html' in r.content[:100]:
                print("❌ Это HTML страница, а не DLL. Пропускаем.")
                continue
                
            # Проверяем сигнатуру DLL (MZ)
            if not r.content.startswith(b'MZ'):
                print("❌ Файл не является DLL (нет MZ заголовка). Пропускаем.")
                continue

            filename = 'opus.dll'
            
            with open(filename, 'wb') as f:
                f.write(r.content)
            
            print(f"🎉 Успешно сохранено как {filename}")
            print("Теперь попробуйте запустить бота!")
            sys.exit(0)
            
        elif r.status_code == 404:
            print("❌ Ошибка 404: Файл не найден на этом зеркале.")
        else:
            print(f"❌ Ошибка {r.status_code}")
            
    except Exception as e:
        print(f"❌ Ошибка соединения: {e}")

print("\n⛔ Не удалось скачать opus.dll ни с одного зеркала.")
print("Попробуйте скачать вручную: https://github.com/discord-net/Discord.Net/raw/dev/src/Discord.Net.Core/opus.dll")

print(f"Скачиваю с {url}...")
try:
    # Скачиваем архив
    r = requests.get(url, timeout=30)
    
    if r.status_code == 200:
        print("Скачивание успешно. Распаковка...")
        
        # Открываем архив в памяти
        with zipfile.ZipFile(io.BytesIO(r.content)) as z:
            found = False
            # Ищем файл libopus-0.dll внутри архива
            for name in z.namelist():
                if name.endswith('libopus-0.dll'):
                    print(f"Нашел файл: {name}")
                    
                    # Извлекаем и сохраняем как opus.dll
                    with z.open(name) as source, open('opus.dll', 'wb') as target:
                        target.write(source.read())
                    
                    print("✅ Успешно! Файл сохранен как opus.dll")
                    found = True
                    break
            
            if not found:
                print("❌ Ошибка: DLL файл не найден внутри архива.")
    else:
        print(f"❌ Ошибка скачивания: Статус {r.status_code}")

except Exception as e:
    print(f"❌ Произошла ошибка: {e}")
