import discord
from discord.ext import commands
import json
import re
import os
import random
from typing import Dict, List, Optional, Tuple

# -------------------------------------------------
# Helpers
# -------------------------------------------------

def load_json(path: str, default: dict) -> dict:
    """Load JSON file or return default if missing/invalid."""
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def save_json(path: str, data: dict) -> None:
    """Save dictionary as JSON."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


# -------------------------------------------------
# League Manager
# -------------------------------------------------

class LeagueManager:
    def __init__(self, path: str = "league.json"):
        self.path = path
        self.data: Dict[str, dict] = load_json(path, {})

    def save(self) -> None:
        save_json(self.path, self.data)

    def add_player(self, user_id: str) -> bool:
        if user_id in self.data:
            return False
        self.data[user_id] = {"points": 0, "opponents": [], "received_bye": False}
        self.save()
        return True
    
    def remove_player(self, user_id):
        if user_id in self.data:
            del self.data[user_id]
            self.save()
            return True
        return False

    def add_points(self, user_id: str, pts: int) -> None:
        if user_id not in self.data:
            self.add_player(user_id)
        self.data[user_id]["points"] += pts
        self.save()

    def standings(self) -> List[Tuple[str, dict]]:
        return sorted(
            self.data.items(),
            key=lambda x: (-x[1]["points"], x[0])
        )

    def swiss_pairings(self) -> List[Tuple[str, Optional[str]]]:
        players = self.standings()
        pairings = []
        used = set()

        for i, (p1, _) in enumerate(players):
            if p1 in used:
                continue
            opponent = None
            for j in range(i+1, len(players)):
                p2, _ = players[j]
                if p2 in used:
                    continue
                if p2 not in self.data[p1]["opponents"]:
                    opponent = p2
                    break
            if opponent:
                pairings.append((p1, opponent))
                used.update({p1, opponent})
                self.data[p1]["opponents"].append(opponent)
                self.data[opponent]["opponents"].append(p1)

        leftovers = [p for p, _ in players if p not in used]
        if leftovers:
            bye = leftovers[0]
            pairings.append((bye, None))
            self.add_points(bye, 3)
            self.data[bye]["received_bye"] = True

        self.save()
        return pairings


# -------------------------------------------------
# Decklist Manager
# -------------------------------------------------

class DecklistManager:
    def __init__(self, path: str = "decklists.json"):
        self.path = path
        self.data: Dict[str, dict] = load_json(path, {})

    def save(self) -> None:
        save_json(self.path, self.data)

    def save_decklist(self, user_id: str, text: str, images: List[str]) -> None:
        self.data[user_id] = {"text": text, "images": images}
        self.save()

    def get_decklist(self, user_id: str) -> Optional[dict]:
        return self.data.get(user_id)
    
# -------------------------------------------------    
# Load borrowed cards data
# -------------------------------------------------
BORROW_FILE = "borrowed_cards.json"

if os.path.exists(BORROW_FILE):
    with open(BORROW_FILE, "r") as f:
        borrowed_data = json.load(f)
else:
    borrowed_data = {}  # Structure: {lender_id: {borrower_id: {card_name: qty}}}

def save_borrowed():
    with open(BORROW_FILE, "w") as f:
        json.dump(borrowed_data, f, indent=4)

def parse_cards(message: str) -> dict:
    """
    Parses a string of cards into a dictionary: {"card name": quantity, ...}
    Accepts formats like:
      - 2x Quantum Riddler
      - 2 Quantum Riddler
      - Multiple cards separated by commas or 'and'
    Case-insensitive, returns card names in lowercase for normalization.
    """
    cards = {}
    
    # Normalize separators: commas and 'and'
    message = re.sub(r'\s+and\s+', ',', message, flags=re.IGNORECASE)
    
    # Split by comma
    entries = [e.strip() for e in message.split(",") if e.strip()]
    
    for entry in entries:
        # Match optional 'x' after number
        match = re.match(r"(\d+)\s*x?\s*(.+)", entry, re.IGNORECASE)
        if match:
            qty = int(match.group(1))
            card_name = match.group(2).strip().lower()  # normalize
            if card_name in cards:
                cards[card_name] += qty
            else:
                cards[card_name] = qty

    return cards

# -------------------------------------------------
# Dean Counter
# -------------------------------------------------

class DeanCounter:
    def __init__(self, path: str = "dean.json"):
        self.path = path
        self.data = load_json(path, {"count": 0})

    def save(self) -> None:
        save_json(self.path, self.data)

    def increment(self) -> int:
        self.data["count"] += 1
        self.save()
        return self.data["count"]

    def reset(self) -> None:
        self.data["count"] = 0
        self.save()


def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1:'st', 2:'nd', 3:'rd'}.get(n % 10, 'th') }"


# -------------------------------------------------
# Quote Pool
# -------------------------------------------------

class QuotePool:
    def __init__(self, quotes: List[str]):
        self.quotes = quotes
        self.pool = random.sample(quotes, len(quotes))

    def next(self) -> str:
        if not self.pool:
            self.pool = random.sample(self.quotes, len(self.quotes))
        return self.pool.pop()


# -------------------------------------------------
# Bot Setup
# -------------------------------------------------

bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())

league = LeagueManager()
decklists = DecklistManager()
dean = DeanCounter()
quotes = QuotePool([
    "Sometimes I wonder if I’m holding my sword the wrong way...",
    "They told me to follow my heart… problem is, I’m not sure where I left it.",
    "Failure builds character. At this rate, I must be the most ‘characterful’ bloke alive.",
    "Yer ma's a boot",
    "People on zero deserve to be at the bottom 👀",
])


# -------------------------------------------------
# Commands
# -------------------------------------------------

### Hi! ###
@bot.command()
async def hello(ctx):
    await ctx.send(f"Hello {ctx.author.mention}! I am Clive, and I am a big dumb idiot.")

### League Related Commands ###
@bot.command()
async def joinleague(ctx):
    added = league.add_player(str(ctx.author.id))
    if added:
        await ctx.send(f"✅ {ctx.author.mention} has joined the league!")
    else:
        await ctx.send(f"{ctx.author.mention}, you’re already in the league!")
        
@bot.command()
async def removeleague(ctx):
    if not ctx.message.mentions:
        await ctx.send("⚠️ Please tag at least one user to remove them from the league.")
        return

    removed, not_found = [], []

    for user in ctx.message.mentions:
        if league.remove_player(str(user.id)):
            removed.append(user.name)
        else:
            not_found.append(user.name)

    response = []
    if removed:
        response.append(f"❌ Removed: {', '.join(removed)}")
    if not_found:
        response.append(f"ℹ️ Not in league: {', '.join(not_found)}")

    await ctx.send("\n".join(response))

@bot.command()
async def pairings(ctx):
    matchups = league.swiss_pairings()
    if not matchups:
        await ctx.send("⚠️ Not enough players to generate pairings.")
        return

    lines = ["📜 **Round Pairings:**"]
    for p1, p2 in matchups:
        if p2 is None:
            lines.append(f"- <@{p1}> has a **bye** (awarded 3 points).")
        else:
            lines.append(f"- <@{p1}> vs <@{p2}>")
    await ctx.send("\n".join(lines))


@bot.command()
async def table(ctx):
    standings = league.standings()
    if not standings:
        await ctx.send("📊 The league table is empty!")
        return

    lines = ["📊 **League Table** 📊"]
    for i, (uid, stats) in enumerate(standings, 1):
        user = await bot.fetch_user(int(uid))
        lines.append(f"{i}. {user.name} — {stats['points']} pts")
    await ctx.send("\n".join(lines))

### Decklist related commands ###
@bot.command()
async def decklist(ctx):
    if ctx.message.mentions:
        target = ctx.message.mentions[0]
        entry = decklists.get_decklist(str(target.id))
        if not entry:
            await ctx.send(f"❌ {target.mention} has not saved a decklist yet.")
            return
        msg = f"📜 {target.name}'s decklist:\n"
        if entry.get("text"):
            msg += f"```{entry['text']}```"
        await ctx.send(msg)
        for img in entry.get("images", []):
            await ctx.send(img)
    else:
        text = ctx.message.content[len("!decklist"):].strip()
        images = [a.url for a in ctx.message.attachments]
        if not text and not images:
            await ctx.send("⚠️ Please include text or attach an image of your decklist.")
            return
        decklists.save_decklist(str(ctx.author.id), text, images)
        await ctx.send(f"🗡️ Clive remembers your decklist, {ctx.author.mention}.")

### Borrowing card commands ###
@bot.command()
async def borrow(ctx):
    if not ctx.message.mentions:
        await ctx.send("⚠️ Please tag the lender(s).")
        return

    content = ctx.message.content
    # Remove command prefix and mentions
    for user in ctx.message.mentions:
        content = content.replace(f"<@!{user.id}>", "")
    content = content.replace("!borrow", "").strip()

    if not content:
        await ctx.send("⚠️ Please specify the cards and quantities to borrow.")
        return

    for lender in ctx.message.mentions:
        lender_id = str(lender.id)
        if lender_id not in borrowed_data:
            borrowed_data[lender_id] = {}
        borrower_id = str(ctx.author.id)
        if borrower_id not in borrowed_data[lender_id]:
            borrowed_data[lender_id][borrower_id] = {}

        cards_to_add = parse_cards(content)
        for card_name, qty in cards_to_add.items():
            borrowed_data[lender_id][borrower_id][card_name] = borrowed_data[lender_id][borrower_id].get(card_name, 0) + qty

    save_borrowed()
    await ctx.send(f"✅ Cards recorded for {ctx.author.mention} borrowing from {[user.name for user in ctx.message.mentions]}.")

# Command to subtract returned cards
@bot.command()
async def returncards(ctx):
    if not ctx.message.mentions:
        await ctx.send("⚠️ Please tag the lender(s).")
        return

    # Remove mentions and command
    content = ctx.message.content
    for user in ctx.message.mentions:
        content = content.replace(f"<@!{user.id}>", "")
        content = content.replace(f"<@{user.id}>", "")
    content = content.replace("!returncards", "").strip()

    if not content:
        await ctx.send("⚠️ Please specify the cards and quantities being returned.")
        return

    cards_to_subtract = parse_cards(content)

    for lender in ctx.message.mentions:
        lender_id = str(lender.id)
        borrower_id = str(ctx.author.id)

        if lender_id not in borrowed_data or borrower_id not in borrowed_data[lender_id]:
            await ctx.send(f"⚠️ No records found for {ctx.author.mention} borrowing from {lender.name}.")
            continue

        borrower_cards = borrowed_data[lender_id][borrower_id]

        # Subtract quantities case-insensitively
        for card_name, qty in cards_to_subtract.items():
            for stored_card in list(borrower_cards.keys()):
                if stored_card.lower() == card_name:
                    borrower_cards[stored_card] -= qty
                    if borrower_cards[stored_card] <= 0:
                        del borrower_cards[stored_card]
                    break

        # Clean up empty borrower/lender entries
        if not borrower_cards:
            del borrowed_data[lender_id][borrower_id]
        if not borrowed_data[lender_id]:
            del borrowed_data[lender_id]

    save_borrowed()
    await ctx.send(f"✅ Cards updated for {ctx.author.mention} returning to {[u.name for u in ctx.message.mentions]}.")


# Command to view borrowed cards
@bot.command()
async def borrowed(ctx):
    lender_id = str(ctx.author.id)
    if lender_id not in borrowed_data or not borrowed_data[lender_id]:
        await ctx.send("📭 No borrowed cards recorded for you.")
        return

    lines = ["📋 **Borrowed Cards:**"]
    for borrower_id, cards in borrowed_data[lender_id].items():
        borrower = await bot.fetch_user(int(borrower_id))
        card_lines = ", ".join(f"{qty}x {name}" for name, qty in cards.items())
        lines.append(f"- {borrower.name}: {card_lines}")

    await ctx.send("\n".join(lines))

### Fuck Dean lol ###
@bot.command()
async def fd(ctx):
    count = dean.increment()
    await ctx.send(f"Get fucked Dean! 🍆 This is the {ordinal(count)} time Dean has been fucked.")


@bot.command()
async def resetfd(ctx):
    dean.reset()
    await ctx.send("🔄 Dean’s fuck counter has been reset to 0.")


### Say something stupid Clive ####
@bot.command()
async def quote(ctx):
    await ctx.send(f'🗡️ Clive says: *"{quotes.next()}"*')


# -------------------------------------------------
# Run Bot
# -------------------------------------------------

TOKEN = os.getenv("DISCORD_TOKEN")
bot.run(TOKEN)
