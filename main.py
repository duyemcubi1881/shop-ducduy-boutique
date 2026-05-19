"""
Chạy: python debug_sepay.py
Mục đích: In toàn bộ field của giao dịch SePay để tìm field chứa nội dung CK
"""
import asyncio
import aiohttp
import json
import os
from dotenv import load_dotenv

load_dotenv()
SEPAY_TOKEN = os.getenv("SEPAY_TOKEN", "")

async def main():
    if not SEPAY_TOKEN:
        print("❌ SEPAY_TOKEN chưa cấu hình trong .env")
        return

    headers = {"Authorization": f"Bearer {SEPAY_TOKEN}"}
    async with aiohttp.ClientSession() as s:
        async with s.get(
            "https://my.sepay.vn/userapi/transactions/list",
            headers=headers,
            params={"limit": 5},
            timeout=aiohttp.ClientTimeout(total=8),
        ) as r:
            data = await r.json()
            txns = data.get("transactions", [])
            print(f"\n✅ Nhận được {len(txns)} giao dịch\n")
            print("=" * 60)
            for i, txn in enumerate(txns):
                print(f"\n📦 GIAO DỊCH [{i}]")
                print("-" * 40)
                # In toàn bộ field
                for key, value in txn.items():
                    print(f"  {key:35s} = {value}")
            print("\n" + "=" * 60)
            print("\n👆 Tìm field nào chứa mã NAPxxxxx trong nội dung CK")

asyncio.run(main())
