import os
import re
import shutil
import tempfile
import traceback

import requests
from flask import (Flask, jsonify, request, send_file, send_from_directory,
                   after_this_request, Response, stream_with_context)
import yt_dlp

BASE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__)

ALLOWED = re.compile(
    r"^https?://([a-z0-9-]+\.)*(tiktok\.com|youtube\.com|youtu\.be)/", re.I
)
TIKTOK = re.compile(r"^https?://([a-z0-9-]+\.)*tiktok\.com/", re.I)
COOKIES = os.environ.get("COOKIES_FILE")  # اختياري: ملف كوكيز يوتيوب
UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")


def log_error(where):
    print(f"[ERROR] {where}\n{traceback.format_exc()}", flush=True)


def base_opts():
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True,
            "http_headers": {"User-Agent": UA}}
    if COOKIES and os.path.exists(COOKIES):
        opts["cookiefile"] = COOKIES
    return opts


def check_url(url):
    if not url or not ALLOWED.match(url.strip()):
        raise ValueError("الرابط غير مدعوم. استخدم رابط تيك توك أو يوتيوب فقط.")
    return url.strip()


# ---------- تيك توك عبر tikwm (يعمل من الخوادم ويعطي نسخة بدون علامة مائية) ----------
def tikwm(url):
    r = requests.post("https://www.tikwm.com/api/",
                      data={"url": url, "hd": 1},
                      headers={"User-Agent": UA}, timeout=20)
    j = r.json()
    if j.get("code") != 0 or not j.get("data"):
        raise RuntimeError(f"tikwm: {j.get('msg')}")
    d = j["data"]

    def full(u):
        if not u:
            return None
        return u if u.startswith("http") else "https://www.tikwm.com" + u

    return {
        "title": d.get("title") or "tiktok",
        "thumbnail": full(d.get("cover")),
        "duration": d.get("duration"),
        "uploader": (d.get("author") or {}).get("nickname"),
        "video": full(d.get("hdplay")) or full(d.get("play")),
        "audio": full(d.get("music")),
        "id": d.get("id") or "video",
    }


def stream_remote(src, filename):
    up = requests.get(src, stream=True, headers={"User-Agent": UA}, timeout=60)
    up.raise_for_status()
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    if up.headers.get("Content-Length"):
        headers["Content-Length"] = up.headers["Content-Length"]
    return Response(stream_with_context(up.iter_content(64 * 1024)),
                    content_type=up.headers.get("Content-Type", "application/octet-stream"),
                    headers=headers)


PROXY_OK = re.compile(
    r"^https://([a-z0-9-]+\.)*(tikwm\.com|tiktokcdn\.com|tiktokcdn-us\.com|"
    r"tiktokv\.com|muscdn\.com|byteoversea\.com|ibytedtos\.com)/", re.I)


@app.get("/api/proxy")
def proxy():
    src = request.args.get("src", "")
    name = re.sub(r"[^\w.-]", "_", request.args.get("name", "video.mp4"))[:80]
    if not PROXY_OK.match(src):
        return jsonify(error="رابط غير مسموح"), 400
    try:
        return stream_remote(src, name)
    except Exception:
        log_error("proxy")
        return jsonify(error="فشل التحميل"), 502


# ---------- تحويل منشور الصور إلى فيديو (يعمل في الخلفية) ----------
import json
import subprocess
import threading
import uuid

JOBS = {}  # job_id -> {"status": "working|done|error", "path": ..., "dir": ...}


def fetch_to(src, path):
    r = requests.get(src, headers={"User-Agent": UA}, timeout=60)
    r.raise_for_status()
    with open(path, "wb") as f:
        f.write(r.content)


def build_slideshow(job_id, images, audio, audio_dur):
    job = JOBS[job_id]
    d = job["dir"]
    try:
        import imageio_ffmpeg
        ff = imageio_ffmpeg.get_ffmpeg_exe()

        imgs = []
        for i, src in enumerate(images):
            p = os.path.join(d, f"img{i}")
            fetch_to(src, p)
            imgs.append(p)

        a_path = None
        if audio:
            try:
                a_path = os.path.join(d, "audio")
                fetch_to(audio, a_path)
            except Exception:
                log_error("slideshow audio")
                a_path = None

        n = len(imgs)
        per = 3.0
        if a_path and audio_dur and audio_dur > 0:
            per = max(2.0, min(5.0, audio_dur / n))
        total_imgs = per * n
        total = audio_dur if (a_path and audio_dur and audio_dur > total_imgs) else total_imgs
        total = min(total, 180)  # حد أقصى 3 دقائق

        # نكرر الصور إن كان الصوت أطول منها
        seq, t = [], 0.0
        while t < total:
            for p in imgs:
                seq.append(p)
                t += per
                if t >= total:
                    break
        lst = os.path.join(d, "list.txt")
        with open(lst, "w") as f:
            for p in seq:
                f.write(f"file '{p}'\nduration {per}\n")
            f.write(f"file '{seq[-1]}'\n")

        out = os.path.join(d, "slideshow.mp4")
        cmd = [ff, "-y", "-f", "concat", "-safe", "0", "-i", lst]
        if a_path:
            cmd += ["-i", a_path]
        cmd += ["-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,"
                       "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,format=yuv420p",
                "-r", "15", "-c:v", "libx264", "-preset", "veryfast",
                "-tune", "stillimage", "-crf", "20"]
        if a_path:
            cmd += ["-c:a", "aac", "-b:a", "192k"]
        cmd += ["-t", f"{total:.2f}", "-movflags", "+faststart", out]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if res.returncode != 0:
            raise RuntimeError(res.stderr[-1500:])
        job["path"] = out
        job["status"] = "done"
    except Exception:
        log_error("slideshow")
        job["status"] = "error"


