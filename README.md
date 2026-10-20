# نَصّ — Nass MCP

خادم MCP مجاني ومفتوح المصدر لتفريغ مقاطع YouTube، مع **الرجوع إلى الصوت الفعلي** إذا لم تتوفر subtitles/captions، ومن دون الاعتماد على API مدفوعة.

> **الحالة**: نسخة أولية مكتوبة ومختبرة اختبارات وحدة محلية، وليست خدمة إنترنت منشورة أو موصولة بحساب ChatGPT. اختبارات الشبكة الحقيقية تعتمد على بيئة التشغيل والوصول إلى YouTube. لا يمكن ضمان الوصول إلى جميع المقاطع.

## المتطلبات

- Python 3.11+، `ffmpeg` و`ffprobe`، و`Deno` (مفضّل) أو Node حديث لدعم تحديات JavaScript الحديثة في yt-dlp. مع Node قد يلزم ضبط yt-dlp لتفعيله صراحةً. راجع [دليل EJS](https://github.com/yt-dlp/yt-dlp/wiki/EJS).
- حاسوب يعمل باستمرار إذا رغبت في ربطه بـChatGPT عبر شبكة؛ لا حاجة لاستضافة تجارية أو دفع مقابل نموذج Whisper.
- تنزيل النموذج للمرة الأولى يحتاج إنترنت ومساحة تخزين؛ بعد ذلك يتعرف Whisper محليًا على الملفات الصوتية، ولا يرسلها إلى طرف ثالث.

## التثبيت

```bash
# Ubuntu/Debian
sudo apt-get update && sudo apt-get install -y ffmpeg
# ثبّت Deno من مصدره الرسمي (الإصدارات المدعومة مذكورة في Wiki الخاصة بـyt-dlp).

python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e '.[all]'

nass-doctor
nass-mcp  # stdio; يطلقه MCP host تلقائيًا عادة
```

للتجربة عبر HTTP محليًا:

```bash
NASS_TRANSPORT=http nass-mcp
# http://127.0.0.1:8000/mcp
```

**تنبيه أمني:** لا تفتح المنفذ للإنترنت بدون نظام توثيق حقيقي (OAuth أو reverse proxy مع ضوابط وصول). HTTP الافتراضي محلي فقط. ربط ChatGPT يتطلب وسيلة وصول HTTPS آمنة وميزات متاحة لحسابك؛ لا يكفي نشر الشيفرة.

## ربط MCP محلي بعميل يدعم stdio

استدعِ البرنامج التنفيذي `nass-mcp` من البيئة الافتراضية، أو ضعه في إعداد الخادم:

```json
{
  "mcpServers": {
    "nass": {
      "command": "/absolute/path/to/nass-mcp/.venv/bin/nass-mcp",
      "env": {
        "NASS_WHISPER_MODEL": "small",
        "NASS_DATA_DIR": "/absolute/path/to/my-nass-data"
      }
    }
  }
}
```

## الاستخدام

1. `nass_health`: فحص المكتبات وFFmpeg وبيئة JS ومُعرّفات المحركات.
2. `nass_start_transcription(video_url, language="ar", mode="audio")`: **تفريغ الكلام من الصوت مباشرة**. بينما `mode="auto"` يفضل النصوص المتاحة توفيرًا للموارد، و`mode="verify"` يقارن مسارين مستقلين دون الدمج الآلي المضلل.
3. `nass_job_status(job_id)`: الاستعلام عن الحالة ومراحل النجاح والفشل.
4. `nass_get_transcript(job_id, start_segment, count)`: قراءة النص مقطعًا مقطعًا مع التوقيت حتى للفيديوهات الطويلة.
5. `nass_start_audio_download(video_url)`: جلب الصوت فعليًا بمهمة خلفية قابلة للاستعلام، أو `nass_download_original_audio(video_url)` للمقاطع القصيرة. الملف الصوتي **على جهاز تشغيل الخادم**، وليس هاتف المستخدم.
6. `nass_audio_excerpt(job_id, start_seconds, duration_seconds)`: **إعادة مقطع صوتي حقيقي يصل إلى 45 ثانية ككتلة صوت MCP** للمراجعة السمعية؛ ويعتمد سماعه داخل الواجهة على دعم العميل لمحتوى الصوت.
7. `nass_export(job_id, output_format="srt"/"txt"/"json")`: تصدير النتيجة محليًا.
8. `nass_search_transcript(job_id, query, max_matches=15)`: البحث داخل التفريغ عن الأقوال الموثقة زمنيًا، مع رابط فيديو يبدأ عند الموضع نفسه. البحث يتسامح مع التشكيل وبعض صيغ الألف والـ«ى»، ولا يغير النص الأصلي.
9. `nass_start_local_file(filename)`: تفريغ ملف صوتي وضعته أنت تحت `NASS_MEDIA_DIR`، عند تعذر استخراج الفيديو عبر الإنترنت.

## الإضافات المستقلة من المشاريع غير المشهورة (v0.2.0)

اكتُشفت مشروعات قليلة الشهرة قابلة لإضافات مفيدة فعلًا. أضيفت **ثلاث وصلات اختيارية**، ويستمر الخادم في العمل دون تثبيتها:

- **Go `yt-transcript`** للحصول على captions عبر Android/IOS InnerTube وwatch-page. التثبيت (Go 1.23+):
  `go install github.com/rapha30/yt-youtube-transcript/cmd/yt-transcript@latest`
- **Go `youtubedr`** لمصدر صوت مستقل. التثبيت (تتطلب نسخته الحالية Go 1.26+):
  `go install github.com/kkdai/youtube/v2/cmd/youtubedr@latest`
- **Node `youtubei.js`** لاستخراج الصوت مع حد حجم مفعّل أثناء البث. بعد تثبيت `nass-mcp`:

```bash
mkdir -p "$HOME/.local/share/nass-youtubejs"
python -c 'from pathlib import Path; import nass_mcp; print(Path(nass_mcp.__file__).parent / "_node" / "youtubejs_audio.mjs")'
# انسخ ملف youtubejs_audio.mjs المشار إليه إلى المجلد أعلاه، ثم نفّذ:
cd "$HOME/.local/share/nass-youtubejs"
npm install --no-audit --no-fund youtubei.js
export NASS_YOUTUBEJS_SCRIPT="$HOME/.local/share/nass-youtubejs/youtubejs_audio.mjs"
```

هذا التثبيت الاختياري يجب أن يتم على جهاز الخادم؛ لا يتم تحميل حزم Node تلقائيًا أثناء طلب MCP.
`nass_health` يعرض توافر ملفات المحولات، وباقي البرامج؛ وقد يظل فشل الاتصال بالمصدر ممكنًا بعد تثبيتها.

تفاصيل الدراسة والمشروعات التي تقرر عدم دمجها: `docs/NICHE_RADAR.md`.

## مصادر متعددة بدون اشتراكات

| المرحلة | المسار | النوع | ملاحظات |
|---|---|---|---|
| captions | `youtube-transcript-api` | مجاني، لا مفتاح | قد يتعطل عند حجب IP أو توقف واجهة المصدر |
| captions | `yt-dlp` subtitles | مجاني | مصدر برمجي ثانٍ، لكن يعتمد كذلك على بيانات يوتيوب |
| captions | `yt-transcript` (Go) | مجاني اختياري | بدائل InnerTube مستقلة داخل الأداة |
| audio | `yt-dlp` default player | مجاني | يحتاج تحديث وإعداد EJS/بيئة JS وفقًا ليوتيوب |
| audio | `yt-dlp` iOS player | مجاني | عميل بديل، ليس ضمانًا لتجاوز جميع أنواع المنع |
| audio | `pytubefix` | مجاني | مكتبة استخراج مستقلة برمجيًا؛ نفس الموقع مصدره |
| audio | `YouTube.js` | مجاني اختياري | JavaScript InnerTube؛ يحتاج Node وحزمة npm محلية |
| audio | `youtubedr` | مجاني اختياري | Go؛ يختار itag 140 الصوتي إن كان موجودًا |
| cache | إعادة استخدام الصوت والنص السابقين | مجاني ومحلي | يعمل حتى إذا تعطل يوتيوب بعد الحصول على نسخة صالحة |
| ASR | `faster-whisper` | مجاني ومحلي | الافتراضي small/CPU int8؛ يدعم العربية |
| ASR | `whisper.cpp` | مجاني ومحلي | نسخة بديلة تتطلب binary وملف نموذج محلي |
| ASR | `Groq` | **اختياري** بخطة مجانية محدودة | ليس مطلوبًا للتشغيل المجاني الدائم؛ يحتاج مفتاحًا وموافقة صريحة على رفع الصوت |

لا نستعين بمواقع proxy مجهولة، ولا نتجاوز إعدادات خصوصية الفيديو، ولا نستخدم بيانات دخول أو رموز جلسات أو نسخًا غير مصرح بها.

## إعدادات مفيدة

```bash
export NASS_WHISPER_MODEL=small   # medium/large-v3 متاحة، لكنها تحتاج قدرات أعلى
export NASS_INITIAL_PROMPT='حديث، إسناد، رواية، الصحابة، الإمام البخاري، الإمام مسلم' 
export NASS_DEVICE=cpu
export NASS_COMPUTE_TYPE=int8
export NASS_WORKERS=1
export NASS_JOB_QUEUE_LIMIT=8  # حصة لكل عملية تشغيل لمنع تراكم المهام
export NASS_PROVIDER_TIMEOUT=600
export NASS_AUDIO_CACHE=1
export NASS_AUDIO_CACHE_LIMIT_BYTES=3221225472
export NASS_CAPTION_CACHE_SECONDS=86400
export NASS_MAX_DURATION_SEC=14400
export NASS_MEDIA_DIR="$HOME/nass-input"

# بديل Whisper.cpp إذا ثبتته وأنزلت نموذجه:
export NASS_WHISPER_CPP_BIN=/path/to/whisper-cli
export NASS_WHISPER_CPP_MODEL=/path/to/ggml-model.bin

# بديل سحابي مجاني *اختياري* وخاضع للحصص والخصوصية:
export NASS_ALLOW_EXTERNAL_ASR=1
export GROQ_API_KEY='YOUR_KEY'
```

**احتياطات منهجية للباحث الشرعي:** تخريج الأحاديث ومناقشة الأقوال لا يجوز بناؤهما على التفريغ الآلي وحده. يجب الإبقاء على الرابط والتوقيت، والتمييز بين caption يدوي، وcaption تلقائي، وASR من الصوت، والتحقق من الألفاظ المشكلة عبر سماع المقطع.

## تجربة حيّة عند توفر الإنترنت

```bash
PYTHONPATH=src python scripts/live_smoke.py 'https://youtu.be/QxC5E44QoZY' --mode audio --language ar
```

هذا الأمر **لم يُختبر ضد YouTube من داخل بيئة تأليف المشروع** بسبب غياب حزم الاعتماد والوصول المباشر. نجاح الاختبارات المحلية لا يُغني عن اختبار التشغيل الحيّ. تُحفظ النتيجة، بما فيها سجل إخفاق كل مزوّد، بصيغة JSON.

لدمج الخادم مع «الباحث الشرعي» انظر `integration/RESEARCHER_INTEGRATION.md`.

## تطوير لاحق

- تحميل وتشغيل واقعي على بيئة متصلة مع تقارير لروابط حقيقية متنوعة (منها فيديوهات عربية بلا captions)، وتحديث مستمر عند تغييرات YouTube.
- حماية HTTP بOAuth/HTTPS ودمج رسمي مع حساب المستخدم حيث تسمح سياسات المنتج.
- تخزين مؤقت مع حصص وإيقاف للمهام واختبارات تكامل، وواجهة لعرض مقارنة النصوص مع الصوت. حُدِّد عدد المهام المنتظرة في v0.2.0، لكن إلغاء المهام وإدارة التخزين عبر عمليات متعددة لم يُنفذا بعد.

## اختبارات الإصدار 0.2.1

```bash
pip install -e '.[test]'
pytest -q
```

اجتاز الإصدار 39 اختبارًا محليًا (35 اختبارًا سابقًا وأربعة اختبارات تشغيلية جديدة) تشمل إخفاق مزودَي captions ونجاح الثالث، وإخفاق أربعة مسارات صوتية ونجاح الخامس، ورفض ملف فيديو لا يحوي صوتًا. البيئة التي أُعدّ فيها هذا الإصدار لم تتمكن من استخدام DNS أو تنزيل بيانات YouTube؛ لذلك لا يُدّعى إجراء اختبار حيّ.

## حدود معروفة

- فيديوهات YouTube المحجوبة، أو التي تحتاج موافقات حقوق/تسجيل دخول، قد تفشل جميع طرق الصوت معها؛ استخدم حينها ملفًا تملكه أو لديك إذن باستخدامه.
- الموديلات الكبيرة مكلفة **حاسوبيًا** وإن كانت مجانية ماليًا. أول تشغيل قد يحمّل وزن النموذج.
- الفشل المتعدد في حال جميع المسارات تعتمد على منع مشترك (مثل IP) لا يُحل بمجرد زيادة عدد المكتبات.
- الـMCP يعمل الآن داخل بيئة عملية واحدة؛ قاعدة المهام مخزنة ولكن المهام الجارية تحتاج إعادة إرسال بعد إعادة تشغيل الخدمة.


## تقرير الاختبارات التشغيلية (20 أكتوبر 2026)

لم تنجح اختبارات YouTube الحية، ولم يبدأ خادم MCP الحقيقي، بسبب عدم توفر DNS
وغياب حزم `mcp` و`yt-dlp` و`faster-whisper` في بيئة الفحص.
الاختبارات **الناجحة** تثبت مراحل FFmpeg/FFprobe وNode وJobStore مع مصدر صوت فعلي محلي،
لكن مصدر YouTube.js ومسار ASR في اختبارات التكامل جرى تمثيلهما بمزوّدات محلية تجريبية.
هذا لا يثبت دقة نموذج Whisper أو وصول المشروع الفعلي إلى YouTube.

أثناء المراجعة تم تصحيح مسار استيراد `Audio` حسب هيكلة MCP SDK v2
إلى `mcp.server.mcpserver.utilities.types`.

أعد الفحص بعد تثبيت جميع الاعتماديات والوصول للإنترنت بواسطة:

```bash
python scripts/operational_check.py --live \
  --video 'https://youtu.be/QxC5E44QoZY' \
  --output nass-operational-report.json
```

التفاصيل في `docs/OPERATIONAL_TEST_2026-10-20.md` والملف
`docs/operational-report.json`، مع نتائج محاولتي YouTube في `docs/attempts-*`.

## Remote MCP gateway — Netlify (v0.3.0)

The repository now includes `remote-netlify/` and a protected Python ASGI worker (`nass_mcp.remote`). This separates Netlify's lightweight, stateless HTTPS gateway from the actual multi-provider YouTube audio capture and Whisper execution on a Python host.

The gateway has no CPU-heavy ASR and cannot operate if the upstream host is offline. Source and installation notes: [`remote-netlify/README.md`](remote-netlify/README.md).

```bash
pip install -e '.[all,remote]'
export NASS_BACKEND_TOKEN="$(openssl rand -hex 32)" # set the same secret on Netlify
nass-backend  # binds only to 127.0.0.1:8000
```

Expose the worker via an authenticated HTTPS tunnel that preserves `/mcp`, then set Netlify's `NASS_BACKEND_URL` and `NASS_BACKEND_TOKEN` environment variables. A third, separate `NASS_MCP_BEARER_TOKEN` is the MCP client's authentication key. After deploying the Netlify code, the client connects to `https://<site>.netlify.app/mcp`.

**Deployment status (2026-10-20):** the Netlify project `nass-mcp-remote` was created in the linked account, but its code is not yet deployed and no permanent ASR worker has been provisioned. Do not treat the project URL as an operational MCP endpoint before deployment and real YouTube/audio testing.

## Render Free backend experiment (v0.3.1)

`Dockerfile` and `render.yaml` are now present in the repository root. This is a
*deployable proposal*, not evidence of deployment. See
[`docs/RENDER_REMOTE_SETUP.md`](docs/RENDER_REMOTE_SETUP.md).

Render Free has 512 MiB RAM and 0.1 CPU. The preconfigured model is multilingual
Whisper `tiny`; larger Arabic ASR workloads can fail or run too slowly. No audio
transcription may be claimed complete until it has finished and been verified
against the source. The free worker is not durable across sleep/redeploy.
