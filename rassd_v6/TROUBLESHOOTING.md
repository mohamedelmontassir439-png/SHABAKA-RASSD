# 🔧 دليل استكشاف الأخطاء — ATLAS PRO

هذا الملف يحتوي على حلول للمشاكل الأكثر شيوعاً. إذا كنت تواجه مشكلة، ابحث هنا أولاً.

---

## 🚨 مشاكل التشغيل الأساسية

### 1. التطبيق لا يبدأ — `RuntimeError: SECRET_KEY manquant`

**السبب:** لم تُعيّن `SECRET_KEY` في ملف `.env` أو في متغيرات Railway.

**الحل:**
```bash
# ولّد مفتاحاً جديداً
python -c "import secrets; print(secrets.token_hex(32))"
# انسخ النتيجة (64 حرف) وضعها في .env
SECRET_KEY=النتيجة_المُولّدة_هنا
```

**ملاحظة:** هذه ليست محض إزعاج — إنها حماية. لو قبل التطبيق العمل بدون مفتاح، لكان أي مهاجم قادراً على انتحال أي مستخدم.

---

### 2. لوحة الإدارة ترفض الدخول — `503: ADMIN_PASS non configuré`

**السبب:** تستخدم كلمة المرور الافتراضية `atlas2026` (معروفة لأي شخص يقرأ التوثيق).

**الحل:**
```bash
# في .env
ADMIN_PASS=كلمة_مرور_قوية_فريدة_16_حرف_على_الأقل
```

**توليد كلمة مرور قوية:**
```bash
python -c "import secrets; print(secrets.token_urlsafe(24))"
```

---

### 3. قاعدة البيانات فارغة بعد Deploy على Railway

**السبب:** SQLite على Railway يُخزَّن في filesystem مؤقت. كل redeploy = مسح البيانات.

**الحلول المُرتّبة من الأسهل للأفضل:**

#### الحل: Railway Volumes
1. في Railway Dashboard → Settings → Volumes
2. أضف Volume جديد mounted على `/app/data`
3. عدّل `DB_PATH=/app/data/atlas.db`
4. البيانات ستبقى بين redeployments

---

## 🕷️ مشاكل Scraper

### 4. Scraper لا يرجع نتائج

**تشخيص سريع:**
```bash
# اختبر الوصول للموقع
curl -I https://www.marchespublics.gov.ma
# يجب أن يرد 200 أو 301
```

**أسباب محتملة وحلول:**

| السبب | الحل |
|-------|------|
| الموقع down | انتظر، أو جرّب لاحقاً |
| IP محظور | تغيير User-Agent (موجود بالفعل بالتدوير) |
| شهادة SSL مرفوضة | `TLSAdapter` في الكود يحلّ هذا |
| Timeout | زد `SCRAPER_TIMEOUT` في `config.py` |

**اختبار يدوي:**
1. سجّل دخول admin: `https://yoursite.com/admin/login`
2. اضغط "Scan Now"
3. راقب SSE logs مباشرة

### 5. Scraper يُرجع نفس الصفقات القديمة

**السبب:** `max_id` لا يتحدّث.

**الحل:** في لوحة الإدارة:
- `Reset State` لمسح الحالة الحالية
- ثم `Scan Now` لإعادة البدء

---

## 📧 مشاكل الإشعارات

### 6. Emails لا تصل (Brevo)

