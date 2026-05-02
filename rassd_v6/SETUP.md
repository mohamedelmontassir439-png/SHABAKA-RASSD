# 🚀 دليل النشر — ATLAS PRO

هذا الدليل يُرشدك خطوة بخطوة لنشر ATLAS PRO من الصفر حتى الموقع يعمل على الإنترنت.

---

## 📋 قائمة التحقّق قبل البدء

قبل النشر، تأكّد أن لديك:

- [ ] حساب GitHub
- [ ] حساب Railway (أو بديل للاستضافة)
- [ ] بوت Telegram (اختياري لكن موصى به)
- [ ] حساب Brevo للإيميلات (اختياري)
- [ ] نطاق مخصص (اختياري)

**الوقت المتوقع:** 30-45 دقيقة للمرة الأولى.

---

## المرحلة 1: التحضير المحلي (10 دقائق)

### 1.1 نزّل الكود

```bash
git clone https://github.com/YOUR_USERNAME/atlas-pro.git
cd atlas-pro
```

### 1.2 أنشئ بيئة افتراضية واختبر التشغيل محلياً

```bash
# إنشاء البيئة
python -m venv venv

# تفعيلها
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows PowerShell

# تثبيت المكتبات
pip install -r requirements.txt

# نسخ ملف البيئة
cp .env.example .env
```

### 1.3 ولّد المفاتيح السرية

```bash
# SECRET_KEY (64 حرف)
python -c "import secrets; print('SECRET_KEY=' + secrets.token_hex(32))"

# ADMIN_PASS (24 حرف)
python -c "import secrets; print('ADMIN_PASS=' + secrets.token_urlsafe(24))"
```

**احفظ هاتين القيمتين** — ستحتاجهما لاحقاً على Railway.

### 1.4 اختبار محلي سريع

```bash
# فعّل البيئة
source venv/bin/activate

# شغّل التطبيق
uvicorn main:app --reload --port 8000
```

افتح `http://localhost:8000` — يجب أن ترى صفحة الترحيب.

**إذا رأيت أخطاء**، راجع [TROUBLESHOOTING.md](./TROUBLESHOOTING.md).

---

## المرحلة 2: إعداد الخدمات الخارجية (15 دقيقة)

### 2.1 بوت Telegram

