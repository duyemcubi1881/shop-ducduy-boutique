import discord
from discord.ext import commands, tasks
from discord.ui import View, Button, Modal, TextInput, Select
from aiohttp import web
from dotenv import load_dotenv

import aiohttp
import logging
import random
import asyncio
import json
import os

# ╔══════════════════════════════════════════════╗
# ║                LOAD ENV                     ║
# ╚══════════════════════════════════════════════╝

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

BANK_NAME = os.getenv("BANK_NAME", "msb")
BANK_NUMBER = os.getenv("BANK_NUMBER")

SEPAY_TOKEN = os.getenv("SEPAY_TOKEN", "")

API_BASE = os.getenv(
    "API_BASE",
    "https://aovduy.onrender.com"
)

API_ADMIN_USER = os.getenv("API_ADMIN_USER")
API_ADMIN_PASS = os.getenv("API_ADMIN_PASS")

PORT = int(os.getenv("PORT", "10000"))

# ╔══════════════════════════════════════════════╗
# ║                  LOGGING                    ║
# ╚══════════════════════════════════════════════╝

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

log = logging.getLogger("shop")

# ╔══════════════════════════════════════════════╗
# ║                   BOT                       ║
# ╚══════════════════════════════════════════════╝

intents = discord.Intents.all()

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

# ╔══════════════════════════════════════════════╗
# ║                 DATABASE                    ║
# ╚══════════════════════════════════════════════╝

balances = {}
orders = {}

# ╔══════════════════════════════════════════════╗
# ║                 PRODUCTS                    ║
# ╚══════════════════════════════════════════════╝

PRODUCTS = {
    "aimbot": {
        "label": "Aimbot Head",
        "emoji": "🔫",
        "packages": [
            {
                "id": "ah_1d",
                "name": "Aimbot 1 Ngày",
                "price": 15000,
                "days": 1
            },
            {
                "id": "ah_7d",
                "name": "Aimbot 7 Ngày",
                "price": 60000,
                "days": 7
            },
            {
                "id": "ah_1m",
                "name": "Aimbot 1 Tháng",
                "price": 240000,
                "days": 30
            }
        ]
    },

    "drag": {
        "label": "Legit Drag",
        "emoji": "🎯",
        "packages": [
            {
                "id": "ld_1d",
                "name": "Legit Drag 1 Ngày",
                "price": 10000,
                "days": 1
            },
            {
                "id": "ld_7d",
                "name": "Legit Drag 7 Ngày",
                "price": 50000,
                "days": 7
            },
            {
                "id": "ld_1m",
                "name": "Legit Drag 1 Tháng",
                "price": 120000,
                "days": 30
            }
        ]
    }
}

PKG = {}

for p in PRODUCTS.values():
    for pkg in p["packages"]:
        PKG[pkg["id"]] = pkg

# ╔══════════════════════════════════════════════╗
# ║                 UTILITIES                   ║
# ╚══════════════════════════════════════════════╝

def get_balance(uid):
    return balances.get(uid, 0)

def add_balance(uid, amount):
    balances[uid] = balances.get(uid, 0) + amount
    return balances[uid]

def deduct_balance(uid, amount):
    if balances.get(uid, 0) < amount:
        return False

    balances[uid] -= amount
    return True

def make_order_id():
    oid = f"NAP{random.randint(10000,99999)}"

    while oid in orders:
        oid = f"NAP{random.randint(10000,99999)}"

    return oid

def build_qr(amount, order_id):

    return (
        f"https://img.vietqr.io/image/"
        f"{BANK_NAME}-{BANK_NUMBER}-compact2.png"
        f"?amount={amount}"
        f"&addInfo={order_id}"
        f"&accountName=DUCDUY"
    )

# ╔══════════════════════════════════════════════╗
# ║              BACKEND CREATE KEY             ║
# ╚══════════════════════════════════════════════╝

async def fetch_key(pkg_id):

    pkg = PKG[pkg_id]

    try:

        async with aiohttp.ClientSession() as session:

            # LOGIN

            login = await session.post(
                f"{API_BASE}/api/login",
                json={
                    "username": API_ADMIN_USER,
                    "password": API_ADMIN_PASS
                },
                timeout=10
            )

            if login.status != 200:

                txt = await login.text()

                log.error(f"LOGIN FAIL {login.status}: {txt}")

                return None

            log.info("LOGIN BACKEND OK")

            # CREATE KEY

            create = await session.post(
                f"{API_BASE}/api/createkey",
                json={
                    "days": pkg["days"],
                    "note": "Auto Shop"
                },
                timeout=10
            )

            data = await create.json()

            log.info(f"CREATE KEY RESPONSE: {data}")

            if create.status in [200, 201]:

                key = data.get("key")

                return key

            return None

    except Exception as e:

        log.error(f"FETCH KEY ERROR: {e}")

        return None

