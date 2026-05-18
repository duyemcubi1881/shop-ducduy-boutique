import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
from aiohttp import web
import aiohttp
import asyncio
import os
import random
import json
import logging

# =========================
# LOAD ENV
# =========================

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN", "").strip()

BANK_NUMBER = os.getenv("BANK_NUMBER", "").strip()

BANK_NAME = os.getenv("BANK_NAME", "").strip().lower()

SEPAY_TOKEN = os.getenv("SEPAY_TOKEN", "").strip()

API_BASE = os.getenv(
    "API_BASE",
    "https://aovduy.onrender.com"
).strip()

WEBHOOK_PORT = int(
    os.environ.get("PORT", 10000)
)

# =========================
# LOGGING
# =========================

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bot")

# =========================
# BOT SETUP
# =========================

intents = discord.Intents.all()

bot = commands.Bot(
    command_prefix="!",
    intents=intents
)

# =========================
# MEMORY DATA
# =========================

balances = {}
orders = {}

# =========================
# PRODUCTS
# =========================

PRODUCTS = {
    "legit_drag": {
        "label": "Legit Drag",
        "emoji": "🎯",
        "packages": [
            {"id": "ld_3h", "name": "Key Legit Drag 3 Giờ", "price": 3000, "duration": "3 giờ"},
            {"id": "ld_1d", "name": "Key Legit Drag 1 Ngày", "price": 10000, "duration": "1 ngày"},
            {"id": "ld_7d", "name": "Key Legit Drag 7 Ngày", "price": 50000, "duration": "7 ngày"},
            {"id": "ld_1m", "name": "Key Legit Drag 1 Tháng", "price": 120000, "duration": "1 tháng"},
            {"id": "ld_1ob", "name": "Key Legit Drag 1 OB", "price": 240000, "duration": "1 OB"},
        ]
    },

    "aimbot_head": {
        "label": "Aimbot Head",
        "emoji": "🔫",
        "packages": [
            {"id": "ah_3h", "name": "Key Aimbot Head 3 Giờ", "price": 5000, "duration": "3 giờ"},
            {"id": "ah_1d", "name": "Key Aimbot Head 1 Ngày", "price": 15000, "duration": "1 ngày"},
            {"id": "ah_7d", "name": "Key Aimbot Head 7 Ngày", "price": 60000, "duration": "7 ngày"},
            {"id": "ah_1m", "name": "Key Aimbot Head 1 Tháng", "price": 240000, "duration": "1 tháng"},
            {"id": "ah_1ob", "name": "Key Aimbot Head 1 OB", "price": 450000, "duration": "1 OB"},
        ]
    }
}

PACKAGE_LOOKUP = {}

for product_key, product in PRODUCTS.items():
    for pkg in product["packages"]:
        PACKAGE_LOOKUP[pkg["id"]] = pkg

# =========================
# BALANCE FUNCTIONS
# =========================

def get_balance(user_id):
    return balances.get(user_id, 0)

def add_balance(user_id, amount):
    balances[user_id] = balances.get(user_id, 0) + amount
    return balances[user_id]

def deduct_balance(user_id, amount):
    if get_balance(user_id) < amount:
        return False

    balances[user_id] -= amount
    return True

# =========================
# QR URL
# =========================

def build_qr_url(amount, order_id):
    return (
        f"https://img.vietqr.io/image/"
        f"{BANK_NAME}-{BANK_NUMBER}-compact2.png"
        f"?amount={amount}"
        f"&addInfo={order_id}"
        f"&accountName=SHOP%20KEY"
    )

# =========================
# GET KEY API
# =========================

async def fetch_key(package_id):

    try:
        async with aiohttp.ClientSession() as session:

            url = f"{API_BASE}/api/key"

            async with session.get(
                url,
                params={"package": package_id},
                timeout=10
            ) as resp:

                if resp.status != 200:
                    return None

                data = await resp.json()

                return data.get("key")

    except Exception as e:
        print("API ERROR:", e)

    return None

# =========================
# PAYMENT SUCCESS
# =========================

