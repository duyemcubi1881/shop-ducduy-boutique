# =========================================================
# DISCORD SHOP BOT + SEPAY AUTO TOPUP
# FIX FULL AUTO NAP TIEN
# =========================================================

import discord
from discord.ext import commands, tasks
from aiohttp import web
from dotenv import load_dotenv

import aiohttp
import asyncio
import datetime
import json
import logging
import os
import random
import time

# =========================================================
# LOAD ENV
# =========================================================

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

BANK_NUMBER = os.getenv("BANK_NUMBER")
BANK_NAME = os.getenv("BANK_NAME", "msb")

SEPAY_TOKEN = os.getenv("SEPAY_TOKEN")

WEBHOOK_PORT = int(os.getenv("PORT", "8080"))

# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

log = logging.getLogger("SHOP")

# =========================================================
# BOT
# =========================================================

intents = discord.Intents.all()

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

# =========================================================
# DATABASE
# =========================================================

DATA_FILE = "data.json"

balances = {}
orders = {}

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({
            "balances": balances,
            "orders": orders
        }, f, ensure_ascii=False, indent=2)

def load_data():
    global balances, orders

    if not os.path.exists(DATA_FILE):
        return

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        balances = {
            int(k): v
            for k, v in data.get("balances", {}).items()
        }

        orders = data.get("orders", {})

        log.info("Loaded %d orders", len(orders))

    except Exception as e:
        log.error("Load data error: %s", e)

load_data()

# =========================================================
# HELPERS
# =========================================================

def get_balance(uid: int):
    return balances.get(uid, 0)

def add_balance(uid: int, amount: int):
    balances[uid] = balances.get(uid, 0) + amount
    save_data()
    return balances[uid]

def make_order_id():
    while True:
        oid = "NAP" + str(random.randint(10000, 99999))

        if oid not in orders:
            return oid

def build_qr(amount: int, order_id: str):
    return (
        f"https://img.vietqr.io/image/"
        f"{BANK_NAME}-{BANK_NUMBER}-compact2.png"
        f"?amount={amount}"
        f"&addInfo={order_id}"
        f"&accountName=DUCDUY"
    )

# =========================================================
# SEPAY PARSER
# =========================================================

def get_txn_amount(txn: dict) -> int:
    fields = [
        "transferAmount",
        "amount_in",
        "amount",
        "value"
    ]

    for field in fields:
        val = txn.get(field)

        if val is not None:
            try:
                return int(float(val))
            except:
                pass

    return 0

def get_txn_text(txn: dict) -> str:
    fields = [
        "transaction_content",
        "content",
        "description",
        "code",
        "reference_number",
        "referenceCode",
        "sub_account",
        "subAccount",
        "gateway"
    ]

    texts = []

    for field in fields:
        val = txn.get(field)

        if val:
            texts.append(str(val))

    return " ".join(texts).upper().strip()

def match_order(txn: dict, oid: str, order: dict):

    amount = get_txn_amount(txn)
    text = get_txn_text(txn)

    log.info(
        "[CHECK] %s | amount=%s/%s | text=%s",
        oid,
        amount,
        order["amount"],
        text
    )

    # MATCH MA DON
    if oid.upper() in text:

        # MATCH SO TIEN
        if amount == order["amount"]:

            log.info("MATCH SUCCESS %s", oid)
            return True

    return False

# =========================================================
# CONFIRM PAYMENT
# =========================================================

async def confirm_payment(order_id: str):

    order = orders.get(order_id)

    if not order:
        return

    if order.get("paid"):
        return

    order["paid"] = True

    uid = order["user_id"]
    amount = order["amount"]

    bal = add_balance(uid, amount)

    save_data()

    log.info(
        "PAYMENT CONFIRMED %s | +%s",
        order_id,
        amount
    )

    try:

        user = await bot.fetch_user(uid)

        embed = discord.Embed(
            title="✅ Nạp tiền thành công",
            color=0x00ff00
        )

        embed.description = (
            f"💰 Đã cộng: **{amount:,}đ**\n"
            f"💳 Số dư: **{bal:,}đ**\n"
            f"🧾 Mã đơn: `{order_id}`"
        )

        await user.send(embed=embed)

    except Exception as e:
        log.error("DM ERROR: %s", e)

# =========================================================
# POLL SEPAY
# =========================================================

@tasks.loop(seconds=15)
async def poll_sepay():

    if not SEPAY_TOKEN:
        return

    pending = [
        (oid, o)
        for oid, o in orders.items()
        if not o.get("paid")
    ]

    if not pending:
        return

    log.info("Polling %d pending orders", len(pending))

    try:

        headers = {
            "Authorization": f"Bearer {SEPAY_TOKEN}"
        }

        async with aiohttp.ClientSession() as session:

            async with session.get(
                "https://my.sepay.vn/userapi/transactions/list",
                headers=headers,
                params={
                    "limit": 200
                },
                timeout=aiohttp.ClientTimeout(total=10)
            ) as r:

                if r.status != 200:
                    log.error("SEPAY ERROR %s", r.status)
                    return

                data = await r.json()

        txns = data.get("transactions", [])

        log.info("Received %d transactions", len(txns))

        used_txns = set()

        for oid, order in pending:

            if order.get("paid"):
                continue

            for txn in txns:

                txn_id = str(txn.get("id"))

                if txn_id in used_txns:
                    continue

                if match_order(txn, oid, order):

                    used_txns.add(txn_id)

                    await confirm_payment(oid)

                    break

    except Exception as e:
        log.error("POLL ERROR: %s", e)

