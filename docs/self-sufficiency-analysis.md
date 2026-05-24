# Self-Sufficiency Analysis — Koza Agent

## 1. Giriş

Bu doküman, Koza agent'ının gerçek anlamda otonom çalışabilmesi için mevcut eksiklikleri analiz eder.
Analiz beş ana kategoride yapılmıştır: eksik tool kapasiteleri, error recovery pattern'leri,
context management sorunları, prompt optimization fırsatları ve dış bağımlılık/fallback stratejileri.

Her kategori için somut çözüm önerileri dokümanın sonunda sunulmaktadır.

---

## 2. Eksik Tool Kapasiteleri

### 2.1 Dosya Sistemi Operasyonları

**Mevcut durum:** `skills/filesystem.py` — `read_file`, `write_file`, `list_dir`, `create_dir`, `delete_file`

**Eksikler:**

| Eksik Kapasite | Açıklama | Etki |
|---|---|---|
| File watching | Dosya değişikliklerini izleme (inotify/FSEvents) yok | Agent dosya değişikliklerine reaktif olamıyor |
| Atomic writes | `write_file` atomik değil — yarıda kesilirse corrupt olabilir | Veri kaybı riski |
| File locking | Concurrent erişimde dosya kilitleme yok | Multi-thread/multi-agent çakışma |
| Binary file support | Sadece UTF-8 text okuma/yazma var | Resim, PDF, binary dosya işleyemez |
| Glob/pattern search | Dosya içeriğinde regex arama yok | `grep` için shell'e bağımlı |
| File metadata | Boyut, tarih, izinler gibi metadata okuma yok | Dosya yönetimi kısıtlı |
| Streaming read | Büyük dosyalar tamamen memory'ye yükleniyor | Memory overflow riski |

### 2.2 Network Operasyonları

**Mevcut durum:** `skills/web.py` — `web_search`, `fetch_url` (HTTP GET tabanlı)

**Eksikler:**

| Eksik Kapasite | Açıklama | Etki |
|---|---|---|
| WebSocket desteği | Gerçek zamanlı bağlantı kuramıyor | Canlı veri akışı (borsa, chat) imkansız |
| HTTP streaming | Büyük response'ları stream edemez | Timeout ve memory sorunları |
| POST/PUT/DELETE | Sadece GET var, REST API'lere tam erişim yok | API entegrasyonları kısıtlı |
| Rate limiting awareness | Kendi isteklerini throttle etmiyor | API ban riski |
| Proxy/VPN desteği | Network routing kontrolü yok | Geo-restricted içeriğe erişemez |
| DNS resolution | Özel DNS sorguları yapamıyor | Network diagnostics kısıtlı |
| Download manager | Büyük dosya indirme/resume desteği yok | İndirme güvenilirliği düşük |

### 2.3 Sistem Entegrasyonu

**Mevcut durum:** `skills/system_info.py` — temel OS bilgisi, `skills/shell.py` — komut çalıştırma

**Eksikler:**

| Eksik Kapasite | Açıklama | Etki |
|---|---|---|
| Clipboard erişimi | Panoya okuma/yazma yok | Kullanıcıyla veri paylaşımı kısıtlı |
| Notification sistemi | OS-level bildirim gönderemiyor | Uzun görevlerde kullanıcıyı bilgilendiremez |
| Process monitoring | Çalışan process'leri izleyemiyor | Kaynak yönetimi yapamaz |
| Service management | Systemd/Windows Service kontrolü yok | Daemon yönetimi kısıtlı |
| Environment isolation | Sanal ortam (venv) yönetimi otomatik değil | Dependency conflict riski |
| Scheduled execution | Cron var ama OS-level scheduler entegrasyonu yok | Platform bağımlı zamanlama |

### 2.4 Mevcut vs. İhtiyaç Duyulan Tool Matrisi

```
Kategori              Mevcut Tool Sayısı    Eksik (Tahmini)    Kapsam %
─────────────────────────────────────────────────────────────────────────
File System           5                     7                  ~42%
Network/Web           2                     7                  ~22%
Shell/System          2                     6                  ~25%
Memory                7                     3                  ~70%
Messaging             6                     2                  ~75%
Code Execution        6                     2                  ~75%
DevOps                3                     4                  ~43%
Security              4                     3                  ~57%
─────────────────────────────────────────────────────────────────────────
TOPLAM                35+                   34                 ~51%
```

