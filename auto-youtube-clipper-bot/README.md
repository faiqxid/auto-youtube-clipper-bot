# Auto YouTube Clipper Bot (Telegram)

Bot Telegram untuk menerima link YouTube, menganalisis momen terbaik, memotong jadi short video 9:16, menambahkan subtitle otomatis + watermark opsional, lalu mengirim hasil clip ke Telegram.

## Fitur Utama

- Terima link YouTube dari Telegram
- Download video via `yt-dlp`
- Transkrip detail (timestamp) via `WhisperX`
- Analisis momen viral via `Gemini API`
- Scoring + anti-overlap clip
- Render clip 9:16 via `FFmpeg`
- Auto-crop fokus wajah/gerakan via `OpenCV`
- Subtitle otomatis (opsional)
- Watermark fleksibel dari input Telegram (teks, posisi, opacity, font)
- Caption bahasa Indonesia + hashtag
- Logging lengkap per tahap proses
- Cleanup file temporary
- Siap jalan 24/7 di VPS

## Teknologi

- Python
- Telegram Bot API (`python-telegram-bot`)
- `yt-dlp`
- WhisperX
- Gemini API (`google-generativeai`)
- FFmpeg / FFprobe
- OpenCV

## Struktur Proyek

```text
auto-youtube-clipper-bot/
├── bot.py
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
├── config/
│   └── settings.py
├── app/
│   ├── telegram_bot.py
│   ├── downloader.py
│   ├── transcriber.py
│   ├── analyzer.py
│   ├── clipper.py
│   ├── cropper.py
│   ├── subtitle.py
│   ├── watermark.py
│   ├── caption.py
│   ├── scoring.py
│   └── utils.py
├── temp/
├── outputs/
└── logs/
```

## Instalasi Lokal

1. Clone project lalu masuk folder:

```bash
cd auto-youtube-clipper-bot
```

2. Buat virtual env:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

3. Install dependency Python:

```bash
pip install -r requirements.txt
```

4. Install FFmpeg:

```bash
sudo apt update
sudo apt install -y ffmpeg
```

5. Copy env:

```bash
cp .env.example .env
```

6. Isi `.env`:

- `TELEGRAM_BOT_TOKEN`
- `GEMINI_API_KEYS_FILE` (direkomendasikan untuk multi key)
- `GEMINI_API_KEY` (opsional fallback 1 key)
- konfigurasi lain sesuai kebutuhan

7. (Opsional tapi direkomendasikan) buat file key pool:

```bash
cp config/gemini_api_keys.example.txt config/gemini_api_keys.txt
```

Isi dengan 1 key per baris. Bot akan auto failover ke key berikutnya jika key aktif error/rate-limit.

8. Jalankan bot:

```bash
python3 bot.py
```

## Deployment VPS Ubuntu

### 1) Install dependency sistem

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip ffmpeg git libgl1 libglib2.0-0
```

### 2) Setup project

```bash
git clone <repo-url> auto-youtube-clipper-bot
cd auto-youtube-clipper-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### 3) Jalankan manual

```bash
source .venv/bin/activate
python3 bot.py
```

## Menjalankan 24/7 dengan PM2

Install PM2:

```bash
sudo npm i -g pm2
```

Start bot:

```bash
pm2 start bot.py --name youtube-clipper-bot --interpreter python3
pm2 save
pm2 startup
```

Monitoring:

```bash
pm2 logs youtube-clipper-bot
pm2 restart youtube-clipper-bot
pm2 stop youtube-clipper-bot
```

## Menjalankan 24/7 dengan systemd

Buat file service:

`/etc/systemd/system/youtube-clipper-bot.service`

```ini
[Unit]
Description=Auto YouTube Clipper Telegram Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/auto-youtube-clipper-bot
ExecStart=/home/ubuntu/auto-youtube-clipper-bot/.venv/bin/python /home/ubuntu/auto-youtube-clipper-bot/bot.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

Enable service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable youtube-clipper-bot
sudo systemctl start youtube-clipper-bot
```

Log service:

```bash
sudo systemctl status youtube-clipper-bot
journalctl -u youtube-clipper-bot -f
```

Restart/Stop:

```bash
sudo systemctl restart youtube-clipper-bot
sudo systemctl stop youtube-clipper-bot
```

## Alur Telegram Singkat

1. `/start`
2. Kirim link YouTube
3. Atur:
- jumlah clip
- durasi clip
- subtitle on/off
- watermark on/off + detail watermark
- kualitas output
4. Bot proses otomatis dan kirim hasil clip + detail score/reason/caption/hashtag

## Logging

Log disimpan ke folder `logs/`:

- proses download
- transkrip
- analisis Gemini
- render FFmpeg
- error
- user Telegram ID

## Skalabilitas Multi User

- Implementasi ini sudah punya limiter `MAX_CONCURRENT_JOBS` agar VPS tidak overload.
- Saat server sibuk, request baru akan masuk antrian.
- Untuk trafik besar, tetap disarankan tambah worker queue (Redis + Celery/RQ) agar lebih stabil.

## Update Setelah Pull

```bash
git pull
source .venv/bin/activate
pip install -r requirements.txt
pm2 restart youtube-clipper-bot
```

Jika pakai systemd:

```bash
sudo systemctl restart youtube-clipper-bot
```

## Troubleshooting

- `Konfigurasi wajib belum diisi`: pastikan `TELEGRAM_BOT_TOKEN` terisi dan minimal ada 1 key di `config/gemini_api_keys.txt` atau `GEMINI_API_KEY`.
- `ffmpeg not found`: install ffmpeg di VPS.
- `WhisperX error`: cek kompatibilitas `torch`, memory, dan model.
- `Video terlalu panjang`: naikkan `MAX_VIDEO_DURATION_MINUTES` bila diperlukan.
- `File terlalu besar`: turunkan quality atau durasi clip.
- proses lama/crash: cek log `logs/bot.log` dan ruang disk VPS.
- `Semua Gemini API key gagal`: cek quota/key invalid, lalu tambah key baru di file key pool.

## Keamanan API Key

- Jangan hardcode secret di source code
- Simpan key di `.env` atau `config/gemini_api_keys.txt`
- `.env` sudah masuk `.gitignore`
- `config/gemini_api_keys.txt` sudah masuk `.gitignore`
- Jangan upload `.env` ke GitHub
- Jangan upload file key pool ke GitHub
- Gunakan `.env.example` sebagai template konfigurasi

## Catatan Implementasi Awal

Versi ini adalah implementasi awal produksi-minimum yang sudah end-to-end. Untuk peningkatan kualitas lanjutan, disarankan:

- queue worker (Celery/RQ) agar load multi-user lebih stabil
- penyimpanan status job di Redis/DB
- retry policy granular untuk Gemini/yt-dlp/ffmpeg
- model alignment subtitle lebih halus per kata
- OCR/logo-aware safe area untuk subtitle dan watermark