# ╔══════════════════════════════════════════════╗
# ║            PAYMENT CONFIRM                  ║
# ╚══════════════════════════════════════════════╝

async def confirm_payment(order_id):

    order = orders.get(order_id)

    if not order:
        return

    if order.get("paid"):
        return

    order["paid"] = True

    uid = order["user_id"]
    amount = order["amount"]

    bal = add_balance(uid, amount)

    log.info(f"CONFIRM PAYMENT {order_id}")

    try:

        user = await bot.fetch_user(uid)

        embed = discord.Embed(
            title="✅ Nạp tiền thành công",
            color=0x00ff99
        )

        embed.description = (
            f"💵 Đã nạp: **{amount:,}đ**\n"
            f"💰 Số dư: **{bal:,}đ**\n"
            f"🧾 Mã đơn: `{order_id}`"
        )

        await user.send(embed=embed)

    except Exception as e:

        log.error(e)

# ╔══════════════════════════════════════════════╗
# ║                 SEPAY POLL                  ║
# ╚══════════════════════════════════════════════╝

@tasks.loop(seconds=10)
async def poll_sepay():

    if not SEPAY_TOKEN:
        return

    pending = [
        oid for oid, o in orders.items()
        if not o.get("paid")
    ]

    if not pending:
        return

    try:

        headers = {
            "Authorization": f"Bearer {SEPAY_TOKEN}"
        }

        async with aiohttp.ClientSession() as session:

            async with session.get(
                "https://my.sepay.vn/userapi/transactions/list",
                headers=headers,
                params={"limit": 20},
                timeout=10
            ) as res:

                text = await res.text()

                log.info(f"SEPAY RESPONSE: {text[:500]}")

                if res.status != 200:
                    return

                data = json.loads(text)

        transactions = data.get("transactions", [])

        for txn in transactions:

            content = str(
                txn.get("transaction_content", "")
            ).upper()

            amount = int(
                txn.get("amount_in", 0)
            )

            for oid in pending:

                if oid.upper() in content:

                    if amount >= orders[oid]["amount"]:

                        log.info(f"MATCH PAYMENT {oid}")

                        await confirm_payment(oid)

    except Exception as e:

        log.error(f"SEPAY ERROR: {e}")

# ╔══════════════════════════════════════════════╗
# ║                  WEBHOOK                    ║
# ╚══════════════════════════════════════════════╝

async def handle_home(request):

    return web.Response(
        text="BOT ONLINE"
    )

async def handle_webhook(request):

    try:

        if request.method == "GET":

            return web.json_response({
                "status": "online"
            })

        data = await request.json()

        log.info(f"WEBHOOK: {data}")

        content = str(
            data.get("transaction_content", "")
        ).upper()

        amount = int(
            data.get("amount_in", 0)
        )

        for oid, order in orders.items():

            if order.get("paid"):
                continue

            if oid.upper() in content:

                if amount >= order["amount"]:

                    await confirm_payment(oid)

                    return web.json_response({
                        "success": True
                    })

        return web.json_response({
            "success": False
        })

    except Exception as e:

        log.error(f"WEBHOOK ERROR: {e}")

        return web.json_response({
            "success": False
        })

async def start_web():

    app = web.Application()

    app.router.add_get("/", handle_home)

    app.router.add_route(
        "*",
        "/webhook",
        handle_webhook
    )

    runner = web.AppRunner(app)

    await runner.setup()

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        PORT
    )

    await site.start()

    log.info(f"WEB RUNNING PORT {PORT}")

# ╔══════════════════════════════════════════════╗
# ║                  MODAL                      ║
# ╚══════════════════════════════════════════════╝

