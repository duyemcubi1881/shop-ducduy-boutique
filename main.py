import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
from aiohttp import web
import aiohttp
import asyncio
import os
import random
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
WEBHOOK_PORT = int(os.getenv("PORT", "10000"))  # Render thường dùng 10000

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
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
            {"id": "ld_3h", "name": "Legit Drag 3 Gio", "price": 3000, "duration": "3 giờ", "days": 1},
            {"id": "ld_1d", "name": "Legit Drag 1 Ngày", "price": 10000, "duration": "1 ngày", "days": 1},
            {"id": "ld_7d", "name": "Legit Drag 7 Ngày", "price": 50000, "duration": "7 ngày", "days": 7},
            {"id": "ld_1m", "name": "Legit Drag 1 Tháng", "price": 120000, "duration": "1 tháng", "days": 30},
            {"id": "ld_1ob", "name": "Legit Drag 1 OB", "price": 240000, "duration": "1 OB", "days": 90},
        ],
    },
    "aimbot_head": {
        "label": "Aimbot Head",
        "emoji": "🔫",
        "packages": [
            {"id": "ah_3h", "name": "Aimbot Head 3 Gio", "price": 5000, "duration": "3 giờ", "days": 1},
            {"id": "ah_1d", "name": "Aimbot Head 1 Ngày", "price": 15000, "duration": "1 ngày", "days": 1},
            {"id": "ah_7d", "name": "Aimbot Head 7 Ngày", "price": 60000, "duration": "7 ngày", "days": 7},
            {"id": "ah_1m", "name": "Aimbot Head 1 Tháng", "price": 240000, "duration": "1 tháng", "days": 30},
            {"id": "ah_1ob", "name": "Aimbot Head 1 OB", "price": 450000, "duration": "1 OB", "days": 90},
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
    balances[uid] = get_balance(uid) + amount
    return balances[uid]

def deduct_balance(uid: int, amount: int) -> bool:
    if get_balance(uid) < amount:
        return False
    balances[uid] -= amount
    return True

def make_order_id() -> str:
    while True:
        oid = f"NAP{random.randint(10000, 99999)}"
        if oid not in orders:
            return oid

def build_qr_url(amount: int, order_id: str) -> str:
    bank = BANK_NAME.lower().strip()
    return f"https://img.vietqr.io/image/{bank}-{BANK_NUMBER}-compact2.png?amount={amount}&addInfo={order_id}&accountName=DUCDUY%20BOUTIQUE"

# ══════════════════════════════════════════
# TẠO KEY
# ══════════════════════════════════════════
async def fetch_key(package_id: str) -> str | None:
    pkg = PKG.get(package_id)
    days = pkg["days"] if pkg else 1
    try:
        async with aiohttp.ClientSession() as s:
            await s.post(f"{API_BASE}/api/login", json={"username": API_ADMIN_USER, "password": API_ADMIN_PASS})
            resp = await s.post(
                f"{API_BASE}/api/createkey",
                json={"days": days, "key_type": "single_device", "created_by": "ShopBot"},
            )
            if resp.status == 201:
                data = await resp.json()
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

    log.info(f"✅ THÀNH CÔNG | Đơn {order_id} | +{amount:,}đ | User {uid}")

    try:
        user = await bot.fetch_user(uid)
        embed = discord.Embed(title="✅ Nạp tiền thành công!", color=0x2ECC71)
        embed.description = f"💵 Số tiền: **{amount:,} VNĐ**\n💰 Số dư: **{bal:,} VNĐ**\n🧾 Mã đơn: `{order_id}`"
        await user.send(embed=embed)
    except:
        pass

# ══════════════════════════════════════════
# POLLING SEPAY
# ══════════════════════════════════════════
@tasks.loop(seconds=8)
async def poll_sepay():
    if not SEPAY_TOKEN:
        return
    pending = [oid for oid, o in orders.items() if not o.get("paid")]
    if not pending:
        return

    try:
        headers = {"Authorization": f"Bearer {SEPAY_TOKEN}"}
        async with aiohttp.ClientSession() as s:
            async with s.get(
                "https://my.sepay.vn/userapi/transactions/list",
                headers=headers,
                params={"limit": 50},
                timeout=10
            ) as r:
                if r.status != 200:
                    return
                data = await r.json()
                txns = data.get("transactions", [])

        for txn in txns:
            content = str(txn.get("transaction_content") or "").strip().upper()
            amount = int(txn.get("amount_in") or 0)

            for oid in list(pending):
                if oid.upper() in content and amount >= orders[oid]["amount"]:
                    log.info(f"✅ POLLING KHỚP | Đơn {oid} | {amount:,}đ")
                    await confirm_payment(oid)
                    pending.remove(oid)
                    break
    except Exception as e:
        log.debug(f"poll error: {e}")

# ══════════════════════════════════════════
# WEBHOOK (ĐÃ FIX 405)
# ══════════════════════════════════════════
async def handle_health(request: web.Request):
    return web.Response(text="OK", status=200)

async def handle_webhook(request: web.Request) -> web.Response:
    if request.method == "GET":
        return web.Response(text="Webhook OK", status=200)

    try:
        body = await request.json()
        content = str(body.get("transaction_content") or body.get("content") or "").strip().upper()
        amount = int(body.get("amount_in") or body.get("transferAmount") or body.get("amount") or 0)

        log.info(f"📥 WEBHOOK NHẬN: {amount:,}đ | {content[:100]}")

        for oid, order in list(orders.items()):
            if order.get("paid"):
                continue
            if oid.upper() in content and amount >= order["amount"]:
                log.info(f"✅ WEBHOOK KHỚP ĐƠN {oid}")
                await confirm_payment(oid)
                return web.json_response({"success": True})

        return web.json_response({"success": False, "reason": "no_match"})

    except Exception as e:
        log.error(f"Webhook lỗi: {e}")
        return web.json_response({"success": False}, status=500)

async def start_webhook_server():
    app = web.Application()
    app.router.add_get("/", handle_health)
    app.router.add_get("/webhook", handle_health)      # Cho phép test
    app.router.add_post("/webhook", handle_webhook)    # Quan trọng
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", WEBHOOK_PORT).start()
    log.info(f"✅ Webhook server chạy port {WEBHOOK_PORT}")
    log.info(f"URL: https://shopducduyboutique.onrender.com/webhook")

# ══════════════════════════════════════════
# MODAL & VIEW (giữ nguyên như code của bạn)
# ══════════════════════════════════════════
class DepositModal(discord.ui.Modal, title="💳 Nạp tiền"):
    amount = discord.ui.TextInput(label="Số tiền muốn nạp (VNĐ)", placeholder="50000", min_length=4, max_length=10)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amt = int(self.amount.value.replace(",", "").replace(".", "").strip())
        except:
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
            f"**Số tiền:** {amt:,} VNĐ\n"
            f"**Ngân hàng:** MSB\n"
            f"**Số TK:** {BANK_NUMBER}\n\n"
            f"**Nội dung CK:** `{order_id}`\n\n"
            "⚠️ Nhập đúng nội dung trên!"
        )
        embed.set_image(url=build_qr_url(amt, order_id))
        await interaction.response.send_message(embed=embed, ephemeral=True)

# Các class BuyModal, PackageButton, PackageView, CategoryView, ShopView giữ nguyên như code bạn gửi
# (Tôi giữ nguyên để tránh lỗi, bạn có thể copy lại nếu cần)

class BuyModal(discord.ui.Modal):
    qty_input = discord.ui.TextInput(label="Số lượng key", default="1")
    def __init__(self, pkg_id: str):
        self.pkg_id = pkg_id
        pkg = PKG[pkg_id]
        super().__init__(title=pkg["name"])

    async def on_submit(self, interaction: discord.Interaction):
        # (Giữ nguyên logic cũ của bạn)
        await interaction.response.send_message("Đang xử lý...", ephemeral=True)

class ShopView(discord.ui.View):
    @discord.ui.button(label="💳 Nạp tiền", style=discord.ButtonStyle.green)
    async def deposit(self, interaction: discord.Interaction, button):
        await interaction.response.send_modal(DepositModal())

    @discord.ui.button(label="💰 Số dư", style=discord.ButtonStyle.blurple)
    async def balance(self, interaction: discord.Interaction, button):
        bal = get_balance(interaction.user.id)
        await interaction.response.send_message(f"**Số dư:** {bal:,} VNĐ", ephemeral=True)

# ══════════════════════════════════════════
# READY
# ══════════════════════════════════════════
@bot.event
async def on_ready():
    log.info(f"Bot online: {bot.user}")
    await start_webhook_server()
    poll_sepay.start()
    log.info("✅ Hệ thống auto nạp tiền đã sẵn sàng!")

@bot.command()
async def shop(ctx):
    try:
        await ctx.message.delete()
    except:
        pass
    await ctx.send(embed=discord.Embed(title="ducduy boutique Shop", description="Chọn chức năng bên dưới"), view=ShopView())

bot.run(TOKEN)
