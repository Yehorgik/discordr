import discord
from discord.ext import commands
try:
    from discord.ext import voice_recv  # Для старых команд
except ImportError:
    voice_recv = None
# from discord import opus  # ❌ БЕЗ OPUS
import os
from dotenv import load_dotenv
import asyncio
import time
import json
import audioop
from pathlib import Path
from datetime import datetime
from groq import Groq
from gtts import gTTS
import io
import requests
import speech_recognition as sr
import tempfile
import pyttsx3
import threading
import sys
import subprocess
import wave
import random

load_dotenv()
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
GROQ_API_KEY = os.getenv('GROQ_API_KEY')
DATA_FILE = 'bot_data.json'
LOGS_FILE = 'logs.txt'

# Fix for Windows console encoding
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Определяем путь к FFmpeg (кроссплатформенный)
def get_ffmpeg_path():
    """Возвращает путь к FFmpeg в зависимости от ОС"""
    if sys.platform == 'win32':
        # Windows
        return r"C:\ffmpeg-master-latest-win64-gpl-shared\bin\ffmpeg.exe"
    else:
        # Linux/Mac - FFmpeg установлен системно
        return "ffmpeg"

FFMPEG_PATH = get_ffmpeg_path()

print(f"[PYTHON] {sys.version.split()[0]} ({sys.executable})")
print(f"[SYSTEM] OS: {sys.platform}")
print(f"[FFMPEG] Path: {FFMPEG_PATH}")

