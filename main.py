import discord
from discord.ext import commands
from fastapi import FastAPI, Request, HTTPException, status, Header
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
import asyncio
import os
from dotenv import load_dotenv
from sqlalchemy import func
from contextlib import asynccontextmanager

from models import SessionLocal, Donation

load_dotenv()

# ====================== SECRET KEY ======================
SAWERIA_SECRET_KEY = os.getenv("SAWERIA_SECRET_KEY")

if not SAWERIA_SECRET_KEY:
    print("⚠️  WARNING: SAWERIA_SECRET_KEY tidak ditemukan di .env!")
    print("    Webhook Saweria tidak akan terproteksi!")

# Dependency untuk verifikasi secret (Header)
async def verify_saweria_secret(
    x_secret_key: str = Header(None, alias="X-Secret-Key")
):
    if not SAWERIA_SECRET_KEY:
        return  # Jika secret belum di-set, skip pengecekan (mode development)
    
    if not x_secret_key or x_secret_key != SAWERIA_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid or missing X-Secret-Key"
        )
    return x_secret_key


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


# ====================== SAWERIA WEBHOOK (DIPROTEKSI) ======================
@app.post("/saweria")
async def saweria_webhook(
    request: Request,
    x_secret_key: str = Header(None, alias="X-Secret-Key")   # Header wajib
):
    # Cek secret key
    if SAWERIA_SECRET_KEY and (not x_secret_key or x_secret_key != SAWERIA_SECRET_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid or missing X-Secret-Key"
        )

    try:
        data = await request.json()
        nama = data.get("donator_name", "Anonymous")
        nominal = int(data.get("amount_raw", 0))
        pesan = data.get("message")
        saweria_id = data.get("id")

        db = SessionLocal()
        try:
            if db.query(Donation).filter(Donation.saweria_id == saweria_id).first():
                return JSONResponse({"status": "already_exists"}, status_code=200)

            donasi = Donation(
                saweria_id=saweria_id,
                nama=nama,
                nominal=nominal,
                pesan=pesan
            )
            db.add(donasi)
            db.commit()

            print(f"✅ Donasi masuk: {nama} - Rp {nominal:,}")
            return JSONResponse({"status": "success"})
        finally:
            db.close()

    except Exception as e:
        print(f"❌ Webhook error: {e}")
        return JSONResponse({"status": "error"}, status_code=400)


# ====================== API FOR WEBSITE (Tetap Terbuka) ======================
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


# ====================== SERVE STATIC FILES ======================
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
    print(f"🚀 Server berjalan di port {port}")

    uvicorn.run(
        app, 
        host="0.0.0.0", 
        port=port,
        log_level="info"
    )
