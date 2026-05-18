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

TOKEN        = os.getenv("DISCORD_TOKEN")
BANK_NUMBER  = os.getenv("BANK_NUMBER")       # Số tài khoản ngân hàng
BANK_NAME    = os.getenv("BANK_NAME")         # Tên ngân hàng viết tắt, VD: "vietcombank"
SEPAY_TOKEN  = os.getenv("SEPAY_TOKEN", "")   # Token webhook từ SePay (tuỳ chọn)
API_BASE     = os.getenv("API_BASE", "https://aovduy.onrender.com")

# QUAN TRỌNG: Render tự động cấp cổng thông qua biến hệ thống 'PORT'. 
# Nếu không có (chạy ở máy cục bộ), code sẽ tự động dùng 'WEBHOOK_PORT' hoặc mặc định '10000'.
WEBHOOK_PORT = int(os.getenv("PORT", os.getenv("WEBHOOK_PORT", "10000")))

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bot")

# =========================
# BOT SETUP
# =========================
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

# =========================
# DATA (in-memory)
# =========================
balances: dict[int, int] = {}   # {user_id: số_dư_VND}
orders:   dict[str, dict] = {}  # {order_id: {...}}

# =========================
# DANH MỤC SẢN PHẨM
# =========================
PRODUCTS = {
    "legit_drag": {
        "label": "Legit Drag",
        "emoji": "🎯",
        "packages": [
            {"id": "ld_3h",  "name": "Key Legit Drag 3 Giờ",   "price": 3_000,   "duration": "3 giờ"},
            {"id": "ld_1d",  "name": "Key Legit Drag 1 Ngày",   "price": 10_000,  "duration": "1 ngày"},
            {"id": "ld_7d",  "name": "Key Legit Drag 7 Ngày",   "price": 50_000,  "duration": "7 ngày"},
            {"id": "ld_1m",  "name": "Key Legit Drag 1 Tháng",  "price": 120_000, "duration": "1 tháng"},
            {"id": "ld_1ob", "name": "Key Legit Drag 1 OB",     "price": 240_000, "duration": "1 OB"},
        ]
    },
    "aimbot_head": {
        "label": "Aimbot Head",
        "emoji": "🔫",
        "packages": [
            {"id": "ah_3h",  "name": "Key Aimbot Head 3 Giờ",   "price": 5_000,   "duration": "3 giờ"},
            {"id": "ah_1d",  "name": "Key Aimbot Head 1 Ngày",   "price": 15_000,  "duration": "1 ngày"},
            {"id": "ah_7d",  "name": "Key Aimbot Head 7 Ngày",   "price": 60_000,  "duration": "7 ngày"},
            {"id": "ah_1m",  "name": "Key Aimbot Head 1 Tháng",  "price": 240_000, "duration": "1 tháng"},
            {"id": "ah_1ob", "name": "Key Aimbot Head 1 OB",     "price": 450_000, "duration": "1 OB"},
        ]
    },
}

# Tra cứu nhanh package theo id
PACKAGE_LOOKUP: dict[str, dict] = {}
for _prod_key, _prod in PRODUCTS.items():
    for _pkg in _prod["packages"]:
        PACKAGE_LOOKUP[_pkg["id"]] = {**_pkg, "product_label": _prod["label"]}

# =========================
# HÀM TIỆN ÍCH
# =========================
def get_balance(user_id: int) -> int:
    return balances.get(user_id, 0)

def add_balance(user_id: int, amount: int) -> int:
    balances[user_id] = balances.get(user_id, 0) + amount
    return balances[user_id]

def deduct_balance(user_id: int, amount: int) -> bool:
    if balances.get(user_id, 0) < amount:
        return False
    balances[user_id] -= amount
    return True

def build_qr_url(amount: int, order_id: str) -> str:
    bank_n = BANK_NAME.upper() if BANK_NAME else "UNKNOWN"
    return (
        f"https://img.vietqr.io/image/"
        f"{bank_n}-{BANK_NUMBER}-compact2.png"
        f"?amount={amount}"
        f"&addInfo={order_id}"
        f"&accountName=SHOP%20KEY"
    )

