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

# ══════════════════════════════════════════
# LOAD ENV
# ══════════════════════════════════════════
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
BANK_NUMBER = os.getenv("BANK_NUMBER")
BANK_NAME = os.getenv("BANK_NAME", "msb")
SEPAY_TOKEN = os.getenv("SEPAY_TOKEN", "")
API_BASE = os.getenv("API_BASE", "https://aovduy.onrender.com")
API_ADMIN_USER = os.getenv("API_ADMIN_USER", "admin")
API_ADMIN_PASS = os.getenv("API_ADMIN_PASS", "admin123")
WEBHOOK_PORT = int(os.getenv("PORT", "8080"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("shop")

# ══════════════════════════════════════════
# BOT SETUP
# ══════════════════════════════════════════
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# ══════════════════════════════════════════
# DATA
# ══════════════════════════════════════════
balances: dict[int, int] = {}
orders: dict[str, dict] = {}

# ══════════════════════════════════════════
# DANH MỤC SẢN PHẨM
# ══════════════════════════════════════════
PRODUCTS = {
    "legit_drag": {
        "label": "Legit Drag",
        "emoji": "🎯",
        "packages": [
            {"id": "ld_3h", "name": "Legit Drag 3 Gio", "price": 3_000, "duration": "3 gio", "days": 1},
            {"id": "ld_1d", "name": "Legit Drag 1 Ngay", "price": 10_000, "duration": "1 ngay", "days": 1},
            {"id": "ld_7d", "name": "Legit Drag 7 Ngay", "price": 50_000, "duration": "7 ngay", "days": 7},
            {"id": "ld_1m", "name": "Legit Drag 1 Thang", "price": 120_000, "duration": "1 thang", "days": 30},
            {"id": "ld_1ob", "name": "Legit Drag 1 OB", "price": 240_000, "duration": "1 OB", "days": 90},
        ],
    },
    "aimbot_head": {
        "label": "Aimbot Head",
        "emoji": "🔫",
        "packages": [
            {"id": "ah_3h", "name": "Aimbot Head 3 Gio", "price": 5_000, "duration": "3 gio", "days": 1},
            {"id": "ah_1d", "name": "Aimbot Head 1 Ngay", "price": 15_000, "duration": "1 ngay", "days": 1},
            {"id": "ah_7d", "name": "Aimbot Head 7 Ngay", "price": 60_000, "duration": "7 ngay", "days": 7},
            {"id": "ah_1m", "name": "Aimbot Head 1 Thang", "price": 240_000, "duration": "1 thang", "days": 30},
            {"id": "ah_1ob", "name": "Aimbot Head 1 OB", "price": 450_000, "duration": "1 OB", "days": 90},
        ],
    },
}

PKG: dict[str, dict] = {}
for _pk, _pv in PRODUCTS.items():
    for _pkg in _pv["packages"]:
        PKG[_pkg["id"]] = {**_pkg, "product_label": _pv["label"]}

# ══════════════════════════════════════════
# HÀM TIỆN ÍCH
# ══════════════════════════════════════════
def get_balance(uid: int) -> int:
    return balances.get(uid, 0)

def add_balance(uid: int, amount: int) -> int:
    balances[uid] = balances.get(uid, 0) + amount
    return balances[uid]

def deduct_balance(uid: int, amount: int) -> bool:
    if balances.get(uid, 0) < amount:
        return False
    balances[uid] -= amount
    return True

def make_order_id() -> str:
    oid = f"NAP{random.randint(10000, 99999)}"
    while oid in orders:
        oid = f"NAP{random.randint(10000, 99999)}"
    return oid

def build_qr_url(amount: int, order_id: str) -> str:
    bank = BANK_NAME.lower().strip()
    return (
        f"https://img.vietqr.io/image/{bank}-{BANK_NUMBER}-compact2.png"
        f"?amount={amount}&addInfo={order_id}&accountName=DUCDUY%20BOUTIQUE"
    )

# ══════════════════════════════════════════
# TẠO KEY TỪ BACKEND
# ══════════════════════════════════════════
async def fetch_key(package_id: str) -> str | None:
    pkg = PKG.get(package_id)
    days = pkg["days"] if pkg else 1
    try:
        async with aiohttp.ClientSession() as s:
            login_resp = await s.post(
                f"{API_BASE}/api/login",
                json={"username": API_ADMIN_USER, "password": API_ADMIN_PASS},
                timeout=aiohttp.ClientTimeout(total=10),
            )
            if login_resp.status != 200:
                return None

            key_resp = await s.post(
                f"{API_BASE}/api/createkey",
                json={
                    "days": days,
                    "key_type": "single_device",
                    "created_by": "ShopBot",
                    "note": f"Auto-{package_id}",
                },
                timeout=aiohttp.ClientTimeout(total=10),
            )
            if key_resp.status == 201:
                data = await key_resp.json()
                return data.get("key")
    except Exception as e:
        log.error(f"fetch_key lỗi: {e}")
    return None

# ══════════════════════════════════════════
# XÁC NHẬN THANH TOÁN
# ══════════════════════════════════════════
async def confirm_payment(order_id: str):
    order = orders.get(order_id)
    if not order or order.get("paid"):
        return

    order["paid"] = True
    uid = order["user_id"]
    amount = order["amount"]
    bal = add_balance(uid, amount)

    log.info(f"✅ XÁC NHẬN ĐƠN {order_id} | +{amount:,}đ | User {uid}")

    try:
        user = await bot.fetch_user(uid)
        embed = discord.Embed(title="✅ Nạp tiền thành công!", color=0x2ECC71)
        embed.description = (
            f"💵 Số tiền nạp: **{amount:,} VNĐ**\n"
            f"💰 Số dư hiện tại: **{bal:,} VNĐ**\n"
            f"🧾 Mã đơn: `{order_id}`\n\n"
            f"👉 Dùng lệnh `!shop` để mua key ngay!"
        )
        embed.set_footer(text="ducduy boutique")
        await user.send(embed=embed)
    except Exception as e:
        log.warning(f"Không gửi DM cho user {uid}: {e}")

# ══════════════════════════════════════════
# POLLING SEPAY
# ══════════════════════════════════════════
@tasks.loop(seconds=10)
async def poll_sepay():
    pending = [oid for oid, o in orders.items() if not o.get("paid")]
    if not pending or not SEPAY_TOKEN:
        return

    try:
        headers = {"Authorization": f"Bearer {SEPAY_TOKEN}"}
        async with aiohttp.ClientSession() as s:
            async with s.get(
                "https://my.sepay.vn/userapi/transactions/list",
                headers=headers,
                params={"limit": 50},
                timeout=aiohttp.ClientTimeout(total=12),
            ) as r:
                if r.status != 200:
                    return
                data = await r.json()
                txns = data.get("transactions", [])

        for txn in txns:
            content = str(txn.get("transaction_content") or txn.get("content") or "").strip().upper()
            amount = int(txn.get("amount_in") or txn.get("transferAmount") or 0)

            for oid in list(pending):
                order = orders.get(oid)
                if not order or order.get("paid"):
                    continue
                if oid.upper() in content and amount >= order["amount"]:
                    log.info(f"✅ POLLING KHỚP ĐƠN {oid} | {amount:,}đ")
                    await confirm_payment(oid)
                    pending.remove(oid)
                    break
    except Exception as e:
        log.debug(f"poll_sepay: {e}")

# ══════════════════════════════════════════
# DỌN ĐƠN CŨ
# ══════════════════════════════════════════
@tasks.loop(minutes=30)
async def clean_old_orders():
    now = asyncio.get_event_loop().time()
    to_remove = [oid for oid, o in orders.items() 
                 if not o.get("paid") and now - o.get("created_at", 0) > 1800]
    for oid in to_remove:
        orders.pop(oid, None)
    if to_remove:
        log.info(f"🧹 Đã dọn {len(to_remove)} đơn cũ")

# ══════════════════════════════════════════
# WEBHOOK SERVER
# ══════════════════════════════════════════
async def handle_health(request: web.Request):
    return web.Response(text="OK", status=200)

async def handle_webhook(request: web.Request) -> web.Response:
    try:
        body = await request.json()
        content = str(body.get("transaction_content") or body.get("content") or "").strip().upper()
        amount = int(body.get("amount_in") or body.get("transferAmount") or 0)

        log.info(f"📥 Webhook nhận: {amount:,}đ | {content[:80]}")

        for oid, order in list(orders.items()):
            if order.get("paid"):
                continue
            if oid.upper() in content and amount >= order["amount"]:
                log.info(f"✅ WEBHOOK KHỚP ĐƠN: {oid}")
                await confirm_payment(oid)
                return web.json_response({"success": True})

        return web.json_response({"success": False, "reason": "no_match"})
    except Exception as e:
        log.error(f"Webhook lỗi: {e}")
        return web.json_response({"success": False}, status=500)

async def start_webhook_server():
    app = web.Application()
    app.router.add_get("/", handle_health)
    app.router.add_post("/webhook", handle_webhook)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", WEBHOOK_PORT).start()
    log.info(f"✅ Webhook server chạy tại port {WEBHOOK_PORT}")

# ══════════════════════════════════════════
# MODAL NẠP TIỀN
# ══════════════════════════════════════════
class DepositModal(discord.ui.Modal, title="💳 Nạp tiền"):
    amount = discord.ui.TextInput(
        label="Số tiền muốn nạp (VNĐ)",
        placeholder="Ví dụ: 50000",
        min_length=4,
        max_length=10,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amt = int(self.amount.value.replace(",", "").replace(".", "").strip())
        except ValueError:
            return await interaction.response.send_message("❌ Số tiền không hợp lệ!", ephemeral=True)

        if amt < 1000:
            return await interaction.response.send_message("❌ Tối thiểu 1.000 VNĐ!", ephemeral=True)

        order_id = make_order_id()
        orders[order_id] = {
            "user_id": interaction.user.id,
            "amount": amt,
            "paid": False,
            "created_at": asyncio.get_event_loop().time(),
        }

        embed = discord.Embed(title="💳 Thông tin chuyển khoản", color=0xE91E8C)
        embed.description = (
            "```\n"
            f"💰 Số tiền : {amt:,} VNĐ\n"
            f"🏦 Ngân hàng : MSB Bank\n"
            f"🔢 Số tài khoản : {BANK_NUMBER}\n"
            "```\n"
            f"📝 **Nội dung chuyển khoản:**\n`{order_id}`\n\n"
            "⚠️ **Nhập đúng nội dung trên, không thêm bớt**\n"
            "✅ Bot sẽ tự động cộng tiền khi nhận được giao dịch"
        )
        embed.set_image(url=build_qr_url(amt, order_id))
        embed.set_footer(text=f"Mã đơn: {order_id} • Hết hạn sau 30 phút")
        await interaction.response.send_message(embed=embed, ephemeral=True)

# ══════════════════════════════════════════
# MODAL MUA KEY
# ══════════════════════════════════════════
class BuyModal(discord.ui.Modal):
    qty_input = discord.ui.TextInput(
        label="Số lượng key muốn mua",
        placeholder="Ví dụ: 1",
        max_length=2,
        default="1",
    )

    def __init__(self, pkg_id: str):
        pkg = PKG[pkg_id]
        super().__init__(title=f"🛒 {pkg['name']}")
        self.pkg_id = pkg_id

    async def on_submit(self, interaction: discord.Interaction):
        try:
            qty = max(1, int(self.qty_input.value.strip()))
        except ValueError:
            return await interaction.response.send_message("❌ Số lượng không hợp lệ!", ephemeral=True)

        pkg = PKG[self.pkg_id]
        total = pkg["price"] * qty
        uid = interaction.user.id
        bal = get_balance(uid)

        if bal < total:
            return await interaction.response.send_message(
                f"❌ Số dư không đủ!\nCần: **{total:,} VNĐ**\nBạn có: **{bal:,} VNĐ**", ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)
        deduct_balance(uid, total)

        keys_ok = []
        keys_err = 0
        for _ in range(qty):
            k = await fetch_key(self.pkg_id)
            if k:
                keys_ok.append(k)
            else:
                keys_err += 1

        if keys_err:
            add_balance(uid, pkg["price"] * keys_err)

        new_bal = get_balance(uid)
        embed = discord.Embed(title="✅ Mua key thành công!", color=0x2ECC71)
        embed.description = (
            f"🛒 **{pkg['name']}**\n"
            f"🔢 Số lượng: **{len(keys_ok)}**\n"
            f"💰 Đã trừ: **{pkg['price'] * len(keys_ok):,} VNĐ**\n"
            f"💵 Số dư còn: **{new_bal:,} VNĐ**"
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

        if keys_ok:
            try:
                user = await bot.fetch_user(uid)
                dm = discord.Embed(title="🔑 Key của bạn", color=0xE91E8C)
                dm.description = f"**{pkg['name']}**\n\n" + "\n".join(f"`{k}`" for k in keys_ok)
                await user.send(embed=dm)
            except:
                pass

# ══════════════════════════════════════════
# VIEWS
# ══════════════════════════════════════════
class PackageButton(discord.ui.Button):
    def __init__(self, pkg: dict):
        super().__init__(label=f"{pkg['name']} — {pkg['price']:,}đ", style=discord.ButtonStyle.primary)
        self.pkg_id = pkg["id"]

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(BuyModal(self.pkg_id))

class PackageView(discord.ui.View):
    def __init__(self, product_key: str):
        super().__init__(timeout=120)
        for pkg in PRODUCTS[product_key]["packages"]:
            self.add_item(PackageButton(pkg))

class CategoryView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.select(
        placeholder="Chọn sản phẩm...",
        options=[
            discord.SelectOption(label="Legit Drag", value="legit_drag", emoji="🎯"),
            discord.SelectOption(label="Aimbot Head", value="aimbot_head", emoji="🔫"),
        ],
    )
    async def select_product(self, interaction: discord.Interaction, select: discord.ui.Select):
        pk = select.values[0]
        await interaction.response.edit_message(embed=embed_packages(pk), view=PackageView(pk))

class ShopView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="💳 Nạp tiền", style=discord.ButtonStyle.green, row=0)
    async def btn_deposit(self, interaction: discord.Interaction, _btn):
        await interaction.response.send_modal(DepositModal())

    @discord.ui.button(label="💰 Số dư", style=discord.ButtonStyle.blurple, row=0)
    async def btn_balance(self, interaction: discord.Interaction, _btn):
        bal = get_balance(interaction.user.id)
        await interaction.response.send_message(f"**Số dư:** `{bal:,} VNĐ`", ephemeral=True)

    @discord.ui.button(label="🛒 Mua Key", style=discord.ButtonStyle.red, row=0)
    async def btn_shop(self, interaction: discord.Interaction, _btn):
        await interaction.response.send_message(embed=embed_category(), view=CategoryView(), ephemeral=True)

# ══════════════════════════════════════════
# EMBED
# ══════════════════════════════════════════
def embed_shop() -> discord.Embed:
    e = discord.Embed(title="🛍️ ducduy boutique - Shop Key", color=0xE91E8C)
    e.description = "Chọn chức năng bên dưới để nạp tiền hoặc mua key."
    return e

def embed_category() -> discord.Embed:
    e = discord.Embed(title="🛒 Danh mục sản phẩm", color=0xFFD700)
    e.description = "Chọn sản phẩm trong menu bên dưới."
    return e

def embed_packages(product_key: str) -> discord.Embed:
    pv = PRODUCTS[product_key]
    e = discord.Embed(title=f"{pv['emoji']} {pv['label']}", color=0x00BFFF)
    e.description = "\n".join(f"• {p['name']} — **{p['price']:,}đ**" for p in pv["packages"])
    return e

# ══════════════════════════════════════════
# COMMANDS
# ══════════════════════════════════════════
@bot.command()
async def shop(ctx: commands.Context):
    try:
        await ctx.message.delete()
    except:
        pass
    await ctx.send(embed=embed_shop(), view=ShopView())

@bot.command()
@commands.has_permissions(administrator=True)
async def xacnhan(ctx, order_id: str):
    await confirm_payment(order_id.upper())
    await ctx.send("✅ Đã xác nhận thủ công!")

@bot.command()
@commands.has_permissions(administrator=True)
async def doncho(ctx):
    pending = [(k, v) for k, v in orders.items() if not v.get("paid")]
    if not pending:
        return await ctx.send("Không có đơn chờ.")
    txt = "\n".join(f"`{k}` - {v['amount']:,}đ <@{v['user_id']}>" for k, v in pending)
    await ctx.send(f"**Đơn chờ:**\n{txt}")

# ══════════════════════════════════════════
# READY
# ══════════════════════════════════════════
_webhook_started = False

@bot.event
async def on_ready():
    global _webhook_started
    log.info(f"Bot đã online: {bot.user}")

    if not _webhook_started:
        try:
            await start_webhook_server()
            _webhook_started = True
        except Exception as e:
            log.error(f"Webhook lỗi: {e}")

    if not poll_sepay.is_running():
        poll_sepay.start()
    if not clean_old_orders.is_running():
        clean_old_orders.start()

    log.info("Hệ thống tự động nạp tiền đã sẵn sàng!")

# ══════════════════════════════════════════
bot.run(TOKEN)