**التشخيص:**
1. تحقّق من `BREVO_API_KEY` في `.env`
2. اذهب لـ [Brevo Dashboard](https://app.brevo.com) → Logs → تحقّق من آخر محاولات إرسال

**أسباب شائعة:**

| السبب | الحل |
|-------|------|
| الحساب معلّق | تواصل مع Brevo support |
| وصلت حدّ الـ 300/يوم المجاني | ترقية أو انتظار غد |
| `FROM_EMAIL` غير موثّق | أضف DNS records في Brevo |
| البريد في spam | تحقّق من مجلد Spam للمُستقبل |

### 7. Telegram لا يعمل

**الأخطاء الشائعة:**

```
[TG] Erreur 401: Unauthorized
```
→ `TELEGRAM_BOT` خاطئ. احصل على واحد جديد من [@BotFather](https://t.me/BotFather).

```
[TG] Erreur 400: chat not found
```
→ المستخدم لم يبدأ محادثة مع البوت بعد. يجب أن يرسل `/start` للبوت أولاً.

**الحصول على Chat ID الخاص بك:**
1. أرسل أي رسالة لـ [@userinfobot](https://t.me/userinfobot)
2. سيرجع Chat ID الخاص بك
3. ضعه في `ADMIN_CHAT_ID`

### 8. WhatsApp لا يعمل

WhatsApp يتطلّب تشغيل خدمة Node.js منفصلة (`whatsapp_service/`) — تطبيق Python الرئيسي لا يشغّلها تلقائياً.

**محلياً:**
```bash
cd whatsapp_service
npm install
npm start
# افتح http://localhost:3001/qr وامسح الـ QR من هاتفك (WhatsApp → الأجهزة المرتبطة)
```

**على Railway (كخدمة ثانية منفصلة في نفس المشروع):**
1. فـ Railway Dashboard → مشروع ATLAS PRO → **+ New** → **GitHub Repo** (نفس المستودع)
2. فـ إعدادات الخدمة الجديدة → **Settings → Root Directory** → `whatsapp_service`
3. زيد Volume مربوط بـ `/app/auth_info` (باش الجلسة ماتضيعش عند كل redeploy — بحال ما ديرنا مع SQLite)
4. زيد المتغيرات: `WA_SECRET` (نفس القيمة اللي حطيتيها فخدمة Python)، و`WA_PORT` اختياري
5. بعد أول deploy، افتح `<url-diال-khidma>/qr` وامسح الـ QR من هاتفك — مرة وحدة فقط، الجلسة كتبقى محفوظة فـ Volume
6. فخدمة Python الرئيسية، زيد المتغير `WA_SERVICE_URL` بعنوان الخدمة الثانية الداخلي (Railway كيعطيك رابط `.railway.internal` بين الخدمات فنفس المشروع)

**مهم:** الحساب اللي كتربطو بـ QR هو حساب WhatsApp حقيقي (رقم هاتف) خاص يبقى مفتوح/متصل بالأنترنت من وقت لآخر — بحال أي "WhatsApp Web" آخر.

---

## 🔐 مشاكل المصادقة

### 9. المستخدمون يُطردون بعد كل redeploy

**السبب:** `SECRET_KEY` تغيّر بين redeployments → كل التوكنات القديمة أصبحت غير صالحة.

**الحل:** **لا تُغيّر `SECRET_KEY`**. ضعه مرة واحدة في Railway Variables ولا تلمسه.

### 10. "Mot de passe trop faible"

التطبيق يرفض:
- أقل من 8 حروف
- كلمات مرور شائعة مثل `password`, `12345678`, `atlas123`
- كلمة مرور بدون رقم أو رمز

**مثال على كلمة مرور مقبولة:**
- ✅ `Atlas2026!Morocco`
- ✅ `mon-mot-de-passe-fort-123`
- ❌ `password` (ضعيف)
- ❌ `atlasatlas` (لا رقم/رمز)

---

## 🐛 أخطاء التطوير

### 11. `ModuleNotFoundError: No module named 'bcrypt'`

```bash
# تأكّد أنك في البيئة الافتراضية
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows

# ثم
pip install -r requirements.txt
```

### 12. `sqlite3.OperationalError: database is locked`

**السبب:** عدة عمليات تكتب للـ DB في نفس الوقت.

**الحل:** WAL mode مفعّل بالفعل. إذا استمرّت المشكلة:
```python
# في app/core/database.py، زد timeout
db = sqlite3.connect(cfg.DB_PATH, timeout=30.0, check_same_thread=False)
```

---

## 🔍 كيف تُصحّح مشاكل جديدة

### الخطوة 1: اقرأ الـ logs

```bash
# محلياً
uvicorn main:app --reload --log-level debug

# على Railway
Railway Dashboard → Logs
```

### الخطوة 2: اختبر المسارات يدوياً

```bash
# Health check
curl http://localhost:8000/health

# تأكّد من scraper state
curl http://localhost:8000/api/v1/stats
```

### الخطوة 3: فعّل DEBUG مؤقتاً

⚠️ **فقط محلياً، لا أبداً في production:**
```bash
# في .env
DEBUG=true
```

### الخطوة 4: راجع قاعدة البيانات

```bash
sqlite3 data/atlas.db
> .tables
> SELECT COUNT(*) FROM tenders WHERE statut='actif';
> SELECT * FROM scrape_log ORDER BY id DESC LIMIT 5;
```

---

## 🆘 لم أجد حلاً

1. ابحث في GitHub Issues
2. اكتب وصفاً كاملاً:
   - نسخة Python (`python --version`)
   - نسخة المكتبات (`pip list`)
   - رسالة الخطأ الكاملة (traceback)
   - خطوات إعادة إنتاج المشكلة
3. أرسل عبر صفحة `/feedback` في التطبيق