async def fetch_key_from_api(package_id: str) -> str | None:
    try:
        async with aiohttp.ClientSession() as session:
            url = f"{API_BASE}/api/key"
            async with session.get(url, params={"package": package_id}, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("key") or data.get("data") or str(data)
                log.warning(f"API trả về {resp.status} cho package {package_id}")
    except Exception as e:
        log.error(f"Lỗi gọi API lấy key: {e}")
    return None

async def confirm_payment(order_id: str):
    order = orders.get(order_id)
    if not order or order.get("paid"):
        return

    order["paid"] = True
    user_id = order["user_id"]
    amount  = order["amount"]

    new_bal = add_balance(user_id, amount)

    try:
        user = await bot.fetch_user(user_id)
        embed = discord.Embed(title="✅ Nạp tiền thành công", color=0x00FF7F)
        embed.description = (
            f"💵 Số tiền nạp: **{amount:,} VNĐ**\n"
            f"💰 Số dư hiện tại: **{new_bal:,} VNĐ**\n"
            f"🧾 Mã đơn: `{order_id}`"
        )
        await user.send(embed=embed)
        log.info(f"Đã cộng {amount} VNĐ cho user {user_id}, đơn {order_id}")
    except Exception as e:
        log.error(f"Không thể DM user {user_id}: {e}")

# =========================
# POLLING TỰ ĐỘNG
# =========================
@tasks.loop(seconds=10)
async def poll_transactions():
    pending = [oid for oid, o in orders.items() if not o.get("paid")]
    if not pending:
        return

    try:
        headers = {}
        if SEPAY_TOKEN:
            headers["Authorization"] = f"Bearer {SEPAY_TOKEN}"

        async with aiohttp.ClientSession() as session:
            url = f"{API_BASE}/api/transactions/latest"   
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as resp:
                if resp.status != 200:
                    return
                data = await resp.json()
                txns = data if isinstance(data, list) else data.get("transactions", [])

        for txn in txns:
            content = str(txn.get("content", "") or txn.get("description", "")).upper()
            for oid in pending:
                if oid.upper() in content:
                    await confirm_payment(oid)
                    break
    except Exception as e:
        log.debug(f"poll_transactions lỗi: {e}")

# =========================
# WEBHOOK SERVER (MÁY CHỦ LIÊN KẾT)
# =========================
async def handle_webhook(request: web.Request) -> web.Response:
    try:
        body = await request.json()
        log.info(f"Webhook nhận: {json.dumps(body, ensure_ascii=False)[:200]}")

        content  = str(body.get("content", "") or body.get("description", "")).upper()
        amount   = int(body.get("transferAmount", 0) or body.get("amount", 0))

        for oid, order in orders.items():
            if order.get("paid"):
                continue
            if oid.upper() in content and amount >= order["amount"]:
                await confirm_payment(oid)
                return web.json_response({"status": "ok", "order": oid})

        return web.json_response({"status": "no_match"})
    except Exception as e:
        log.error(f"Webhook error: {e}")
        return web.json_response({"status": "error"}, status=400)

# =========================
# INTERFACES & MODALS
# =========================
class DepositModal(discord.ui.Modal, title="💳 Nạp tiền"):
    amount = discord.ui.TextInput(
        label="Nhập số tiền cần nạp (VNĐ)",
        placeholder="Ví dụ: 50000",
        min_length=4,
        max_length=10,
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amount = int(self.amount.value.replace(",", "").replace(".", "").strip())
        except ValueError:
            return await interaction.response.send_message("❌ Số tiền không hợp lệ.", ephemeral=True)

        if amount < 1_000:
            return await interaction.response.send_message("❌ Số tiền tối thiểu là **1.000 VNĐ**.", ephemeral=True)

        order_id = f"NAP{random.randint(10000, 99999)}"
        while order_id in orders:
            order_id = f"NAP{random.randint(10000, 99999)}"

        orders[order_id] = {
            "user_id": interaction.user.id,
            "amount": amount,
            "paid": False,
        }

        qr_url = build_qr_url(amount, order_id)

        embed = discord.Embed(title="💳 Thông tin chuyển khoản", color=0x00BFFF)
        bank_display = BANK_NAME.upper() if BANK_NAME else "CHƯA THIẾT LẬP"
        embed.description = (
            f"💰 Số tiền: **{amount:,} VNĐ**\n"
            f"🏦 Ngân hàng: **{bank_display}**\n"
            f"🔢 Số tài khoản: `{BANK_NUMBER}`\n"
            f"📝 Nội dung CK: **`{order_id}`** *(bắt buộc)*\n\n"
            f"📱 Quét mã QR bên dưới hoặc chuyển khoản thủ công.\n"
            f"✅ Bot sẽ **tự động cộng tiền** sau khi nhận được giao dịch."
        )
        embed.set_image(url=qr_url)
        embed.set_footer(text=f"Mã đơn: {order_id} • Hết hạn sau 15 phút")

        await interaction.response.send_message(embed=embed, ephemeral=True)

class BuyQuantityModal(discord.ui.Modal):
    quantity_input = discord.ui.TextInput(
        label="Số lượng key muốn mua",
        placeholder="Nhập số nguyên, ví dụ: 1",
        max_length=3,
        default="1",
    )

    def __init__(self, package_id: str):
        self.package_id = package_id
        pkg = PACKAGE_LOOKUP[package_id]
        super().__init__(title=f"🛒 Mua {pkg['name']}")

    async def on_submit(self, interaction: discord.Interaction):
        try:
            qty = int(self.quantity_input.value.strip())
            if qty < 1:
                raise ValueError
        except ValueError:
            return await interaction.response.send_message("❌ Số lượng không hợp lệ.", ephemeral=True)

        pkg     = PACKAGE_LOOKUP[self.package_id]
        total   = pkg["price"] * qty
        user_id = interaction.user.id
        balance = get_balance(user_id)

        if balance < total:
            shortage = total - balance
            return await interaction.response.send_message(
                f"❌ Số dư không đủ!\n"
                f"💰 Số dư: **{balance:,} VNĐ**\n"
                f"💸 Cần thêm: **{shortage:,} VNĐ**",
                ephemeral=True,
            )

        await interaction.response.defer(ephemeral=True)
        deduct_balance(user_id, total)

        keys_received = []
        failed = 0
        for _ in range(qty):
            key = await fetch_key_from_api(self.package_id)
            if key:
                keys_received.append(key)
            else:
                failed += 1

        if failed:
            refund = pkg["price"] * failed
            add_balance(user_id, refund)

        new_bal = get_balance(user_id)

        embed = discord.Embed(title=f"✅ Mua key thành công", color=0x00FF7F)
        embed.description = (
            f"🛒 Đã mua: **{len(keys_received)}x {pkg['name']}**\n"
            f"⏱ Thời gian sử dụng: **{pkg['duration']}**\n"
            f"💸 Đã trừ: **{pkg['price'] * len(keys_received):,} VNĐ**\n"
            f"💰 Số dư còn lại: **{new_bal:,} VNĐ**"
        )
        if failed:
            embed.add_field(name="⚠️ Lưu ý", value=f"{failed} key lấy thất bại — đã hoàn tiền.", inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

        if keys_received:
            try:
                user = await bot.fetch_user(user_id)
                dm_embed = discord.Embed(title="🔑 Key của bạn đây!", color=0xFFD700)
                key_list = "\n".join(f"`{k}`" for k in keys_received)
                dm_embed.description = (
                    f"🛒 Sản phẩm: **{pkg['name']}**\n"
                    f"⏱ Thời gian sử dụng: **{pkg['duration']}**\n\n"
                    f"**Key:**\n{key_list}\n\n"
                    f"📁 File & hướng dẫn sử dụng trong server\n"
                    f"🙏 Cảm ơn bạn đã sử dụng dịch vụ\n"
                    f"🌐 {API_BASE}"
                )
                dm_embed.set_footer(text="Không chia sẻ key với người khác!")
                await user.send(embed=dm_embed)
            except discord.Forbidden:
                await interaction.followup.send("⚠️ Không thể DM cho bạn. Vui lòng mở DM để nhận key.", ephemeral=True)
            except Exception as e:
                log.error(f"Lỗi gửi DM key: {e}")

class PackageSelectView(discord.ui.View):
    def __init__(self, product_key: str):
        super().__init__(timeout=120)
        prod = PRODUCTS[product_key]
        for pkg in prod["packages"]:
            self.add_item(PackageButton(pkg))

    @discord.ui.button(label="◀ Quay lại", style=discord.ButtonStyle.secondary, row=4)
    async def back_button(self, interaction: discord.Interaction, _button):
        await interaction.response.edit_message(embed=build_category_embed(), view=CategorySelectView())

class PackageButton(discord.ui.Button):
    def __init__(self, pkg: dict):
        super().__init__(
            label=f"{pkg['name']} — {pkg['price']:,}đ",
            style=discord.ButtonStyle.primary,
            custom_id=f"pkg_{pkg['id']}",
        )
        self.pkg_id = pkg["id"]

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(BuyQuantityModal(self.pkg_id))

class CategorySelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=120)

    @discord.ui.select(
        placeholder="🎮 Chọn sản phẩm...",
        options=[
            discord.SelectOption(label="Legit Drag", value="legit_drag", emoji="🎯", description="Key Legit Drag — từ 3.000đ"),
            discord.SelectOption(label="Aimbot Head", value="aimbot_head", emoji="🔫", description="Key Aimbot Head — từ 5.000đ"),
        ],
    )
    async def select_product(self, interaction: discord.Interaction, select: discord.ui.Select):
        product_key = select.values[0]
        await interaction.response.edit_message(embed=build_package_embed(product_key), view=PackageSelectView(product_key))

    @discord.ui.button(label="◀ Quay lại", style=discord.ButtonStyle.secondary)
    async def back_button(self, interaction: discord.Interaction, _button):
        await interaction.response.edit_message(embed=build_shop_embed(), view=ShopView())

class ShopView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="💳 Nạp tiền", style=discord.ButtonStyle.green, row=0)
    async def deposit_button(self, interaction: discord.Interaction, _button):
        await interaction.response.send_modal(DepositModal())

    @discord.ui.button(label="💰 Số dư", style=discord.ButtonStyle.blurple, row=0)
    async def balance_button(self, interaction: discord.Interaction, _button):
        bal = get_balance(interaction.user.id)
        embed = discord.Embed(title="💰 Số dư của bạn", description=f"**{bal:,} VNĐ**", color=0x5865F2)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="🛒 Mua Key", style=discord.ButtonStyle.red, row=0)
    async def shop_button(self, interaction: discord.Interaction, _button):
        embed = build_category_embed()
        await interaction.response.send_message(embed=embed, view=CategorySelectView(), ephemeral=True)

