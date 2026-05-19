import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
from aiohttp import web
import aiohttp
import asyncio
import os
import random
import logging

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
BANK_NUMBER = os.getenv("BANK_NUMBER")
BANK_NAME = os.getenv("BANK_NAME", "msb")
SEPAY_TOKEN = os.getenv("SEPAY_TOKEN", "")
WEBHOOK_PORT = int(os.getenv("PORT", "10000"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger("shop")

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

balances: dict[int, int] = {}
orders: dict[str, dict] = {}

# ================== UTILS ==================
def make_order_id():
    while True:
        oid = f"NAP{random.randint(10000, 99999)}"
        if oid not in orders:
            return oid

def build_qr_url(amount, order_id):
    return f"https://img.vietqr.io/image/{BANK_NAME.lower()}-{BANK_NUMBER}-compact2.png?amount={amount}&addInfo={order_id}&accountName=DUCDUY%20BOUTIQUE"

async def confirm_payment(order_id: str):
    order = orders.get(order_id)
    if not order or order.get("paid"):
        return
    order["paid"] = True
    uid = order["user_id"]
    amount = order["amount"]
    new_bal = balances[uid] = balances.get(uid, 0) + amount

    log.info(f"🎉 TỰ ĐỘNG CỘNG TIỀN | Đơn {order_id} | +{amount:,}đ")

    try:
        user = await bot.fetch_user(uid)
        embed = discord.Embed(title="✅ Nạp tiền thành công!", color=0x2ECC71)
        embed.description = f"💵 **{amount:,} VNĐ**\n💰 Số dư: **{new_bal:,} VNĐ**"
        await user.send(embed=embed)
    except:
        pass

# ================== POLLING (ĐÃ FIX LỖI AMOUNT) ==================
@tasks.loop(seconds=7)
async def poll_sepay():
    if not SEPAY_TOKEN:
        log.error("❌ SEPAY_TOKEN rỗng!")
        return

    pending = [oid for oid, o in orders.items() if not o.get("paid")]
    log.info(f"📊 Đang có {len(pending)} đơn chờ")

    try:
        headers = {"Authorization": f"Bearer {SEPAY_TOKEN}"}
        async with aiohttp.ClientSession() as s:
            async with s.get(
                "https://my.sepay.vn/userapi/transactions/list",
                headers=headers,
                params={"limit": 30},
                timeout=10
            ) as r:
                if r.status != 200:
                    return
                data = await r.json()
                txns = data.get("transactions", [])

        log.info(f"📥 Nhận được {len(txns)} giao dịch")

        for txn in txns:
            # === FIX LỖI Ở ĐÂY ===
            raw_amount = str(txn.get("amount_in") or txn.get("amount") or "0")
            try:
                amount = int(float(raw_amount))
            except:
                continue

            content = str(txn.get("transaction_content") or "").strip().upper()

            for oid in list(pending):
                order = orders.get(oid)
                if not order or order.get("paid"):
                    continue
                if oid.upper() in content and amount >= order["amount"]:
                    log.info(f"✅ KHỚP ĐƠN! {oid} | {amount:,}đ")
                    await confirm_payment(oid)
                    pending.remove(oid)
                    break
    except Exception as e:
        log.error(f"Poll lỗi: {e}")

# ================== WEBHOOK ==================
async def handle_webhook(request: web.Request):
    if request.method == "GET":
        return web.Response(text="Webhook OK")

    try:
        body = await request.json()
        raw_amount = str(body.get("amount_in") or body.get("amount") or "0")
        amount = int(float(raw_amount))
        content = str(body.get("transaction_content") or "").strip().upper()

        log.info(f"📥 Webhook: {amount:,}đ | {content[:100]}")

        for oid, order in orders.items():
            if not order.get("paid") and oid.upper() in content and amount >= order["amount"]:
                log.info(f"✅ WEBHOOK KHỚP {oid}")
                await confirm_payment(oid)
                return web.json_response({"success": True})
    except Exception as e:
        log.error(f"Webhook lỗi: {e}")

    return web.json_response({"success": False})

async def start_webhook():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="OK"))
    app.router.add_get("/webhook", handle_webhook)
    app.router.add_post("/webhook", handle_webhook)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", WEBHOOK_PORT).start()
    log.info(f"✅ Webhook chạy port {WEBHOOK_PORT}")

# ================== MODAL NẠP ==================
class DepositModal(discord.ui.Modal, title="💳 Nạp tiền"):
    amount = discord.ui.TextInput(label="Số tiền muốn nạp", placeholder="10000")

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amt = int(self.amount.value.replace(",", "").strip())
        except:
            return await interaction.response.send_message("❌ Số tiền không hợp lệ!", ephemeral=True)

        oid = make_order_id()
        orders[oid] = {"user_id": interaction.user.id, "amount": amt, "paid": False}
        log.info(f"📝 Tạo đơn: {oid} - {amt:,} VNĐ")

        embed = discord.Embed(title="💳 Thông tin chuyển khoản", color=0xE91E8C)
        embed.description = f"**Số tiền:** {amt:,} VNĐ\n**Nội dung:** `{oid}`"
        embed.set_image(url=build_qr_url(amt, oid))
        await interaction.response.send_message(embed=embed, ephemeral=True)

class ShopView(discord.ui.View):
    @discord.ui.button(label="💳 Nạp tiền", style=discord.ButtonStyle.green)
    async def nap(self, i: discord.Interaction, b):
        await i.response.send_modal(DepositModal())

    @discord.ui.button(label="💰 Số dư", style=discord.ButtonStyle.blurple)
    async def balance(self, i: discord.Interaction, b):
        await i.response.send_message(f"**Số dư:** {balances.get(i.user.id, 0):,} VNĐ", ephemeral=True)

# ================== READY ==================
@bot.event
async def on_ready():
    log.info(f"Bot online: {bot.user}")
    await start_webhook()
    poll_sepay.start()
    log.info("🚀 Hệ thống auto nạp đã sẵn sàng!")

@bot.command()
async def shop(ctx):
    await ctx.send("**ducduy boutique**", view=ShopView())

@bot.command()
@commands.has_permissions(administrator=True)
async def doncho(ctx):
    pending = [(k, v) for k, v in orders.items() if not v.get("paid")]
    await ctx.send(f"**Đơn chờ:** {len(pending)}\n" + "\n".join(f"`{k}` → {v['amount']:,}đ" for k, v in pending))

bot.run(TOKEN)