**Sonuç:** Agent mevcut tool seti ile görevlerin yaklaşık yarısını bağımsız yapabilir.
Geri kalanı için shell komutlarına veya kullanıcı müdahalesine bağımlıdır.

---

## 3. Error Recovery Pattern Eksiklikleri

### 3.1 LLM Çağrı Hataları

**Mevcut durum:** `providers/fallback_provider.py` — tek seviye fallback (primary → secondary)

**Analiz edilen senaryolar:**

| Senaryo | Mevcut Davranış | Eksik |
|---|---|---|
| Rate limit (429) | Exception → fallback provider | Retry-after header'ı okunmuyor, exponential backoff yok |
| Timeout | Exception → fallback | Timeout süresi konfigüre edilemiyor, partial response kurtarılmıyor |
| Invalid JSON response | `RoutingDecision()` (boş) döner | Hatalı response loglanmıyor, pattern analizi yok |
| Context too long (413) | Exception → fallback | Otomatik context truncation yok, mesaj özetleme yok |
| Network disconnect | Exception → fallback | Reconnection stratejisi yok, offline queue yok |
| API key expired | Exception → fallback | Kullanıcıya bildirim yok, otomatik key rotation yok |

**Kritik eksiklikler:**

1. **Retry stratejisi yok:** `FallbackProvider` sadece bir kez dener, exponential backoff uygulamaz
2. **Circuit breaker yok:** Sürekli başarısız olan provider hâlâ deneniyor
3. **Partial response recovery yok:** Stream kesildiğinde alınan kısım kayboluyor
4. **Error classification yok:** Tüm hatalar aynı şekilde ele alınıyor (geçici vs. kalıcı ayrımı yok)

### 3.2 Tool Execution Hataları

**Mevcut durum:** `core.py` → `_execute_tool()` — try/except ile error string döner

```python
# Mevcut pattern (core.py:_execute_tool)
try:
    result = handler(**args)
    return result
except Exception as e:
    return f"Tool error ({name}): {e}"
```

**Eksikler:**

| Eksik Pattern | Açıklama |
|---|---|
| Retry logic | Geçici hatalar (network timeout, file lock) için yeniden deneme yok |
| Timeout enforcement | Tool çağrıları sınırsız süre çalışabilir (deadlock riski) |
| Graceful degradation | Bir tool başarısız olduğunda alternatif yol önerilmiyor |
| Error categorization | Tüm hatalar string olarak döner, yapısal hata bilgisi yok |
| Rollback | Yarıda kalan multi-step operasyonlar geri alınamıyor |
| Resource cleanup | Tool crash'inde açık dosya/connection temizlenmiyor |

### 3.3 Background Task Hataları

**Mevcut durum:** `skills/agents/background.py` → `_run_task()` — exception yakalanır, status ERROR olur

```python
# Mevcut pattern (background.py:_run_task)
try:
    for event in task.session.run(task.goal):
        task.event_queue.append(event)
        ...
    task.status = TaskStatus.DONE
except Exception as e:
    task.status = TaskStatus.ERROR
    task.error_message = str(e)
```

**Eksikler:**

| Eksik Pattern | Açıklama |
|---|---|
| Auto-restart | Crash olan task otomatik yeniden başlatılmıyor |
| Checkpoint/resume | Uzun görevler yarıda kalınca baştan başlamak zorunda |
| Health check | Çalışan task'ların "alive" olduğu doğrulanmıyor |
| Timeout | Sonsuz döngüye giren task tespit edilemiyor |
| Partial result save | Hata öncesi üretilen dosyalar korunmuyor/raporlanmıyor |
| Error escalation | Kritik hatalar kullanıcıya bildirilmiyor (sadece status değişiyor) |

### 3.4 Genel Recovery Pattern Eksiklikleri

- **Dead letter queue yok:** Başarısız mesajlar/görevler kaybolabiliyor
- **Graceful shutdown yok:** Agent kapanırken çalışan task'lar aniden sonlanıyor
- **State persistence yok:** Agent restart'ında in-flight görevler kayboluyor
- **Cascading failure protection yok:** Bir servisin çökmesi diğerlerini etkileyebilir

---

## 4. Context Management Sorunları

### 4.1 Token Limit Yönetimi

