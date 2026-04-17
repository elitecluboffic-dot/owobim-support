import discord
from discord.ext import commands
from fastapi import FastAPI, Request, HTTPException, status, Header, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
import asyncio
import os
import traceback
from dotenv import load_dotenv
from sqlalchemy import func
from contextlib import asynccontextmanager

from models import SessionLocal, Donation

load_dotenv()

# ====================== SECRET KEY ======================
SAWERIA_SECRET_KEY = os.getenv("SAWERIA_SECRET_KEY")
if not SAWERIA_SECRET_KEY:
    print("⚠️ WARNING: SAWERIA_SECRET_KEY tidak ditemukan di .env!")
    print("   Webhook Saweria tidak akan terproteksi!")

# Dependency untuk verifikasi secret (Header + Query Param)
async def verify_saweria_secret(
    request: Request,
    x_secret_key: str = Header(None, alias="X-Secret-Key")
):
    if not SAWERIA_SECRET_KEY:
        return  # Mode development: skip proteksi

    secret = x_secret_key
    if not secret:
        secret = request.query_params.get("secret")

    if not secret or secret != SAWERIA_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid or missing secret key"
        )
    return secret


# ====================== LIFESPAN ======================
@asynccontextmanager
async def lifespan(app: FastAPI):
    token = os.getenv("DISCORD_TOKEN")
    if token:
        print("🔄 Menjalankan Discord Bot...")
        asyncio.create_task(bot.start(token))
    else:
        print("⚠️ DISCORD_TOKEN tidak ditemukan.")

    yield
    print("🛑 Server sedang shutdown...")


# ====================== FASTAPI ======================
app = FastAPI(title="OwoBim Support", lifespan=lifespan)


# ====================== DISCORD BOT ======================
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f"✅ Discord Bot {bot.user} online!")
    await bot.change_presence(activity=discord.Game(name="!support"))


@bot.command(name="support")
async def support(ctx):
    embed = discord.Embed(
        title="☕ Support OwoBim",
        description="**Support langsung melalui website**",
        color=0xff6b35,
        url="https://advance.kraxx.my.id"
    )
    embed.add_field(name="🔗 Link Utama", value="https://advance.kraxx.my.id", inline=False)
    embed.add_field(name="💸 Saweria", value="https://saweria.co/teamowo", inline=False)
    embed.set_footer(text="Terima kasih telah support OwoBim ❤️ • !support")
    await ctx.send(embed=embed)


# ====================== SAWERIA WEBHOOK - FINAL AUTO FIX ======================
@app.post("/saweria")
async def saweria_webhook(
    request: Request,
    _: str = Depends(verify_saweria_secret)
):
    try:
        data = await request.json()

        # LOG FULL PAYLOAD (INI YANG PALING PENTING)
        print("🔍 [SAWERIA WEBHOOK] Payload diterima:")
        print(data)

        # Parsing yang lebih aman & fleksibel
        saweria_id = data.get("id")

        nama = (
            data.get("donator_name") 
            or data.get("donator") 
            or data.get("username") 
            or "Anonymous"
        )

        # Handle nominal (bisa string atau number)
        amount_raw = data.get("amount_raw") or data.get("amount")
        if isinstance(amount_raw, str):
            nominal = int(float(str(amount_raw).replace(",", "")))
        else:
            nominal = int(amount_raw) if amount_raw is not None else 0

        pesan = data.get("message") or data.get("note") or ""

        if not saweria_id:
            raise ValueError("Missing 'id' in Saweria payload")
        if nominal <= 0:
            raise ValueError(f"Nominal tidak valid: {nominal}")

        db = SessionLocal()
        try:
            if db.query(Donation).filter(Donation.saweria_id == saweria_id).first():
                print(f"ℹ️ Donasi sudah ada: {saweria_id}")
                return JSONResponse({"status": "already_exists"}, status_code=200)

            donasi = Donation(
                saweria_id=saweria_id,
                nama=nama,
                nominal=nominal,
                pesan=pesan
            )
            db.add(donasi)
            db.commit()

            print(f"✅ DONASI OTOMATIS MASUK → {nama} | Rp {nominal:,} | Pesan: {pesan or '-'}")
            return JSONResponse({"status": "success"})

        finally:
            db.close()

    except Exception as e:
        print(f"❌ Webhook Error: {type(e).__name__} - {e}")
        traceback.print_exc()   # Tampilkan error lengkap
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=400)


# ====================== API FOR WEBSITE ======================
@app.get("/api/saweria")
async def get_donatur():
    db = SessionLocal()
    try:
        results = db.query(
            Donation.nama,
            func.sum(Donation.nominal).label("total_nominal"),
            func.max(Donation.pesan).label("last_pesan"),
            func.max(Donation.created_at).label("last_date")
        ).group_by(Donation.nama)\
         .order_by(func.sum(Donation.nominal).desc())\
         .all()

        donatur_list = [
            {
                "nama": row.nama,
                "nominal": int(row.total_nominal),
                "pesan": row.last_pesan,
                "createdAt": row.last_date.isoformat() if row.last_date else None
            }
            for row in results
        ]

        grand_total = sum(d["nominal"] for d in donatur_list)

        return {
            "list": donatur_list,
            "total_donasi": grand_total,
            "total_donatur": len(donatur_list)
        }
    finally:
        db.close()


# ====================== STATIC FILES ======================
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", response_class=HTMLResponse)
async def serve_index():
    try:
        with open("static/index.html", "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return HTMLResponse("<h1>index.html tidak ditemukan di folder static/</h1>")


# ====================== RUN ======================
if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    print(f"🚀 Server berjalan di http://0.0.0.0:{port}")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info"
    )