class DepositModal(Modal, title="💳 Nạp tiền"):

    amount = TextInput(
        label="Số tiền",
        placeholder="50000"
    )

    async def on_submit(self, interaction):

        try:

            amount = int(
                self.amount.value
            )

        except:

            return await interaction.response.send_message(
                "❌ Số tiền không hợp lệ",
                ephemeral=True
            )

        order_id = make_order_id()

        orders[order_id] = {
            "user_id": interaction.user.id,
            "amount": amount,
            "paid": False
        }

        embed = discord.Embed(
            title="💳 Chuyển khoản",
            color=0xff0099
        )

        embed.description = (
            f"💰 Số tiền: **{amount:,}đ**\n"
            f"🏦 Bank: **{BANK_NAME.upper()}**\n"
            f"🔢 STK: `{BANK_NUMBER}`\n\n"
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

# ╔══════════════════════════════════════════════╗
# ║                  BUY MODAL                  ║
# ╚══════════════════════════════════════════════╝

class BuyModal(Modal):

    qty = TextInput(
        label="Số lượng",
        default="1"
    )

    def __init__(self, pkg_id):

        super().__init__(
            title="🛒 Mua Key"
        )

        self.pkg_id = pkg_id

    async def on_submit(self, interaction):

        qty = int(self.qty.value)

        pkg = PKG[self.pkg_id]

        total = pkg["price"] * qty

        uid = interaction.user.id

        if get_balance(uid) < total:

            return await interaction.response.send_message(
                "❌ Không đủ tiền",
                ephemeral=True
            )

        deduct_balance(uid, total)

        await interaction.response.defer(
            ephemeral=True
        )

        keys = []

        for _ in range(qty):

            key = await fetch_key(self.pkg_id)

            if key:
                keys.append(key)

        embed = discord.Embed(
            title="✅ Mua thành công",
            color=0x00ff99
        )

        embed.description = (
            f"🛒 Gói: **{pkg['name']}**\n"
            f"💸 Giá: **{total:,}đ**\n"
            f"🔑 Số key: **{len(keys)}**"
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True
        )

        if keys:

            user = await bot.fetch_user(uid)

            dm = discord.Embed(
                title="🔑 KEY CỦA BẠN",
                color=0xff0099
            )

            dm.description = "\n".join(
                [f"`{k}`" for k in keys]
            )

            await user.send(embed=dm)

# ╔══════════════════════════════════════════════╗
# ║                   VIEW                      ║
# ╚══════════════════════════════════════════════╝

class PackageButton(Button):

    def __init__(self, pkg):

        super().__init__(
            label=f"{pkg['name']} - {pkg['price']:,}đ",
            style=discord.ButtonStyle.primary
        )

        self.pkg_id = pkg["id"]

    async def callback(self, interaction):

        await interaction.response.send_modal(
            BuyModal(self.pkg_id)
        )

class PackageView(View):

    def __init__(self, key):

        super().__init__(timeout=120)

        for pkg in PRODUCTS[key]["packages"]:

            self.add_item(
                PackageButton(pkg)
            )

class CategorySelect(Select):

    def __init__(self):

        options = []

        for key, p in PRODUCTS.items():

            options.append(
                discord.SelectOption(
                    label=p["label"],
                    value=key,
                    emoji=p["emoji"]
                )
            )

        super().__init__(
            placeholder="Chọn sản phẩm",
            options=options
        )

    async def callback(self, interaction):

        key = self.values[0]

        embed = discord.Embed(
            title="🛒 Chọn gói",
            color=0x00bfff
        )

        txt = []

        for pkg in PRODUCTS[key]["packages"]:

            txt.append(
                f"• {pkg['name']} - {pkg['price']:,}đ"
            )

        embed.description = "\n".join(txt)

        await interaction.response.edit_message(
            embed=embed,
            view=PackageView(key)
        )

class CategoryView(View):

    def __init__(self):

        super().__init__(timeout=120)

        self.add_item(
            CategorySelect()
        )

class ShopView(View):

    def __init__(self):

        super().__init__(timeout=None)

    @discord.ui.button(
        label="💳 Nạp tiền",
        style=discord.ButtonStyle.green
    )
    async def deposit(
        self,
        interaction,
        button
    ):

        await interaction.response.send_modal(
            DepositModal()
        )

    @discord.ui.button(
        label="🛒 Mua Key",
        style=discord.ButtonStyle.red
    )
    async def shop(
        self,
        interaction,
        button
    ):

        embed = discord.Embed(
            title="🛍️ DANH MỤC",
            color=0xff0099
        )

        embed.description = (
            "🎯 Legit Drag\n"
            "🔫 Aimbot Head"
        )

        await interaction.response.send_message(
            embed=embed,
            view=CategoryView(),
            ephemeral=True
        )

    @discord.ui.button(
        label="💰 Số dư",
        style=discord.ButtonStyle.blurple
    )
    async def balance(
        self,
        interaction,
        button
    ):

        bal = get_balance(
            interaction.user.id
        )

        await interaction.response.send_message(
            f"💰 Số dư: **{bal:,}đ**",
            ephemeral=True
        )

# ╔══════════════════════════════════════════════╗
# ║                 COMMANDS                    ║
# ╚══════════════════════════════════════════════╝

@bot.command()
async def shop(ctx):

    embed = discord.Embed(
        title="🛍️ SHOP DUCDUY BOUTIQUE",
        color=0xff0099
    )

    embed.description = (
        "```"
        "\n🔥 SHOP KEY TỰ ĐỘNG"
        "\n💳 Nạp tiền tự động"
        "\n🔑 Giao key tự động"
        "\n⚡ Hệ thống realtime"
        "\n```"
    )

    await ctx.send(
        embed=embed,
        view=ShopView()
    )

# ╔══════════════════════════════════════════════╗
# ║                   READY                     ║
# ╚══════════════════════════════════════════════╝

_started = False

@bot.event
async def on_ready():

    global _started

    log.info(f"ONLINE {bot.user}")

    if not _started:

        await start_web()

        poll_sepay.start()

        _started = True

# ╔══════════════════════════════════════════════╗
# ║                    RUN                      ║
# ╚══════════════════════════════════════════════╝

bot.run(TOKEN)