**Mevcut durum:** `core.py` → `MAX_CONTEXT_MESSAGES = 20` — sabit pencere

**Sorunlar:**

| Sorun | Detay |
|---|---|
| Sabit pencere boyutu | 20 mesaj limiti model'in token kapasitesine göre ayarlanmıyor |
| Token sayımı yok | Gerçek token kullanımı ölçülmüyor, sadece mesaj sayısı |
| Mesaj boyutu farkı | Kısa "evet" mesajı ile 5000 karakterlik tool sonucu aynı ağırlıkta |
| Model-aware değil | GPT-4o (128K) ile GPT-3.5 (16K) aynı pencere boyutunu kullanıyor |

### 4.2 Context Window Overflow

**Mevcut durum:** `_trim_messages()` — son N mesajı tutar, gerisini siler

**Sorunlar:**

- **Özetleme yok:** Eski mesajlar tamamen siliniyor, özet bile tutulmuyor
- **Öncelik sistemi yok:** Önemli mesajlar (kullanıcı kararları, hata çözümleri) ile
  rutin mesajlar aynı şekilde ele alınıyor
- **Tool sonuçları büyük:** Uzun tool çıktıları (dosya içerikleri, arama sonuçları)
  context'i hızla dolduruyor ama truncate edilmiyor
- **System prompt sabit:** Dinamik section'lar eklendikçe system prompt büyüyor,
  kullanıcı mesajları için yer azalıyor

### 4.3 Bilgi Kaybı

**Mevcut durum:**
- Working Memory: Son 20 event (ring buffer, `skills/working_memory.py`)
- Shared Memory: Kalıcı key-value store (`skills/shared_memory.py`)
- Session Memory: Konuşma geçmişi (`skills/session_memory.py`)

**Sorunlar:**

| Sorun | Detay |
|---|---|
| Working memory çok küçük | 20 event, yoğun tool kullanımında 2-3 dakikada doluyor |
| Otomatik özetleme yok | Eski context özetlenip saklanmıyor |
| Semantic search zayıf | `LIKE %query%` ile arama — embedding-based retrieval yok |
| Cross-session continuity | Yeni session'da önceki session'ın bağlamı otomatik yüklenmiyor |
| Goal tracking yok | Uzun görevlerde ana hedef context'ten düşebiliyor |
| Decision memory yok | Kullanıcının verdiği kararlar (tercihler) ayrıca saklanmıyor |

### 4.4 Memory Sistemi Limitleri

```
Katman              Kapasite        Persistence    Otomatik Inject
────────────────────────────────────────────────────────────────────
Working Memory      20 event        Session        ✅ Her prompt'a
Shared Memory       Sınırsız        Kalıcı         ❌ Sadece tool ile
Session Memory      Sınırsız        Kalıcı         ❌ Sadece tool ile
Error Memory        Session         Session        ✅ Coding mode'da
────────────────────────────────────────────────────────────────────
```

**Ana sorun:** Sadece Working Memory otomatik inject ediliyor. Shared Memory'deki
kritik bilgiler (kullanıcı tercihleri, proje bilgileri) agent'ın her zaman
erişebildiği context'te değil.

---

## 5. Prompt Optimization Fırsatları

### 5.1 Mevcut Token Kullanımı Analizi

```
Bileşen                          Tahmini Token    Her Çağrıda?
──────────────────────────────────────────────────────────────────
core/system.md (CORE_PROMPT)     ~350 token       ✅ Her zaman
sections/workspace.md            ~200 token       Keyword match
sections/code.md                 ~250 token       Keyword match
sections/web.md                  ~150 token       Keyword match
sections/shell.md                ~100 token       Keyword match
sections/memory.md               ~150 token       Keyword match
sections/agent.md                ~150 token       Keyword match
sections/security.md             ~150 token       Keyword match
sections/devops.md               ~100 token       Keyword match
sections/background.md           ~300 token       Keyword match
channels/{name}.md               ~100 token       Kanal varsa
Working Memory context           ~200-400 token   ✅ Her zaman
CWD bilgisi                      ~20 token        ✅ Her zaman
──────────────────────────────────────────────────────────────────
TOPLAM (worst case)              ~2,420 token     System prompt
```

### 5.2 Redundancy Analizi

**Tespit edilen tekrarlar:**