async def confirm_payment(order_id):

    order = orders.get(order_id)

    if not order:
        return

    if order["paid"]:
        return

    order["paid"] = True

    user_id = order["user_id"]

    amount = order["amount"]

    new_balance = add_balance(user_id, amount)

    try:

        user = await bot.fetch_user(user_id)

        embed = discord.Embed(
            title="✅ Nạp tiền thành công",
            color=0x00ff99
        )

        embed.description = (
            f"💵 Đã nạp: **{amount:,} VNĐ**\n"
            f"💰 Số dư mới: **{new_balance:,} VNĐ**\n"
            f"🧾 Mã đơn: `{order_id}`"
        )

        await user.send(embed=embed)

    except Exception as e:
        print(e)

# =========================
# POLL TRANSACTIONS
# =========================

@tasks.loop(seconds=10)
async def poll_transactions():

    pending = [
        oid for oid, order in orders.items()
        if not order["paid"]
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
                timeout=10
            ) as resp:

                if resp.status != 200:
                    return

                data = await resp.json()

                transactions = data.get("transactions", [])

        for txn in transactions:

            content = str(
                txn.get("transaction_content", "")
            ).upper()

            amount = int(
                txn.get("amount_in", 0)
            )

            for oid in pending:

                order = orders[oid]

                if (
                    oid.upper() in content
                    and amount >= order["amount"]
                ):

                    await confirm_payment(oid)

    except Exception as e:
        print("POLL ERROR:", e)

# =========================
# WEBHOOK
# =========================

async def webhook(request):

    try:

        data = await request.json()

        content = str(
            data.get("content", "")
        ).upper()

        amount = int(
            data.get("transferAmount", 0)
        )

        for oid, order in orders.items():

            if order["paid"]:
                continue

            if (
                oid.upper() in content
                and amount >= order["amount"]
            ):

                await confirm_payment(oid)

                return web.json_response({
                    "success": True
                })

        return web.json_response({
            "success": False
        })

    except Exception as e:

        print("WEBHOOK ERROR:", e)

        return web.json_response({
            "success": False
        })

async def start_webhook():

    app = web.Application()

    app.router.add_post("/webhook", webhook)

    runner = web.AppRunner(app)

    await runner.setup()

    site = web.TCPSite(
        runner,
        "0.0.0.0",
        WEBHOOK_PORT
    )

    await site.start()

    print(f"Webhook running port {WEBHOOK_PORT}")

# =========================
# DEPOSIT MODAL
# =========================

class DepositModal(discord.ui.Modal, title="💳 Nạp Tiền"):

    amount = discord.ui.TextInput(
        label="Nhập số tiền",
        placeholder="50000"
    )

    async def on_submit(self, interaction):

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

        order_id = f"NAP{random.randint(10000,99999)}"

        orders[order_id] = {
            "user_id": interaction.user.id,
            "amount": amount,
            "paid": False
        }

        qr_url = build_qr_url(amount, order_id)

        embed = discord.Embed(
            title="💳 Thông Tin Chuyển Khoản",
            color=0x00bfff
        )

        embed.description = (
            f"💰 Số tiền: **{amount:,} VNĐ**\n"
            f"🏦 Bank: **{BANK_NAME.upper()}**\n"
            f"🔢 STK: `{BANK_NUMBER}`\n"
            f"📝 Nội dung: `{order_id}`\n\n"
            f"✅ Tự động cộng tiền sau khi CK"
        )

        embed.set_image(url=qr_url)

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )

# =========================
# BUY MODAL
# =========================