# ======================== СИСТЕМА ЛОГИРОВАНИЯ ========================
def log_event(event_type: str, details: str):
    """Логирует событие в файл logs.txt"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_message = f"[{timestamp}] [{event_type}] {details}"
    
    try:
        with open(LOGS_FILE, 'a', encoding='utf-8') as f:
            f.write(log_message + '\n')
            f.flush()  # Принудительно записываем на диск
        print(log_message)  # Также выводим в консоль
    except Exception as e:
        print(f"[ERROR] Ошибка логирования: {e}")

# ====================== КОНЕЦ СИСТЕМЫ ЛОГИРОВАНИЯ ====================

# Проверка окружения для кодека Opus (без PyNaCl)

# ✅ БЕЗ OPUS.DLL - используем FFmpeg для воспроизведения!
print("[OK] Opus.dll НЕ требуется!")
print("[INFO] БОТ ГОВОРИТ в голосовой канал через FFmpeg + opuslib")
print("[INFO] Слышит через микрофон компьютера (!микрофон команда)")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.dm_messages = True  # Для ЛС

bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

support_tickets = {}
ticket_counter = 0
support_requests = {}  # Отслеживание количества запросов поддержки: {user_id: count}
current_audio_file = None  # Текущий проигрываемый аудиофайл
current_audio_start_time = None  # Время начала проигрывания (для отслеживания позиции)
current_voice_connection = None  # Текущее голосовое подключение для музыки
processed_messages = set()
voice_logging_enabled = True  # Включено ли логирование голосового чата
voice_interaction_enabled = False # Включен ли режим диалога
ADMIN_ID = 999283699826831452  # твой ID
SUPPORT_CHANNEL_ID = 1426258029082574920  # КОНТУЖЕНЫЕ!
report_processing = set()  # Блокирую дублирование жалоб

# Подслушивание: {guild_id: {'vc': VoiceClient, 'task': asyncio.Task, 'sink': sink_obj, 'file': path}}
listening_sessions = {}
active_voice_channels = {} # guild_id -> channel_id (для автоподключения)
user_cooldowns = {}  # user_id -> time последней команды (для кулдауна)
COOLDOWN_SECONDS = 20  # Кулдаун между командами (20 секунд)

# Системы
user_warnings = {}  # Варны юзеров {user_id: count}
user_reputation = {}  # Репутация {user_id: points}
moderation_logs = []  # Логи модерации
muted_users = {}  # Замутленные {user_id: until_time}
banned_words = []  # Запрещённые слова
current_voice_client = None  # Текущое подключение к голосу
new_year_announced = False  # Флаг новогоднего поздравления
auto_comment_enabled = False  # Флаг автокомментирования
current_text_channel = None  # Текущий текстовый канал для сообщений
voice_recording = {}  # Запись пользователей {user_id: AudioData}
recognizer = sr.Recognizer()  # Для распознавания речи
current_volume = 100  # Текущая громкость (0-100)

# Groq клиент для TTS и комментариев
groq_client = Groq(api_key=GROQ_API_KEY)

# Список оскорблений (русский/английский)
INSULTS = [
    'бля', 'блять', 'блядь', 'пиз', 'пизд', 'хуй', 'хуе', 'сука', 'суки', 'гавно', 'дерьмо',
    'хуйня', 'ебал', 'ебут', 'ебать', 'ебется', 'пиздец', 'пиздит', 'мудак', 'мудила',
    'дебил', 'тупой', 'идиот', 'долбоеб', 'ебанутый', 'уродина', 'гавна', 'гавень',
    'блин', 'блинская', 'пидор', 'педик', 'педик', 'мать твоя', 'мать ебу', 'ебали',
    'твоя мать', 'твой папа', 'твоя семья', 'твои родители', 'урод', 'гад', 'сволочь',
    'shit', 'fuck', 'bitch', 'asshole', 'damn', 'crap', 'bastard', 'dick', 'ass'
]

# === ФУНКЦИИ СОХРАНЕНИЯ ===
def load_data():
    """Загрузить данные из файла"""
    global user_warnings, user_reputation, banned_words, support_tickets, moderation_logs, support_requests, active_voice_channels
    if Path(DATA_FILE).exists():
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                user_warnings = {int(k): v for k, v in data.get('warnings', {}).items()}
                user_reputation = {int(k): v for k, v in data.get('reputation', {}).items()}
                banned_words = data.get('banned_words', [])
                support_tickets = data.get('support_tickets', {})
                moderation_logs = data.get('moderation_logs', [])
                support_requests = {int(k): v for k, v in data.get('support_requests', {}).items()}
                active_voice_channels = {int(k): v for k, v in data.get('active_voice_channels', {}).items()}
                print(f'✅ Данные загружены из {DATA_FILE}')
        except:
            print(f'⚠️ Ошибка при загрузке {DATA_FILE}')

def save_data():
    """Сохранить данные в файл"""
    try:
        data = {
            'warnings': {str(k): v for k, v in user_warnings.items()},
            'reputation': {str(k): v for k, v in user_reputation.items()},
            'banned_words': banned_words,
            'support_tickets': support_tickets,
            'moderation_logs': moderation_logs[-1000:],  # Последние 1000 логов
            'support_requests': {str(k): v for k, v in support_requests.items()},
            'active_voice_channels': {str(k): v for k, v in active_voice_channels.items()}
        }
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f'💾 Данные сохранены в {DATA_FILE}')
    except Exception as e:
        print(f'❌ Ошибка сохранения: {e}')

async def autosave_loop():
    """Автосохранение каждый час"""
    await bot.wait_until_ready()
    while not bot.is_closed():
        await asyncio.sleep(3600)  # 1 час = 3600 секунд
        save_data()

async def check_new_year():
    """Проверка наступления нового года"""
    await bot.wait_until_ready()
    global new_year_announced
    last_checked_date = None
    
    while not bot.is_closed():
        now = datetime.now()
        current_date = (now.month, now.day, now.hour)
        
        # Поздравление в 00:00 (полночь) 1 января
        if now.month == 1 and now.day == 1 and now.hour == 0 and not new_year_announced and last_checked_date != current_date:
            new_year_announced = True
            last_checked_date = current_date
            
            # Поздравление в чате
            for guild in bot.guilds:
                # Находим первый текстовый канал
                for channel in guild.text_channels:
                    if channel.permissions_for(guild.me).send_messages:
                        await channel.send("🎉 **С НОВЫМ ГОДОМ ВСЕМ!!!** 🎉\n" +
                            "🎊 Поздравляю вас с приходом нового года! 🎊\n" +
                            "Пусть этот год принесёт вам радость, успех и исполнение всех мечтаний! 🌟")
                        break
                
                # Поздравление в голосовом канале
                for voice_channel in guild.voice_channels:
                    try:
                        vc = await voice_channel.connect()
                        await asyncio.sleep(0.5)
                        # Отправляем текст через Groq для озвучивания
                        await send_voice_message(vc, "Поздравляю вас с наступлением Нового года!")
                        await vc.disconnect()
                        break
                    except:
                        pass
        
        # Сброс флага после полночи
        if now.hour != 0:
            new_year_announced = False
        
        await asyncio.sleep(60)  # Проверяем каждую минуту

async def send_voice_message(voice_client, text):
    """Отправить голосовое сообщение в голосовой канал Discord (БЕЗ opus.dll!)"""
    try:
        print(f"[VOICE] Озвучиваю: {text}")
        
        # 1. Генерируем MP3 через gTTS
        tts = gTTS(text=text, lang='ru', slow=False)
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp:
            tmp_path = tmp.name
            tts.save(tmp_path)
        
        print(f"[FILE] MP3: {tmp_path}")
        await asyncio.sleep(0.3)
        
        # 2. Воспроизводим в голосовой канал через FFmpeg
        ffmpeg_path = FFMPEG_PATH
        if not os.path.exists(ffmpeg_path) and sys.platform == 'win32':
            ffmpeg_path = "ffmpeg"
        
        print(f"🎵 FFmpeg: {ffmpeg_path}")
        
        try:
            audio_source = discord.FFmpegPCMAudio(tmp_path, executable=ffmpeg_path)
            voice_client.play(audio_source, after=lambda e: print(f"✅ Готово: {e}"))
            print(f"[PLAY] Воспроизведение начато...")
            
            # Ждём завершения
            max_wait = 60
            waited = 0
            while voice_client.is_playing() and waited < max_wait:
                await asyncio.sleep(0.1)
                waited += 0.1
            
            print(f"⏹️ Воспроизведение завершено")
        except Exception as e:
            print(f"[ERROR] Ошибка воспроизведения: {e}")
            # Отправляем файл в чат как fallback
            channel = voice_client.channel.guild.text_channels[0]
            await channel.send(f"🎤 Ответ: {text}", file=discord.File(tmp_path))
        
        # 3. Удаляем временный файл
        await asyncio.sleep(0.5)
        try:
            os.remove(tmp_path)
        except:
            pass
            
    except Exception as e:
        print(f"❌ Ошибка озвучивания: {e}")
        import traceback
        traceback.print_exc()
        print(f"⏹️ Воспроизведение завершено")
        
        # Удаляем временный файл
        await asyncio.sleep(0.5)
        try:
            os.remove(tmp_path)
            print(f"🗑️ MP3 файл удалён")
        except:
            pass
        
        print(f"✅ Озвучивание завершено в Discord: {text}")
    except Exception as e:
        print(f"❌ Ошибка озвучивания: {e}")
        import traceback
        traceback.print_exc()

async def _ensure_and_play_pishun(guild, author, text_channel=None):
    """Убедиться, что бот в голосовом канале автора, и проиграть музыку из папки 'музыка' (или pishun.mp3)."""
    try:
        # Ищем существующее подключение этого сервера
        vc = None
        for c in bot.voice_clients:
            if c.guild == guild and c.is_connected():
                vc = c
                break

        # Если нет — подключаемся к каналу автора
        if vc is None:
            if not getattr(author, 'voice', None) or not author.voice:
                if text_channel:
                    await text_channel.send('❌ Я не в голосовом канале и ты тоже. Зайди в канал или используй `!подключиться`.')
                return
            try:
                vc = await author.voice.channel.connect()
                await wait_until_connected(vc, 5.0)
            except Exception as e:
                if text_channel:
                    await text_channel.send(f'❌ Не удалось подключиться к голосовому каналу: {e}')
                return

        base_dir = os.path.dirname(os.path.abspath(__file__))
        music_dir = os.path.join(base_dir, 'музыка')
        try:
            os.makedirs(music_dir, exist_ok=True)
        except Exception:
            pass

        # Собираем список треков из папки музыка
        exts = ('.mp3', '.wav', '.ogg', '.m4a')
        try:
            files = [os.path.join(music_dir, f) for f in os.listdir(music_dir) if f.lower().endswith(exts)]
        except Exception:
            files = []

        music_path = None
        if files:
            import random
            music_path = random.choice(files)
        else:
            # Фоллбек: pishun.mp3 рядом с main.py
            fallback = os.path.join(base_dir, 'pishun.mp3')
            if os.path.exists(fallback):
                music_path = fallback
            else:
                if text_channel:
                    await text_channel.send('❌ В папке `музыка` нет треков и не найден `pishun.mp3`. Добавь файлы и повтори.')
                return

        # Останавливаем текущее воспроизведение
        try:
            if vc.is_playing():
                vc.stop()
        except Exception:
            pass

        # Выбираем FFmpeg и запускаем проигрывание
        ffmpeg_path = r"C:\ffmpeg-master-latest-win64-gpl-shared\bin\ffmpeg.exe"
        try:
            if os.path.exists(ffmpeg_path):
                source = discord.FFmpegPCMAudio(music_path, executable=ffmpeg_path)
            else:
                source = discord.FFmpegPCMAudio(music_path)
            vc.play(source, after=lambda e: print(f"[пишюн] Воспроизведение завершено: {e}"))
            # Сохраняем текущий трек и время начала для команд позиции/время
            global current_audio_file, current_audio_start_time
            current_audio_file = music_path
            current_audio_start_time = time.time()
            if text_channel:
                try:
                    shown = os.path.basename(music_path)
                except Exception:
                    shown = 'трек'
                await text_channel.send(f'🎵 Проигрываю: {shown}')
        except Exception as e:
            if text_channel:
                await text_channel.send(f'❌ Ошибка воспроизведения: {e}')
    except Exception as e:
        print(f"❌ Ошибка _ensure_and_play_pishun: {e}")

async def wait_until_connected(voice_client, timeout: float = 5.0) -> bool:
    """Дождаться установления голосового соединения с таймаутом."""
    try:
        start = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start < timeout:
            if voice_client and voice_client.is_connected():
                return True
            await asyncio.sleep(0.2)
        return bool(voice_client and voice_client.is_connected())
    except Exception:
        return False

def _is_direct_audio_url(url: str) -> bool:
    try:
        u = url.lower().strip()
        if not (u.startswith('http://') or u.startswith('https://')):
            return False
        base = u.split('?', 1)[0]
        return base.endswith(('.mp3', '.wav', '.ogg', '.m4a'))
    except Exception:
        return False

async def _play_url_in_voice(ctx, url: str):
    """Потоковое воспроизведение прямой аудиоссылки в голосовом канале."""
    # Ищем подключение для текущего сервера
    vc = None
    for c in bot.voice_clients:
        if c.guild == ctx.guild and c.is_connected():
            vc = c
            break
    if vc is None:
        # Подключаемся к каналу автора если он там
        if not ctx.author.voice:
            await ctx.send('❌ Я не в голосовом канале и ты тоже. Зайди в канал или используй `!подключиться`.')
            return False
        try:
            vc = await ctx.author.voice.channel.connect()
            await wait_until_connected(vc, 5.0)
        except Exception as e:
            await ctx.send(f'❌ Не удалось подключиться к голосовому каналу: {e}')
            return False

    # Останавливаем текущее воспроизведение
    try:
        if vc.is_playing():
            vc.stop()
    except Exception:
        pass

    ffmpeg_path = r"C:\ffmpeg-master-latest-win64-gpl-shared\bin\ffmpeg.exe"
    try:
        source = discord.FFmpegPCMAudio(url, executable=ffmpeg_path) if os.path.exists(ffmpeg_path) else discord.FFmpegPCMAudio(url)
        vc.play(source, after=lambda e: print(f"[url] Завершено: {e}"))
        # Сохраняем время начала для потоковой ссылки (позиция относительно запуска)
        global current_audio_file, current_audio_start_time
        current_audio_file = url
        current_audio_start_time = time.time()
        await ctx.send(f'🎵 Проигрываю по ссылке: {url}')
        return True
    except Exception as e:
        await ctx.send(f'❌ Ошибка воспроизведения: {e}')
        return False

async def generate_ai_comment():
    """Генерировать комментарий через AI (Groq)"""
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{
                "role": "user",
                "content": "Напиши короткий нейтральный комментарий (одно предложение, максимум 15 слов) в дружелюбном, позитивном и уместном стиле. Без оскорблений, токсичности и насилия."
            }],
            temperature=0.7,
            max_tokens=100
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"❌ Ошибка генерации комментария: {e}")
        return "Помогите! Он ловит меня!"

async def auto_comment_loop():
    """Автоматическое комментирование только в голосовом канале"""
    global current_text_channel
    await bot.wait_until_ready()
    
    import random
    
    while not bot.is_closed():
        try:
            # Проверяем есть ли активные голосовые подключения и комментарии включены
            if auto_comment_enabled and bot.voice_clients and any(vc.is_connected() for vc in bot.voice_clients):
                # Генерируем комментарий через AI
                comment = await generate_ai_comment()
                
                # Озвучиваем ТОЛЬКО в голосовых каналах
                for vc in bot.voice_clients:
                    if vc.is_connected():
                        try:
                            await send_voice_message(vc, comment)
                        except Exception as e:
                            print(f"❌ Ошибка озвучивания: {e}")
                
                # Интервал от 0 до 100 секунд
                wait_time = random.randint(0, 100)
                print(f"⏰ Ждём {wait_time} секунд до следующего комментария...")
                await asyncio.sleep(wait_time)
            else:
                # Если нет голосовых подключений или комментарии отключены, ждём 10 секунд и проверяем снова
                await asyncio.sleep(10)
        except Exception as e:
            print(f"❌ Ошибка в цикле автокомментирования: {e}")
            await asyncio.sleep(10)

async def demo_voice_loop():
    """Демонстрация возможностей в голосовом канале"""
    await bot.wait_until_ready()
    
    demo_phrases = [
        "Я умею комментировать события!",
        "Я слушаю то, что вы говорите!",
        "Я могу поздравить вас с Новым годом!",
        "Я знаю модерацию и репутацию!",
        "Я развлекаю людей смешными историями!",
        "Я реагирую на ваши команды!",
        "Я помогаю поддерживать порядок на сервере!",
        "Я умею записывать звук и распознавать речь!",
        "Я Чикатило - ваш верный помощник!",
        "Вы можете запросить мою помощь командой демо!",
    ]
    
    import random
    while not bot.is_closed():
        try:
            # Озвучиваем демонстрацию в активные голосовые каналы
            for vc in bot.voice_clients:
                if vc.is_connected():
                    try:
                        demo_phrase = random.choice(demo_phrases)
                        await send_voice_message(vc, demo_phrase)
                    except Exception as e:
                        print(f"❌ Ошибка демо: {e}")
            
            # Демонстрируем каждые 2-3 минуты
            await asyncio.sleep(random.randint(120, 180))
        except Exception as e:
            print(f"❌ Ошибка в цикле демо: {e}")
            await asyncio.sleep(10)

# Класс AudioRecorder удален - не совместим с discord.py 2.3.2

async def recognize_speech(audio_data, language='ru-RU'):
    """Распознать речь из аудиоданных"""
    try:
        # Сохраняем аудио в временный файл
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
            tmp_path = tmp.name
            tmp.write(audio_data)
        
        # Распознаём речь
        with sr.AudioFile(tmp_path) as source:
            audio = recognizer.record(source)
        
        try:
            text = recognizer.recognize_google(audio, language=language)
            print(f"🎤 Распознано: {text}")
            return text
        except sr.UnknownValueError:
            return None
        except sr.RequestError:
            return None
        finally:
            try:
                os.remove(tmp_path)
            except:
                pass
    except Exception as e:
        print(f"❌ Ошибка распознавания: {e}")
        return None

async def handle_voice_command(text, ctx):
    """Обработать голосовую команду"""
    text_lower = text.lower()
    
    # Реагируем на ключевые слова
    if 'привет' in text_lower or 'hello' in text_lower:
        await ctx.send(f'👋 Привет! Я тебя услышал!')
        return
    
    if 'чикатило' in text_lower:
        await ctx.send('😈 Я услышал своё имя!')
        return
    
    if 'помощь' in text_lower or 'help' in text_lower:
        await ctx.send('📋 Напиши !помощь для списка команд')
        return
    
    # Для других слов генерируем ответ через AI
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{
                "role": "user",
                "content": f"Пользователь сказал: '{text}'. Ответь кратко (1-2 предложения) по делу, дружелюбно и нейтрально. Избегай токсичности и насилия."
            }],
            temperature=0.7,
            max_tokens=150
        )
        answer = response.choices[0].message.content
        await ctx.send(f"💭 {answer}")
    except:
        pass

@bot.event
async def on_ready():
    log_event("BOT", f"✅ Bot connected as {bot.user}")
    print(f'{bot.user} connected to Discord!')
    print(f'Loaded {len(support_tickets)} tickets from file')
    print('Bot ready!\n')
    print('Commands:')
    for cmd in bot.commands:
        aliases = f" ({', '.join(cmd.aliases)})" if cmd.aliases else ""
        print(f"  !{cmd.name}{aliases}")
    
    # Сообщение когда бот активируется
    for guild in bot.guilds:
        for channel in guild.text_channels:
            if channel.permissions_for(guild.me).send_messages:
                await channel.send("меня выпустил из подвала чикатило")
                break
    
    # Автоподключение к голосовым каналам (из сохраненных данных)
    global current_voice_client, auto_comment_enabled, current_text_channel
    
    # Пропускаем восстановление old voice_recv сессий если voice_recv недоступен
    if voice_recv is not None:
        for guild_id_str, channel_id in active_voice_channels.items():
            try:
                guild_id = int(guild_id_str)
                guild = bot.get_guild(guild_id)
                if not guild:
                    continue
                    
                channel = guild.get_channel(channel_id)
                if not channel:
                    continue
                    
                # Проверяем, не подключены ли мы уже
                if guild.voice_client and guild.voice_client.is_connected():
                    continue
                    
                print(f"🔄 Auto-reconnecting to {channel.name} in {guild.name}...")
                
                # Подключаемся с VoiceRecvClient
                vc = await channel.connect(cls=voice_recv.VoiceRecvClient)
                
                # Запускаем прослушивание
                sink = SpeechLogSink(voice_client=vc)
                vc.listen(sink)
                listening_sessions[guild_id] = {'sink': sink, 'vc': vc}
                
                # Восстанавливаем глобальные переменные (частично)
                current_voice_client = vc
                auto_comment_enabled = True
                
                print(f"✅ Auto-reconnected and listening in {guild.name}")
                
            except Exception as e:
                print(f"❌ Failed to auto-reconnect in guild {guild_id_str}: {e}")
    
    # Автоподключение к любому голосовому каналу где есть люди (если не подключены уже)
    print("\n📡 Проверяю доступные голосовые каналы...")
    for guild in bot.guilds:
        # Пропускаем если уже подключены на этом сервере
        if guild.voice_client and guild.voice_client.is_connected():
            print(f"   ✓ {guild.name}: уже подключен к {guild.voice_client.channel.name}")
            continue
        
        # Ищем первый канал с людьми
        for vc_channel in guild.voice_channels:
            # Считаем людей (исключаем самого бота)
            members_count = sum(1 for m in vc_channel.members if not m.bot)
            
            if members_count > 0:
                try:
                    print(f"   🔗 {guild.name}: подключаюсь к {vc_channel.name} ({members_count} чел.)...")
                    # Подключаемся как VoiceRecvClient для записи
                    if voice_recv is not None:
                        vc = await vc_channel.connect(cls=voice_recv.VoiceRecvClient)
                        print(f"   ✅ Подключен с поддержкой записи!")
                    else:
                        vc = await vc_channel.connect()
                        print(f"   ✅ Подключен!")
                    break
                except Exception as e:
                    print(f"   ❌ Не удалось подключиться к {vc_channel.name}: {e}")
                    continue

    # Запуск фоновых задач
    bot.loop.create_task(autosave_loop())
    bot.loop.create_task(check_new_year())
    
    # Озвучиваем при включении в голосовых каналах которые уже были подключены
    for vc in bot.voice_clients:
        if vc.is_connected() and vc != current_voice_client:
            try:
                await send_voice_message(vc, "Меня выпустил из подвала Чикатило!")
            except:
                pass
    
    # Запуск цикла автосохранения
    bot.loop.create_task(autosave_loop())
    # Запуск проверки новогоднего поздравления
    bot.loop.create_task(check_new_year())
    # Запуск автокомментирования
    bot.loop.create_task(auto_comment_loop())
    # Запуск демонстрации в голосе
    bot.loop.create_task(demo_voice_loop())

@bot.event
async def on_message(message):
    """Handle messages and check banned words"""
    # Логирование всех сообщений (включая боты)
    channel_name = message.channel.name if hasattr(message.channel, 'name') else "DM"
    author_name = f"{message.author.name} (BOT)" if message.author.bot else message.author.name
    log_event("MESSAGE", f"{author_name} в #{channel_name}: {message.content[:100]}")
    
    if message.author == bot.user or message.author.bot:
        await bot.process_commands(message)
        return
    
    if message.id in processed_messages:
        return
    
    content_lower = message.content.lower()
    
    # Кулдаун: проверяем, не командует ли пользователь слишком часто
    user_id = message.author.id
    now = time.time()
    if user_id in user_cooldowns:
        time_passed = now - user_cooldowns[user_id]
        if time_passed < COOLDOWN_SECONDS:
            return  # Игнорируем сообщение (кулдаун активен)
    
    user_cooldowns[user_id] = now
    
    # Триггер "кимпитяо" или "кимпинтяо" — отправляем фотку из папки
    if ('кимпитяо' in content_lower or 'кимпинтяо' in content_lower) and not content_lower.strip().startswith('!'):
        try:
            photos_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'photos')
            os.makedirs(photos_dir, exist_ok=True)
            
            photo_files = [f for f in os.listdir(photos_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.gif'))]
            
            if photo_files:
                random_photo = random.choice(photo_files)
                photo_path = os.path.join(photos_dir, random_photo)
                
                with open(photo_path, 'rb') as f:
                    await message.channel.send(file=discord.File(f, filename=random_photo))
            else:
                await message.channel.send('📁 Папка `photos` пуста. Добавь фотки!')
        except Exception as e:
            await message.channel.send(f'❌ Ошибка отправки фотки: {e}')
        
        return

    # Проверка на громкость (например "47%" или "100%")
    import re as regex_module
    volume_match = regex_module.search(r'(\d+)%', message.content)
    if volume_match:
        volume_level = int(volume_match.group(1))
        if 0 <= volume_level <= 100:
            global current_volume
            current_volume = volume_level
            await message.channel.send(f'🔊 Громкость установлена на **{volume_level}%**')

    # Триггер "пишюн" без команды — проигрываем музыку
    if 'пишюн' in content_lower and not content_lower.strip().startswith('!'):
        try:
            # Если вложили файл, сохраняем его в папку "музыка" и играем
            if message.attachments:
                for att in message.attachments:
                    name = (att.filename or '').lower()
                    ctype = (att.content_type or '').lower() if hasattr(att, 'content_type') else ''
                    if name.endswith(('.mp3', '.wav', '.ogg', '.m4a')) or ctype.startswith('audio'):
                        base_dir = os.path.dirname(os.path.abspath(__file__))
                        music_dir = os.path.join(base_dir, 'музыка')
                        os.makedirs(music_dir, exist_ok=True)
                        # Сохраняем под оригинальным именем (при конфликте перезаписываем)
                        target_path = os.path.join(music_dir, att.filename)
                        await att.save(target_path)
                        await message.channel.send(f'📥 Трек сохранён: `музыка/{att.filename}`')
                        break
        except Exception as e:
            await message.channel.send(f'⚠️ Не удалось сохранить вложение: {e}')
        
        await _ensure_and_play_pishun(message.guild, message.author, message.channel)
        return
    
    # Ответ на "привет" (без команды)
    if 'привет' in content_lower or 'hello' in content_lower or 'hi' in content_lower:
        await message.reply(f'Привет {message.author.name}! 👋')
        return
    
    # Проверка запрещённых слов
    for banned_word in banned_words:
        if banned_word in content_lower:
            try:
                await message.delete()
                await message.channel.send(f'⚠️ {message.author.name}, слово "{banned_word}" запрещено!')
                moderation_logs.append(f"[ЗАПРЕЩЁННОЕ СЛОВО] {message.author.name} написал: {banned_word}")
            except:
                pass
            return
    
    # Если прислали прямую аудиоссылку — сразу проигрываем (без скачивания)
    try:
        import re
        urls = re.findall(r'https?://\S+', message.content)
        direct = next((u for u in urls if _is_direct_audio_url(u)), None)
        if direct:
            # Используем контекст-обёртку для вызова
            class SimpleCtx:
                def __init__(self, msg):
                    self.guild = msg.guild
                    self.author = msg.author
                    self.channel = msg.channel
            ctx_like = SimpleCtx(message)
            await message.channel.send('🔗 Найдена прямая аудиоссылка — запускаю воспроизведение...')
            await _play_url_in_voice(ctx_like, direct)
    except Exception:
        pass

    processed_messages.add(message.id)
    if len(processed_messages) > 1000:
        processed_messages.clear()
    
    await bot.process_commands(message)

@bot.command(name='пинг', aliases=['ping'])
async def ping(ctx):
    """Проверить пинг"""
    log_event("COMMAND", f"{ctx.author.name} использовал !ping")
    latency = round(bot.latency * 1000)
    await ctx.send(f'🏓 Понг! {latency}мс')

@bot.command(name='привет', aliases=['hello', 'hi'])
async def hello(ctx):
    """Приветствие"""
    await ctx.send(f'Привет {ctx.author.name}! 👋')

@bot.command(name='myid', aliases=['айди', 'мойид'])
async def myid(ctx):
    """Показать твой ID"""
    await ctx.send(f'Твой ID: `{ctx.author.id}`')

@bot.command(name='channelid')
async def channelid(ctx, *, channel_name: str = None):
    """Найти ID канала"""
    if channel_name is None:
        await ctx.send(f'ID этого канала: `{ctx.channel.id}`')
        return
    
    channel = discord.utils.get(ctx.guild.text_channels, name=channel_name)
    if channel:
        await ctx.send(f'Канал **{channel_name}** ID: `{channel.id}`')
    else:
        await ctx.send(f'❌ Канал **{channel_name}** не найден')

@bot.command(name='инфо', aliases=['info', 'информация'])
async def info(ctx):
    """Твоя информация"""
    embed = discord.Embed(title=f'Инфо {ctx.author.name}', color=discord.Color.blue())
    embed.add_field(name='Ник', value=ctx.author.name, inline=False)
    embed.add_field(name='ID', value=ctx.author.id, inline=False)
    created = getattr(ctx.author, 'created_at', None)
    embed.add_field(name='Создан', value=(created.strftime('%d.%m.%Y') if created else 'N/A'), inline=False)
    await ctx.send(embed=embed)

@bot.command(name='профіль', aliases=['userinfo', 'юзер'])
@commands.has_permissions(administrator=True)
async def userinfo(ctx, member: discord.Member = None):
    """Информация о юзере (админы)"""
    if member is None:
        member = ctx.author
    
    embed = discord.Embed(title=f'Юзер: {member.name}', color=discord.Color.green())
    embed.add_field(name='Ник', value=member.name, inline=False)
    embed.add_field(name='ID', value=member.id, inline=False)
    embed.add_field(name='Статус', value=str(member.status), inline=False)
    
    created = getattr(member, 'created_at', None)
    joined = getattr(member, 'joined_at', None)
    embed.add_field(name='Создан', value=(created.strftime('%d.%m.%Y %H:%M') if created else 'N/A'), inline=False)
    embed.add_field(name='Присоединился', value=(joined.strftime('%d.%m.%Y %H:%M') if joined else 'N/A'), inline=False)
    
    roles = [r.name for r in member.roles if r.name != '@everyone']
    embed.add_field(name='Роли', value=(', '.join(roles) if roles else 'Нет ролей'), inline=False)
    
    if member.avatar:
        embed.set_thumbnail(url=member.avatar.url)
    
    await ctx.send(embed=embed)

@bot.command(name='чатик', aliases=['chat', 'чат', 'ai'])
async def chatik(ctx, *, message: str):
    """AI чат через Groq"""
    api_key = os.getenv('GROQ_API_KEY')
    if not api_key:
        await ctx.send('❌ AI недоступен - нет API ключа')
        return

    async with ctx.typing():
        try:
            from groq import Groq
            client = Groq(api_key=api_key)
            response = client.chat.completions.create(
                model='llama-3.3-70b-versatile',
                messages=[{'role': 'user', 'content': message}],
                max_tokens=400,
                temperature=0.7,
            )
            content = response.choices[0].message.content.strip()
            if len(content) > 1900:
                content = content[:1900] + '\n...'
            await ctx.send(content)
        except Exception as e:
            await ctx.send(f'❌ Ошибка: {e}')

def has_insults(text):
    """Проверяет есть ли оскорбления в тексте"""
    text_lower = text.lower()
    for insult in INSULTS:
        if insult in text_lower:
            return True
    return False

@bot.command(name='жалоба', aliases=['report', 'complaint'])
@commands.cooldown(1, 60, commands.BucketType.user)
async def report(ctx, member: discord.Member, *, reason: str):
    """Пожаловаться на юзера за оскорбления"""
    # Блокирую дублирование
    report_key = f"{ctx.author.id}_{member.id}"
    if report_key in report_processing:
        return
    report_processing.add(report_key)
    
    try:
        if ctx.guild is None:
            await ctx.send('❌ Только на сервере!')
            return
        
        if member.id == ctx.author.id:
            await ctx.send('❌ Не можешь пожаловаться на себя!')
            return
        
        await ctx.send(f'🔍 Проверяю `{member.name}`...')
        
        # Проверяю последние 100 сообщений
        found_insults = []
        try:
            async for message in ctx.channel.history(limit=100):
                if message.author.id == member.id:
                    if has_insults(message.content):
                        found_insults.append(message.content)
        except:
            pass
        
        if found_insults:
            # Баним если нашли оскорбления
            try:
                await member.ban(reason=f'Оскорбления: {reason}')
                await ctx.send(f'✅ **{member.name} ЗАБАНЕН** за оскорбления!\n\n' \
                              f'Найдено {len(found_insults)} сообщений с оскорблениями')
                print(f'[ЖАЛОБА] {member.name} забанен за оскорбления')
            except Exception as e:
                await ctx.send(f'❌ Не могу забанить: {e}')
        else:
            await ctx.send(f'❌ Оскорблений не найдено в сообщениях `{member.name}`')
    finally:
        report_processing.discard(report_key)

@bot.command(name='поддержка', aliases=['support', 'help_me'])
@commands.cooldown(1, 300, commands.BucketType.user)
async def support(ctx, *, message: str):
    """Send support request"""
    global ticket_counter, support_requests, user_reputation
    
    # Игнорирую если в канале
    if ctx.guild is not None:
        return
    
    user_id = ctx.author.id
    
    # Отслеживаю количество запросов
    if user_id not in support_requests:
        support_requests[user_id] = 0
    
    support_requests[user_id] += 1
    request_count = support_requests[user_id]
    
    # Применяю штрафы репутации
    if request_count == 1:
        # 1-й раз: -50 репутации
        current_rep = user_reputation.get(user_id, 0)
        user_reputation[user_id] = current_rep - 50
        penalty_msg = "⚠️ **-50 репутации** за обращение в поддержку"
    elif request_count == 2:
        # 2-й раз: -50 репутации
        current_rep = user_reputation.get(user_id, 0)
        user_reputation[user_id] = current_rep - 50
        penalty_msg = "⚠️ **-50 репутации** за второе обращение в поддержку"
    elif request_count >= 3:
        # 3-й раз и более: БАН
        try:
            await ctx.author.send('❌ **ВЫ ЗАБАНЕНЫ** за чрезмерное обращение в поддержку!')
            moderation_logs.append(f"[БАН] {ctx.author.name} забанен автоматически за 3-е обращение в поддержку")
            return
        except:
            pass
    
    ticket_counter += 1
    ticket_id = ticket_counter
    
    support_tickets[ticket_id] = {
        'user_id': user_id,
        'username': ctx.author.name,
        'message': message,
        'request_number': request_count
    }
    
    # Отправляю уведомление пользователю
    if request_count < 3:
        await ctx.send(penalty_msg + f'\n\n📬 Тикет #{ticket_id} создан')
    
    # Отправляю админу в ЛС: ник, номер билета, причина, номер обращения
    try:
        admin = await bot.fetch_user(ADMIN_ID)
        if admin:
            warning_text = ""
            if request_count == 3:
                warning_text = "\n⚠️ **ВНИМАНИЕ: ЭТО 3-е ОБРАЩЕНИЕ - ПОЛЬЗОВАТЕЛЬ ДОЛЖЕН БЫТЬ ЗАБАНЕН!**"
            msg = f'📬 **New Support Ticket**\n\n' \
                  f'🎫 Ticket #: `{ticket_id}`\n' \
                  f'👤 User: `{ctx.author.name}`\n' \
                  f'📊 Обращение #: `{request_count}`\n' \
                  f'📝 Reason: {message}' + warning_text
            await admin.send(msg)
            print(f'[SUPPORT] Sent ticket #{ticket_id} to admin')
    except Exception as e:
        print(f"[SUPPORT] Error: {e}")

@bot.command(name='ответтикет', aliases=['answer_ticket', 'reply_ticket'])
async def answer_support(ctx, ticket_id: int, *, response: str):
    """Ответ на тикет поддержки (только админ)"""
    if ctx.author.id != ADMIN_ID:
        await ctx.send('❌ Только админ может использовать эту команду')
        return

    if ticket_id not in support_tickets:
        await ctx.send(f'❌ Тикет #{ticket_id} не найден')
        return

    ticket = support_tickets[ticket_id]
    username = ticket['username']

    try:
        channel = bot.get_channel(SUPPORT_CHANNEL_ID)
        if channel:
            msg = (
                f'✅ **Support Response - Ticket #{ticket_id}**\n\n'
                f'👤 User: `{username}`\n'
                f'💬 Response: {response}'
            )
            await channel.send(msg)
            await ctx.send('✅ Отправлено в канал!')
            print(f'[SUPPORT] Response #{ticket_id} sent to channel')
            del support_tickets[ticket_id]
        else:
            await ctx.send('❌ Канал поддержки не найден')
    except Exception as e:
        await ctx.send(f'❌ Ошибка: {e}')

@bot.command(name='ответ', aliases=['answer', 'reply'])
async def reply_command(ctx, *, text: str = None):
    """Ответить на последнее сообщение (или указанный текст) голосом"""
    # Ищем голосовое подключение в этом сервере
    vc = None
    for c in bot.voice_clients:
        if c.guild == ctx.guild and c.is_connected():
            vc = c
            break
    if vc is None:
        # Фоллбек на глобальный, если он для этого сервера
        global current_voice_client
        if current_voice_client and getattr(current_voice_client, 'guild', None) == ctx.guild and current_voice_client.is_connected():
            vc = current_voice_client

    if vc is None:
        await ctx.send('❌ Я не в голосовом канале. Используй `!подключиться`.')
        return

    # Если текст не передан — берём последнее сообщение в канале от не-бота
    target_text = text
    if not target_text:
        try:
            async for m in ctx.channel.history(limit=20):
                if m.author.bot:
                    continue
                # Пропускаем команды
                if m.content.strip().startswith('!'):
                    continue
                target_text = m.content.strip()
                if target_text:
                    break
        except Exception:
            pass

    if not target_text:
        await ctx.send('❌ Не нашёл текста для ответа. Укажи текст: `!ответ твой текст`')
        return

    await ctx.send(f'💬 Отвечаю на: "{target_text}"')

    # Генерируем ответ через AI в нейтральном тоне
    try:
        response = groq_client.chat.completions.create(
            model='llama-3.3-70b-versatile',
            messages=[{
                'role': 'user',
                'content': f'Ответь кратко (1–2 предложения) по делу, дружелюбно и нейтрально, без токсичности и насилия. Сообщение: {target_text}'
            }],
            temperature=0.6,
            max_tokens=180,
        )
        answer = response.choices[0].message.content.strip()
    except Exception as e:
        await ctx.send(f'❌ Ошибка генерации ответа: {e}')
        return

    # Озвучиваем ответ в голосовом канале и дублируем текстом
    try:
        await send_voice_message(vc, answer)
        await ctx.send(f'🎤 Ответ: {answer}')
    except Exception as e:
        await ctx.send(f'❌ Ошибка озвучивания: {e}')

@bot.command(name='очистить', aliases=['clear', 'очисть'])
@commands.has_permissions(administrator=True)
async def clear(ctx, amount: int = 10):
    """Очистить сообщения"""
    if amount > 100:
        await ctx.send('❌ Максимум 100 сообщений')
        return
    
    deleted = await ctx.channel.purge(limit=amount)
    await ctx.send(f'✅ Удалено {len(deleted)} сообщений')

@bot.command(name='кик', aliases=['kick'])
@commands.has_permissions(administrator=True)
async def kick(ctx, member: discord.Member, *, reason=None):
    """Кикнуть юзера"""
    try:
        await member.kick(reason=reason)
        await ctx.send(f'✅ {member.name} кикнут. Причина: {reason or "нет"}')
    except discord.Forbidden:
        await ctx.send('❌ Нет прав')

@bot.command(name='бан', aliases=['ban'])
@commands.has_permissions(administrator=True)
async def ban(ctx, member: discord.Member, *, reason=None):
    """Забанить юзера"""
    try:
        await member.ban(reason=reason)
        await ctx.send(f'✅ Забанен. Причина: {reason or "нет"}')
    except discord.Forbidden:
        await ctx.send('❌ Нет прав')

@bot.command(name='разбан', aliases=['unban'])
@commands.has_permissions(administrator=True)
async def unban(ctx, user: discord.User, *, reason=None):
    """Разбанить юзера"""
    try:
        await ctx.guild.unban(user, reason=reason)
        await ctx.send(f'✅ Разбанен {user.name}. Причина: {reason or "нет"}')
    except discord.Forbidden:
        await ctx.send('❌ Нет прав')
    except discord.NotFound:
        await ctx.send('❌ Юзер не найден в банах')

# ====== ВАРНЫ И РЕПУТАЦИЯ ======
@bot.command(name='варн', aliases=['warn'])
@commands.has_permissions(administrator=True)
async def warn(ctx, member: discord.Member, *, reason='Без причины'):
    """Выдать варн юзеру"""
    if member.id not in user_warnings:
        user_warnings[member.id] = 0
    
    user_warnings[member.id] += 1
    warns = user_warnings[member.id]
    
    # Логирую
    moderation_logs.append(f"[ВАРН] {ctx.author.name} выдал варн {member.name} ({warns}/3). Причина: {reason}")
    
    await ctx.send(f'⚠️ {member.name} получил варн ({warns}/3)\nПричина: {reason}')
    
    # Если 3 варна - баним
    if warns >= 3:
        try:
            await member.ban(reason='3 варна - автобан')
            await ctx.send(f'🔨 {member.name} забанен за 3 варна')
            user_warnings[member.id] = 0
        except:
            pass

@bot.command(name='очиститьварны', aliases=['clearwarns'])
@commands.has_permissions(administrator=True)
async def clear_warns(ctx, member: discord.Member):
    """Очистить варны юзеру"""
    user_warnings[member.id] = 0
    await ctx.send(f'✅ Варны {member.name} очищены')

@bot.command(name='+реп', aliases=['++rep'])
@commands.cooldown(1, 60, commands.BucketType.user)
async def add_rep(ctx, member: discord.Member):
    """Дать репутацию"""
    if member.id not in user_reputation:
        user_reputation[member.id] = 0
    
    user_reputation[member.id] += 1
    await ctx.send(f'⭐ {member.name} получил +1 репутацию! (Всего: {user_reputation[member.id]})')

@bot.command(name='-реп', aliases=['--rep'])
@commands.cooldown(1, 60, commands.BucketType.user)
async def remove_rep(ctx, member: discord.Member):
    """Отнять репутацию"""
    if member.id not in user_reputation:
        user_reputation[member.id] = 0
    
    user_reputation[member.id] -= 1
    await ctx.send(f'💔 {member.name} потерял -1 репутацию! (Всего: {user_reputation[member.id]})')

@bot.command(name='репутация', aliases=['rep', 'мойрейтинг'])
async def reputation(ctx, member: discord.Member = None):
    """Показать репутацию"""
    if member is None:
        member = ctx.author
    
    rep = user_reputation.get(member.id, 0)
    await ctx.send(f'⭐ Репутация {member.name}: **{rep}**')

@bot.command(name='сетреп', aliases=['setrep', 'установитьреп'])
@commands.has_permissions(administrator=True)
async def set_reputation(ctx, member: discord.Member, value: int):
    """Установить репутацию пользователю (только админы)"""
    user_reputation[member.id] = value
    await ctx.send(f'⭐ Репутация {member.name} установлена на **{value}**')
    moderation_logs.append(f"[РЕПУТАЦИЯ] {ctx.author.name} установил репутацию {member.name} на {value}")

@bot.command(name='топ', aliases=['top', 'топрейтинг'])
async def top_users(ctx):
    """Топ 10 активных юзеров по репутации"""
    if not user_reputation:
        await ctx.send('❌ Нет данных')
        return
    
    top_10 = sorted(user_reputation.items(), key=lambda x: x[1], reverse=True)[:10]
    embed = discord.Embed(title='🏆 Топ 10 Репутация', color=discord.Color.gold())
    
    for i, (user_id, rep) in enumerate(top_10, 1):
        user = await bot.fetch_user(user_id)
        embed.add_field(name=f'{i}. {user.name}', value=f'⭐ {rep}', inline=False)
    
    await ctx.send(embed=embed)

# ====== РАЗВЛЕЧЕНИЕ ======
@bot.command(name='монета', aliases=['coin', 'монетка'])
async def coin(ctx):
    """Орел или решка"""
    import random
    result = random.choice(['🪙 Орел!', '🪙 Решка!'])
    await ctx.send(result)

@bot.command(name='кубик', aliases=['dice', 'кость'])
async def dice(ctx):
    """Бросить кубик (1-6)"""
    import random
    number = random.randint(1, 6)
    await ctx.send(f'🎲 Выпало: **{number}**')

@bot.command(name='случайный', aliases=['random'])
async def random_user(ctx):
    """Выбрать случайного юзера"""
    import random
    if not ctx.guild or not ctx.guild.members:
        await ctx.send('❌ Нет участников')
        return
    
    members = [m for m in ctx.guild.members if not m.bot]
    if not members:
        await ctx.send('❌ Нет участников')
        return
    
    lucky = random.choice(members)
    await ctx.send(f'🎰 Повезло: **{lucky.name}**!')

@bot.command(name='8ball', aliases=['шар', 'предсказание'])
async def eight_ball(ctx, *, question: str):
    """Магический шар - предсказание"""
    import random
    answers = [
        '✅ Да, конечно!', '❌ Нет, никогда', '🤔 Возможно...', '⏳ Спроси позже',
        '💯 Точно да!', '😐 Маловероятно', '🎯 Определённо', '⚠️ Сомневаюсь'
    ]
    answer = random.choice(answers)
    await ctx.send(f'🔮 На вопрос "{question}" ответ: **{answer}**')

# ====== ЛОГИРОВАНИЕ И ИНФОРМАЦИЯ ======
@bot.command(name='логи', aliases=['logs', 'история'])
@commands.has_permissions(administrator=True)
async def logs(ctx, amount: int = 10):
    """Показать последние логи модерации"""
    if not moderation_logs:
        await ctx.send('❌ Логов нет')
        return
    
    logs_text = '\n'.join(moderation_logs[-amount:])
    if len(logs_text) > 2000:
        logs_text = logs_text[-1997:] + '...'
    
    await ctx.send(f'📋 Последние логи:\n```{logs_text}```')

@bot.command(name='статистика', aliases=['stats', 'статус'])
async def stats(ctx):
    """Статистика сервера"""
    guild = ctx.guild
    embed = discord.Embed(title=f'📊 Статистика {guild.name}', color=discord.Color.blue())
    embed.add_field(name='👥 Участники', value=guild.member_count, inline=True)
    embed.add_field(name='📝 Каналы', value=len(guild.channels), inline=True)
    embed.add_field(name='👑 Роли', value=len(guild.roles), inline=True)
    embed.add_field(name='⚙️ Боты', value=len([m for m in guild.members if m.bot]), inline=True)
    
    await ctx.send(embed=embed)

# ====== ЗАПРЕЩЁННЫЕ СЛОВА ======
@bot.command(name='запретить', aliases=['ban_word', 'block_word'])
@commands.has_permissions(administrator=True)
async def ban_word(ctx, *, word: str):
    """Запретить слово (будет удаляться)"""
    if word.lower() not in banned_words:
        banned_words.append(word.lower())
        await ctx.send(f'🚫 Слово "{word}" запрещено!')
        moderation_logs.append(f"[БАН СЛОВА] {ctx.author.name} запретил слово: {word}")
    else:
        await ctx.send(f'⚠️ Слово уже запрещено')

@bot.command(name='разрешить', aliases=['unban_word', 'allow_word'])
@commands.has_permissions(administrator=True)
async def allow_word(ctx, *, word: str):
    """Разрешить слово"""
    if word.lower() in banned_words:
        banned_words.remove(word.lower())
        await ctx.send(f'✅ Слово "{word}" разрешено!')
    else:
        await ctx.send(f'⚠️ Слово не в списке запрещённых')

@bot.command(name='демо', aliases=['demo', 'demonstration'])
async def demo(ctx):
    """Демонстрация возможностей бота"""
    embed = discord.Embed(
        title='🎭 ДЕМОНСТРАЦИЯ БОТА "ЧИКАТИЛО"',
        description='Вот что я умею делать:',
        color=discord.Color.red()
    )
    
    embed.add_field(
        name='🎤 Голосовые возможности',
          value='• `!подключиться` - подключиться к голосовому каналу\n' +
              '• `!отключиться` - отключиться\n' +
              '• `!сказать текст` - произнести текст голосом\n' +
              '• `!пишюн` или слово "пишюн" — играет случайный трек из папки `музыка`\n' +
              '• Автоматическое комментирование каждые 40-90 сек\n' +
              '• Распознавание речи пользователей',
        inline=False
    )
    
    embed.add_field(
        name='💬 Текстовые команды',
        value='• `!привет` - поздравить\n' +
              '• `!пинг` - проверить задержку\n' +
              '• `!инфо` - показать инфо\n' +
              '• `!помощь` - полный список команд',
        inline=False
    )
    
    embed.add_field(
        name='🔧 Модерация',
        value='• `!варн @user` - выдать варн\n' +
              '• `!кик @user` - кикнуть\n' +
              '• `!бан @user` - забанить\n' +
              '• `!запретить слово` - запретить слово',
        inline=False
    )
    
    embed.add_field(
        name='⭐ Репутация',
        value='• `!+реп @user` - дать репутацию\n' +
              '• `!-реп @user` - отнять\n' +
              '• `!топ` - топ пользователей',
        inline=False
    )
    
    embed.add_field(
        name='🎮 Развлечения',
        value='• `!монета` - орёл/решка\n' +
              '• `!кубик` - бросить кубик\n' +
              '• `!случайный` - случайный юзер\n' +
              '• `!8ball вопрос` - магический шар',
        inline=False
    )
    
    embed.add_field(
        name='🆘 Поддержка',
        value='• `!поддержка причина` - создать тикет в ДМ\n' +
              '• Admin: `!ответ ID ответ` - ответить',
        inline=False
    )
    
    embed.set_footer(text='Я буду помогать вам! Чикатило на связи 👹')
    
    await ctx.send(embed=embed)
    
    # Демонстрация озвучивания
    await ctx.send('🎤 Демонстрирую голос:')
    for vc in bot.voice_clients:
        if vc.is_connected():
            try:
                await send_voice_message(vc, "Привет! Я Чикатило! Я умею слушать, говорить и комментировать!")
            except:
                pass

@bot.command(name='shutdown', aliases=['выключить', 'stop'])
async def shutdown(ctx):
    """Shutdown bot (только для админа)"""
    # Проверяем, это ты (админ)
    if ctx.author.id != ADMIN_ID:
        await ctx.send('❌ Только админ может выключить бота')
        return
    
    await ctx.send('меня поймал чикатило')
    
    # Озвучиваем в голосовом канале если бот там подключен
    for vc in bot.voice_clients:
        if vc.is_connected():
            try:
                await send_voice_message(vc, "Меня поймал Чикатило!")
            except:
                pass
    
    await asyncio.sleep(1)
    await bot.close()

@bot.command(name='restart', aliases=['перезагрузка', 'reboot'])
@commands.has_permissions(administrator=True)
async def restart(ctx):
    """Restart bot (admin only)"""
    await ctx.send('Restarting...')
    import sys
    await bot.close()
    sys.exit(0)

@bot.command(name='помощь', aliases=['help', 'хелп'])
async def help_command(ctx):
    """Список команд"""
    embed = discord.Embed(title='📚 Команды Бота', color=discord.Color.blue())
    
    embed.add_field(name='📌 Основное', value=
        '`!пинг` - Проверить пинг\n' +
        '`!привет` - Приветствие\n' +
        '`!инфо` - Твоя информация\n' +
        '`!статистика` - Статистика сервера\n' +
        '`!помощь` - Эта команда',
        inline=False)
    
    embed.add_field(name='🛡️ Модерация', value=
        '`!кик @user` - Кикнуть\n' +
        '`!бан @user` - Забанить\n' +
        '`!разбан @user` - Разбанить\n' +
        '`!варн @user` - Выдать варн (3 варна = бан)\n' +
        '`!очиститьварны @user` - Очистить варны\n' +
        '`!очистить [кол-во]` - Удалить сообщения',
        inline=False)
    
    embed.add_field(name='⭐ Репутация', value=
        '`!+реп @user` - Дать репутацию (+1)\n' +
        '`!-реп @user` - Отнять репутацию (-1)\n' +
        '`!репутация [@user]` - Показать репутацию\n' +
        '`!топ` - Топ 10 по репутации',
        inline=False)
    
    embed.add_field(name='🎮 Развлечение', value=
        '`!монета` - Орел или решка\n' +
        '`!кубик` - Бросить кубик (1-6)\n' +
        '`!случайный` - Выбрать случайного юзера\n' +
        '`!8ball вопрос` - Магический шар',
        inline=False)
    
    embed.add_field(name='💬 Поддержка & Жалобы', value=
        '`!поддержка текст` - Отправить тикет\n' +
        '`!ответтикет ID текст` - Ответить на тикет (админ)\n' +
        '`!жалоба @user причина` - Пожаловаться',
        inline=False)
    
    embed.add_field(name='🤖 AI & Запрещённые слова', value=
        '`!чатик текст` - AI чат (Groq)\n' +
        '`!ответ [текст]` - Ответить голосом на последнее сообщение или указанный текст\n' +
        '`!запретить слово` - Запретить слово\n' +
        '`!разрешить слово` - Разрешить слово',
        inline=False)
    
    embed.add_field(name='📋 Логирование', value=
        '`!логи [кол-во]` - Показать логи модерации\n' +
        '`!логиголосовой` - Включить запись голоса в логи\n' +
        '`!нелогиголосовой` - Выключить запись голоса в логи\n' +
        '**Автоматически:** Бот записывает все разговоры в logs.txt при подключении (!подключиться)',
        inline=False)
    
    await ctx.send(embed=embed)

# === СТАРЫЕ ГОЛОСОВЫЕ КОМАНДЫ (ОТКЛЮЧЕНЫ - ИСПОЛЬЗУЙТЕ !диалог ВМЕСТО ЭТОГО) ===

# @bot.command(name='диалог')
# async def enable_dialogue(ctx):
#     """Включить режим диалога (бот отвечает на голос)"""
#     global voice_interaction_enabled
#     voice_interaction_enabled = True
#     await ctx.send("Режим диалога включен!")

# @bot.command(name='недиалог')
# async def disable_dialogue(ctx):
#     """Выключить режим диалога"""
#     global voice_interaction_enabled
#     voice_interaction_enabled = False
#     await ctx.send("Режим диалога выключен.")

@bot.command(name='логиголосовой')
async def enable_voice_logs(ctx):
    """Включить логирование голосового чата"""
    global voice_logging_enabled
    voice_logging_enabled = True
    await ctx.send("✅ Логирование голосового чата включено.")

@bot.command(name='нелогиголосовой')
async def disable_voice_logs(ctx):
    """Выключить логирование голосового чата"""
    global voice_logging_enabled
    voice_logging_enabled = False
    await ctx.send("❌ Логирование голосового чата выключено.")

@bot.command(name='debug_voice')
async def debug_voice(ctx):
    """Отладочная информация о голосе"""
    info = []
    info.append(f"Opus loaded: Не используется (используем opuslib вместо opus.dll)")
    
    vc = ctx.guild.voice_client
    if vc:
        info.append(f"Connected: {vc.is_connected()}")
        info.append(f"Client type: {type(vc)}")
        info.append(f"Session ID: {vc.session_id}")
        info.append(f"Endpoint: {vc.endpoint}")
        
        # Проверка на заглушение
        if ctx.guild.me.voice:
            info.append(f"Self Mute: {ctx.guild.me.voice.self_mute}")
            info.append(f"Self Deaf: {ctx.guild.me.voice.self_deaf}")
            info.append(f"Server Mute: {ctx.guild.me.voice.mute}")
            info.append(f"Server Deaf: {ctx.guild.me.voice.deaf}")
        
        if hasattr(vc, 'is_listening'):
            info.append(f"Is listening: {vc.is_listening()}")
        else:
            info.append("Is listening: N/A (Not a VoiceRecvClient?)")
            
        if ctx.guild.id in listening_sessions:
            session = listening_sessions[ctx.guild.id]
            sink = session['sink']
            info.append(f"Sink attached: Yes")
            if hasattr(sink, 'packet_count'):
                info.append(f"Packets received: {sink.packet_count}")
            else:
                info.append(f"Packets received: 0 (No data yet)")
        else:
            info.append("Sink attached: No")
    else:
        info.append("Not connected to voice")
        
    await ctx.send("```\n" + "\n".join(info) + "\n```")

@bot.command(name='подключиться', aliases=['join', 'voice'])
async def join_voice(ctx):
    """Подключиться к голосовому каналу"""
    if not ctx.author.voice:
        await ctx.send('❌ Ты не в голосовом канале')
        return
    
    global current_voice_client, auto_comment_enabled, current_text_channel
    
    # Отключаемся от всех существующих подключений на этом сервере
    for vc in bot.voice_clients:
        if vc.guild == ctx.guild:
            try:
                await vc.disconnect()
                await asyncio.sleep(1.0) # Увеличил задержку для надежности
            except:
                pass
    
    channel = ctx.author.voice.channel
    try:
        print(f"🔌 Подключаюсь к {channel.name}...")
        # Используем VoiceRecvClient для поддержки получения аудио (если доступен)
        if voice_recv is not None:
            current_voice_client = await channel.connect(cls=voice_recv.VoiceRecvClient)
        else:
            current_voice_client = await channel.connect()
        
        # Ждем завершения подключения
        await asyncio.sleep(1.0)
        
        current_text_channel = ctx.channel
        auto_comment_enabled = True
        
        # Автоматический запуск прослушивания для логов
        if voice_recv is not None:
            try:
                print("🎧 Запускаю прослушивание (Sink)...")
                sink = SpeechLogSink(voice_client=current_voice_client)
                current_voice_client.listen(sink)
                listening_sessions[ctx.guild.id] = {'sink': sink, 'vc': current_voice_client}
                
                # Сохраняем активный канал для автоподключения
                active_voice_channels[ctx.guild.id] = channel.id
                save_data()
                
                print(f"DEBUG: Auto-listening started for guild {ctx.guild.name}")
            except Exception as e:
                print(f"Error starting auto-listen: {e}")
                traceback.print_exc()
        else:
            print("⚠️ voice_recv не доступен - прослушивание отключено")
        
        await ctx.send(f'✅ Подключился к каналу {channel.name}! 👂 Слушаю голос и записываю логи...')
        await ctx.send(f'💡 Чтобы включить режим диалога, напиши `!диалог`')
        
        # Сразу начинаем слышать и комментировать
        await asyncio.sleep(0.5)  # Небольшая задержка после подключения
        comment = await generate_ai_comment()
        await ctx.send(f"🎤 Слышу: {comment}")
        await send_voice_message(current_voice_client, comment)
        
    except Exception as e:
        error_msg = f'❌ Ошибка подключения: {type(e).__name__}: {str(e)}'
        print(f"[ERROR] {error_msg}")
        log_event("ERROR", error_msg)
        await ctx.send(error_msg)
        import traceback
        traceback.print_exc()

@bot.command(name='отключиться', aliases=['leave', 'disconnect'])
async def leave_voice(ctx):
    """Отключиться от голосового канала"""
    global current_voice_client, auto_comment_enabled
    
    # Удаляем из автоподключения
    if ctx.guild.id in active_voice_channels:
        del active_voice_channels[ctx.guild.id]
        save_data()
    
    # Проверяем все голосовые подключения на сервере
    for vc in bot.voice_clients:
        if vc.guild == ctx.guild:
            try:
                auto_comment_enabled = False
                await vc.disconnect()
                current_voice_client = None
                await ctx.send('✅ Отключился от голосового канала')
                return
            except Exception as e:
                await ctx.send(f'❌ Ошибка отключения: {e}')
                return
    
    await ctx.send('❌ Бот не в голосовом канале')

@bot.command(name='сказать', aliases=['speak', 'say'])
async def speak(ctx, *, text: str):
    """Произнести текст в голосовом канале"""
    global current_voice_client
    
    if not current_voice_client:
        await ctx.send('❌ Бот не в голосовом канале. Используй !подключиться')
        return
    
    if not current_voice_client.is_connected():
        await ctx.send('❌ Голосовое соединение потеряно')
        return
    
    await ctx.send(f'🎤 Произношу: "{text}"')
    print(f'🎤 Голосовое сообщение: {text}')
    await send_voice_message(current_voice_client, text)

@bot.command(name='музыка', aliases=['music'])
async def music_cmd(ctx):
    """Проиграть MP3 файл в голосовом канале (!музыка + файл)"""
    global current_voice_client, current_audio_file
    
    # Если прикреплен аудиофайл — сразу проигрываем его
    if not ctx.message.attachments:
        await ctx.send('❌ Прикрепи MP3 файл. Пример: `!музыка` + файл')
        return
    
    # Ищем первый аудиофайл
    audio_file = None
    for att in ctx.message.attachments:
        name = (att.filename or '').lower()
        ctype = (getattr(att, 'content_type', '') or '').lower()
        if name.endswith(('.mp3', '.wav', '.ogg', '.m4a')) or ctype.startswith('audio'):
            audio_file = att
            break
    
    if not audio_file:
        await ctx.send('❌ Не найден аудиофайл (mp3, wav, ogg, m4a)')
        return
    
    # Проверяем подключение к голосу
    vc = None
    
    # Если команда в ЛС - ищем любое подключение бота
    if ctx.guild is None:
        # Сначала проверяем current_voice_client
        if current_voice_client and current_voice_client.is_connected():
            vc = current_voice_client
        else:
            # Если нет, ищем в bot.voice_clients
            if bot.voice_clients:
                vc = bot.voice_clients[0]
        
        if not vc or not vc.is_connected():
            await ctx.send('❌ Бот не подключен к голосовому каналу. Используй `!подключиться`')
            return
    else:
        # Если команда на сервере - ищем подключение в этом сервере
        for c in bot.voice_clients:
            if c.guild == ctx.guild and c.is_connected():
                vc = c
                break
        
        if vc is None:
            # Подключаемся к каналу автора если он там
            if not ctx.author.voice:
                await ctx.send('❌ Я не в голосовом канале и ты тоже. Зайди в канал или используй `!подключиться`.')
                return
            try:
                vc = await ctx.author.voice.channel.connect()
                await wait_until_connected(vc, 5.0)
            except Exception as e:
                await ctx.send(f'❌ Не удалось подключиться: {e}')
                return
    
    # Скачиваем файл во временное хранилище
    try:
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp:
            tmp_path = tmp.name
            await audio_file.save(tmp_path)
        
        # Сохраняем путь текущего файла для перезапуска
        current_audio_file = tmp_path
        
        # Останавливаем текущее воспроизведение
        if vc.is_playing():
            vc.stop()
        
        # Запускаем проигрывание с применением громкости
        ffmpeg_path = r"C:\ffmpeg-master-latest-win64-gpl-shared\bin\ffmpeg.exe"
        try:
            # Вычисляем множитель громкости (от 0 до 1)
            volume_multiplier = current_volume / 100.0
            
            if os.path.exists(ffmpeg_path):
                # Используем options для FFmpeg фильтра громкости
                source = discord.FFmpegPCMAudio(
                    tmp_path, 
                    executable=ffmpeg_path,
                    options=f'-filter:a volume={volume_multiplier}'
                )
            else:
                source = discord.FFmpegPCMAudio(
                    tmp_path,
                    options=f'-filter:a volume={volume_multiplier}'
                )
            
            def cleanup(error):
                try:
                    os.remove(tmp_path)
                except:
                    pass
            
            vc.play(source, after=cleanup)
            # Сохраняем время начала проигрывания
            current_audio_start_time = time.time()
            await ctx.send(f'🎵 Проигрываю: `{audio_file.filename}` (громкость {current_volume}%)')
        except Exception as e:
            await ctx.send(f'❌ Ошибка воспроизведения: {e}')
            try:
                os.remove(tmp_path)
            except:
                pass
    except Exception as e:
        await ctx.send(f'⚠️ Ошибка загрузки файла: {e}')

@bot.command(name='снова', aliases=['replay', 'again'])
async def replay_music(ctx):
    """Перезапустить текущую музыку с начала"""
    global current_audio_file, current_audio_start_time
    
    # Ищем голосовое подключение
    vc = None
    
    if ctx.guild is None:
        # Если в ЛС
        if current_voice_client and current_voice_client.is_connected():
            vc = current_voice_client
        else:
            if bot.voice_clients:
                vc = bot.voice_clients[0]
    else:
        # Если на сервере
        for c in bot.voice_clients:
            if c.guild == ctx.guild and c.is_connected():
                vc = c
                break
    
    if vc is None:
        await ctx.send('❌ Бот не в голосовом канале')
        return
    
    if not current_audio_file:
        await ctx.send('❌ Нет сохраненного трека для перезапуска')
        return
    
    try:
        # Останавливаем текущее воспроизведение
        if vc.is_playing():
            vc.stop()
        
        await asyncio.sleep(0.3)  # Небольшая пауза
        
        # Перезапускаем музыку с начала
        ffmpeg_path = r"C:\ffmpeg-master-latest-win64-gpl-shared\bin\ffmpeg.exe"
        volume_multiplier = current_volume / 100.0
        
        if os.path.exists(ffmpeg_path):
            source = discord.FFmpegPCMAudio(
                current_audio_file,
                executable=ffmpeg_path,
                options=f'-filter:a volume={volume_multiplier}'
            )
        else:
            source = discord.FFmpegPCMAudio(
                current_audio_file,
                options=f'-filter:a volume={volume_multiplier}'
            )
        
        def cleanup(error):
            pass
        
        vc.play(source, after=cleanup)
        current_audio_start_time = time.time()
        await ctx.send(f'🔄 Музыка перезапущена с начала (громкость {current_volume}%)')
    except Exception as e:
        await ctx.send(f'❌ Ошибка при перезапуске: {e}')

@bot.command(name='позиция', aliases=['pos', 'position'])
async def position(ctx):
    """Показать текущую позицию проигрывания"""
    if not current_audio_file or not current_audio_start_time:
        await ctx.send('❌ Нет активного трека')
        return
    elapsed = time.time() - current_audio_start_time
    await ctx.send(f'⏱️ Позиция: **{elapsed:.1f}s**')


def _get_audio_duration(path: str) -> float | None:
    """Попытка получить длительность аудиофайла через ffprobe, возвращает секунды или None."""
    try:
        ffprobe_path = None
        ffmpeg_path = r"C:\ffmpeg-master-latest-win64-gpl-shared\bin\ffmpeg.exe"
        if os.path.exists(ffmpeg_path):
            ffprobe_path = os.path.join(os.path.dirname(ffmpeg_path), 'ffprobe.exe')
            if not os.path.exists(ffprobe_path):
                ffprobe_path = 'ffprobe'  # попробовать из PATH
        else:
            ffprobe_path = 'ffprobe'

        import subprocess
        cmd = [ffprobe_path, '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', path]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if proc.returncode == 0 and proc.stdout:
            s = proc.stdout.strip().split('\n')[0]
            return float(s)
    except Exception:
        pass
    return None


@bot.command(name='время', aliases=['time', 'settime', 'seek'])
async def time_command(ctx, *, time_arg: str = None):
    """Показать или выставить время воспроизведения.

    Использование:
    - `!время` — показать текущую позицию
    - `!время 1:30` или `!время 90` — перемотать на 1 минуту 30 секунд или на 90 секунд
    """
    global current_audio_start_time

    if not current_audio_file:
        await ctx.send('❌ Нет активного трека')
        return

    def fmt(sec):
        m = int(sec // 60)
        s = int(sec % 60)
        return f'{m:02d}:{s:02d}'

    total = _get_audio_duration(current_audio_file)

    # Если аргумента нет — показываем позицию
    if not time_arg:
        if not current_audio_start_time:
            await ctx.send('❌ Трек не воспроизводится сейчас')
            return
        elapsed = time.time() - current_audio_start_time
        if total:
            await ctx.send(f'⏱️ Позиция: **{fmt(elapsed)}** / **{fmt(total)}**')
        else:
            await ctx.send(f'⏱️ Позиция: **{fmt(elapsed)}** (общая длительность: неизвестна)')
        return

    # Парсим строку времени
    def parse_time_str(s: str) -> float | None:
        try:
            s = s.strip()
            # hh:mm:ss or mm:ss
            parts = s.split(':')
            parts = [p for p in parts if p != '']
            if len(parts) == 1:
                # seconds
                return float(parts[0])
            elif len(parts) == 2:
                return int(parts[0]) * 60 + float(parts[1])
            elif len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        except Exception:
            return None
        return None

    pos = parse_time_str(time_arg)
    if pos is None or pos < 0:
        await ctx.send('❌ Неверный формат времени. Пример: `1:30` или `90`')
        return

    # Останавливаем текущее воспроизведение (если есть) и перезапускаем с позиции
    # Ищем голосовое подключение
    vc = None
    if ctx.guild is None:
        if current_voice_client and current_voice_client.is_connected():
            vc = current_voice_client
        else:
            # Найдём любое активное подключение (включая воспроизведение)
            for c in bot.voice_clients:
                if c.is_connected():
                    vc = c
                    break
    else:
        for c in bot.voice_clients:
            if c.guild == ctx.guild and c.is_connected():
                vc = c
                break

    if vc is None:
        await ctx.send('❌ Бот не подключён ни к одному голосовому каналу')
        return

    # Если файла нет или отсутствует на диске — сообщаем
    if not current_audio_file or not os.path.exists(current_audio_file):
        await ctx.send('❌ Нет активного трека на сервере (файл недоступен). Отправь `!музыка` + файл, чтобы загрузить и воспроизвести.')
        return

    try:
        if vc.is_playing():
            vc.stop()
            await asyncio.sleep(0.2)

        ffmpeg_path = r"C:\ffmpeg-master-latest-win64-gpl-shared\bin\ffmpeg.exe"
        volume_multiplier = current_volume / 100.0
        # Опции: перемотка + фильтр громкости
        options_str = f'-ss {pos:.3f} -filter:a volume={volume_multiplier}'
        await ctx.send(f'🔧 Перематываю на **{fmt(pos)}** (options: `{options_str}`)')

        if os.path.exists(ffmpeg_path):
            source = discord.FFmpegPCMAudio(current_audio_file, executable=ffmpeg_path, options=options_str)
        else:
            source = discord.FFmpegPCMAudio(current_audio_file, options=options_str)

        def cleanup(error):
            pass

        vc.play(source, after=cleanup)
        current_audio_start_time = time.time() - pos
        await ctx.send(f'✅ Трек воспроизводится с **{fmt(pos)}**')
    except Exception as e:
        await ctx.send(f'❌ Ошибка при установке времени: {e}')

import traceback

# Обёртываем класс SpeechLogSink, так как voice_recv может быть недоступен
if voice_recv is not None:
    class SpeechLogSink(voice_recv.AudioSink):
        """Sink для записи аудио и распознавания речи в реальном времени"""
        def __init__(self, voice_client=None):
            super().__init__()
            self.voice_client = voice_client
            self.user_buffers = {} # user_id -> bytearray (для распознавания)
            self.audio_data = {} # user_id -> bytearray (для сохранения в файл)
            self.last_packet_time = {} # user_id -> time
            self.loop = asyncio.get_running_loop()
            self.processing_task = self.loop.create_task(self.process_audio_queue())
            print("DEBUG: SpeechLogSink initialized")
            
        def wants_opus(self):
            return False # Мы хотим PCM

        def write(self, user, data):
            if user is None:
                # print("?", end="", flush=True) 
                return

            # data - это VoiceData объект в discord-ext-voice-recv
            # data.pcm - это PCM байты
            pcm = data.pcm
            
            # DEBUG: Визуализация активности (точка каждые 10 пакетов)
            if not hasattr(self, 'packet_count'):
                self.packet_count = 0
            self.packet_count += 1
            if self.packet_count % 10 == 0: 
                print(".", end="", flush=True)

            # Сохраняем для распознавания
            if user.id not in self.user_buffers:
                self.user_buffers[user.id] = bytearray()
                # Инициализируем общий буфер только если его нет
                if user.id not in self.audio_data:
                    self.audio_data[user.id] = bytearray()
                
                print(f"\nDEBUG: Начало приема данных от {user.name}")
            
            self.user_buffers[user.id].extend(pcm)
            self.audio_data[user.id].extend(pcm)
            self.last_packet_time[user.id] = time.time()
        
    async def process_audio_queue(self):
        print("DEBUG: process_audio_queue started")
        while True:
            await asyncio.sleep(0.5)
            try:
                now = time.time()
                # Проверяем тишину
                for user_id in list(self.user_buffers.keys()):
                    # Если прошло больше 1 секунды с последнего пакета
                    if now - self.last_packet_time.get(user_id, 0) > 1.0:
                        # Тишина > 1 сек, обрабатываем буфер
                        audio_data = self.user_buffers.pop(user_id)
                        # Не удаляем last_packet_time здесь, чтобы не ломать логику
                        
                        print(f"\nDEBUG: Processing buffer for {user_id}, size: {len(audio_data)}")
                        
                        if len(audio_data) > 10000: # Уменьшил порог еще сильнее (было 20000)
                            self.loop.create_task(self.recognize_and_log(user_id, audio_data))
                        else:
                            print(f"DEBUG: Buffer too small ({len(audio_data)}), ignoring")
            except Exception as e:
                print(f"Error in process_audio_queue: {e}")
                traceback.print_exc()
    
    async def recognize_and_log(self, user_id, pcm_data):
        # Если выключено и логирование, и диалог - выходим
        if not voice_logging_enabled and not voice_interaction_enabled:
            return

        print(f"DEBUG: Starting recognition for {user_id}")
        try:
            # Конвертируем PCM в AudioData для speech_recognition
            # Discord: 48kHz, Stereo (2 channels), 16-bit (2 bytes)
            import speech_recognition as sr
            
            # Конвертируем стерео в моно
            try:
                # Проверяем длину данных (должна быть кратна 4 для стерео 16 бит)
                if len(pcm_data) % 4 != 0:
                    # Обрезаем лишние байты
                    pcm_data = pcm_data[:-(len(pcm_data) % 4)]
                
                mono_data = audioop.tomono(bytes(pcm_data), 2, 0.5, 0.5)
            except Exception as e:
                print(f"Error converting to mono: {e}")
                mono_data = bytes(pcm_data) # Fallback

            # Создаем AudioData (48kHz, Mono, 16-bit)
            # Важно: AudioData ожидает raw PCM данные
            audio = sr.AudioData(mono_data, 48000, 2)
            r = sr.Recognizer()
            
            # Распознаем (в отдельном потоке, чтобы не блокировать бота)
            print(f"DEBUG: Sending to Google Speech Recognition...")
            text = await self.loop.run_in_executor(None, lambda: r.recognize_google(audio, language="ru-RU"))
            print(f"DEBUG: Recognized text: {text}")
            
            user = bot.get_user(user_id)
            username = user.name if user else f"User {user_id}"

            # 1. Логирование
            if voice_logging_enabled:
                if 'log_event' in globals():
                    log_event("VOICE", f"{username}: {text}")
                else:
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    log_msg = f"[{timestamp}] [VOICE] {username}: {text}"
                    print(log_msg)
                    with open('logs.txt', 'a', encoding='utf-8') as f:
                        f.write(log_msg + '\n')
                        f.flush()

            # 2. Интерактивный режим (ответы на вопросы)
            if voice_interaction_enabled and self.voice_client and self.voice_client.is_connected():
                # Проверяем триггеры (добавил 'вот' так как часто путает с 'бот')
                triggers = ['бот', 'bot', 'эй бот', 'слушай бот', 'bot', 'бот,', 'вот']
                lower_text = text.lower()
                
                # Простая проверка на вхождение слова
                is_triggered = False
                for trigger in triggers:
                    if trigger in lower_text:
                        is_triggered = True
                        break
                
                # ОТЛАДКА: Пишем в чат, что услышали
                if 'current_text_channel' in globals() and current_text_channel:
                    try:
                        await current_text_channel.send(f"👂 **Распознано:** {text}")
                    except:
                        pass

                if is_triggered:
                    print(f"🤖 Trigger detected in: {text}")
                    if 'current_text_channel' in globals() and current_text_channel:
                        await current_text_channel.send(f"🤖 **Думаю над ответом...**")
                    
                    # Формируем промпт для Groq
                    prompt = f"Пользователь {username} сказал: '{text}'. Ответь ему кратко (максимум 20 слов), смешно и дерзко."
                    
                    try:
                        # Запрос к Groq
                        chat_completion = await self.loop.run_in_executor(None, lambda: groq_client.chat.completions.create(
                            messages=[
                                {"role": "system", "content": "Ты - дерзкий бот. Отвечай на русском языке."},
                                {"role": "user", "content": prompt}
                            ],
                            model="llama3-8b-8192",
                        ))
                        
                        response_text = chat_completion.choices[0].message.content
                        print(f"🤖 AI Response: {response_text}")
                        
                        # Озвучиваем ответ
                        await send_voice_message(self.voice_client, response_text)
                        
                    except Exception as e:
                        print(f"❌ Error generating AI response: {e}")
                else:
                    print(f"DEBUG: No trigger found in '{text}'")

        except sr.UnknownValueError:
            print(f"DEBUG: Speech not recognized (UnknownValueError)")
            # Логируем неразборчивую речь тоже, чтобы было видно активность
            if voice_logging_enabled:
                user = bot.get_user(user_id)
                username = user.name if user else f"User {user_id}"
                if 'log_event' in globals():
                    log_event("VOICE_NOISE", f"{username}: <Неразборчиво>")
        except Exception as e:
            print(f"Error in recognition: {e}")
            traceback.print_exc()

    def cleanup(self):
        if hasattr(self, 'processing_task'):
            self.processing_task.cancel()
else:
    # voice_recv недоступен, создаём пустой класс
    class SpeechLogSink:
        def __init__(self, voice_client=None):
            self.voice_client = voice_client
        def cleanup(self):
            pass
        def write(self, user, data):
            pass
        def wants_opus(self):
            return False

@bot.command(name='слушать', aliases=['listen', 'hear'])
async def listen_command(ctx, duration: int = 5):
    """Записать звук из голосового канала в файл
    
    Использование:
    !слушать           — записывает 5 сек (по умолчанию)
    !слушать 10        — записывает 10 сек
    
    ТРЕБУЕТ: Бот должен быть в голосовом канале!
    Используй: !подключиться
    """
    
    # Проверка: команда работает только локально, не на Railway
    if voice_recv and not hasattr(voice_recv.VoiceRecvClient, 'record'):
        await ctx.send("❌ Команда `!слушать` недоступна на Railway/Linux. Используйте локально на Windows.")
        return
    
    if not isinstance(ctx.channel, discord.DMChannel):
        await ctx.send("❌ Эту команду можно использовать только в ДМ")
        return
    
    if duration < 1 or duration > 120:
        await ctx.send("❌ Длительность от 1 до 120 сек")
        return
    
    if voice_recv is None:
        await ctx.send("❌ voice_recv недоступен. На локальном ПК используй sounddevice.")
        return
    
    # Ищем подключение бота к голосовому каналу
    target_vc = None
    for guild in ctx.bot.guilds:
        vc = guild.voice_client
        if vc and vc.is_connected() and isinstance(vc, voice_recv.VoiceRecvClient):
            target_vc = vc
            break
    
    if not target_vc:
        await ctx.send("❌ Бот не подключен к голосовому каналу. Напиши `!подключиться` на сервере.")
        return
    
    try:
        status_msg = await ctx.send(f"🎙️ **Начинаю запись** ({duration} сек)...")
        
        # Создаем sink для записи (простой класс, не абстрактный)
        class RecordSink:
            def __init__(self):
                self.audio_data = bytearray()
            
            async def wants_opus(self):
                return False
            
            async def recv_audio(self, user, audio):
                if audio and hasattr(audio, 'pcm'):
                    self.audio_data.extend(audio.pcm)
            
            def cleanup(self):
                self.audio_data.clear()
            
            def write(self, data):
                if data:
                    self.audio_data.extend(data)
        
        sink = RecordSink()
        
        # Начинаем запись (используем record() вместо start_recording)
        try:
            target_vc.record(sink)
        except AttributeError:
            # Fallback если нет record()
            await ctx.send("❌ Метод запись недоступен на этом хосте")
            return
        
        # Ждем
        await asyncio.sleep(duration)
        
        # Стопим запись
        try:
            target_vc.stop_recording()
        except:
            pass
        
        if not sink.audio_data:
            await ctx.send("❌ Не было записано никакого звука.")
            return
        
        await status_msg.edit(content="💾 **Сохраняю файл**...")
        
        # Сохраняем в WAV
        import wave
        import tempfile
        import os
        
        temp_dir = tempfile.gettempdir()
        audio_file = os.path.join(temp_dir, f'recording_{int(time.time())}.wav')
        
        with wave.open(audio_file, 'wb') as wav_file:
            wav_file.setnchannels(2)
            wav_file.setsampwidth(2)
            wav_file.setframerate(48000)
            wav_file.writeframes(bytes(sink.audio_data))
        
        file_size_mb = os.path.getsize(audio_file) / (1024 * 1024)
        
        await status_msg.edit(content=f"✅ **Запись готова** ({file_size_mb:.2f} МБ)")
        
        # Отправляем файл
        with open(audio_file, 'rb') as f:
            await ctx.send(file=discord.File(f, filename=f'recording_{duration}sec.wav'))
        
        # Удаляем
        try:
            os.remove(audio_file)
        except:
            pass
        
    except Exception as e:
        await ctx.send(f"❌ Ошибка: {str(e)}")
        traceback.print_exc()

@bot.command(name='стопслушать', aliases=['stoplisten', 'stophearing'])
async def stop_listen_command(ctx):
    """Остановить запись и получить файл в ЛС (только в ЛС)"""
    if not isinstance(ctx.channel, discord.DMChannel):
        await ctx.send("❌ Эту команду можно использовать только в личных сообщениях.")
        return

    # Ищем активную запись
    target_guild_id = None
    target_session = None
    
    for guild_id, session in listening_sessions.items():
        if session['vc'].is_connected():
            target_guild_id = guild_id
            target_session = session
            break
    
    if not target_session:
        await ctx.send('❌ Я сейчас ничего не записываю.')
        return

    vc = target_session['vc']
    sink = target_session['sink']
    
    try:
        vc.stop_listening()
        sink.cleanup()
        del listening_sessions[target_guild_id]
        
        await ctx.send('🛑 Запись остановлена. Сведение аудио в один файл (это может занять время)...')
        
        input_wavs = []
        
        ffmpeg_path = r"C:\ffmpeg-master-latest-win64-gpl-shared\bin\ffmpeg.exe"
        if not os.path.exists(ffmpeg_path):
            ffmpeg_path = "ffmpeg"

        # 1. Сохраняем все потоки в WAV
        for user_id, pcm_data in sink.audio_data.items():
            if len(pcm_data) < 1000: continue # Пустые
            
            try:
                with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_wav:
                    temp_wav_path = temp_wav.name
                    with wave.open(temp_wav, 'wb') as wav_file:
                        wav_file.setnchannels(2)
                        wav_file.setsampwidth(2)
                        wav_file.setframerate(48000)
                        wav_file.writeframes(pcm_data)
                input_wavs.append(temp_wav_path)
            except Exception as e:
                print(f"Error saving wav for {user_id}: {e}")

        if not input_wavs:
            await ctx.send("🎧 Запись пуста.")
            return

        # 2. Сводим в один MP3
        output_mp3 = f"conversation_{target_guild_id}_{int(time.time())}.mp3"
        
        try:
            cmd = [ffmpeg_path, '-y']
            
            # Добавляем все входы
            for wav_path in input_wavs:
                cmd.extend(['-i', wav_path])
            
            # Если больше 1 файла, используем amix
            if len(input_wavs) > 1:
                cmd.extend(['-filter_complex', f'amix=inputs={len(input_wavs)}:duration=longest', '-b:a', '192k', output_mp3])
            else:
                # Просто конвертируем
                cmd.extend(['-b:a', '192k', output_mp3])
            
            # Запускаем
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # Отправляем
            if os.path.exists(output_mp3):
                await ctx.send("🎧 Общая запись разговора:", file=discord.File(output_mp3))
            else:
                await ctx.send("❌ Ошибка: Файл записи не был создан.")
                
        except Exception as e:
            await ctx.send(f"❌ Ошибка сведения аудио: {e}")
            traceback.print_exc()
            
        finally:
            # Чистим мусор
            for f in input_wavs:
                try: os.remove(f)
                except: pass
            try:
                if os.path.exists(output_mp3): os.remove(output_mp3)
            except: pass
            
    except Exception as e:
        await ctx.send(f'❌ Ошибка остановки: {e}')
        traceback.print_exc()


@bot.command(name='комментировать', aliases=['comment'])
async def comment(ctx):
    """Произнести случайный комментарий"""
    global current_voice_client
    
    if not current_voice_client:
        await ctx.send('Бот не в голосовом канале')
        return
    
    comments = [
        'Привет всем!',
        'Как дела?',
        'Хорошего дня!',
        'Кто здесь?',
        'Веселимся?',
        'Ха-ха!',
        'Класс!',
        'Восхитительно!',
    ]
    
    import random
    comment_text = random.choice(comments)
    await ctx.send(f'🎤 Комментирую: "{comment_text}"')
    
    # Озвучиваем комментарий
    try:
        await send_voice_message(current_voice_client, comment_text)
    except:
        pass

@bot.command(name='видео', aliases=['video'])
async def video_cmd(ctx):
    """Воспроизвести MP4 видео (звук + инструкция для демо экрана)"""
    # Если прикреплен видеофайл — проигрываем его
    if not ctx.message.attachments:
        await ctx.send('❌ Прикрепи MP4 файл. Пример: `!видео` + файл')
        return
    
    # Ищем первый видеофайл
    video_file = None
    for att in ctx.message.attachments:
        name = (att.filename or '').lower()
        ctype = (getattr(att, 'content_type', '') or '').lower()
        if name.endswith(('.mp4', '.avi', '.mov', '.mkv', '.webm')) or ctype.startswith('video'):
            video_file = att
            break
    
    if not video_file:
        await ctx.send('❌ Не найден видеофайл (mp4, avi, mov, mkv, webm)')
        return
    
    # Проверяем подключение к голосу
    vc = None
    for c in bot.voice_clients:
        if c.guild == ctx.guild and c.is_connected():
            vc = c
            break
    
    if vc is None:
        # Подключаемся к каналу автора если он там
        if not ctx.author.voice:
            await ctx.send('❌ Я не в голосовом канале и ты тоже. Зайди в канал или используй `!подключиться`.')
            return
        try:
            vc = await ctx.author.voice.channel.connect()
            await wait_until_connected(vc, 5.0)
        except Exception as e:
            await ctx.send(f'❌ Не удалось подключиться: {e}')
            return
    
    # Скачиваем файл во временное хранилище
    try:
        with tempfile.NamedTemporaryFile(suffix='.mp4', delete=False) as tmp:
            tmp_path = tmp.name
            await video_file.save(tmp_path)
        
        # Останавливаем текущее воспроизведение
        if vc.is_playing():
            vc.stop()
        
        # Запускаем проигрывание звука из видео
        ffmpeg_path = r"C:\ffmpeg-master-latest-win64-gpl-shared\bin\ffmpeg.exe"
        try:
            if os.path.exists(ffmpeg_path):
                audio_source = discord.FFmpegPCMAudio(tmp_path, executable=ffmpeg_path)
            else:
                audio_source = discord.FFmpegPCMAudio(tmp_path)
            
            def cleanup(error):
                try:
                    os.remove(tmp_path)
                except:
                    pass
            
            # Воспроизводим аудиодорожку видео
            vc.play(audio_source, after=cleanup)
            await ctx.send(
                f'🎬 **Воспроизвожу видео:** `{video_file.filename}`\n'
                f'🔊 Звук включен!\n\n'
                f'**Для просмотра видео:**\n'
                f'1️⃣ Нажми на аватарку бота в голосовом канале\n'
                f'2️⃣ Нажми "Смотреть экран" или "Watch Stream"\n'
                f'3️⃣ Выбери свой экран или приложение\n\n'
                f'_Примечание: демонстрацию экрана может включить только пользователь вручную_'
            )
        except Exception as e:
            await ctx.send(f'❌ Ошибка воспроизведения: {e}')
            try:
                os.remove(tmp_path)
            except:
                pass
    except Exception as e:
        await ctx.send(f'⚠️ Ошибка загрузки файла: {e}')

@bot.command(name='музыкарандом', aliases=['musicrandom', 'рандоммузыка'])
async def music_random(ctx):
    """Найти случайную музыку: присылает ссылки поиска (SoundCloud/YouTube Music)."""
    seeds = [
        'lofi chill', 'electronic upbeat', 'ambient', 'hip hop instrumental',
        'synthwave', 'pop hits', 'rock classic', 'jazz cafe', 'house mix', 'trap beat'
    ]
    import random
    q = random.choice(seeds)
    sc_url = f'https://soundcloud.com/search?q={requests.utils.quote(q)}'
    yt_url = f'https://music.youtube.com/search?q={requests.utils.quote(q)}'
    await ctx.send(
        f'🔎 Случайный запрос: "{q}"\n'
        f'• SoundCloud: {sc_url}\n'
        f'• YouTube Music: {yt_url}\n'
        'Выберите трек и пришлите ссылку — включу по ней.'
    )



@bot.command(name='вопрос', aliases=['question', 'q'])
async def question(ctx, *, question_text=None):
    """Ответить на вопрос голосом в голосовой чат (!вопрос вопрос здесь)"""
    global current_voice_client
    
    # Проверяем есть ли бот в голосовом канале
    if not current_voice_client or not current_voice_client.is_connected():
        await ctx.send('❌ Я не в голосовом канале! Подключитесь с !подключиться')
        return
    
    # Проверяем есть ли вопрос
    if not question_text:
        await ctx.send('❌ Укажите вопрос! Пример: !вопрос как это работает?')
        return
    
    # Отправляем вопрос в чат
    await ctx.send(f'❓ Вопрос: "{question_text}"')
    print(f"❓ Вопрос получен: {question_text}")
    
    try:
        # Генерируем ответ через AI
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{
                "role": "user",
                "content": f"Ответь кратко (1–2 предложения) по делу, дружелюбно и нейтрально, без токсичности и насилия. Вопрос: {question_text}"
            }],
            temperature=0.7,
            max_tokens=150
        )
        
        answer = response.choices[0].message.content
        
        # Озвучиваем ответ в голосовом канале (без текста в чат)
        await send_voice_message(current_voice_client, answer)
        
    except Exception as e:
        await ctx.send(f'❌ Ошибка генерации ответа: {e}')
        print(f"❌ Ошибка AI ответа: {e}")

@bot.command(name='некоментировать', aliases=['nocomment', 'стоп'])
async def no_comment(ctx):
    """Отключить автокомментарии"""
    global auto_comment_enabled
    
    auto_comment_enabled = False
    await ctx.send('⏸️ Автокомментарии отключены')
    print("⏸️ Автокомментарии отключены")

@bot.command(name='твоеимя', aliases=['name', 'имя'])
async def my_name(ctx):
    """Сказать своё имя в голосовом канале"""
    global current_voice_client
    
    if not current_voice_client or not current_voice_client.is_connected():
        await ctx.send('❌ Я не в голосовом канале! Используй !подключиться')
        return
    
    await ctx.send('🎤 Говорю своё имя...')
    await send_voice_message(current_voice_client, "Я Чикатило")

@bot.command(name='стопмузыка', aliases=['stopmusic', 'stop_music', 'пауза'])
async def stop_music(ctx):
    """Выключить музыку"""
    # Ищем голосовое подключение
    vc = None

    # Если команда в ЛС - ищем любое активное подключение
    if ctx.guild is None:
        if current_voice_client and current_voice_client.is_connected():
            vc = current_voice_client
        else:
            for c in bot.voice_clients:
                if c.is_connected():
                    vc = c
                    break
    else:
        for c in bot.voice_clients:
            if c.guild == ctx.guild and c.is_connected():
                vc = c
                break

    if vc is None:
        await ctx.send('❌ Бот не в голосовом канале')
        return

    if vc.is_playing():
        vc.stop()
        await ctx.send('⏹️ Музыка остановлена')
    else:
        await ctx.send('❌ Музыка не проигрывается')

@bot.command(name='громкость', aliases=['volume', 'vol'])
async def volume(ctx, level: int = None):
    """Установить громкость музыки (0-100)"""
    global current_volume, current_audio_file, current_voice_client, current_audio_start_time
    
    # Ищем голосовое подключение
    vc = None
    
    # Если команда в ЛС - ищем любое подключение
    if ctx.guild is None:
        if current_voice_client and current_voice_client.is_connected():
            vc = current_voice_client
        elif bot.voice_clients:
            vc = bot.voice_clients[0]
    else:
        # Если команда на сервере - ищем в этом сервере
        for c in bot.voice_clients:
            if c.guild == ctx.guild and c.is_connected():
                vc = c
                break
    
    if vc is None:
        await ctx.send('❌ Бот не в голосовом канале')
        return
    
    # Если уровень не указан - показываем текущую громкость
    if level is None:
        await ctx.send(f'🔊 Текущая громкость: **{current_volume}%**')
        return
    
    # Проверяем диапазон
    if level < 0 or level > 100:
        await ctx.send('❌ Громкость должна быть от 0 до 100')
        return
    
    # Устанавливаем новую громкость
    old_volume = current_volume
    current_volume = level
    await ctx.send(f'🔊 Громкость изменена: {old_volume}% → **{level}%**')
    
    # Если музыка проигрывается и есть сохраненный файл - перезапускаем трек с начала с новой громкостью
    if vc.is_playing() and current_audio_file:
        try:
            vc.stop()
            await asyncio.sleep(0.3)  # Небольшая пауза для остановки
            
            # Перезапускаем музыку с начала с новой громкостью
            ffmpeg_path = r"C:\ffmpeg-master-latest-win64-gpl-shared\bin\ffmpeg.exe"
            volume_multiplier = current_volume / 100.0
            options_str = f'-filter:a volume={volume_multiplier}'
            
            # Debug
            await ctx.send(f'🔧 Перезапускаю трек с начала, громкость={level}%')
            
            if os.path.exists(ffmpeg_path):
                source = discord.FFmpegPCMAudio(
                    current_audio_file,
                    executable=ffmpeg_path,
                    options=options_str
                )
            else:
                source = discord.FFmpegPCMAudio(
                    current_audio_file,
                    options=options_str
                )
            
            def cleanup(error):
                pass
            
            vc.play(source, after=cleanup)
            current_audio_start_time = time.time()
            await ctx.send(f'🎵 Музыка перезапущена с громкостью **{level}%**')
        except Exception as e:
            await ctx.send(f'⚠️ Ошибка при перезапуске: {e}')
            try:
                if os.path.exists(ffmpeg_path):
                    source = discord.FFmpegPCMAudio(
                        current_audio_file, 
                        executable=ffmpeg_path,
                        options=f'-filter:a volume={volume_multiplier}'
                    )
                else:
                    source = discord.FFmpegPCMAudio(
                        current_audio_file,
                        options=f'-filter:a volume={volume_multiplier}'
                    )
                vc.play(source, after=cleanup)
                current_audio_start_time = time.time()
                await ctx.send(f'🎵 Музыка перезапущена с громкостью **{level}%**')
            except Exception as e:
                await ctx.send(f'❌ Не удалось перезапустить: {e}')
        except Exception as e:
            await ctx.send(f'⚠️ Ошибка при перезапуске: {e}')

@bot.event
async def on_command_error(ctx, error):
    log_event("ERROR", f"{ctx.author.name} вызвал !{ctx.command.name if ctx.command else 'unknown'} - Ошибка: {str(error)[:100]}")
    if isinstance(error, commands.CommandNotFound):
        await ctx.send('❌ Команда не найдена. Введи !помощь')
        return
    if isinstance(error, commands.MissingPermissions):
        await ctx.send('❌ Нет прав')
        return
    await ctx.send(f'❌ Ошибка: {error}')

@bot.command(name='отправить-сообщение', aliases=['send_message', 'send', 'сообщение-отправить'])
async def send_message(ctx, *, message: str = None):
    """Отправить сообщение/фото в канал #общее (только админ, работает в ЛС)"""
    if ctx.author.id != ADMIN_ID:
        await ctx.send('Только админ может использовать эту команду')
        return
    
    # Игнорирую если в канале
    if ctx.guild is not None:
        await ctx.send('Эту команду можно использовать только в личных сообщениях!')
        return
    
    try:
        # Ищем канал "общее" в гильдии
        guild = bot.guilds[0] if bot.guilds else None
        if not guild:
            await ctx.send('Бот не подключен к серверу')
            return
        
        # Ищем канал по названию
        channel = discord.utils.get(guild.channels, name='общее')
        if not channel:
            await ctx.send('Канал "общее" не найден')
            return
        
        # Обработка вложений (фото)
        if ctx.message.attachments:
            files_to_send = []
            for attachment in ctx.message.attachments:
                file_data = await attachment.read()
                files_to_send.append(discord.File(io.BytesIO(file_data), filename=attachment.filename))
            
            # Отправляем вложения с текстом (если есть)
            send_message_text = message if message else "Файл от админа"
            await channel.send(send_message_text, files=files_to_send)
            await ctx.send(f'Отправлено {len(files_to_send)} файл(ов) в #{channel.name}')
            moderation_logs.append(f"[ФАЙЛЫ] {ctx.author.name} отправил {len(files_to_send)} файл(ов) в #{channel.name}")
        elif message:
            # Отправляем только текст
            await channel.send(message)
            await ctx.send(f'Сообщение отправлено в #{channel.name}')
            moderation_logs.append(f"[СООБЩЕНИЕ] {ctx.author.name} отправил сообщение в #{channel.name}: {message[:50]}")
        else:
            await ctx.send('Укажи текст или прикрепи файл!')
            return
            
    except Exception as e:
        await ctx.send(f'Ошибка: {e}')

