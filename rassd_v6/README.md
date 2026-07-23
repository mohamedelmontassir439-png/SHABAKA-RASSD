# ATLAS PRO 🏛️

**منصة مراقبة الصفقات العمومية المغربية في الوقت الفعلي**

نظام SaaS متكامل يراقب [بوابة الصفقات العمومية](https://www.marchespublics.gov.ma) ويُنبّه المقاولات المغربية فور نشر صفقات جديدة تناسب قطاعها.

---

## 🎯 ماذا يفعل ATLAS PRO؟

تخيّل مقاولاً مغربياً يستيقظ كل صباح ليقضي ساعة كاملة في تصفّح بوابة الصفقات العمومية بحثاً عن فرص تناسبه. **ATLAS PRO يُلغي هذه الساعة** — يفعل الأمر تلقائياً 24/7 ويُرسل تنبيهاً فورياً عبر Email أو Telegram أو WhatsApp بمجرد نشر صفقة في قطاعه.

### الميزات الرئيسية

- 🔄 **مراقبة آلية** — Scraper يعمل كل 60 دقيقة على بوابة الصفقات
- 🎯 **16 قطاعاً مُصنّفاً** — BTP، IT، صحة، نقل، وغيرها
- 📧 **إشعارات متعددة** — Email (Brevo) + Telegram + WhatsApp
- ⭐ **مفضّلات شخصية** — احفظ الصفقات المهمّة
- 📊 **لوحة تحكم إدارية** — مع SSE live logs
- 🔌 **API REST** — للمشتركين في Business plan
- 🔐 **نظام اشتراكات** — 3 خطط: Free / Pro / Business

---

## 🚀 البدء السريع

### المتطلبات

- **Python 3.11+**
- **Git**
- حساب على [Railway](https://railway.app) أو أي خدمة استضافة أخرى
- حساب مجاني على [Brevo](https://www.brevo.com) للإيميلات (300/يوم مجاناً)
- بوت Telegram من [@BotFather](https://t.me/BotFather) للإشعارات

### خطوات التثبيت المحلي

```bash
# 1. استنساخ المشروع
git clone https://github.com/YOUR_USERNAME/atlas-pro.git
cd atlas-pro

# 2. إنشاء بيئة افتراضية
python -m venv venv
source venv/bin/activate  # Linux/Mac
# أو
venv\Scripts\activate     # Windows

# 3. تثبيت المكتبات
pip install -r requirements.txt

# 4. نسخ ملف البيئة
cp .env.example .env

# 5. توليد SECRET_KEY آمن
python -c "import secrets; print(secrets.token_hex(32))"
# انسخ النتيجة في .env عند SECRET_KEY

# 6. تعديل .env وملء بقية القيم

# 7. تشغيل التطبيق
uvicorn main:app --reload --port 8000
```

افتح المتصفح على `http://localhost:8000` وستجد الموقع يعمل! 🎉

---

## 📂 بنية المشروع

```
atlas-pro/
├── main.py                    # نقطة الدخول — 41 مسار API
├── app/
│   ├── core/
│   │   ├── config.py          # إعدادات التطبيق
│   │   ├── database.py        # قاعدة البيانات (SQLite)
│   │   ├── security.py        # المصادقة والتشفير
│   │   └── sectors.py         # قائمة القطاعات الـ 16
│   └── services/
│       ├── scraper.py         # Scraper مصدر رئيسي
│       ├── multi_scraper.py   # مصادر ثانوية
│       ├── notifications.py   # Email + Telegram + WhatsApp
│       └── whatsapp.py        # WhatsApp عبر Baileys
├── templates/                 # 14 template Jinja2
├── whatsapp_service/          # خدمة Node.js للـ WhatsApp
├── .env.example               # قالب المتغيرات
├── .gitignore
├── requirements.txt
├── nixpacks.toml              # إعداد Railway
└── README.md                  # أنت هنا
```

---

## 🔐 الأمان — قواعد حاسمة

### 1. `SECRET_KEY` — لا تُشاركه أبداً

هذا المفتاح يُشفّر كل التوكنات في التطبيق. إذا تسرّب:
- يستطيع أي شخص انتحال أي مستخدم
- يستطيع الوصول للوحة الإدارة

**القواعد:**
- ❌ لا تضعه في الكود
- ❌ لا تُشاركه على GitHub
- ✅ فقط في `.env` محلياً أو في متغيرات Railway
- ✅ استبدله فوراً إذا اشتبهت بتسرّبه

### 2. `ADMIN_PASS` — اجعله قوياً

التطبيق **يرفض التشغيل** إذا بقي على القيمة الافتراضية `atlas2026`. استخدم كلمة مرور:
- 16+ حرف
- حروف + أرقام + رموز
- فريدة (غير مستخدمة في أي مكان آخر)

### 3. قاعدة البيانات

قاعدة البيانات الحالية SQLite في `data/atlas.db`. على Railway، هذا الملف **قد يُمحى** عند كل redeploy.

**توصية:** أضف Railway Volume مربوط بـ `/app/data` (راجع `TROUBLESHOOTING.md`) للاحتفاظ الدائم بالبيانات.

---

## 📡 النشر على Railway

### الخطوات

1. **أنشئ حساباً** على [Railway.app](https://railway.app)

2. **أنشئ مشروعاً جديداً** ← "Deploy from GitHub repo"

3. **أضف متغيرات البيئة** في Railway Dashboard:
   ```
   SECRET_KEY = [مفتاح عشوائي 64 حرف]
   ADMIN_PASS = [كلمة مرور قوية]
   SITE_URL = https://your-app.up.railway.app
   TELEGRAM_BOT = [token البوت]
   ADMIN_CHAT_ID = [chat ID الخاص بك]
   BREVO_API_KEY = [مفتاح API من Brevo]
   ```

4. **Deploy** — Railway سيُشغّل `uvicorn main:app` تلقائياً

5. **اختبر** أن `https://your-app.up.railway.app/health` يُعيد `{"status":"ok"}`

---

## 🧪 الاختبار

```bash
# تأكد من أن التطبيق يعمل
curl http://localhost:8000/health

# اختبر Scraper يدوياً (admin)
# 1. سجّل دخول admin: http://localhost:8000/admin/login
# 2. اضغط "Scan Now" في لوحة الإدارة
```

---

## 🛠️ استكشاف الأخطاء الشائعة

### "SECRET_KEY manquant"
لم تضع `SECRET_KEY` في `.env` أو في Railway. ولّد واحداً وأضفه.

### "ADMIN_PASS non configuré"
غيّر `ADMIN_PASS` في `.env` من `atlas2026` إلى كلمة مرور قوية.

### Scraper لا يُرجع نتائج
- تحقّق من [marchespublics.gov.ma](https://www.marchespublics.gov.ma) أنه يعمل
- راجع logs في لوحة الإدارة (`/admin`)

### Emails لا تصل
- تحقّق أن `BREVO_API_KEY` صحيح
- تحقّق من لوحة Brevo أن الحساب غير محظور

### Telegram لا يعمل
- تأكّد من `TELEGRAM_BOT` (token كامل)
- تأكّد من `ADMIN_CHAT_ID` (رقم، لا username)

---

## 🗺️ خارطة الطريق

### ✅ منجز
- [x] Scraper يعمل على `marchespublics.gov.ma`
- [x] نظام مستخدمين كامل (تسجيل، دخول، استعادة كلمة المرور)
- [x] إشعارات متعددة (Email، Telegram، WhatsApp)
- [x] 41 مسار API
- [x] لوحة إدارة
- [x] API REST v1
- [x] نظام اشتراكات بـ 3 خطط
- [x] إصلاحات أمان شاملة

### 🚧 قيد العمل
- [ ] تقسيم `main.py` (815 سطر) إلى routers منفصلة
- [ ] اختبارات أساسية (pytest)
- [ ] CSRF protection
- [ ] تصدير CSV للصفقات

### 🔮 مستقبلي
- [ ] تطبيق Mobile (React Native)
- [ ] AI لتلخيص كراسات التحملات
- [ ] مقارنة الأسعار مع الصفقات السابقة
- [ ] Integration مع محاسبة

---

## 💬 الدعم والاتصال

- **الموقع:** [atlas-pro.ma](https://web-production-b4ae4.up.railway.app)
- **البريد:** للاستفسارات والدعم
- **Feedback:** استخدم صفحة `/feedback` داخل التطبيق

---

## ⚖️ الرخصة

هذا المشروع ملكية خاصة. الاستخدام مسموح للمشتركين فقط حسب الخطة المختارة.

---

**بُني بـ ❤️ في المغرب 🇲🇦**
