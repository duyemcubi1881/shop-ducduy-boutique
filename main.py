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
            # Login
            login_resp = await s.post(
                f"{API_BASE}/api/login",
                json={"username": API_ADMIN_USER, "password": API_ADMIN_PASS},
                timeout=aiohttp.ClientTimeout(total=10),
            )
            if login_resp.status != 200:
                return None

            # Tạo key
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

    log.info(f"✅ XÁC NHẬN ĐƠN {order_id} | +{amount:,}đ | User {uid} | Số dư: {bal:,}đ")

    try:
        user = await bot.fetch_user(uid)
        embed = discord.Embed(title="✅ Nạp tiền thành công!", color=0x2ECC71)
        embed.description = (
            f"💵 Số tiền: **{amount:,} VNĐ**\n"
            f"💰 Số dư hiện tại: **{bal:,} VNĐ**\n"
            f"🧾 Mã đơn: `{order_id}`\n\n"
            f"👉 Dùng lệnh `!shop` để mua key ngay!"
        )
        embed.set_footer(text="ducduy boutique")
        await user.send(embed=embed)
    except Exception as e:
        log.warning(f"Không gửi DM user {uid}: {e}")

# ══════════════════════════════════════════
# POLLING SEPAY (ĐÃ TỐI ƯU)
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

        log.info(f"🔄 Polling: {len(txns)} giao dịch | {len(pending)} đơn chờ")

        for txn in txns:
            content = str(txn.get("transaction_content") or txn.get("content") or "").strip().upper()
            amount = int(txn.get("amount_in") or txn.get("transferAmount") or 0)

            for oid in list(pending):
                order = orders.get(oid)
                if not order or order.get("paid"):
                    continue
                if oid.upper() in content and amount >= order["amount"]:
                    log.info(f"✅ POLLING KHỚP: {oid} | {amount:,}đ")
                    await confirm_payment(oid)
                    pending.remove(oid)
                    break
    except Exception as e:
        log.debug(f"poll_sepay error: {e}")

# ══════════════════════════════════════════
# DỌN ĐƠN CŨ
# ══════════════════════════════════════════
@tasks.loop(minutes=30)
async def clean_old_orders():
    now = asyncio.get_event_loop().time()
    to_remove = [oid for oid, o in orders.items() if not o.get("paid") and now - o.get("created_at", 0) > 1800]
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

        log.info(f"📥 Webhook: {amount:,}đ | {content[:100]}")

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
    log.info(f"Webhook server chạy port {WEBHOOK_PORT}")

# ══════════════════════════════════════════
# MODAL NẠP TIỀN
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
            "```\n"
            f"💰 Số tiền : {amt:,} VNĐ\n"
            f"🏦 Ngân hàng: MSB\n"
            f"🔢 Số TK   : {BANK_NUMBER}\n"
            "```\n"
            f"📝 **Nội dung CK:** `{order_id}`\n"
            "⚠️ **Nhập đúng nội dung, không thêm bớt!**\n\n"
            "✅ Bot sẽ tự động cộng tiền sau khi nhận giao dịch."
        )
        embed.set_image(url=build_qr_url(amt, order_id))
        embed.set_footer(text=f"Mã đơn: {order_id} • Hết hạn sau 30 phút")
        await interaction.response.send_message(embed=embed, ephemeral=True)

# (Các class Modal, View, Embed còn lại giữ nguyên như code cũ của bạn)

# ══════════════════════════════════════════
# Các phần View, Modal Mua Key, Embed... (giữ nguyên)
# Tôi rút gọn để code không quá dài, bạn copy phần này từ code cũ của bạn
# Nếu cần tôi sẽ paste đầy đủ, nhưng để ngắn gọn tôi giữ nguyên như cũ.

# ══════════════════════════════════════════
# LENH BOT
# ══════════════════════════════════════════
@bot.command()
async def shop(ctx: commands.Context):
    try:
        await ctx.message.delete()
    except:
        pass
    await ctx.send(embed=embed_shop(), view=ShopView())

# Các lệnh admin khác giữ nguyên...

# ══════════════════════════════════════════
# READY
# ══════════════════════════════════════════
_webhook_started = False

@bot.event
async def on_ready():
    global _webhook_started
    log.info(f"Bot online: {bot.user}")

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

    log.info("Auto nạp tiền đã sẵn sàng!")

# ══════════════════════════════════════════
# RUN
# ══════════════════════════════════════════
bot.run(TOKEN)