# =========================
# EMBED CREATORS
# =========================
def build_shop_embed() -> discord.Embed:
    embed = discord.Embed(title="🔥 SHOP KEY — AOV DUY", color=0x2F3136)
    embed.description = (
        "💳 **Nạp tiền** — VietQR tự động, cộng tiền tức thì\n"
        "🛒 **Mua Key** — Nhận key qua DM ngay lập tức\n"
        "💰 **Số dư** — Kiểm tra ví của bạn\n\n"
        f"🌐 `{API_BASE}`"
    )
    embed.set_footer(text="Chọn chức năng bên dưới ↓")
    return embed

def build_category_embed() -> discord.Embed:
    lines = []
    for pk, prod in PRODUCTS.items():
        lines.append(f"{prod['emoji']} **{prod['label']}**")
        for pkg in prod["packages"]:
            lines.append(f"  └ {pkg['name']} — **{pkg['price']:,}đ**")
    embed = discord.Embed(title="🛒 Danh mục sản phẩm", color=0xFFD700)
    embed.description = "\n".join(lines) + "\n\n*Chọn sản phẩm bên dưới ↓*"
    return embed

def build_package_embed(product_key: str) -> discord.Embed:
    prod = PRODUCTS[product_key]
    embed = discord.Embed(title=f"{prod['emoji']} {prod['label']} — Chọn gói", color=0x00BFFF)
    lines = [f"• **{pkg['name']}** — {pkg['price']:,}đ" for pkg in prod["packages"]]
    embed.description = "\n".join(lines) + "\n\n*Ấn nút bên dưới để mua ↓*"
    return embed