@bot.command(name='лскоманды', aliases=['lscommands', 'дмкоманды'])
async def ls_commands(ctx):
    """Показать команды, которые можно использовать в ЛС (личных сообщениях)"""
    embed = discord.Embed(title='Команды для ЛС', color=discord.Color.blue())
    embed.add_field(name='Поддержка', value='`!поддержка <текст>` — создать тикет в ЛС', inline=False)
    embed.add_field(name='Отправить сообщение (админ)', value='`!отправить-сообщение <текст>` — отправить сообщение/фото в #общее (админ может прикрепить фото)', inline=False)
    embed.add_field(name='Музыка', value='`!музыка` + прикрепи MP3 — проиграть в голосовом канале', inline=False)
    embed.add_field(name='Стоп музыки', value='`!стопмузыка` — остановить воспроизведение', inline=False)
    embed.add_field(name='Громкость', value='`!громкость <0-100>` — установить громкость', inline=False)
    embed.add_field(name='⏱️ Время', value='`!время` — показать позицию; `!время 1:30` — перемотать на 1:30', inline=False)
    embed.add_field(name='🔁 Снова', value='`!снова` — перезапустить текущий трек с начала', inline=False)
    embed.add_field(name='🎤 Сказать', value='`!сказать <текст>` — произнести текст в голосовом канале (бот должен быть подключён)', inline=False)
    embed.add_field(name='🕒 Позиция', value='`!позиция` — показать текущую позицию трека', inline=False)
    embed.add_field(name='� Подслушивание', value='`!подслушивать начать <guild_id> <channel_name?> [sec]` и `!подслушивать остановить` — запись голоса и отправка MP3 в ЛС админу (только в ЛС, только для админа)', inline=False)
    embed.add_field(name='�🔧 Дополнительно', value='`!время` и `!лскоманды` работают в ЛС; некоторые команды требуют подключения бота к голосу или прав админа.', inline=False)
    await ctx.send(embed=embed)

