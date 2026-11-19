# محمّل تيك توك ويوتيوب بدون علامة مائية

## التشغيل على جهازك
```bash
pip install -r requirements.txt
python app.py
```
ثم افتح: http://localhost:5000

## نشره كرابط إلكتروني مجاني (Render.com)
1. ارفع هذا المجلد إلى مستودع على GitHub.
2. ادخل render.com ← New ← Web Service ← اختر المستودع.
3. Build Command: `pip install -r requirements.txt`
4. Start Command: `gunicorn app:app --timeout 120`
5. اضغط Deploy، وستحصل على رابط مثل: `https://your-app.onrender.com`

(يعمل بنفس الطريقة على Railway أو أي استضافة تدعم Python.)

## ملاحظات
- تيك توك: يُحمَّل المقطع بدون علامة مائية تلقائياً.
- يوتيوب: يُحمَّل بصيغة MP4 (غالباً حتى 720p) دون الحاجة إلى ffmpeg.
- إذا ظهر خطأ في يوتيوب بسبب الحماية من البوتات على الخادم، صدّر ملف cookies.txt من متصفحك وضع مساره في متغير البيئة `COOKIES_FILE`.
- حدّث yt-dlp دورياً (`pip install -U yt-dlp`) لأن المنصات تغيّر أنظمتها باستمرار.
- للاستخدام الشخصي فقط، مع احترام حقوق أصحاب المحتوى وشروط المنصات.