# =========================
# COMMANDS
# =========================
@bot.command()
async def shop(ctx: commands.Context):
    await ctx.send(embed=build_shop_embed(), view=ShopView())

@bot.command()
@commands.has_permissions(administrator=True)
async def xacnhan(ctx: commands.Context, order_id: str):
    order = orders.get(order_id.upper())
    if not order:
        return await ctx.send(f"❌ Không tìm thấy đơn `{order_id}`.", delete_after=10)
    if order.get("paid"):
        return await ctx.send(f"❌ Đơn `{order_id}` đã thanh toán rồi.", delete_after=10)
    await confirm_payment(order_id.upper())
    await ctx.send(f"✅ Đã xác nhận đơn `{order_id.upper()}`.", delete_after=10)

@bot.command()
@commands.has_permissions(administrator=True)
async def capnhapkey(ctx: commands.Context, user: discord.Member, amount: int):
    new_bal = add_balance(user.id, amount)
    await ctx.send(f"✅ Đã cộng **{amount:,} VNĐ** cho {user.mention}. Số dư: **{new_bal:,} VNĐ**")

@bot.command()
@commands.has_permissions(administrator=True)
async def doncho(ctx: commands.Context):
    pending = [(oid, o) for oid, o in orders.items() if not o.get("paid")]
    if not pending:
        return await ctx.send("✅ Không có đơn nào đang chờ.")
    lines = [f"`{oid}` — {o['amount']:,}đ — <@{o['user_id']}>" for oid, o in pending]
    embed = discord.Embed(title=f"⏳ Đơn chờ thanh toán ({len(pending)})", color=0xFFAA00)
    embed.description = "\n".join(lines[:20])
    await ctx.send(embed=embed)