@bot.command(name='подслушивать', aliases=['eavesdrop', 'record_voice'])
async def listen_cmd(ctx, action: str = None, channel_name: str = None, max_seconds: int = 300):
    """Команда для записи голоса в голосовом канале где бот находится и отправки в ЛС (только админ и только в ЛС)

    Примеры:
    - `!подслушивать начать` — начать запись в текущем канале бота
    - `!подслушивать начать 300` — начать запись на 300 сек
    - `!подслушивать остановить` — остановить запись
    """
    if ctx.guild is not None:
        await ctx.send('❌ Используй эту команду только в ЛС боту')
        return
    if ctx.author.id != ADMIN_ID:
        await ctx.send('❌ Только админ может использовать эту команду')
        return
    
    if not action:
        await ctx.send('❌ Укажи действие: `!подслушивать начать` или `!подслушивать остановить`')
        return

    # Простая запись без сложных зависимостей

    if action.lower() in ('start', 'начать'):
        # Найти голосовое подключение бота
        vc = None
        voice_channel = None
        
        # Ищем среди всех голосовых подключений бота
        for voice_client in bot.voice_clients:
            if voice_client and voice_client.is_connected():
                vc = voice_client
                voice_channel = voice_client.channel
                break
        
        if not vc or not voice_channel:
            await ctx.send('❌ Бот не подключен ни к одному голосовому каналу. Сначала подключи его: `!подключиться`')
            return

        # Параметры записи
        recording_duration = max_seconds
        if channel_name and isinstance(channel_name, str) and channel_name.isdigit():
            # Если второй параметр - число, это длительность
            recording_duration = int(channel_name)

        # Создаём буфер для записи
        guild_id = voice_channel.guild.id
        
        # К сожалению, встроенной записи нет в этой версии discord.py
        # Предлагаем альтернативу
        await ctx.send('❌ Запись голоса требует специальной библиотеки которая не доступна.\n\n'
                      '**Альтернативы:**\n'
                      '1️⃣ Используй встроенный Discord Voice Activity\n'
                      '2️⃣ Запроси через !слушать для просмотра очереди голоса\n'
                      '3️⃣ Используй OBS для захвата голоса на уровне ОС')
        return

    elif action.lower() in ('stop', 'остановить'):
        # Найти активную запись
        found = False
        for guild_id, session in list(listening_sessions.items()):
            if session.get('vc') and session['vc'].is_connected():
                await stop_listening_internal(guild_id)
                await ctx.send('✅ Остановлено, файл будет отправлен в ЛС')
                found = True
                break
        
        if not found:
            await ctx.send('❌ Нет активной записи')
    else:
        await ctx.send('❌ Неверное действие. Используй `начать` или `остановить`.')


