import discord
from discord.ext import commands, tasks
from aiohttp import web
import aiohttp
import json
import os
import random
import time
import logging

# =========================
# CONFIG
# =========================

TOKEN = os.getenv("DISCORD_TOKEN")
SEPAY_TOKEN = os.getenv("SEPAY_TOKEN")

BANK_NAME = os.getenv("BANK_NAME", "msb")
BANK_NUMBER = os.getenv("BANK_NUMBER")

PORT = int(os.getenv("PORT", "8080"))

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("PAYMENT")

# =========================
# BOT
# =========================

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# =========================
# DATABASE
# =========================

DATA_FILE = "data.json"

balances = {}
orders = {}
used_txns = set()

def save():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "balances": balances,
            "orders": orders
        }, f, indent=2)

def load():
    global balances, orders
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            d = json.load(f)
            balances = {int(k): v for k, v in d.get("balances", {}).items()}
            orders = d.get("orders", {})

load()

# =========================
# BALANCE
# =========================

def add_balance(uid, amount):
    balances[uid] = balances.get(uid, 0) + amount
    save()
    return balances[uid]

def get_balance(uid):
    return balances.get(uid, 0)

# =========================
# ORDER CREATE (PRO FIX)
# =========================

def create_order(amount: int):
    """
    PRO SYSTEM:
    - amount unique để match 100%
    """
    oid = "NAP" + str(random.randint(10000, 99999))
    unique_amount = amount + random.randint(1, 999)

    orders[oid] = {
        "user_id": None,
        "amount": unique_amount,
        "base_amount": amount,
        "paid": False,
        "txn_id": None,
        "created": time.time()
    }

    save()
    return oid, unique_amount

# =========================
# SEPAY PARSER PRO
# =========================

def get_amount(txn):
    for k in ["transferAmount", "amount_in", "amount", "value"]:
        try:
            if txn.get(k) is not None:
                return int(float(txn[k]))
        except:
            pass
    return 0

def match_txn(txn, oid, order):
    txn_id = str(txn.get("id"))

    # chống double
    if txn_id == order.get("txn_id"):
        return False

    amount = get_amount(txn)

    log.info("[CHECK] %s | %s/%s", oid, amount, order["amount"])

    # MATCH CHUẨN PRO
    if amount == order["amount"]:
        order["txn_id"] = txn_id
        return True

    return False

# =========================
# CONFIRM PAYMENT
# =========================

async def confirm_payment(order_id):
    order = orders.get(order_id)

    if not order or order["paid"]:
        return

    order["paid"] = True

    uid = order["user_id"]
    amount = order["base_amount"]

    new_balance = add_balance(uid, amount)

    save()

    try:
        user = await bot.fetch_user(uid)

        embed = discord.Embed(
            title="✅ NẠP TIỀN THÀNH CÔNG",
            color=0x00ff88
        )

        embed.add_field(name="Cộng", value=f"{amount:,}đ", inline=False)
        embed.add_field(name="Số dư", value=f"{new_balance:,}đ", inline=False)

        await user.send(embed=embed)

    except Exception as e:
        log.error("DM FAIL: %s", e)

# =========================
# SEPAY POLLING (BACKUP AUTO)
# =========================

@tasks.loop(seconds=10)
async def poll_sepay():

    if not SEPAY_TOKEN:
        return

    headers = {"Authorization": f"Bearer {SEPAY_TOKEN}"}

    async with aiohttp.ClientSession() as s:
        async with s.get(
            "https://my.sepay.vn/userapi/transactions/list",
            headers=headers,
            params={"limit": 200}
        ) as r:
            data = await r.json()

    txns = data.get("transactions", [])

    for txn in txns:

        tid = str(txn.get("id"))

        if tid in used_txns:
            continue

        for oid, order in orders.items():

            if order["paid"]:
                continue

            if match_txn(txn, oid, order):

                used_txns.add(tid)

                await confirm_payment(oid)

                break

# =========================
# WEBHOOK (REALTIME)
# =========================

async def webhook(request):

    try:
        body = await request.json()
    except:
        body = {}

    for oid, order in orders.items():

        if order["paid"]:
            continue

        if match_txn(body, oid, order):

            await confirm_payment(oid)

            return web.json_response({"ok": True})

    return web.json_response({"ok": False})

async def start_webhook():
    app = web.Application()
    app.router.add_post("/webhook", webhook)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

    log.info("WEBHOOK RUNNING")

# =========================
# DISCORD COMMANDS
# =========================

@bot.command()
async def nap(ctx, amount: int):

    oid, real_amount = create_order(amount)

    orders[oid]["user_id"] = ctx.author.id

    qr = (
        f"https://img.vietqr.io/image/{BANK_NAME}-{BANK_NUMBER}-compact2.png"
        f"?amount={real_amount}&addInfo={oid}"
    )

    embed = discord.Embed(title="💳 NẠP TIỀN AUTO")

    embed.add_field(name="Số tiền phải chuyển", value=f"{real_amount:,}đ", inline=False)
    embed.add_field(name="Mã đơn", value=oid, inline=False)

    embed.set_image(url=qr)

    await ctx.send(embed=embed)

@bot.command()
async def balance(ctx):
    await ctx.send(f"💰 Số dư: {get_balance(ctx.author.id):,}đ")

# =========================
# READY
# =========================

@bot.event
async def on_ready():
    log.info("BOT READY")

    await start_webhook()

    poll_sepay.start()

# =========================
# RUN
# =========================

bot.run(TOKEN)
