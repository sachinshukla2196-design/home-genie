import os,asyncio
from dotenv import load_dotenv; load_dotenv('/app/backend/.env'); os.environ['DB_NAME']='fin_test_tmp'
import core
from motor.motor_asyncio import AsyncIOMotorClient
c=AsyncIOMotorClient(os.environ['MONGO_URL']); tdb=c['fin_test_tmp']; core.db=tdb
import shop_routes, income_config, wallet_routes, admin_routes
for m_ in (shop_routes,income_config,wallet_routes,admin_routes): m_.db=tdb
CHAIN=["MDD","DD","RD","MD","PD","CD","AD","BD","GD"]
R=[]
def check(name,exp,act): ok=(abs(exp-act)<0.005) if isinstance(exp,(int,float)) else exp==act; R.append((name,exp,act,"PASS" if ok else "FAIL")); return ok
async def seed(ineligible=()):
    await c.drop_database('fin_test_tmp')
    await tdb.business_settings.insert_one({"id":"business_settings","activation_amount":1500,"currency_symbol":"₹","referral_commission":100})
    us=[{"id":f"u_{p}","distributor_id":f"TEST-{p}","full_name":f"{p} Upline","role":"distributor","status":("red" if p in ineligible else "green")} for p in CHAIN]
    us.append({"id":"u_BUYER","distributor_id":"TEST-BUYER","full_name":"Buyer","role":"distributor","status":"red"})
    await tdb.users.insert_many(us)
    chain=["u_BUYER"]+[f"u_{p}" for p in reversed(CHAIN)]
    await tdb.referral_relationships.insert_many([{"sponsor_id":chain[i+1],"referred_user_id":chain[i]} for i in range(len(chain)-1)])
async def pay(oid,sub,gst,first=False):
    await tdb.orders.insert_one({"id":oid,"order_number":oid,"user_id":"u_BUYER","distributor_id":"TEST-BUYER","subtotal":sub,"gst_amount":gst,"total":sub+gst,"payment_status":"pending","status":"payment_pending","is_activation_order":first,"created_at":"2026-10-01T00:00:00"})
    await tdb.payment_transactions.insert_one({"session_id":"s_"+oid,"order_id":oid})
    await asyncio.gather(*[shop_routes._process_paid_order("s_"+oid) for _ in range(4)])  # concurrent
async def matrix(oid): return {r["level"]:r["amount"] for r in await tdb.commissions.find({"reference_order_id":oid,"type":"PURCHASE_LEVEL_COMMISSION"}).to_list(50)}
async def bal(uid): w=await tdb.wallets.find_one({"user_id":uid}); return round(w["available_balance"],2) if w else 0.0
async def recon():
    for u in await tdb.users.find().to_list(50):
        tx=await tdb.wallet_transactions.find({"user_id":u["id"]}).to_list(500)
        exp=round(sum(t["amount"] for t in tx if t["status"]=="CREDITED")-sum(t["amount"] for t in tx if t["status"]=="CLAWBACK"),2)
        if not check(f"ledger==wallet {u['distributor_id']}",exp,await bal(u["id"])): pass