# =========================
# READY EVENT
# =========================
@bot.event
async def on_ready():
    log.info(f"✅ Bot online: {bot.user} (ID: {bot.user.id})")
    if not poll_transactions.is_running():
        poll_transactions.start()

# =========================
# KHỞI CHẠY KHÔNG BỊ CHẶN (ASYNCHRONOUS RUN)
# =========================
async def main():
    # 1. Khởi động Webhook server cục bộ trước
    app = web.Application()
    app.router.add_post("/webhook", handle_webhook)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", WEBHOOK_PORT)
    await site.start()
    log.info(f"🚀 Webhook server đang lắng nghe tại cổng {WEBHOOK_PORT}")

    # 2. Khởi động Bot Discord đồng bộ trên cùng một vòng lặp sự kiện (Event Loop)
    async with bot:
        await bot.start(TOKEN)

if __name__ == "__main__":
    if not TOKEN:
        log.error("❌ LỖI CHÍ MẠNG: Thiếu DISCORD_TOKEN trong cấu hình biến môi trường!")
    else:
        # In kiểm tra độ dài Token thu được từ Render để bắt lỗi nhập trống/nhập thiếu
        log.info(f"⚙️ Đang đọc Token từ hệ thống... Độ dài chuỗi nhận được: {len(TOKEN)} ký tự.")
        try:
            asyncio.run(main())
        except KeyboardInterrupt:
            log.info("🤖 Bot đang tắt...")
