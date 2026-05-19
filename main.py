import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
from aiohttp import web
import aiohttp
import os
import random
import logging

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
BANK_NUMBER = os.getenv("BANK_NUMBER")
BANK_NAME = os.getenv("BANK_NAME", "msb")
SEPAY_TOKEN = os.getenv("SEPAY_TOKEN", "")
WEBHOOK_PORT = int(os.getenv("PORT", "10000"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("shop")

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

balances: dict[int, int] = {}
orders: dict[str, dict] = {}

def make_order_id():
    while True:
        oid = f"NAP{random.randint(10000, 99999)}"
        if oid not in orders: return oid

def build_qr_url(amount: int, order_id: str) -> str:
    return (
        f"https://img.vietqr.io/image/{BANK_NAME.lower()}-{BANK_NUMBER}-compact2.png"
        f"?amount={amount}&addInfo={order_id}&accountName=NGO%20DUC%20DUY"
    )

async def confirm_payment(order_id: str):
    order = orders.get(order_id)
    if not order or order.get("paid"): return
    order["paid"] = True
    uid = order["user_id"]
    amount = order["amount"]
    new_bal = balances[uid] = balances.get(uid, 0) + amount

    log.info(f"🎉 THÀNH CÔNG | Cộng {amount:,}đ | Đơn {order_id}")

    try:
        user = await bot.fetch_user(uid)
        embed = discord.Embed(title="✅ Nạp tiền thành công!", color=0x2ECC71)
        embed.description = f"💵 Số tiền: **{amount:,} VNĐ**\n💰 Số dư: **{new_bal:,} VNĐ**"
        await user.send(embed=embed)
    except:
        pass

# ================== POLLING - MATCHING THÔNG MINH ==================
@tasks.loop(seconds=5)
async def poll_sepay():
    pending = {oid: data for oid, data in orders.items() if not data.get("paid")}
    if not pending:
        return

    log.info(f"📊 Đơn chờ: {len(pending)}")

    try:
        headers = {"Authorization": f"Bearer {SEPAY_TOKEN}"}
        async with aiohttp.ClientSession() as s:
            async with s.get(
                "https://my.sepay.vn/userapi/transactions/list",
                headers=headers, params={"limit": 30}, timeout=10
            ) as r:
                if r.status != 200: return
                data = await r.json()
                txns = data.get("transactions", [])

        for txn in txns:
            raw_amount = str(txn.get("amount_in") or 0)
            try:
                amount = int(float(raw_amount))
            except:
                continue

            content = str(txn.get("transaction_content") or "").strip()
            log.info(f"🔍 Giao dịch: {amount:,}đ | Nội dung: '{content}'")

            # 1. Khớp theo mã đơn
            for oid, order in list(pending.items()):
                if oid.upper() in content.upper() and amount >= order["amount"]:
                    log.info(f"🎯 KHỚP THEO MÃ ĐƠN {oid}")
                    await confirm_payment(oid)
                    del pending[oid]
                    break
            else:
                # 2. Khớp theo số tiền (nếu chỉ có 1 đơn chờ với số tiền đó)
                matching_orders = [ (oid, o) for oid, o in pending.items() if o["amount"] == amount ]
                if len(matching_orders) == 1:
                    oid, order = matching_orders[0]
                    log.info(f"🎯 KHỚP THEO SỐ TIỀN {amount:,}đ → Đơn {oid}")
                    await confirm_payment(oid)
                    del pending[oid]
    except Exception as e:
        log.error(f"Poll lỗi: {e}")

# ================== MODAL ==================
class DepositModal(discord.ui.Modal, title="💳 Nạp tiền"):
    amount = discord.ui.TextInput(label="Số tiền", placeholder="10000")

    async def on_submit(self, interaction: discord.Interaction):
        try:
            amt = int(self.amount.value.replace(",", "").strip())
        except:
            return await interaction.response.send_message("❌ Số tiền không hợp lệ!", ephemeral=True)

        oid = make_order_id()
        orders[oid] = {"user_id": interaction.user.id, "amount": amt, "paid": False}

        embed = discord.Embed(title="💳 Thông tin chuyển khoản", color=0xE91E8C)
        embed.description = (
            f"**Số tiền:** {amt:,} VNĐ\n"
            f"**Mã đơn:** `{oid}`\n\n"
            "✅ Chuyển đúng số tiền là được (hệ thống sẽ tự động nhận)"
        )
        embed.set_image(url=build_qr_url(amt, oid))
        await interaction.response.send_message(embed=embed, ephemeral=True)

class ShopView(discord.ui.View):
    @discord.ui.button(label="💳 Nạp tiền", style=discord.ButtonStyle.green)
    async def nap(self, i: discord.Interaction, b):
        await i.response.send_modal(DepositModal())

    @discord.ui.button(label="💰 Số dư", style=discord.ButtonStyle.blurple)
    async def balance(self, i: discord.Interaction, b):
        await i.response.send_message(f"**Số dư:** {balances.get(i.user.id, 0):,} VNĐ", ephemeral=True)

@bot.event
async def on_ready():
    log.info(f"Bot online: {bot.user}")
    poll_sepay.start()
    log.info("🚀 Auto nạp đang chạy (match theo mã + theo tiền)")

@bot.command()
async def shop(ctx):
    await ctx.send("**ducduy boutique**", view=ShopView())

@bot.command()
@commands.has_permissions(administrator=True)
async def doncho(ctx):
    pending = [(k,v) for k,v in orders.items() if not v.get("paid")]
    await ctx.send(f"**Đơn chờ:** {len(pending)}\n" + "\n".join(f"`{k}` → {v['amount']:,}đ" for k,v in pending))

bot.run(TOKEN)