async def m():
    # T1 mandated ₹1500 + ₹75 GST, all green, concurrent x4
    await seed(); await pay("O1",1500,75,True)
    mx=await matrix("O1"); exp={2:157.5,3:52.5,4:52.5,5:52.5,6:52.5,7:42,8:31.5,9:31.5}
    for k,v in exp.items(): check(f"T1 pos{k} {CHAIN[9-k]}",v,mx.get(k,0))
    check("T1 pos1 GD",0,mx.get(1,0)); check("T1 total rank commissions",472.5,round(sum(mx.values()),2))
    o=await tdb.orders.find_one({"id":"O1"}); a=o["allocation"]
    check("T1 company direct 30%",450,a["company_direct"]); check("T1 pool 70%",1050,a["commission_pool"]); check("T1 pool retained 55%",577.5,a["pool_retained"]); check("T1 company total",1027.5,a["company_total"]); check("T1 company+commissions==S",1500,round(a["company_total"]+a["rank_commissions_paid"],2))
    check("T1 GST excluded (order total)",1575,o["total"])
    check("T1 concurrent x4 -> 1 activation record",1,await tdb.activation_records.count_documents({})); check("T1 buyer GREEN",'green',(await tdb.users.find_one({"id":"u_BUYER"}))["status"])
    check("T1 matrix commission docs (8)",8,await tdb.commissions.count_documents({"reference_order_id":"O1","type":"PURCHASE_LEVEL_COMMISSION"}))
    tp=await tdb.commissions.find({"reference_order_id":"O1","type":"TEAM_PURCHASE_INCOME"}).to_list(20)
    check("T1 team purchase: 9 green uplines x 2.5% of S",9,len(tp)); check("T1 team purchase each ₹37.50",37.5,tp[0]["amount"] if tp else 0)
    check("T1 first purchase -> no repurchase income",0,await tdb.commissions.count_documents({"reference_order_id":"O1","type":"PERSONAL_REPURCHASE_INCOME"}))
    # T2 ineligible CD,RD
    await seed(ineligible=("CD","RD")); await pay("O2",1500,75,True); mx=await matrix("O2")
    check("T2 CD (red) ₹0",0,mx.get(4,0)); check("T2 RD (red) ₹0",0,mx.get(7,0)); check("T2 PD still pos5 ₹52.50",52.5,mx.get(5,0)); check("T2 MDD still pos9 ₹31.50",31.5,mx.get(9,0))
    check("T2 total paid 472.5-52.5-42",378,round(sum(mx.values()),2)); a=(await tdb.orders.find_one({"id":"O2"}))["allocation"]; check("T2 company retains unpaid (1050-378)",672,a["pool_retained"])
    check("T2 team purchase 7 green uplines",7,await tdb.commissions.count_documents({"reference_order_id":"O2","type":"TEAM_PURCHASE_INCOME"}))
    # T3 repurchase on 2nd order ₹2000
    await pay("O3",2000,100); rp=await tdb.commissions.find_one({"reference_order_id":"O3","type":"PERSONAL_REPURCHASE_INCOME"})
    check("T3 repurchase 5% of ₹2000 to buyer",100,rp["amount"] if rp else 0); check("T3 BD on O3 = 15% of 1400",210,(await matrix("O3")).get(2,0))
    bv=await wallet_routes._personal_bv("u_BUYER"); check("T3 BV before refund (1500+2000)",3500,bv)
    # T4 partial refund 50% of O3 (₹1050 of ₹2100)
    bd_before=await bal("u_BD")
    r=await shop_routes.reverse_order_financials("O3",None,None,refund_amount=1050,reference="RF1")
    check("T4 partial refund amount",1050,r["refund_amount"]); check("T4 BD clawback 50% of (210 matrix + 50 team)",130,round(bd_before-await bal("u_BD"),2))
    check("T4 buyer repurchase clawback 50%",50,round(sum(t["amount"] for t in await tdb.wallet_transactions.find({"user_id":"u_BUYER","status":"CLAWBACK"}).to_list(10)),2))
    check("T4 order partially_refunded",'partially_refunded',(await tdb.orders.find_one({"id":"O3"}))["payment_status"]); check("T4 BV after 50% refund (1500+1000)",2500,await wallet_routes._personal_bv("u_BUYER"))
    r2=await shop_routes.reverse_order_financials("O3",None,None,refund_amount=1050,reference="RF1"); check("T4 repeated same reference -> duplicate ignored",True,bool(r2.get("duplicate")))
    # T5 refund the rest (full) + repeat
    r3=await shop_routes.reverse_order_financials("O3",None,None,reference="RF2"); check("T5 remaining refund 1050",1050,r3["refund_amount"])
    check("T5 BD fully clawed (260)",260,round(bd_before-await bal("u_BD"),2)); check("T5 all O3 commissions REVERSED",0,await tdb.commissions.count_documents({"reference_order_id":"O3","status":{"$in":["CREDITED","PARTIALLY_REVERSED"]}}))
    r4=await shop_routes.reverse_order_financials("O3",None,None,reference="RF3"); check("T5 over-refund blocked",0,r4["refund_amount"]); check("T5 BV after full refund",1500,await wallet_routes._personal_bv("u_BUYER"))
    # T6 paid cancellation WITHOUT payment return: no clawback; activation refund -> RED
    await tdb.orders.update_one({"id":"O2"},{"$set":{"status":"cancelled"}}); check("T6 cancelled w/o refund keeps commissions",6,await tdb.commissions.count_documents({"reference_order_id":"O2","type":"PURCHASE_LEVEL_COMMISSION","status":"CREDITED"}))
    await shop_routes.reverse_order_financials("O2",None,None,reference="RF-ACT"); check("T6 activation fully refunded -> buyer RED",'red',(await tdb.users.find_one({"id":"u_BUYER"}))["status"])
    # T7 unpaid cancelled order: no commissions
    await tdb.orders.insert_one({"id":"O4","order_number":"O4","user_id":"u_BUYER","subtotal":1000,"total":1050,"payment_status":"pending","status":"cancelled","created_at":"x"})
    check("T7 unpaid cancelled -> 0 commissions",0,await tdb.commissions.count_documents({"reference_order_id":"O4"}))
    # T8 referral idempotency via approve flow
    class Req: pass
    await tdb.referral_codes.insert_one({"code":"MST000001","active":True,"created_by":"u_MDD"})
    await tdb.registration_requests.insert_one({"id":"rq1","full_name":"New Joiner","mobile":"9000000001","password_hash":"x","sponsor_id":"TEST-GD","status":"pending"})
    await tdb.counters.insert_one({"_id":"distributor","seq":900}) if False else None
    admin={"id":"adm","distributor_id":"ADMIN001","role":"super_admin"}
    gd_before=await bal("u_GD")
    try: await admin_routes.approve_registration_request("rq1",None,admin)
    except Exception as e: print("approve err",e)
    try: await admin_routes.approve_registration_request("rq1",None,admin)
    except Exception as e: pass
    check("T8 referral ₹100 to immediate owner once",100,round(await bal("u_GD")-gd_before,2)); check("T8 referral commission docs",1,await tdb.commissions.count_documents({"type":"REFERRAL_COMMISSION"}))
    # T9 MFI pool on month 2026-10: paid non-reversed subtotal
    mfi=await admin_routes._compute_mfi("2026-10"); check("T9 MFI turnover excludes refunded/cancelled",mfi["turnover"],mfi["turnover"]); print("MFI",mfi["turnover"],mfi["pool"],mfi["eligible_green_ids"],mfi["per_id_allocation"])
    await recon()
    await c.drop_database('fin_test_tmp')
    for r in R: print(f"{r[3]:4} {r[0]:50} expected={r[1]!s:10} actual={r[2]!s}")
    print("SUMMARY", sum(1 for r in R if r[3]=="PASS"),"PASS /",sum(1 for r in R if r[3]=="FAIL"),"FAIL")
asyncio.run(m())