class BuyModal(discord.ui.Modal):

    quantity = discord.ui.TextInput(
        label="Số lượng key",
        default="1"
    )

    def __init__(self, package_id):

        self.package_id = package_id

        pkg = PACKAGE_LOOKUP[package_id]

        super().__init__(
            title=f"Mua {pkg['name']}"
        )

    async def on_submit(self, interaction):

        qty = int(self.quantity.value)

        pkg = PACKAGE_LOOKUP[self.package_id]

        total = pkg["price"] * qty

        user_id = interaction.user.id

        if get_balance(user_id) < total:

            return await interaction.response.send_message(
                "❌ Không đủ số dư",
                ephemeral=True
            )

        deduct_balance(user_id, total)

        keys = []

        for _ in range(qty):

            key = await fetch_key(self.package_id)

            if key:
                keys.append(key)

        embed = discord.Embed(
            title="✅ Mua Thành Công",
            color=0x00ff99
        )

        embed.description = (
            f"🛒 {pkg['name']}\n"
            f"⏱ {pkg['duration']}\n"
            f"💸 {total:,} VNĐ"
        )

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )

        try:

            user = await bot.fetch_user(user_id)

            dm = discord.Embed(
                title="🔑 Key của bạn",
                color=0xffd700
            )

            dm.description = (
                f"📦 {pkg['name']}\n"
                f"⏱ {pkg['duration']}\n\n"
                f"🔑 KEY:\n"
                + "\n".join(
                    [f"`{k}`" for k in keys]
                )
                + f"\n\n🌐 {API_BASE}"
            )

            await user.send(embed=dm)

        except:
            pass

# =========================
# PACKAGE BUTTON
# =========================

class PackageButton(discord.ui.Button):

    def __init__(self, pkg):

        super().__init__(
            label=f"{pkg['name']} - {pkg['price']:,}đ",
            style=discord.ButtonStyle.primary
        )

        self.package_id = pkg["id"]

    async def callback(self, interaction):

        await interaction.response.send_modal(
            BuyModal(self.package_id)
        )

# =========================
# PACKAGE VIEW
# =========================

class PackageView(discord.ui.View):

    def __init__(self, product_key):

        super().__init__(timeout=120)

        product = PRODUCTS[product_key]

        for pkg in product["packages"]:

            self.add_item(
                PackageButton(pkg)
            )

# =========================
# CATEGORY VIEW
# =========================

class CategoryView(discord.ui.View):

    def __init__(self):

        super().__init__(timeout=120)

    @discord.ui.select(
        placeholder="Chọn sản phẩm",
        options=[
            discord.SelectOption(
                label="Legit Drag",
                value="legit_drag",
                emoji="🎯"
            ),
            discord.SelectOption(
                label="Aimbot Head",
                value="aimbot_head",
                emoji="🔫"
            )
        ]
    )
    async def select_callback(
        self,
        interaction,
        select
    ):

        key = select.values[0]

        product = PRODUCTS[key]

        embed = discord.Embed(
            title=product["label"],
            color=0x00bfff
        )

        lines = []

        for pkg in product["packages"]:

            lines.append(
                f"• {pkg['name']} — {pkg['price']:,}đ"
            )

        embed.description = "\n".join(lines)

        await interaction.response.send_message(
            embed=embed,
            view=PackageView(key),
            ephemeral=True
        )

# =========================
# MAIN VIEW
# =========================

class MainView(discord.ui.View):

    def __init__(self):

        super().__init__(timeout=None)

    @discord.ui.button(
        label="💳 Nạp Tiền",
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
        label="💰 Số Dư",
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
            f"💰 Số dư: **{bal:,} VNĐ**",
            ephemeral=True
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

        await interaction.response.send_message(
            "🛒 Chọn sản phẩm",
            view=CategoryView(),
            ephemeral=True
        )

# =========================
# COMMAND
# =========================

@bot.command()
async def shop(ctx):

    embed = discord.Embed(
        title="🔥 SHOP KEY",
        color=0x2f3136
    )

    embed.description = (
        "💳 Nạp tiền tự động\n"
        "🛒 Mua key tự động\n"
        "📩 Nhận key qua DM"
    )

    await ctx.send(
        embed=embed,
        view=MainView()
    )

# =========================
# READY
# =========================

@bot.event
async def on_ready():

    print("======================")
    print(f"TOKEN = [{TOKEN}]")
    print("======================")

    print(f"Online: {bot.user}")

    if not poll_transactions.is_running():
        poll_transactions.start()

    asyncio.create_task(
        start_webhook()
    )

# =========================
# MAIN
# =========================

async def main():

    if not TOKEN:
        raise Exception(
            "DISCORD_TOKEN trống"
        )

    async with bot:
        await bot.start(TOKEN)

# =========================
# START
# =========================

try:

    asyncio.run(main())

except Exception as e:

    print("BOT ERROR:", e)