async def stop_listening_internal(guild_id: int):
    """Остановить запись и сохранить файл"""
    sess = listening_sessions.get(guild_id)
    if not sess:
        return
    
    vc = sess.get('vc')
    try:
        vc.stop_recording()
    except Exception:
        pass
    
    # Сохраняем файл
    try:
        base = os.path.dirname(os.path.abspath(__file__))
        out_dir = os.path.join(base, 'recordings')
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f'recording_{guild_id}_{int(time.time())}.wav')
        
        # Конвертируем PCM буфер в WAV файл
        import wave
        sink = sess.get('sink')
        
        if sink and hasattr(sink, 'audio_data'):
            with wave.open(out_path, 'wb') as wav:
                # Discord использует 48kHz, mono, 16-bit PCM
                wav.setnchannels(1)  # mono
                wav.setsampwidth(2)  # 16-bit = 2 bytes
                wav.setframerate(48000)  # 48kHz
                
                # Запишем объединённый аудио от всех пользователей
                for user_id, audio_data in sink.audio_data.items():
                    if audio_data:
                        wav.writeframes(bytes(audio_data))
            
            # Отсоединяемся
            session = listening_sessions.pop(guild_id, None)
            if session and session.get('vc'):
                try:
                    await session['vc'].disconnect()
                except:
                    pass
            
            # Отправляем файл админу в ЛС
            admin = await bot.fetch_user(ADMIN_ID)
            if admin:
                try:
                    await admin.send('📬 Запись завершена. Файл во вложении:', file=discord.File(out_path))
                except Exception as e:
                    print(f'❌ Ошибка отправки записи в ЛС: {e}')
        else:
            listening_sessions.pop(guild_id, None)
            if vc:
                try:
                    await vc.disconnect()
                except:
                    pass
    except Exception as e:
        print(f'❌ Ошибка сохранения записи: {e}')
        listening_sessions.pop(guild_id, None)
        if vc:
            try:
                await vc.disconnect()
            except:
                pass


