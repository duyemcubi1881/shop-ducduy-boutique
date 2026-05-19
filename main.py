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
    level=logging.DEBUG,  # Đổi thành DEBUG để log chi tiết
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

    log.info(f"🎉 TỰ ĐỘNG CỘNG TIỀN THÀNH CÔNG | Đơn {order_id} | +{amount:,}đ")

    try:
        user = await bot.fetch_user(uid)
        embed = discord.Embed(title="✅ Nạp tiền thành công!", color=0x2ECC71)
        embed.description = f"💵 **{amount:,} VNĐ**\n💰 Số dư: **{new_bal:,} VNĐ**"
        await user.send(embed=embed)
    except Exception as e:
        log.error(f"Không gửi DM: {e}")

# ================== POLLING DEBUG ==================
@tasks.loop(seconds=6)
async def poll_sepay():
    log.debug("🔄 Polling SePay đang chạy...")
    
    if not SEPAY_TOKEN:
        log.error("❌ SEPAY_TOKEN KHÔNG TỒN TẠI hoặc rỗng!")
        return

    pending = [oid for oid, o in orders.items() if not o.get("paid")]
    log.info(f"📊 Đang có {len(pending)} đơn chờ | SEPAY_TOKEN: {'Có' if SEPAY_TOKEN else 'Không'}")

    try:
        headers = {"Authorization": f"Bearer {SEPAY_TOKEN}"}
        async with aiohttp.ClientSession() as s:
            async with s.get(
                "https://my.sepay.vn/userapi/transactions/list",
                headers=headers,
                params={"limit": 30},
                timeout=10
            ) as r:
                log.info(f"📡 SePay Response Status: {r.status}")
                if r.status != 200:
                    text = await r.text()
                    log.error(f"SePay lỗi: {r.status} - {text[:300]}")
                    return
                
                data = await r.json()
                txns = data.get("transactions", [])
                log.info(f"📥 Nhận được {len(txns)} giao dịch gần đây")

                for txn in txns:
                    content = str(txn.get("transaction_content") or txn.get("content") or "").strip().upper()
                    amount = int(txn.get("amount_in") or 0)
                    log.debug(f"Giao dịch: {amount:,}đ | Nội dung: {content[:80]}")

                    for oid in pending:
                        if oid.upper() in content and amount >= orders[oid]["amount"]:
                            log.info(f"✅ KHỚP ĐƠN! {oid} | Số tiền {amount:,}đ")
                            await confirm_payment(oid)
                            pending.remove(oid)
                            return
    except Exception as e:
        log.error(f"❌ Poll SePay LỖI: {e}")

# ================== WEBHOOK DEBUG ==================
async def handle_webhook(request: web.Request):
    log.info(f"📥 Webhook nhận request - Method: {request.method} | Path: {request.path}")
    
    if request.method == "GET":
        return web.Response(text="Webhook is running!")

    try:
        body = await request.json()
        log.info(f"📦 Webhook body: {body}")
        
        content = str(body.get("transaction_content") or body.get("content") or "").strip().upper()
        amount = int(body.get("amount_in") or body.get("amount") or 0)
        
        log.info(f"🔍 Webhook parse → Amount: {amount:,}đ | Content: {content}")

        for oid, order in orders.items():
            if not order.get("paid") and oid.upper() in content and amount >= order["amount"]:
                log.info(f"🎉 WEBHOOK KHỚP → Cộng tiền đơn {oid}")
                await confirm_payment(oid)
                return web.json_response({"success": True})
                
    except Exception as e:
        log.error(f"Webhook parse lỗi: {e}")

    return web.json_response({"success": False})

async def start_webhook():
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="OK"))
    app.router.add_get("/webhook", handle_webhook)
    app.router.add_post("/webhook", handle_webhook)
    
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", WEBHOOK_PORT).start()
    log.info(f"✅ Webhook server khởi động thành công port {WEBHOOK_PORT}")

# ================== MODAL ==================
class DepositModal(discord.ui.Modal, title="💳 Nạp tiền"):
    amount = discord.ui.TextInput(label="Số tiền muốn nạp", placeholder="10000")

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amt = int(self.amount.value.replace(",", "").strip())
        except:
            return await interaction.response.send_message("❌ Số tiền không hợp lệ!", ephemeral=True)

        oid = make_order_id()
        orders[oid] = {"user_id": interaction.user.id, "amount": amt, "paid": False}
        
        log.info(f"📝 Tạo đơn nạp: {oid} - {amt:,}đ")

        embed = discord.Embed(title="💳 Thông tin chuyển khoản", color=0xE91E8C)
        embed.description = f"**Số tiền:** {amt:,} VNĐ\n**Nội dung CK:** `{oid}`"
        embed.set_image(url=build_qr_url(amt, oid))
        await interaction.response.send_message(embed=embed, ephemeral=True)

class ShopView(discord.ui.View):
    @discord.ui.button(label="💳 Nạp tiền", style=discord.ButtonStyle.green)
    async def nap(self, interaction: discord.Interaction, button):
        await interaction.response.send_modal(DepositModal())

    @discord.ui.button(label="💰 Số dư", style=discord.ButtonStyle.blurple)
    async def balance(self, interaction: discord.Interaction, button):
        await interaction.response.send_message(f"**Số dư:** {balances.get(interaction.user.id, 0):,} VNĐ", ephemeral=True)

# ================== READY ==================
@bot.event
async def on_ready():
    log.info(f"🤖 Bot online: {bot.user}")
    await start_webhook()
    poll_sepay.start()
    log.info("🚀 Hệ thống auto nạp đã khởi động đầy đủ debug!")

@bot.command()
async def shop(ctx):
    await ctx.send("**ducduy boutique - Shop Key**", view=ShopView())

@bot.command()
@commands.has_permissions(administrator=True)
async def doncho(ctx):
    pending = [(k, v) for k, v in orders.items() if not v.get("paid")]
    await ctx.send(f"**Đơn chờ:** {len(pending)}\n" + "\n".join([f"`{k}` → {v['amount']:,}đ" for k,v in pending]))

@bot.command()
@commands.has_permissions(administrator=True)
async def testpoll(ctx):
    await ctx.send("🔄 Đang test polling...")
    await poll_sepay()

bot.run(TOKEN)