1. **"background" section çok geniş keyword match'i var:**
   ```python
   "background": ["background", "background task", "coding task", "delegate",
                   "long running", "write", "build", "create", "implement",
                   "fix", "refactor", "develop", "add", "modify", "update",
                   "generate", "code"]
   ```
   → "write", "code", "create" gibi genel kelimeler neredeyse her mesajda match ediyor.
   Bu section gereksiz yere çoğu çağrıya ekleniyor (~300 token israf).

2. **workspace + code default olarak ekleniyor:**
   ```python
   if not matched or len(user_input.strip()) < 10:
       matched.update({"workspace", "code"})
   ```
   → Kısa mesajlarda bile ~450 token ekleniyor.

3. **Section içerikleri arasında overlap:**
   - `shell.md` ve `code.md` arasında komut çalıştırma bilgisi tekrarı
   - `background.md` ve `agent.md` arasında sub-agent bilgisi tekrarı

### 5.3 Dinamik Section Loading Etkinliği

**Mevcut keyword matching sistemi sorunları:**

- **False positive oranı yüksek:** "write me a poem" → `background` section tetikleniyor ("write" keyword)
- **False negative:** "bana bir API yap" → Türkçe keyword'ler tanınmıyor
- **Çoklu dil desteği yok:** Keyword'ler sadece İngilizce
- **Intent-based değil:** Keyword matching, gerçek intent'i yakalayamıyor

**IntentRouter ile karşılaştırma:**
Router LLM-based classification yapıyor ama sonuçları prompt section seçiminde kullanılmıyor.
`RoutingDecision.prompt_sections` alanı var ama `build_system_prompt()` bunu almıyor.

### 5.4 Compression Fırsatları

| Fırsat | Potansiyel Tasarruf | Zorluk |
|---|---|---|
| Background section keyword daraltma | ~300 token/çağrı | Düşük |
| Section içerik sıkıştırma (daha kısa yazım) | ~20% (~400 token) | Orta |
| Router-driven section selection | ~500 token/çağrı | Orta |
| Working memory compact format | ~100 token | Düşük |
| Tool result truncation | ~200-1000 token | Düşük |
| Conditional default sections | ~200 token | Düşük |

**Toplam potansiyel tasarruf:** Çağrı başına ~700-1500 token (%30-60 azalma)

---

## 6. Dış Bağımlılıklar ve Fallback Stratejileri

### 6.1 LLM Provider Bağımlılığı

**Mevcut durum:** `providers/` dizininde 10+ provider var, `FallbackProvider` ile tek seviye yedekleme

```
Primary Provider (config'den)
    ↓ fail
Fallback Provider (config'den)
    ↓ fail
❌ Tamamen çalışamaz hale gelir
```

**Eksikler:**

| Eksik | Açıklama |
|---|---|
| Multi-level fallback | İkiden fazla provider zinciri yok |
| Provider health check | Hangi provider'ın çalıştığı önceden bilinmiyor |
| Local model fallback | İnternet kesildiğinde Ollama'ya otomatik geçiş yok |
| Degraded mode | LLM yokken bile basit komutları çalıştırabilme yok |
| Cost-aware routing | Ucuz model'e düşme stratejisi yok |
| Latency-based selection | En hızlı yanıt veren provider seçilmiyor |

### 6.2 Messaging API Bağımlılıkları

**Mevcut durum:** Telegram, Discord, WhatsApp — her biri kendi API'sine bağımlı

| Servis | Bağımlılık | Fallback |
|---|---|---|
| Telegram Bot API | `api.telegram.org` | ❌ Yok |
| Discord API | `discord.com/api` | ❌ Yok |
| WhatsApp (Twilio) | `api.twilio.com` | ❌ Yok |
| CLI | Lokal terminal | ✅ Her zaman çalışır |

**Eksikler:**
- Bir kanal çöktüğünde diğer kanala otomatik geçiş yok
- Mesaj kuyruğu yok — gönderilemeyen mesajlar kayboluyor
- Offline mesaj biriktirme yok

### 6.3 İnternet Bağlantısı Gereksinimleri