async def finished_callback_voice(sink, guild_id):
    """Callback когда запись завершена"""
    await stop_listening_internal(guild_id)


async def record_finished_callback(sink, ctx):
    recorded_users = [f"<@{user_id}>" for user_id, audio in sink.audio_data.items()]
    files = [discord.File(audio.file, f"{user_id}.{sink.encoding}") for user_id, audio in sink.audio_data.items()]
    await ctx.channel.send(f"Запись завершена для: {', '.join(recorded_users)}", files=files)

@bot.command()
async def record(ctx):
    if ctx.author.voice:
        channel = ctx.author.voice.channel
        if ctx.voice_client is None:
            vc = await channel.connect()
        else:
            vc = ctx.voice_client

        # Начинаем запись (используем record вместо start_recording)
        try:
            vc.record(discord.sinks.WaveSink())
            await ctx.send("🎙️ Начинаю запись...")
        except AttributeError:
            # Fallback
            await ctx.send("❌ Метод запись недоступен")
            return
        
        await ctx.send("🔴 Запись пошла! (10 секунд)")
        await asyncio.sleep(10)
        
        vc.stop_recording()
        await ctx.send("🛑 Запись остановлена, обрабатываю...")
        
        # Ждем немного, чтобы callback успел отработать перед отключением
        await asyncio.sleep(1) 
        await vc.disconnect()
    else:
        await ctx.send("Вы должны быть в голосовом канале!")