@app.post("/api/slideshow")
def slideshow():
    body = request.get_json(silent=True) or {}
    images = [u for u in (body.get("images") or []) if PROXY_OK.match(u or "")][:35]
    audio = body.get("audio") if PROXY_OK.match(body.get("audio") or "") else None
    try:
        audio_dur = float(body.get("duration") or 0)
    except ValueError:
        audio_dur = 0
    if not images:
        return jsonify(error="لا توجد صور"), 400
    job_id = uuid.uuid4().hex
    JOBS[job_id] = {"status": "working", "dir": tempfile.mkdtemp(), "path": None}
    threading.Thread(target=build_slideshow,
                     args=(job_id, images, audio, audio_dur), daemon=True).start()
    return jsonify(job=job_id)


@app.get("/api/job/<job_id>")
def job_status(job_id):
    job = JOBS.get(job_id)
    if not job:
        return jsonify(status="error"), 404
    return jsonify(status=job["status"])


@app.get("/api/job/<job_id>/file")
def job_file(job_id):
    job = JOBS.get(job_id)
    if not job or job["status"] != "done":
        return jsonify(error="غير جاهز"), 404

    @after_this_request
    def cleanup(resp):
        JOBS.pop(job_id, None)
        threading.Timer(60, shutil.rmtree, args=(job["dir"],),
                        kwargs={"ignore_errors": True}).start()
        return resp

    return send_file(job["path"], mimetype="video/mp4", as_attachment=True,
                     download_name=f"tiktok_slideshow.mp4")


@app.get("/")
def index():
    return send_from_directory(BASE, "index.html")


@app.get("/api/info")
def info():
    try:
        url = check_url(request.args.get("url"))
    except ValueError as e:
        return jsonify(error=str(e)), 400

    if TIKTOK.match(url):
        try:
            t = tikwm(url)
            return jsonify(title=t["title"], thumbnail=t["thumbnail"],
                           duration=t["duration"], uploader=t["uploader"],
                           platform="TikTok")
        except Exception:
            log_error("tikwm info")  # نجرّب yt-dlp كخطة بديلة

    try:
        with yt_dlp.YoutubeDL(base_opts()) as ydl:
            data = ydl.extract_info(url, download=False)
        return jsonify(title=data.get("title"), thumbnail=data.get("thumbnail"),
                       duration=data.get("duration"), uploader=data.get("uploader"),
                       platform=data.get("extractor_key"))
    except Exception:
        log_error("yt-dlp info")
        return jsonify(error="تعذّر جلب الفيديو. تأكد من الرابط وحاول مرة أخرى."), 500


@app.get("/api/download")
def download():
    try:
        url = check_url(request.args.get("url"))
    except ValueError as e:
        return jsonify(error=str(e)), 400
    kind = request.args.get("type", "video")

    if TIKTOK.match(url):
        try:
            t = tikwm(url)
            src = t["audio"] if kind == "audio" else t["video"]
            ext = "mp3" if kind == "audio" else "mp4"
            if src:
                return stream_remote(src, f"tiktok_{t['id']}.{ext}")
        except Exception:
            log_error("tikwm download")

    tmp = tempfile.mkdtemp()
    opts = base_opts()
    opts["outtmpl"] = os.path.join(tmp, "%(id)s.%(ext)s")
    if kind == "audio":
        opts["format"] = "bestaudio[ext=m4a]/bestaudio"
    else:
        opts["format"] = "best[ext=mp4][format_note!*=watermark]/best[ext=mp4]/best"

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            data = ydl.extract_info(url, download=True)
            path = ydl.prepare_filename(data)
        if not os.path.exists(path):
            path = os.path.join(tmp, os.listdir(tmp)[0])
    except Exception:
        log_error("yt-dlp download")
        shutil.rmtree(tmp, ignore_errors=True)
        return jsonify(error="فشل التحميل. قد يكون الفيديو خاصاً أو محمياً."), 500

    @after_this_request
    def cleanup(resp):
        shutil.rmtree(tmp, ignore_errors=True)
        return resp

    return send_file(path, as_attachment=True, download_name=os.path.basename(path))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
