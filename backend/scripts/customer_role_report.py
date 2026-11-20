"""Decision 5 (customer identity) — READ-ONLY report. It never writes to the database.

New sign-ups can now choose "customer" (role=customer). Existing RED distributors are NOT converted: the owner decided that
existing members keep their established roles and financial history. This report only lists RED distributor accounts that
look like pure shoppers (no sponsor link, nobody they referred, no commission earned, no seller attribution), so the owner
can decide case by case, with the member's consent, whether a conversion is ever wanted.

Usage (point MONGO_URL / DB_NAME at the database to inspect; nothing is changed):
    python scripts/customer_role_report.py            # summary counts
    python scripts/customer_role_report.py --list     # also list the candidate accounts (masked mobile)
"""
import asyncio
import os
import sys

from motor.motor_asyncio import AsyncIOMotorClient


async def main(list_rows: bool) -> None:
    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]
    red = await db.users.find({"role": "distributor", "status": "red"}, {"_id": 0, "id": 1, "distributor_id": 1, "mobile": 1,
                                                                        "sponsor_user_id": 1, "created_at": 1}).to_list(None)
    candidates = []
    for u in red:
        if u.get("sponsor_user_id"):
            continue
        if await db.referral_relationships.find_one({"sponsor_id": u["id"]}, {"_id": 1}):
            continue
        if await db.commissions.find_one({"user_id": u["id"]}, {"_id": 1}):
            continue
        if await db.orders.find_one({"seller_user_id": u["id"]}, {"_id": 1}):
            continue
        candidates.append(u)
    print(f"RED distributors: {len(red)}; look like pure shoppers: {len(candidates)}; customers already: "
          f"{await db.users.count_documents({'role': 'customer'})}")
    print("No account was changed. Conversions, if ever wanted, need the owner's decision and the member's consent.")
    if list_rows:
        for u in candidates:
            m = str(u.get("mobile") or "")
            print(f"  {u.get('distributor_id')}  XXXXXX{m[-4:]}  since {str(u.get('created_at'))[:10]}")
    client.close()


if __name__ == "__main__":
    asyncio.run(main("--list" in sys.argv))