# ======================== ЛОГИРОВАНИЕ ========================
@bot.command(name='очистилоги', aliases=['clearlogs', 'clear_logs'])
@commands.has_permissions(administrator=True)
async def clear_logs(ctx):
    """Очистить логи"""
    log_event("COMMAND", f"{ctx.author.name} очистил логи")
    
    try:
        with open(LOGS_FILE, 'w', encoding='utf-8') as f:
            f.write('')
        await ctx.send('✅ Логи очищены')
    except Exception as e:
        await ctx.send(f'❌ Ошибка очистки логов: {e}')

# ======================== МИКРОФОН (БЕЗ OPUS) ========================
@bot.command(name='диалог', aliases=['talk', 'dialog', 'микрофон'])
async def dialogue_command(ctx, duration: int = 5):
    """Слушать голос в канале, распознать и ответить голосом!
    
    Использование:
    !диалог           — слушает 5 сек (по умолчанию)
    !диалог 10        — слушает 10 сек
    
    ТРЕБУЕТ: Бот должен быть в голосовом канале!
    Используй: !подключиться
    """
    
    # Проверка: команда работает только локально, не на Railway
    if voice_recv and not hasattr(voice_recv.VoiceRecvClient, 'record'):
        await ctx.send("❌ Команда `!диалог` недоступна на Railway/Linux. Используйте локально на Windows.")
        return
    
    if not ctx.author.voice:
        await ctx.send("❌ Ты не в голосовом канале! Зайди в голосовой канал и напиши `!подключиться`")
        return
    
    if duration < 1 or duration > 60:
        await ctx.send("❌ Длительность от 1 до 60 сек")
        return
    
    if voice_recv is None:
        await ctx.send("❌ voice_recv недоступен. На локальном ПК используй !слушать вместо этого.")
        return
    
    # Получаем голосовой клиент бота
    vc = ctx.guild.voice_client
    if not vc or not vc.is_connected():
        await ctx.send("❌ Бот не подключен к голосовому каналу! Напиши `!подключиться`")
        return
    
    # Проверяем что это VoiceRecvClient
    if not isinstance(vc, voice_recv.VoiceRecvClient):
        await ctx.send("❌ Канал не поддерживает запись. Попробуй переподключиться.")
        return
    
    try:
        status_msg = await ctx.send(f"🎙️ **[LISTEN]** Слушаю канал {duration} сек...")
        
        # Создаем sink для записи (простой класс, не абстрактный)
        class DialogSink:
            def __init__(self):
                self.audio_data = bytearray()
            
            async def wants_opus(self):
                return False
            
            async def recv_audio(self, user, audio):
                if audio and hasattr(audio, 'pcm'):
                    self.audio_data.extend(audio.pcm)
            
            def cleanup(self):
                self.audio_data.clear()
            
            def write(self, data):
                if data:
                    self.audio_data.extend(data)
        
        sink = DialogSink()
        
        # Начинаем запись (используем record вместо start_recording)
        try:
            vc.record(sink)
        except AttributeError:
            await ctx.send("❌ Метод запись недоступен на этом хосте")
            return
        
        # Ждем нужное время
        await asyncio.sleep(duration)
        
        # Останавливаем запись
        vc.stop_recording()
        
        if not sink.audio_data:
            await ctx.send("❌ Не было записано никакого звука.")
            return
        
        await status_msg.edit(content="🔄 **[PROCESS]** Обрабатываю...")
        
        # Преобразуем PCM в AudioData для распознавания
        import speech_recognition as sr
        audio_data = sr.AudioData(bytes(sink.audio_data), 48000, 2)
        recognizer = sr.Recognizer()
        
        try:
            text = recognizer.recognize_google(audio_data, language='ru-RU')
            print(f"Recognized: {text}")
            await status_msg.edit(content=f"📝 Распознано: '{text}'")
        except sr.UnknownValueError:
            await ctx.send("❌ Не смог распознать речь")
            return
        except sr.RequestError as e:
            await ctx.send(f"❌ Ошибка Google API: {e}")
            return
        
        await status_msg.edit(content="🤖 **[AI]** Генерирую ответ...")
        
        # Генерируем ответ через Groq
        try:
            chat_completion = groq_client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "Ты - дерзкий и смешной AI бот. Отвечай на русском, кратко (макс 20 слов)."},
                    {"role": "user", "content": f"Человек в канале сказал: '{text}'. Ответь ему дерзко и прикольно."}
                ],
                model="llama-3.3-70b-versatile",
            )
            response_text = chat_completion.choices[0].message.content
        except Exception as e:
            await ctx.send(f"❌ Ошибка Groq API: {e}")
            return
        
        await status_msg.edit(content=f"🔊 **[VOICE]** Озвучиваю...")
        
        # Озвучиваем ответ
        await send_voice_message(vc, response_text)
        
        await status_msg.edit(content=f"✅ **Готово!** Ответ: '{response_text}'")
        
    except Exception as e:
        await ctx.send(f"❌ Ошибка: {str(e)}")
        traceback.print_exc()
    
    # Получаем голосовой канал пользователя
    user_channel = ctx.author.voice.channel
    
    # Подключаемся к голосовому каналу
    vc = ctx.guild.voice_client
    if vc and vc.is_connected():
        # Если подключен в другой канал, отключимся и переподключимся
        if vc.channel != user_channel:
            try:
                await vc.disconnect()
                await asyncio.sleep(0.5)
                vc = await user_channel.connect()
                await asyncio.sleep(0.5)
            except Exception as e:
                error_msg = f"Ошибка переподключения: {type(e).__name__}: {str(e)}"
                print(f"[ERROR] {error_msg}")
                log_event("ERROR", error_msg)
                await ctx.send(error_msg)
                import traceback
                traceback.print_exc()
                return
    else:
        try:
            await ctx.send(f"[CONNECT] Подключаюсь в {user_channel.name}...")
            vc = await user_channel.connect()
            await asyncio.sleep(0.5)
        except Exception as e:
            error_msg = f"Ошибка подключения: {type(e).__name__}: {str(e)}"
            print(f"[ERROR] {error_msg}")
            log_event("ERROR", error_msg)
            await ctx.send(error_msg)
            import traceback
            traceback.print_exc()
            return
    
    await ctx.send(f"[LISTEN] Слушаю микрофон {duration} сек...")
    
    try:
        # Импортируем только когда нужны
        import sounddevice as sd
        import soundfile as sf
        
        # Записываем аудио с микрофона
        print(f"[MIC] Recording for {duration} seconds...")
        sample_rate = 16000
        audio_data = sd.rec(int(duration * sample_rate), samplerate=sample_rate, channels=1, dtype='float32')
        sd.wait()
        
        # Отправляем статус обработки
        status_msg = await ctx.send("[PROCESS] Обрабатываю...")
        
        # Сохраняем во временный файл
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
            tmp_path = tmp.name
            sf.write(tmp_path, audio_data, sample_rate)
        
        print("[RECOGNIZE] Processing speech...")
        
        try:
            recognizer = sr.Recognizer()
            with sr.AudioFile(tmp_path) as source:
                audio = recognizer.record(source)
            
            text = recognizer.recognize_google(audio, language='ru-RU')
            print(f"[USER] {text}")
            
            # Обновляем статус
            await status_msg.edit(content="[AI] Генерирую ответ...")
            
            # Ответ от AI
            response = groq_client.chat.completions.create(
                model='llama-3.3-70b-versatile',
                messages=[{'role': 'user', 'content': text}],
                temperature=0.7,
                max_tokens=150,
            )
            answer = response.choices[0].message.content.strip()
            print(f"[BOT] {answer}")
            
            # Обновляем статус
            await status_msg.edit(content="[VOICE] Воспроизвожу ответ...")
            
            # Отправляем ТОЛЬКО ГОЛОСОМ в голосовой канал
            try:
                await send_voice_message(vc, answer)
                print("[SUCCESS] Voice message sent")
                await status_msg.delete()  # Удаляем статус сообщение
            except Exception as e:
                await status_msg.edit(content=f"Ошибка воспроизведения: {e}")
                print(f"[ERROR] {e}")
            
            # Удаляем временный файл
            try:
                os.remove(tmp_path)
            except:
                pass
            
        except sr.UnknownValueError:
            await ctx.send("Не услышал речь. Говори громче!")
        except sr.RequestError as e:
            await ctx.send(f"Ошибка API: {e}")
            
    except ImportError:
        await ctx.send("Ошибка: sounddevice не установлен. Установи: pip install sounddevice soundfile")
    except Exception as e:
        await ctx.send(f"Ошибка микрофона: {e}")
        print(f"Error: {e}")
        traceback.print_exc()

if __name__ == '__main__':
    token = os.getenv('DISCORD_TOKEN')
    if token:
        load_data()
        print("[START] Запускаю бота...")

        bot.run(token)
    else:
        print('[ERROR] DISCORD_TOKEN not found in .env')