# =========================================================
# WEBHOOK
# =========================================================

async def health(request):
    return web.Response(text="OK")

async def test(request):
    return web.json_response({
        "status": "ok"
    })

async def webhook(request):

    try:

        try:
            body = await request.json()

        except:

            raw = await request.text()

            log.info("RAW WEBHOOK TEXT: %s", raw)

            try:
                body = json.loads(raw)

            except:
                return web.json_response({
                    "success": False
                }, status=400)

        log.info("WEBHOOK RECEIVED = %s", body)

        for oid, order in orders.items():

            if order.get("paid"):
                continue

            if match_order(body, oid, order):

                await confirm_payment(oid)

                return web.json_response({
                    "success": True,
                    "order": oid
                })

        return web.json_response({
            "success": False,
            "message": "No order matched"
        })

    except Exception as e:

        log.error("WEBHOOK ERROR: %s", e)

        return web.json_response({
            "success": False
        }, status=500)

async def start_web():

    app = web.Application()

    app.router.add_get("/", health)

    app.router.add_get("/test", test)

    app.router.add_post("/webhook", webhook)

    runner = web.AppRunner(app)

    await runner.setup()

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        WEBHOOK_PORT
    )

    await site.start()

    log.info("WEBHOOK STARTED PORT %s", WEBHOOK_PORT)

# =========================================================
# MODAL
# =========================================================

class DepositModal(discord.ui.Modal, title="💳 Nạp tiền"):

    amount = discord.ui.TextInput(
        label="Số tiền",
        placeholder="50000"
    )

    async def on_submit(self, interaction: discord.Interaction):

        try:
            amount = int(
                self.amount.value
                .replace(",", "")
                .replace(".", "")
            )

        except:
            return await interaction.response.send_message(
                "❌ Số tiền không hợp lệ",
                ephemeral=True
            )

        if amount < 1000:
            return await interaction.response.send_message(
                "❌ Tối thiểu 1.000đ",
                ephemeral=True
            )

        order_id = make_order_id()

        orders[order_id] = {
            "user_id": interaction.user.id,
            "amount": amount,
            "paid": False,
            "created_at": time.time()
        }

        save_data()

        embed = discord.Embed(
            title="💳 Thông tin chuyển khoản",
            color=0xff00aa
        )

        embed.description = (
            f"🏦 Bank: **MSB**\n"
            f"💳 STK: **{BANK_NUMBER}**\n"
            f"💵 Số tiền: **{amount:,}đ**\n\n"
            f"📝 Nội dung:\n"
            f"```{order_id}```\n"
            f"⚠️ Chuyển đúng nội dung"
        )

        embed.set_image(
            url=build_qr(amount, order_id)
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )

# =========================================================
# VIEW
# =========================================================

class ShopView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="💳 Nạp tiền",
        style=discord.ButtonStyle.green
    )
    async def deposit(
        self,
        interaction: discord.Interaction,
        button
    ):
        await interaction.response.send_modal(
            DepositModal()
        )

    @discord.ui.button(
        label="💰 Số dư",
        style=discord.ButtonStyle.blurple
    )
    async def balance(
        self,
        interaction: discord.Interaction,
        button
    ):

        bal = get_balance(interaction.user.id)

        embed = discord.Embed(
            title="💰 Số dư",
            description=f"**{bal:,}đ**",
            color=0x5865F2
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )

# =========================================================
# COMMANDS
# =========================================================

@bot.command()
async def shop(ctx):

    embed = discord.Embed(
        title="🛒 SHOP AUTO",
        description=(
            "💳 Nạp tiền tự động\n"
            "⚡ Auto cộng tiền SePay\n"
            "🔑 Auto bán key"
        ),
        color=0xff00aa
    )

    await ctx.send(
        embed=embed,
        view=ShopView()
    )

@bot.command()
@commands.has_permissions(administrator=True)
async def xacnhan(ctx, order_id: str):

    oid = order_id.upper()

    if oid not in orders:
        return await ctx.send("❌ Không tồn tại")

    await confirm_payment(oid)

    await ctx.send("✅ Đã cộng tiền")

@bot.command()
@commands.has_permissions(administrator=True)
async def doncho(ctx):

    pending = [
        (oid, o)
        for oid, o in orders.items()
        if not o.get("paid")
    ]

    if not pending:
        return await ctx.send("✅ Không có đơn")

    lines = []

    for oid, o in pending:

        lines.append(
            f"`{oid}` | {o['amount']:,}đ | <@{o['user_id']}>"
        )

    embed = discord.Embed(
        title=f"⏳ {len(pending)} đơn chờ",
        description="\n".join(lines),
        color=0xffaa00
    )

    await ctx.send(embed=embed)

# =========================================================
# READY
# =========================================================

started = False

@bot.event
async def on_ready():

    global started

    log.info("BOT READY %s", bot.user)

    if not started:

        await start_web()

        poll_sepay.start()

        started = True

        log.info("ALL SYSTEM READY")

# =========================================================
# RUN
# =========================================================

bot.run(TOKEN)
