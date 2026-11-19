import os
import re
import shutil
import tempfile

from flask import Flask, jsonify, request, send_file, send_from_directory, after_this_request
import yt_dlp

BASE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__)

ALLOWED = re.compile(
    r"^https?://([a-z0-9-]+\.)*(tiktok\.com|youtube\.com|youtu\.be)/", re.I
)
COOKIES = os.environ.get("COOKIES_FILE")  # اختياري: ملف كوكيز يوتيوب


def base_opts():
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True}
    if COOKIES and os.path.exists(COOKIES):
        opts["cookiefile"] = COOKIES
    return opts


def check_url(url):
    if not url or not ALLOWED.match(url.strip()):
        raise ValueError("الرابط غير مدعوم. استخدم رابط تيك توك أو يوتيوب فقط.")
    return url.strip()


@app.get("/")
def index():
    return send_from_directory(BASE, "index.html")


@app.get("/api/info")
def info():
    try:
        url = check_url(request.args.get("url"))
        with yt_dlp.YoutubeDL(base_opts()) as ydl:
            data = ydl.extract_info(url, download=False)
        return jsonify(
            title=data.get("title"),
            thumbnail=data.get("thumbnail"),
            duration=data.get("duration"),
            uploader=data.get("uploader"),
            platform=data.get("extractor_key"),
        )
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except Exception:
        return jsonify(error="تعذّر جلب الفيديو. تأكد من الرابط وحاول مرة أخرى."), 500


@app.get("/api/download")
def download():
    try:
        url = check_url(request.args.get("url"))
    except ValueError as e:
        return jsonify(error=str(e)), 400

    kind = request.args.get("type", "video")
    tmp = tempfile.mkdtemp()
    opts = base_opts()
    opts["outtmpl"] = os.path.join(tmp, "%(title).80s.%(ext)s")

    if kind == "audio":
        opts["format"] = "bestaudio[ext=m4a]/bestaudio"
    else:
        # تيك توك: yt-dlp يفضّل النسخة بدون علامة مائية تلقائياً
        # يوتيوب: صيغة mp4 مدمجة (فيديو+صوت) لا تحتاج ffmpeg
        opts["format"] = (
            "best[ext=mp4][format_note!*=watermark]/best[ext=mp4]/best"
        )

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            data = ydl.extract_info(url, download=True)
            path = ydl.prepare_filename(data)
        if not os.path.exists(path):
            files = os.listdir(tmp)
            path = os.path.join(tmp, files[0])
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        return jsonify(error="فشل التحميل. قد يكون الفيديو خاصاً أو محمياً."), 500

    @after_this_request
    def cleanup(resp):
        shutil.rmtree(tmp, ignore_errors=True)
        return resp

    return send_file(path, as_attachment=True, download_name=os.path.basename(path))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