**Tamamen internet bağımlı özellikler:**
- LLM çağrıları (Ollama hariç tüm provider'lar)
- Web search / fetch
- Messaging (Telegram, Discord, WhatsApp)
- GitHub entegrasyonu
- Finance (kripto/borsa fiyatları)
- Social media
- Email

**İnternetsiz çalışabilen özellikler:**
- Dosya sistemi operasyonları
- Shell komutları
- Kanban/Cron (lokal SQLite)
- Memory (lokal SQLite)
- Code execution (lokal Python/Node)
- Ollama (lokal LLM)

**Sonuç:** Agent'ın ~%60'ı internet bağımlı. Ollama + lokal tool'lar ile
degraded mode mümkün ama otomatik geçiş mekanizması yok.

### 6.4 Diğer Dış Bağımlılıklar

| Bağımlılık | Kullanım | Risk | Fallback |
|---|---|---|---|
| SQLite | Memory, Kanban, Cron, Sessions | Düşük (lokal) | ❌ |
| Python runtime | Tüm agent | Düşük | ❌ |
| pip packages | openai, anthropic, httpx, vb. | Orta | ❌ |
| OS shell | Komut çalıştırma | Düşük | ❌ |
| Disk alanı | Dosya yazma, DB | Orta | ❌ Uyarı yok |
| ffmpeg | Media işleme | Yüksek (opsiyonel) | ✅ Hata mesajı |
| Git | DevOps | Orta (opsiyonel) | ✅ Hata mesajı |

---

## 7. Çözüm Önerileri

### 7.1 Eksik Tool Kapasiteleri İçin Çözümler

#### P1 — Yüksek Öncelik

**1. File watcher tool:**
```python
# Yeni tool: watch_file / watch_dir
# fswatch veya watchdog kütüphanesi ile
# Event-driven: dosya değiştiğinde callback tetikle
```
→ Hot-reload, otomatik test çalıştırma, log izleme için kritik.

**2. HTTP method desteği genişletme:**
```python
# fetch_url → http_request olarak genişlet
# Desteklenecek: GET, POST, PUT, DELETE, PATCH
# Headers, body, auth parametreleri
```
→ REST API entegrasyonları için zorunlu.

**3. File metadata ve glob search:**
```python
# Yeni tool: file_info(path) → size, mtime, permissions
# Yeni tool: find_files(pattern, path) → glob/regex ile arama
```
→ Shell bağımlılığını azaltır.

#### P2 — Orta Öncelik

**4. Atomic file writes:**
```python
# write_file → temp dosyaya yaz, sonra rename (atomic)
import tempfile, os
def write_file_atomic(path, content):
    dir_path = os.path.dirname(path)
    with tempfile.NamedTemporaryFile(mode='w', dir=dir_path, delete=False) as f:
        f.write(content)
        tmp = f.name
    os.replace(tmp, path)  # atomic on same filesystem
```

**5. Process monitoring tool:**
```python
# Yeni tool: list_processes(filter) → psutil ile
# Yeni tool: kill_process(pid)
# Yeni tool: process_info(pid) → CPU, memory, uptime
```

**6. Notification sistemi:**
```python
# Platform-aware bildirim:
# Windows → toast notification (win10toast)
# macOS → osascript
# Linux → notify-send
# + Telegram/Discord fallback
```

### 7.2 Error Recovery İçin Çözümler

#### P1 — Yüksek Öncelik

**1. Exponential backoff retry wrapper:**
```python
import time
from functools import wraps

def with_retry(max_retries=3, base_delay=1.0, max_delay=30.0,
               retryable_exceptions=(Exception,)):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as e:
                    if attempt == max_retries:
                        raise
                    delay = min(base_delay * (2 ** attempt), max_delay)
                    time.sleep(delay)
        return wrapper
    return decorator
```

**2. Circuit breaker pattern:**
```python
class CircuitBreaker:
    """Provider seviyesinde circuit breaker."""
    CLOSED, OPEN, HALF_OPEN = 0, 1, 2

    def __init__(self, failure_threshold=5, recovery_timeout=60):
        self.state = self.CLOSED
        self.failures = 0
        self.threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.last_failure_time = 0

    def can_execute(self) -> bool:
        if self.state == self.CLOSED:
            return True
        if self.state == self.OPEN:
            if time.time() - self.last_failure_time > self.recovery_timeout:
                self.state = self.HALF_OPEN
                return True
            return False
        return True  # HALF_OPEN: allow one attempt

    def record_success(self):
        self.failures = 0
        self.state = self.CLOSED

    def record_failure(self):
        self.failures += 1
        self.last_failure_time = time.time()
        if self.failures >= self.threshold:
            self.state = self.OPEN
```

**3. Multi-level fallback chain:**
```python
class FallbackChain(LLMProvider):
    """N-seviye provider zinciri, circuit breaker ile."""
    def __init__(self, providers: list[LLMProvider]):
        self.providers = providers
        self.breakers = {p.name: CircuitBreaker() for p in providers}

    def chat(self, messages, tools=None):
        for provider in self.providers:
            breaker = self.breakers[provider.name]
            if not breaker.can_execute():
                continue
            try:
                result = provider.chat(messages, tools=tools)
                breaker.record_success()
                return result
            except Exception as e:
                breaker.record_failure()
                logger.warning(f"{provider.name} failed: {e}")
        raise RuntimeError("All providers exhausted")
```

**4. Tool execution timeout:**
```python
import signal
from concurrent.futures import ThreadPoolExecutor, TimeoutError

_tool_executor = ThreadPoolExecutor(max_workers=4)

def execute_tool_with_timeout(handler, args, timeout=30):
    future = _tool_executor.submit(handler, **args)
    try:
        return future.result(timeout=timeout)
    except TimeoutError:
        future.cancel()
        return f"Tool timeout after {timeout}s"
```

#### P2 — Orta Öncelik

**5. Background task auto-restart:**
```python
# BackgroundTaskManager._run_task içine:
MAX_RETRIES = 2
for attempt in range(MAX_RETRIES + 1):
    try:
        # ... mevcut task execution ...
        break
    except Exception as e:
        if attempt < MAX_RETRIES:
            task.event_queue.append({"type": "retry", "attempt": attempt + 1})
            time.sleep(2 ** attempt)
        else:
            task.status = TaskStatus.ERROR
            task.error_message = str(e)
```

**6. Graceful shutdown handler:**
```python
import atexit, signal

def _shutdown_handler(signum=None, frame=None):
    """Çalışan task'ları düzgün sonlandır."""
    for task in _background_tasks.values():
        if task.status == TaskStatus.RUNNING:
            task.session.interrupt()
            task.status = TaskStatus.CANCELLED
    # Working memory'yi kaydet
    # Session'ı auto-save et

atexit.register(_shutdown_handler)
signal.signal(signal.SIGTERM, _shutdown_handler)
```

### 7.3 Context Management İçin Çözümler

#### P1 — Yüksek Öncelik

**1. Token-aware context windowing:**
```python
import tiktoken

def _trim_messages_token_aware(self, max_tokens: int = None) -> list[dict]:
    """Token sayısına göre context penceresi."""
    if max_tokens is None:
        max_tokens = self._get_model_context_limit() * 0.7  # %70 kullan

    enc = tiktoken.encoding_for_model(self._model)
    system = [m for m in self.messages if m["role"] == "system"]
    rest = [m for m in self.messages if m["role"] != "system"]

    system_tokens = sum(len(enc.encode(m["content"])) for m in system)
    budget = max_tokens - system_tokens

    # En yeni mesajlardan geriye doğru ekle
    selected = []
    used = 0
    for msg in reversed(rest):
        msg_tokens = len(enc.encode(msg.get("content", "") or ""))
        if used + msg_tokens > budget:
            break
        selected.insert(0, msg)
        used += msg_tokens

    return system + selected
```

**2. Otomatik context özetleme:**
```python
def _summarize_old_messages(self, messages: list[dict]) -> str:
    """Eski mesajları LLM ile özetle, context'e ekle."""
    summary_prompt = [
        {"role": "system", "content": "Summarize this conversation in 2-3 sentences. Keep key decisions and facts."},
        {"role": "user", "content": "\n".join(m.get("content","")[:200] for m in messages)}
    ]
    # Ucuz/hızlı model ile özetle
    response = self._summary_provider.chat(summary_prompt)
    return response.get("content", "")
```

**3. Tool result truncation:**
```python
MAX_TOOL_RESULT_TOKENS = 2000

def _truncate_tool_result(result: str, max_tokens: int = MAX_TOOL_RESULT_TOKENS) -> str:
    """Uzun tool sonuçlarını kırp, başı ve sonunu koru."""
    enc = tiktoken.encoding_for_model("gpt-4o")
    tokens = enc.encode(result)
    if len(tokens) <= max_tokens:
        return result
    # İlk %60 + son %40 stratejisi
    head = enc.decode(tokens[:int(max_tokens * 0.6)])
    tail = enc.decode(tokens[-int(max_tokens * 0.4):])
    return f"{head}\n\n[... {len(tokens) - max_tokens} tokens truncated ...]\n\n{tail}"
```

#### P2 — Orta Öncelik

**4. Goal tracking sistemi:**
```python
# Working memory'ye "goal" event tipi ekle
# Her conversation başında ana hedefi kaydet
# Context'e her zaman inject et
def set_goal(self, goal: str):
    working_memory.wm_add(summary=f"GOAL: {goal}", event_type="goal")

# wm_get_context'te goal'ü her zaman en üste koy
```

**5. Semantic memory search (embedding-based):**
```python
# shared_memory'ye embedding kolonu ekle
# sentence-transformers ile lokal embedding
# Cosine similarity ile arama
# Mevcut LIKE %query% yerine veya yanında
```

**6. Auto-inject relevant shared memories:**
```python
def _refresh_memory_context(self, user_input: str):
    # Mevcut: sadece working memory inject
    # Yeni: shared memory'den de relevant entries inject et
    relevant = shared_memory.get_relevant_context(user_input, limit=3)
    if relevant:
        wm_ctx += "\n" + relevant
```

### 7.4 Prompt Optimization İçin Çözümler

#### P1 — Yüksek Öncelik

**1. Background section keyword daraltma:**
```python
# Mevcut (çok geniş):
"background": ["background", "background task", "coding task", "delegate",
               "long running", "write", "build", "create", "implement",
               "fix", "refactor", "develop", "add", "modify", "update",
               "generate", "code"]

# Önerilen (dar ve spesifik):
"background": ["background task", "coding task", "delegate", "long running",
               "in the background", "arka planda", "kod yaz", "proje oluştur"]
```
→ Tahmini tasarruf: Çağrıların ~%70'inde 300 token.

**2. Router-driven section selection:**
```python
def build_system_prompt(user_input="", extra_context="", channel="",
                        routing_decision: RoutingDecision = None) -> str:
    """Router'ın önerdiği section'ları kullan, keyword fallback ile."""
    if routing_decision and routing_decision.prompt_sections:
        matched = set(routing_decision.prompt_sections)
    else:
        # Mevcut keyword matching (fallback)
        matched = _keyword_match(user_input)
    ...
```
→ Daha doğru section seçimi, daha az false positive.

**3. Lazy section content (on-demand loading):**
```python
# Section'ları her zaman string olarak tutmak yerine,
# sadece isimleri belirle, build sırasında yükle
# Bu zaten PromptLoader cache ile hızlı
```

#### P2 — Orta Öncelik

**4. Section içerik sıkıştırma:**
- Her section'ı gözden geçir, gereksiz açıklamaları kaldır
- Bullet point'leri daha kısa yaz
- Örnekleri minimize et (LLM zaten anlıyor)

**5. Conditional defaults:**
```python
# Mevcut: kısa input → workspace + code ekleniyor
# Önerilen: kısa input → sadece core prompt, section ekleme
if not matched and len(user_input.strip()) < 10:
    pass  # Sadece core prompt yeterli
```

**6. Working memory compact format:**
```python
# Mevcut: "  🔧 [14:32] run_command(cmd=pip install flask)"
# Önerilen: "T14:32 run_command(pip install flask)"
# ~%30 daha kısa
```

### 7.5 Dış Bağımlılık Fallback Stratejileri

#### P1 — Yüksek Öncelik

**1. Otomatik Ollama fallback:**
```python
# config.yaml'a ekle:
# offline_fallback: ollama
# offline_model: llama3

class ProviderFactory:
    @staticmethod
    def create_with_offline_fallback(cfg: dict) -> LLMProvider:
        primary = create_provider(cfg)
        fallback = create_provider(cfg.get("fallback", {}))
        # Ollama her zaman son çare
        ollama = OllamaProvider({"model": cfg.get("offline_model", "llama3")})
        return FallbackChain([primary, fallback, ollama])
```

**2. Message queue (offline buffer):**
```python
class MessageQueue:
    """Gönderilemyen mesajları biriktir, bağlantı gelince gönder."""
    def __init__(self, db_path: str):
        self._init_table(db_path)

    def enqueue(self, channel: str, content: str, metadata: dict = None):
        """Mesajı kuyruğa ekle."""
        ...

    def flush(self, channel: str) -> int:
        """Kuyruktaki mesajları gönder, başarılı olanları sil."""
        ...

    def pending_count(self, channel: str = None) -> int:
        ...
```

**3. Health check daemon:**
```python
class HealthChecker:
    """Periyodik olarak provider'ları ve servisleri kontrol et."""
    def __init__(self, check_interval=60):
        self._status: dict[str, bool] = {}
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def _check_provider(self, provider: LLMProvider) -> bool:
        try:
            provider.chat([{"role": "user", "content": "ping"}])
            return True
        except:
            return False

    def is_healthy(self, service_name: str) -> bool:
        return self._status.get(service_name, False)
```

#### P2 — Orta Öncelik

**4. Cross-channel failover:**
```python
# Telegram çöktüğünde Discord'a geç (veya tersi)
CHANNEL_PRIORITY = ["telegram", "discord", "whatsapp", "cli"]

def send_with_failover(message: str, preferred_channel: str = None):
    channels = [preferred_channel] + CHANNEL_PRIORITY if preferred_channel else CHANNEL_PRIORITY
    for ch in channels:
        try:
            return messaging.send(ch, message)
        except Exception:
            continue
    # Son çare: lokal dosyaya yaz
    Path("~/.Koza/unsent_messages.log").expanduser().open("a").write(f"{message}\n")
```

**5. Degraded mode (LLM'siz çalışma):**
```python
# LLM tamamen erişilemez olduğunda:
# - Basit komutları regex ile parse et ("dosya oku X", "komut çalıştır Y")
# - Cron job'ları çalışmaya devam etsin
# - Mesaj kuyruğu biriktirsin
# - Kullanıcıya "degraded mode" bildirimi gönder
```

**6. Disk alanı monitoring:**
```python
import shutil

def check_disk_space(min_free_mb: int = 100) -> bool:
    """Yeterli disk alanı var mı kontrol et."""
    usage = shutil.disk_usage("/")
    free_mb = usage.free / (1024 * 1024)
    if free_mb < min_free_mb:
        logger.warning(f"Low disk space: {free_mb:.0f}MB free")
        return False
    return True
```

---

## 8. Öncelik Matrisi ve Uygulama Yol Haritası

### Acil (Sprint 1 — 1 hafta)
1. Background section keyword daraltma (5 dk, ~300 token/çağrı tasarruf)
2. Tool result truncation (2 saat, context overflow önleme)
3. Exponential backoff retry (3 saat, LLM güvenilirliği)

### Kısa Vade (Sprint 2-3 — 2 hafta)
4. Circuit breaker pattern (4 saat)
5. Token-aware context windowing (6 saat)
6. Multi-level fallback chain (4 saat)
7. HTTP method genişletme (3 saat)
8. Tool execution timeout (2 saat)

### Orta Vade (Sprint 4-6 — 1 ay)
9. Router-driven section selection (8 saat)
10. Otomatik context özetleme (1 gün)
11. Message queue / offline buffer (1 gün)
12. File watcher tool (6 saat)
13. Graceful shutdown (4 saat)

### Uzun Vade (Backlog)
14. Semantic memory search (embedding-based)
15. Degraded mode (LLM'siz çalışma)
16. Cross-channel failover
17. Background task checkpoint/resume
18. Notification sistemi

---

## 9. Sonuç

Koza agent'ı mevcut haliyle **yarı-otonom** çalışabilir durumdadır. Temel eksiklikler:

1. **Error recovery** — Tek seviye fallback yeterli değil; retry, circuit breaker ve timeout gerekli
2. **Context management** — Token-aware windowing ve özetleme olmadan uzun session'lar verimsiz
3. **Prompt efficiency** — Background section'ın geniş keyword match'i gereksiz token harcıyor
4. **Offline resilience** — İnternet kesildiğinde agent tamamen duruyor

Bu eksikliklerin giderilmesi ile agent'ın self-sufficiency skoru tahminen **%51 → %80+** seviyesine çıkabilir.
En yüksek ROI, Sprint 1'deki 3 değişiklikten gelecektir (minimal effort, maksimum etki).