1. افتح Telegram واذهب إلى [@BotFather](https://t.me/BotFather)
2. أرسل `/newbot`
3. اختر اسماً (مثلاً: `ATLAS PRO Alerts`)
4. اختر username (يجب أن ينتهي بـ `bot`، مثلاً: `atlas_pro_alerts_bot`)
5. BotFather سيعطيك **token** — احفظه كـ `TELEGRAM_BOT`

**الحصول على Chat ID الخاص بك:**
1. أرسل أي رسالة لبوتك الجديد
2. اذهب لـ [@userinfobot](https://t.me/userinfobot) وأرسل `/start`
3. سيرد بـ Chat ID (رقم طويل) — احفظه كـ `ADMIN_CHAT_ID`

### 2.2 Brevo للإيميلات (اختياري لكن موصى)

1. سجّل على [brevo.com](https://www.brevo.com) (مجاني، 300 إيميل/يوم)
2. اذهب لـ Settings → SMTP & API → API Keys
3. أنشئ مفتاحاً جديداً — احفظه كـ `BREVO_API_KEY`
4. **مهم:** في Brevo، تحقّق من بريدك الإلكتروني كـ Sender Identity

### 2.3 نطاق مخصص (اختياري)

إذا أردت `atlas-pro.ma` بدل `atlas-pro.up.railway.app`:

1. اشترِ نطاقاً من [Namecheap](https://namecheap.com) أو [Gandi](https://gandi.net) (~10$/سنة)
2. ستضبطه لاحقاً في Railway (الخطوة 4.4)

---

## المرحلة 3: رفع الكود إلى GitHub (5 دقائق)

### 3.1 تأكّد أن `.env` في `.gitignore`

```bash
# تحقّق أن .env غير مرفوع
cat .gitignore | grep -E "^\.env$"
# يجب أن يُخرج: .env
```

**⚠️ هذا حرج جداً — لا تضع `.env` في Git أبداً.**

### 3.2 أنشئ repository

```bash
# على GitHub، أنشئ repo جديداً فارغاً (بدون README)
# ثم محلياً:

git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/atlas-pro.git
git push -u origin main
```

---

## المرحلة 4: النشر على Railway (10 دقائق)

### 4.1 إنشاء المشروع

1. اذهب إلى [railway.app](https://railway.app)
2. اضغط "New Project"
3. اختر "Deploy from GitHub repo"
4. اختر `atlas-pro`
5. Railway سيبدأ الـ build تلقائياً

### 4.2 إضافة متغيرات البيئة

في Railway Dashboard → Variables، أضف:

```
SECRET_KEY          = [ما ولّدته في 1.3]
ADMIN_PASS          = [ما ولّدته في 1.3]
SITE_URL            = https://your-app.up.railway.app
TELEGRAM_BOT        = [token من BotFather]
ADMIN_CHAT_ID       = [Chat ID الخاص بك]
BREVO_API_KEY       = [API key من Brevo]
FROM_EMAIL          = your-email@example.com
DB_PATH             = /app/data/atlas.db
SCAN_INTERVAL_MIN   = 60
DEBUG               = false
```

**بعد كل إضافة**، Railway سيُعيد تشغيل التطبيق تلقائياً.

### 4.3 تفعيل Volume دائم للبيانات

**مهم جداً — بدون هذا، بياناتك ستُمحى مع كل redeploy:**

1. في Railway → Settings → Volumes
2. اضغط "+ New Volume"
3. Mount path: `/app/data`
4. اضغط Create

### 4.4 ربط النطاق المخصّص (اختياري)

1. في Railway → Settings → Networking → Custom Domain
2. أضف نطاقك (مثلاً: `atlas-pro.ma`)
3. اتبع التعليمات لضبط DNS

---

## المرحلة 5: التحقّق من النشر (5 دقائق)

### 5.1 اختبارات أساسية

افتح في المتصفح:

```
https://your-app.up.railway.app/
  ← يجب أن ترى الصفحة الرئيسية

https://your-app.up.railway.app/health
  ← يجب أن ترى: {"status":"ok", ...}

https://your-app.up.railway.app/admin/login
  ← سجّل دخول admin بـ ADMIN_PASS
```

### 5.2 أول scrape يدوي

1. سجّل دخول admin
2. في `/admin`، اضغط "Scan Now"
3. راقب SSE logs مباشرة
4. بعد دقيقتين، يجب أن ترى "✅ X nouveaux marchés"

### 5.3 اختبار Telegram

1. افتح محادثة مع بوتك على Telegram
2. أرسل `/start`
3. في `/admin`، اضغط "Test Notifications"
4. يجب أن تصلك رسالة تجريبية

---

## 🎉 انتهيت!

الموقع يعمل الآن على الإنترنت. الخطوات التالية:

### اختبارات المستخدم الأول

1. سجّل حساباً جديداً (كمستخدم عادي، لا admin)
2. اختر قطاعات تهمّك
3. انتظر الـ scrape التلقائي التالي
4. تحقّق أن الإيميل يصل عند صفقات جديدة

### مراقبة الأداء

- راقب Railway Metrics للـ CPU/RAM usage
- راقب logs للأخطاء
- راقب Brevo dashboard للإيميلات المُرسلة

### النسخ الاحتياطي

```bash
# محلياً، من حين لآخر
sqlite3 data/atlas.db ".backup data/backup-$(date +%Y%m%d).db"
```

على Railway، Volume يحميك من فقدان البيانات بين redeployments، لكن ليس من حذف خاطئ. **احتفظ بنسخ خارجية دورياً.**

---

## 🚨 إجراءات الأمان بعد النشر

### 1. راجع Railway Logs للأخطاء

```
Railway Dashboard → Logs
```
ابحث عن أي `ERROR` أو `WARNING` متكرر.

### 2. اختبر rate limiting

حاول تسجيل دخول خاطئ 6 مرات متتالية — يجب أن يُحظر مؤقتاً.

### 3. تحقّق من Security Headers

استخدم [securityheaders.com](https://securityheaders.com) مع رابط موقعك. يجب أن تحصل على تقييم A أو أعلى.

### 4. راقب الدخولات غير المألوفة

أضف منطقاً لاحقاً لتنبيهك عند دخول admin من IP جديد.

---

## 🔄 التحديثات المستقبلية

عندما تُعدّل الكود:

```bash
git add .
git commit -m "وصف التعديل"
git push origin main
```

Railway سيُعيد النشر تلقائياً في 1-2 دقيقة.

**نصيحة:** بعد كل deploy، افتح `/health` للتأكد أن كل شيء يعمل.

---

## 💸 التكاليف المتوقعة

| الخدمة | التكلفة الشهرية |
|--------|-----------------|
| Railway (Hobby plan) | $5/شهر (مجاني أول $5) |
| Brevo Free | $0 (300 إيميل/يوم) |
| نطاق مخصص | ~$1/شهر (~$12/سنة) |
| Telegram Bot | مجاني |
| **المجموع** | **~$6/شهر** |

للبدء: يكفيك $5 فقط للشهر الأول.

---

**تم! مشروعك على الإنترنت ويعمل. 🚀**
