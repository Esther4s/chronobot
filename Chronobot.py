import discord
from discord.ext import commands, tasks
import random
import requests
import sqlite3
import datetime

# === НАСТРОЙКИ ===
TOKEN = 'Bot_Token'
PREFIX = '/'

bot = commands.Bot(command_prefix=PREFIX, intents=discord.Intents.all())
DB_NAME = 'hangman.db'

# === СОЗДАНИЕ БД ===
conn = sqlite3.connect(DB_NAME)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS players (
    user_id INTEGER PRIMARY KEY,
    balance INTEGER DEFAULT 100,
    score INTEGER DEFAULT 0,
    chips INTEGER DEFAULT 0
)''')
c.execute('''CREATE TABLE IF NOT EXISTS game (
    id INTEGER PRIMARY KEY,
    phrase TEXT,
    display TEXT,
    hint TEXT,
    used_letters TEXT,
    active INTEGER,
    solved_by TEXT DEFAULT ''
)''')
conn.commit()
conn.close()

# === ФУНКЦИИ ===
def fetch_today_event():
    today = datetime.datetime.now()
    month = str(today.month).zfill(2)
    day = str(today.day).zfill(2)
    url = f"https://en.wikipedia.org/api/rest_v1/feed/onthisday/events/{month}/{day}"
    try:
        res = requests.get(url).json()
        events = res['events']
        used_phrases = set()

        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute("SELECT phrase FROM game")
        used_phrases.update(row[0] for row in c.fetchall())
        conn.close()

        random.shuffle(events)
        for e in events:
            text = e['text']
            if text not in used_phrases:
                keywords = ', '.join(e.get('pages', [{}])[0].get('titles', {}).get('normalized', '').split()[:3])
                return text, keywords or "история"
        fallback = events[0]
        keywords = ', '.join(fallback.get('pages', [{}])[0].get('titles', {}).get('normalized', '').split()[:3])
        return fallback['text'], keywords or "история"
    except:
        return ("В этот день произошло что-то, что не удалось загрузить.", "неизвестно")

def obfuscate_phrase(phrase):
    return ''.join([c if not c.isalpha() else '_' for c in phrase])

def get_player(user_id):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT * FROM players WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    if not row:
        c.execute("INSERT INTO players (user_id) VALUES (?)", (user_id,))
        conn.commit()
        c.execute("SELECT * FROM players WHERE user_id = ?", (user_id,))
        row = c.fetchone()
    conn.close()
    return row

def update_player(user_id, balance_change=0, score_change=0, chips_change=0):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE players SET balance = balance + ?, score = score + ?, chips = chips + ? WHERE user_id = ?", (balance_change, score_change, chips_change, user_id))
    conn.commit()
    conn.close()

# === ОБНОВЛЕНИЕ ФРАЗЫ ДНЯ ===
@tasks.loop(hours=24)
async def daily_phrase():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    phrase, keywords = fetch_today_event()
    obfuscated = obfuscate_phrase(phrase)
    hint = phrase[:15] + f"... ({keywords})"
    c.execute("DELETE FROM game")
    c.execute("INSERT INTO game (phrase, display, hint, used_letters, active) VALUES (?, ?, ?, ?, 1)",
              (phrase, obfuscated, hint, '',))
    conn.commit()
    conn.close()

@bot.command()
async def игра(ctx):
    user_id = ctx.author.id
    get_player(user_id)
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT active FROM game WHERE active=1")
    active = c.fetchone()
    if active:
        await ctx.send("Игра уже запущена. Угадайте текущую фразу!")
        conn.close()
        return
    phrase, keywords = fetch_today_event()
    obfuscated = obfuscate_phrase(phrase)
    hint = phrase[:15] + f"... ({keywords})"
    c.execute("INSERT INTO game (phrase, display, hint, used_letters, active) VALUES (?, ?, ?, ?, 1)",
              (phrase, obfuscated, hint, '',))
    conn.commit()
    conn.close()
    await ctx.send(f"Игра началась! Вот загадка:\n`{obfuscated}`\nПодсказка: {hint}")

@bot.command()
async def подсказка(ctx):
    user_id = ctx.author.id
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT balance FROM players WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        await ctx.send("Сначала начните игру командой /игра.")
        return

    balance = row[0]
    if balance < 10:
        conn.close()
        await ctx.send("Недостаточно монет для подсказки. Требуется 10 монет.")
        return

    c.execute("SELECT phrase, used_letters, hint FROM game WHERE active = 1")
    row = c.fetchone()
    if not row:
        conn.close()
        await ctx.send("Нет активной игры.")
        return

    phrase, used, base_hint = row
    all_letters = sorted(set(c.lower() for c in phrase if c.isalpha() and c.lower() not in used))
    if not all_letters:
        conn.close()
        await ctx.send("Все буквы уже открыты.")
        return

    letter = random.choice(all_letters)
    used += letter
    display = ''.join([c if not c.isalpha() or c.lower() in used else '_' for c in phrase])

    c.execute("UPDATE game SET display = ?, used_letters = ? WHERE active = 1", (display, used))
    conn.commit()
    update_player(user_id, balance_change=-10)
    conn.close()
    await ctx.send(f"🔍 Подсказка: открыта буква `{letter.upper()}`. {base_hint} (-10 монет)")

@bot.command()
async def баланс(ctx):
    user_id = ctx.author.id
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT balance, score, chips FROM players WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        balance, score, chips = row
        await ctx.send(f"💰 Баланс: {balance} монет\n🏅 Очки: {score}\n🎰 Фишки: {chips}")
    else:
        await ctx.send("Вы еще не зарегистрированы в системе. Начните с команды `/игра`.")

@bot.command()
async def статистика(ctx):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT user_id, score FROM players ORDER BY score DESC LIMIT 10")
    rows = c.fetchall()
    conn.close()
    if not rows:
        await ctx.send("Нет данных для статистики.")
        return
    leaderboard = "Топ игроков по очкам:\n"
    for idx, (user_id, score) in enumerate(rows, 1):
        member = ctx.guild.get_member(user_id)
        name = member.display_name if member else f"User ID {user_id}"
        leaderboard += f"{idx}. {name} — {score} очков\n"
    await ctx.send(leaderboard)

@bot.event
async def on_ready():
    print(f'Бот запущен как {bot.user}')
    daily_phrase.start()

bot.run(TOKEN)
