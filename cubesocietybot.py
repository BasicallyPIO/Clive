import discord
from discord.ext import commands, tasks
import json
import os
import random
import requests
import time


# Create a bot with a "!" prefix
bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())

PAIRINGS_FILE = "pairings.json"

def _save_pairings(pairs, bye=None):
    data = {
        "pairs": pairs,
        "bye": bye
    }
    with open(PAIRINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

def _clear_pairings():
    if os.path.exists(PAIRINGS_FILE):
        os.remove(PAIRINGS_FILE)

def _load_pairings():
    if not os.path.exists(PAIRINGS_FILE):
        return None
    with open(PAIRINGS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

# --- Tournament Commands ---

# Command: !hello
@bot.command()
async def hello(ctx):
    await ctx.send(f"Hello {ctx.author.mention}! I am Clive, and I am a big dumb idiot.")

# Load or create league data
if os.path.exists("league.json"):
    with open("league.json", "r") as f:
        league = json.load(f)
else:
    league = {}  # {user_id: {"points": int, "matches": int}}

def save_league():
    with open("league.json", "w") as f:
        json.dump(league, f, indent=4)

# Command: join the league
@bot.command()
async def joinleague(ctx):
    user_id = str(ctx.author.id)
    if user_id in league:
        await ctx.send(f"{ctx.author.mention}, you’re already in the league!")
    else:
        league[user_id] = {"points": 0}
        save_league()
        await ctx.send(f"✅ {ctx.author.mention} has joined the league!")

# Command: add tagged players to league
@bot.command()
async def addleague(ctx):
    if not ctx.message.mentions:
        await ctx.send("⚠️ Please tag at least one user to add them to the league.")
        return

    added = []
    already = []

    for user in ctx.message.mentions:
        user_id = str(user.id)
        if user_id in league:
            already.append(user.name)
        else:
            league[user_id] = {"points": 0}
            added.append(user.name)

    save_league()

    response = []
    if added:
        response.append(f"✅ Added: {', '.join(added)}")
    if already:
        response.append(f"ℹ️ Already in league: {', '.join(already)}")

    await ctx.send("\n".join(response))

# Listen for "wins" messages
@bot.event
async def on_message(message):
    if message.author == bot.user:  # Ignore bot messages
        return
    
    if "wins" in message.content.lower():
        if message.mentions:  # Someone tagged themselves
            for user in message.mentions:
                user_id = str(user.id)

                if user_id not in league:
                    league[user_id] = {"points": 0}

                league[user_id]["points"] += 3
                save_league()

                await message.channel.send(
                    f"🏆 {user.mention} gains 3 points! "
                    f"(Total: {league[user_id]['points']} pts)"
                )

    await bot.process_commands(message)  # Ensure commands still work

# Store tournament data
tournament_players = {}  # {user_id: {"points": int, "opponents": set(user_ids)}}
current_round = 3

def swiss_pairings(standings):
    """
    Generate Swiss pairings using existing standings.
    standings = league dict
    Returns list of (player1, player2) tuples
    """
    # Sort players by points, then user_id for consistency
    sorted_players = sorted(standings.items(), key=lambda x: (-x[1]["points"], x[0]))
    pairings = []
    used = set()

    for i, (p1, data1) in enumerate(sorted_players):
        if p1 in used:
            continue
        opponent = None
        for j in range(i+1, len(sorted_players)):
            p2, data2 = sorted_players[j]
            if p2 in used:
                continue
            # Don’t allow repeat pairings
            if "opponents" not in standings[p1]:
                standings[p1]["opponents"] = set()
            if "opponents" not in standings[p2]:
                standings[p2]["opponents"] = set()

            if p2 not in standings[p1]["opponents"]:
                opponent = p2
                break
        if opponent:
            pairings.append((p1, opponent))
            used.add(p1)
            used.add(opponent)
            standings[p1]["opponents"].add(opponent)
            standings[opponent]["opponents"].add(p1)

    # Handle bye if odd number of players
    leftovers = [p for p, _ in sorted_players if p not in used]
    if leftovers:
        bye_player = leftovers[0]
        pairings.append((bye_player, None))
        standings[bye_player]["points"] += 3  # Bye counts as win

    return pairings

@bot.command()
async def pairings(ctx):
    global current_round
    if len(league) < 2:
        await ctx.send("⚠️ Not enough players to generate pairings.")
        return

    current_round += 1
    matchups = swiss_pairings(league)

    response = f"📜 **Round {current_round} Pairings:**\n"
    for p1, p2 in matchups:
        if p2 is None:
            response += f"- <@{p1}> has a **bye** this round (awarded 3 points).\n"
        else:
            response += f"- <@{p1}> vs <@{p2}>\n"

    await ctx.send(response)

@bot.command()
async def repairing(ctx):
    """Repair the current round pairings (re-roll the round)."""
    def _normalize_league():
    	"""Ensure all players in league_standings have required fields."""
    	for player_id, data in league_standings.items():
        	if "points" not in data:
            		data["points"] = 0
        	if "opponents" not in data:
            		data["opponents"] = set()
        	if "received_bye" not in data:
            		data["received_bye"] = False

    # remove previous round pairings file
    _clear_pairings()

    # NOTE: we are NOT undoing points or opponent history from previous rounds.
    # This ensures repair only affects the current round.
    pairs, bye = _generate_pairings_with_retries()
    if pairs is None:
        await ctx.send("❌ Could not create repaired pairings.")
        return

    lines = ["♻️ **Repaired Swiss Pairings:**"]
    for a, b in pairs:
        league[a]["opponents"] = list(set(league[a]["opponents"]) | {b})
        league[b]["opponents"] = list(set(league[b]["opponents"]) | {a})
        lines.append(f"- <@{a}> vs <@{b}>")
    if bye:
        league[bye]["received_bye"] = True
        league[bye]["points"] += 3
        lines.append(f"- <@{bye}> has a **bye** (awarded 3 points).")

    _save_league()
    _save_pairings(pairs, bye)

    await ctx.send("\n".join(lines))

# Command: show leaderboard
@bot.command()
async def table(ctx):
    if not league:
        await ctx.send("📊 The league table is empty!")
        return
    
    # Sort by points (descending)
    sorted_league = sorted(
        league.items(),
        key=lambda x: x[1]["points"],
        reverse=True
    )

    leaderboard = "📊 **League Table** 📊\n"
    for i, (user_id, stats) in enumerate(sorted_league, start=1):
        user = await bot.fetch_user(int(user_id))
        leaderboard += f"{i}. {user.name} — {stats['points']} pts\n"

    await ctx.send(leaderboard)

# Load or create decklist storage
if os.path.exists("decklists.json"):
    with open("decklists.json", "r") as f:
        decklists = json.load(f)
else:
    decklists = {}  # {user_id: "decklist text"}

def save_decklists():
    with open("decklists.json", "w") as f:
        json.dump(decklists, f, indent=4)

@bot.command()
async def decklist(ctx):
    if ctx.message.mentions:
        # Retrieve mode
        target = ctx.message.mentions[0]
        user_id = str(target.id)
        if user_id in decklists:
            entry = decklists[user_id]
            response = f"📜 {target.name}'s decklist:\n"

            # If there's text
            if entry.get("text"):
                response += f"```{entry['text']}```"

            await ctx.send(response)

            # If there are images, send them
            if entry.get("images"):
                for img_url in entry["images"]:
                    await ctx.send(img_url)
        else:
            await ctx.send(f"❌ {target.mention} has not saved a decklist yet.")

    else:
        # Save mode
        content = ctx.message.content[len("!decklist"):].strip()
        attachments = [a.url for a in ctx.message.attachments]

        if not content and not attachments:
            await ctx.send("⚠️ Please include text or attach an image of your decklist.")
            return

        decklists[str(ctx.author.id)] = {
            "text": content if content else "",
            "images": attachments if attachments else []
        }
        save_decklists()
        await ctx.send(f"🗡️ Clive remembers your decklist, {ctx.author.mention}.")


# Command: free Palestine
@bot.command()
async def freepalestine(ctx):
	await ctx.send("Free Palestine! 🇵🇸")

# Command: Fuck Dean
if os.path.exists("dean.json"):
    with open("dean.json", "r") as f:
        dean_count = json.load(f)
else:
    dean_count = {"count": 0}

def save_dean():
    with open("dean.json", "w") as f:
        json.dump(dean_count, f, indent=4)

# Function to turn numbers into ordinals
def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:  # Handle 11th, 12th, 13th
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"

@bot.command()
async def fd(ctx):
    dean_count["count"] += 1
    save_dean()

    await ctx.send(
        f"Get fucked Dean! 🍆 This is the {ordinal(dean_count['count'])} time Dean has been fucked."
    )

@bot.command()
async def resetfd(ctx):
    dean_count["count"] = 0
    save_dean()
    await ctx.send("🔄 Dean’s fuck counter has been reset to 0.")

# Self-deprecating Clive quotes
clive_quotes = [
    "Sometimes I wonder if I’m holding my sword the wrong way. But hey, it still cuts things, so that’s good enough.",
    "They told me to follow my heart… problem is, I’m not sure where I left it.",
    "Failure builds character. At this rate, I must be the most ‘characterful’ bloke alive.",
    "The enemy may outsmart you… which isn’t hard in my case. But swing anyway, maybe you’ll get lucky.",
    "I once trained for hours, only to realise I’d been holding a broom, not a blade. Still, the floor was spotless.",
    "Sometimes victory is just surviving long enough to confuse everyone else.",
    "Don’t worry if you’re lost. I’ve been lost for years, and I turned out… well, I turned out.",
	"Yer ma's a boot",
	"People on zero deserve to be at the bottom 👀",
]

clive_quote_2 = [
	"DJ is my glorious master and without him I would not have tasted the sweet air of life",
]

# Create a pool that will be reshuffled once empty
quote_pool = clive_quotes.copy()
quote_pool_2 = clive_quote_2.copy()
random.shuffle(quote_pool)

@bot.command()
async def quote(ctx):
    global quote_pool
    if not quote_pool:  # If we've used them all, reshuffle
        quote_pool = clive_quotes.copy()
        random.shuffle(quote_pool)

    quote = quote_pool.pop(0)  # Take from the front
    await ctx.send(f'🗡️ Clive says: *"{quote}"*')

@bot.command()
async def quote2(ctx):
    global quote_pool_2

    await ctx.send(f'🗡️ Clive says: *"{quote_pool_2[0]}"*')

# Run the bot
TOKEN = os.getenv("DISCORD_TOKEN")
bot.run(TOKEN)


