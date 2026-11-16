import base64
import binascii
import ctypes
import os
from ctypes import wintypes

import webview


APP_TITLE = "Base64 编码 / 解码器"


# ==========================================================================
# 编解码核心
# ==========================================================================
def encode_text_b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def decode_to_bytes(text: str) -> bytes:
    s = (text or "").strip()
    if s.lower().startswith("data:") and "," in s:
        s = s.split(",", 1)[1]
    s = "".join(s.split())
    if not s:
        return b""
    s = s.replace("-", "+").replace("_", "/")
    pad = (-len(s)) % 4
    if pad:
        s += "=" * pad
    try:
        return base64.b64decode(s, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"不是有效的 Base64 数据：{exc}") from exc


def wrap76(s: str) -> str:
    return "\n".join(s[i:i + 76] for i in range(0, len(s), 76))


# ==========================================================================
# 标题栏深色（尽力而为，失败静默）
# ==========================================================================
def _try_set_titlebar_dark(hwnd: int, dark: bool):
    try:
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        value = ctypes.c_int(1 if dark else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            ctypes.c_int(DWMWA_USE_IMMERSIVE_DARK_MODE),
            ctypes.byref(value),
            ctypes.sizeof(value),
        )
    except Exception:
        pass


# ==========================================================================
# JS 桥接 API
# ==========================================================================
class Api:
    def __init__(self):
        self._window = None

    def bind(self, window):
        self._window = window

    # ---------- 文本 ----------
    def encode_text(self, text: str):
        try:
            out = encode_text_b64(text or "")
            return {"ok": True, "data": out, "inLen": len(text or ""), "outLen": len(out)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def decode_text(self, text: str):
        try:
            data = decode_to_bytes(text or "")
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        warn = None
        try:
            result = data.decode("utf-8")
        except UnicodeDecodeError:
            result = data.decode("utf-8", errors="replace")
            warn = "不是有效的 UTF-8 文本，已用替换字符显示"
        return {"ok": True, "data": result, "bytes": len(data), "warn": warn}

    # ---------- 文件 ----------
    def pick_open_file(self):
        try:
            result = self._window.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=False,
                file_types=("所有文件 (*.*)", "Base64 文件 (*.b64;*.txt)"),
            )
        except Exception:
            return None
        if isinstance(result, (list, tuple)):
            return result[0] if result else None
        return result

    def pick_save_file(self, default_name: str = "", save_ext: str = ""):
        ft = ("所有文件 (*.*)",)
        if save_ext:
            ft = (f"Base64 文件 (*.{save_ext.lstrip('.')})", "所有文件 (*.*)")
        try:
            result = self._window.create_file_dialog(
                webview.SAVE_DIALOG,
                save_filename=default_name or "",
                file_types=ft,
            )
        except Exception:
            return None
        if isinstance(result, (list, tuple)):
            return result[0] if result else None
        return result

    def encode_file(self, path: str, wrap: bool, want_content: bool):
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        b64 = base64.b64encode(data).decode("ascii")
        if wrap:
            b64 = wrap76(b64)
        shown = bool(want_content and len(b64) <= 2_000_000)
        return {
            "ok": True,
            "size": len(data),
            "b64len": len(b64),
            "shown": shown,
            "data": b64 if shown else "",
            "path": path,
        }

    def save_encoded_file(self, src: str, wrap: bool):
        try:
            with open(src, "rb") as f:
                data = f.read()
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        b64 = base64.b64encode(data).decode("ascii")
        if wrap:
            b64 = wrap76(b64)
        target = self.pick_save_file(os.path.basename(src) + ".b64", ".b64")
        if not target:
            return {"ok": False, "canceled": True}
        try:
            with open(target, "w", encoding="ascii", newline="\n") as f:
                f.write(b64)
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "target": target, "size": len(data)}

    def decode_file_to(self, src: str, dst: str = ""):
        try:
            with open(src, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
            data = decode_to_bytes(text)
        except (OSError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}
        if not dst:
            base = src[:-4] if src.lower().endswith(".b64") else src + ".decoded"
            dst = self.pick_save_file(os.path.basename(base), "")
            if not dst:
                return {"ok": False, "canceled": True}
        try:
            with open(dst, "wb") as f:
                f.write(data)
        except OSError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "target": dst, "size": len(data)}

    # ---------- 主题 ----------
    def set_theme(self, dark: bool):
        try:
            gui = self._window.gui
            win = getattr(gui, "window", None)
            if win is not None:
                hwnd = getattr(win, "Handle", None) or getattr(win, "native_handle", None)
                if hwnd:
                    _try_set_titlebar_dark(int(hwnd), bool(dark))
        except Exception:
            pass
        return {"ok": True}


# ==========================================================================
# 前端（WinUI3 Fluent 风格）
# ==========================================================================
HTML = r"""<!DOCTYPE html>
<html lang="zh-CN" data-theme="light">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Base64 编码 / 解码器</title>
<style>
  :root {
    --bg-window: #F3F3F3;
    --bg-card: #FFFFFF;
    --bg-control: #FBFBFB;
    --bg-hover: rgba(0,0,0,0.04);
    --bg-pressed: rgba(0,0,0,0.08);
    --bg-input: #FFFFFF;
    --border: #E5E5E5;
    --border-strong: #C8C8C8;
    --text: #1A1A1A;
    --text-2: #5E5E5E;
    --text-3: #8A8A8A;
    --accent: #0067C0;
    --accent-hover: #0078D4;
    --accent-text: #FFFFFF;
    --danger: #C42B1C;
    --success: #0F7B0F;
    --shadow: 0 2px 8px rgba(0,0,0,0.06);
  }
  [data-theme="dark"] {
    --bg-window: #202020;
    --bg-card: #2C2C2C;
    --bg-control: #282828;
    --bg-hover: rgba(255,255,255,0.06);
    --bg-pressed: rgba(255,255,255,0.10);
    --bg-input: #1E1E1E;
    --border: #3A3A3A;
    --border-strong: #555555;
    --text: #FFFFFF;
    --text-2: #B0B0B0;
    --text-3: #808080;
    --accent: #60CDFF;
    --accent-hover: #79D5FF;
    --accent-text: #000000;
    --danger: #FF99A4;
    --success: #6CCB5F;
    --shadow: 0 2px 8px rgba(0,0,0,0.4);
  }

  * { box-sizing: border-box; }
  html, body {
    margin: 0; padding: 0; height: 100%;
    font-family: "Segoe UI Variable Display", "Segoe UI", "Microsoft YaHei", system-ui, sans-serif;
    font-size: 14px;
    color: var(--text);
    background: var(--bg-window);
    overflow: hidden;
    -webkit-font-smoothing: antialiased;
  }
  .app {
    display: grid;
    grid-template-columns: 220px 1fr;
    height: 100vh;
    transition: background 0.2s, color 0.2s;
  }

  /* ---- NavigationView 风格侧栏 ---- */
  .nav {
    background: var(--bg-card);
    border-right: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    padding: 12px 8px;
    transition: background 0.2s, border-color 0.2s;
  }
  .nav-header {
    display: flex; align-items: center; gap: 10px;
    padding: 8px 10px 16px;
  }
  .logo {
    width: 32px; height: 32px;
    border-radius: 8px;
    background: var(--accent);
    color: var(--accent-text);
    display: flex; align-items: center; justify-content: center;
    font-weight: 700; font-size: 13px; letter-spacing: 0.5px;
  }
  .nav-title { font-weight: 600; font-size: 14px; }

  .nav-items { display: flex; flex-direction: column; gap: 2px; flex: 1; }
  .nav-item {
    appearance: none; border: none; background: transparent;
    color: var(--text); text-align: left;
    padding: 9px 12px; font-size: 14px;
    border-radius: 4px; cursor: pointer;
    position: relative; font-family: inherit;
    transition: background 0.12s;
  }
  .nav-item:hover  { background: var(--bg-hover); }
  .nav-item:active { background: var(--bg-pressed); }
  .nav-item.active { background: var(--bg-hover); font-weight: 600; }
  .nav-item.active::before {
    content: ""; position: absolute;
    left: 0; top: 50%; transform: translateY(-50%);
    width: 3px; height: 16px;
    background: var(--accent);
    border-radius: 0 2px 2px 0;
  }

  .nav-footer { padding-top: 8px; }
  .theme-btn {
    width: 100%; appearance: none;
    border: 1px solid var(--border);
    background: var(--bg-control); color: var(--text);
    padding: 9px 12px; border-radius: 4px;
    font-size: 13px; cursor: pointer;
    display: flex; align-items: center; gap: 10px;
    font-family: inherit;
    transition: background 0.12s, border-color 0.12s;
  }
  .theme-btn:hover  { background: var(--bg-hover); }
  .theme-btn:active { background: var(--bg-pressed); }
  .theme-icon {
    display: inline-block; width: 16px; height: 16px;
    border-radius: 50%;
    background: linear-gradient(135deg, #FFB900, #FF8C00);
  }
  [data-theme="dark"] .theme-icon {
    background: linear-gradient(135deg, #60CDFF, #0078D4);
  }

  /* ---- 内容区 ---- */
  .content { overflow-y: auto; padding: 24px 28px; }
  .page { display: none; animation: fadeIn 0.18s ease; }
  .page.active { display: block; }
  @keyframes fadeIn {
    from { opacity: 0; transform: translateY(4px); }
    to   { opacity: 1; transform: translateY(0); }
  }
  .page-header { margin-bottom: 16px; }
  .page-title { font-size: 22px; font-weight: 600; margin: 0 0 4px; }
  .page-desc  { color: var(--text-2); font-size: 13px; margin: 0; }

  /* ---- 卡片 ---- */
  .card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 8px; padding: 16px;
    box-shadow: var(--shadow); margin-bottom: 16px;
    transition: background 0.2s, border-color 0.2s;
  }
  .card-label {
    font-size: 12px; font-weight: 600; color: var(--text-2);
    margin-bottom: 8px; text-transform: uppercase; letter-spacing: 0.4px;
  }

  /* ---- TextBox（底部强调色，仿 WinUI3） ---- */
  textarea, .file-path {
    width: 100%;
    background: var(--bg-input); color: var(--text);
    border: 1px solid var(--border);
    border-bottom: 2px solid var(--border-strong);
    border-radius: 4px 4px 0 0;
    padding: 10px 12px;
    font-family: "Cascadia Mono", "Consolas", "Microsoft YaHei", monospace;
    font-size: 13px; line-height: 1.5;
    outline: none;
    transition: border-color 0.12s, background 0.2s;
  }
  textarea { min-height: 130px; resize: vertical; }
  textarea:focus, .file-path:focus {
    border-bottom-color: var(--accent);
  }
  textarea[readonly] { background: var(--bg-control); cursor: default; }
  .file-path {
    flex: 1; min-height: 34px;
    display: block;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .file-path::placeholder { color: var(--text-3); }

  /* ---- 按钮 ---- */
  .btn {
    appearance: none;
    border: 1px solid var(--border);
    background: var(--bg-control); color: var(--text);
    padding: 7px 18px; min-height: 32px;
    border-radius: 4px; font-size: 13px; font-weight: 500;
    cursor: pointer; font-family: inherit;
    display: inline-flex; align-items: center; gap: 6px;
    transition: background 0.12s, border-color 0.12s, transform 0.05s;
  }
  .btn:hover  { background: var(--bg-hover); }
  .btn:active { background: var(--bg-pressed); transform: scale(0.99); }
  .btn-primary {
    background: var(--accent); color: var(--accent-text); border-color: transparent;
  }
  .btn-primary:hover { background: var(--accent-hover); }
  .btn-row {
    display: flex; gap: 8px; margin-top: 12px;
    flex-wrap: wrap; align-items: center;
  }
  .spacer { flex: 1; }
  .hint { font-size: 12px; color: var(--text-3); }

  .checkbox {
    display: inline-flex; align-items: center; gap: 6px;
    font-size: 13px; cursor: pointer; color: var(--text);
  }
  .checkbox input { accent-color: var(--accent); width: 16px; height: 16px; }

  .file-row { display: flex; gap: 8px; align-items: stretch; }

  /* ---- Toast ---- */
  .toast-container {
    position: fixed; bottom: 20px; left: 50%;
    transform: translateX(-50%);
    display: flex; flex-direction: column; gap: 8px;
    z-index: 9999; pointer-events: none;
  }
  .toast {
    background: var(--bg-card); color: var(--text);
    border: 1px solid var(--border);
    border-radius: 6px; padding: 10px 16px; font-size: 13px;
    box-shadow: 0 6px 24px rgba(0,0,0,0.18);
    animation: toastIn 0.2s ease;
    pointer-events: auto;
    max-width: 520px; word-break: break-all;
  }
  .toast.success { border-left: 4px solid var(--success); }
  .toast.error   { border-left: 4px solid var(--danger); }
  @keyframes toastIn {
    from { opacity: 0; transform: translateY(10px); }
    to   { opacity: 1; transform: translateY(0); }
  }

  ::-webkit-scrollbar { width: 10px; height: 10px; }
  ::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 5px; }
  ::-webkit-scrollbar-thumb:hover { background: var(--text-3); }
  ::-webkit-scrollbar-track { background: transparent; }
</style>
</head>
<body>
<div class="app">
  <nav class="nav">
    <div class="nav-header">
      <div class="logo">B64</div>
      <div class="nav-title">Base64 工具</div>
    </div>
    <div class="nav-items">
      <button class="nav-item active" data-tab="te">文本编码</button>
      <button class="nav-item" data-tab="td">文本解码</button>
      <button class="nav-item" data-tab="fe">文件编码</button>
      <button class="nav-item" data-tab="fd">文件解码</button>
    </div>
    <div class="nav-footer">
      <button class="theme-btn" id="themeBtn" title="切换深色 / 浅色">
        <span class="theme-icon"></span>
        <span id="themeLabel">深色模式</span>
      </button>
    </div>
  </nav>

  <main class="content">
    <!-- 文本编码 -->
    <section id="te" class="page active">
      <div class="page-header">
        <h1 class="page-title">文本编码</h1>
        <p class="page-desc">把 UTF-8 文本编码为 Base64 字符串</p>
      </div>
      <div class="card">
        <div class="card-label">原文</div>
        <textarea id="te-in" placeholder="在此输入要编码的文本…"></textarea>
      </div>
      <div class="btn-row">
        <button class="btn btn-primary" id="te-run">编码</button>
        <button class="btn" id="te-clear">清空</button>
        <div class="spacer"></div>
        <span class="hint" id="te-hint"></span>
      </div>
      <div class="card" style="margin-top:16px">
        <div class="card-label">Base64 结果</div>
        <textarea id="te-out" readonly placeholder="结果会显示在这里"></textarea>
      </div>
      <div class="btn-row">
        <button class="btn" id="te-copy">复制结果</button>
      </div>
    </section>

    <!-- 文本解码 -->
    <section id="td" class="page">
      <div class="page-header">
        <h1 class="page-title">文本解码</h1>
        <p class="page-desc">把 Base64 字符串还原为 UTF-8 文本（兼容换行、空格、URL-safe）</p>
      </div>
      <div class="card">
        <div class="card-label">Base64 字符串</div>
        <textarea id="td-in" placeholder="在此粘贴 Base64…"></textarea>
      </div>
      <div class="btn-row">
        <button class="btn btn-primary" id="td-run">解码</button>
        <button class="btn" id="td-clear">清空</button>
        <div class="spacer"></div>
        <span class="hint" id="td-hint"></span>
      </div>
      <div class="card" style="margin-top:16px">
        <div class="card-label">解码结果</div>
        <textarea id="td-out" readonly placeholder="结果会显示在这里"></textarea>
      </div>
      <div class="btn-row">
        <button class="btn" id="td-copy">复制结果</button>
      </div>
    </section>

    <!-- 文件编码 -->
    <section id="fe" class="page">
      <div class="page-header">
        <h1 class="page-title">文件编码</h1>
        <p class="page-desc">选择任意文件，生成 Base64 内容或保存为 .b64 文件</p>
      </div>
      <div class="card">
        <div class="card-label">源文件</div>
        <div class="file-row">
          <input class="file-path" id="fe-path" readonly placeholder="尚未选择文件" />
          <button class="btn" id="fe-browse">浏览…</button>
        </div>
      </div>
      <div class="btn-row">
        <label class="checkbox">
          <input type="checkbox" id="fe-wrap" checked />
          每 76 字符换行
        </label>
        <div class="spacer"></div>
        <span class="hint" id="fe-hint"></span>
      </div>
      <div class="btn-row">
        <button class="btn btn-primary" id="fe-run">编码并显示</button>
        <button class="btn" id="fe-save">编码并保存 .b64</button>
      </div>
      <div class="card" style="margin-top:16px">
        <div class="card-label">Base64 结果</div>
        <textarea id="fe-out" readonly placeholder="结果会显示在这里" style="min-height:180px"></textarea>
      </div>
      <div class="btn-row">
        <button class="btn" id="fe-copy">复制结果</button>
      </div>
    </section>

    <!-- 文件解码 -->
    <section id="fd" class="page">
      <div class="page-header">
        <h1 class="page-title">文件解码</h1>
        <p class="page-desc">把 Base64 文件还原为原始二进制文件</p>
      </div>
      <div class="card">
        <div class="card-label">Base64 文件</div>
        <div class="file-row">
          <input class="file-path" id="fd-path" readonly placeholder="尚未选择文件" />
          <button class="btn" id="fd-browse">浏览…</button>
        </div>
      </div>
      <div class="btn-row">
        <button class="btn btn-primary" id="fd-run">解码并保存</button>
        <div class="spacer"></div>
        <span class="hint" id="fd-hint"></span>
      </div>
      <div class="card" style="margin-top:16px">
        <div class="card-label">日志</div>
        <textarea id="fd-log" readonly placeholder="操作日志" style="min-height:140px"></textarea>
      </div>
    </section>
  </main>
</div>

<div class="toast-container" id="toasts"></div>

<script>
  const $ = id => document.getElementById(id);

  function toast(msg, type = "") {
    const el = document.createElement("div");
    el.className = "toast " + type;
    el.textContent = msg;
    $("toasts").appendChild(el);
    setTimeout(() => {
      el.style.transition = "opacity 0.3s";
      el.style.opacity = "0";
      setTimeout(() => el.remove(), 300);
    }, 2600);
  }

  async function copyText(text) {
    if (!text) return toast("没有内容可复制", "error");
    try {
      await navigator.clipboard.writeText(text);
      toast("已复制到剪贴板", "success");
    } catch {
      const ta = document.createElement("textarea");
      ta.value = text; document.body.appendChild(ta);
      ta.select(); document.execCommand("copy"); ta.remove();
      toast("已复制到剪贴板", "success");
    }
  }

  // ---- 主题 ----
  const root = document.documentElement;
  function applyTheme(theme) {
    root.setAttribute("data-theme", theme);
    $("themeLabel").textContent = theme === "dark" ? "浅色模式" : "深色模式";
    try { pywebview.api.set_theme(theme === "dark"); } catch (e) {}
  }
  const prefersDark = window.matchMedia &&
                      window.matchMedia("(prefers-color-scheme: dark)").matches;
  applyTheme(prefersDark ? "dark" : "light");
  $("themeBtn").addEventListener("click", () => {
    applyTheme(root.getAttribute("data-theme") === "dark" ? "light" : "dark");
  });

  // ---- 标签切换 ----
  document.querySelectorAll(".nav-item").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".nav-item").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      document.querySelectorAll(".page").forEach(p => p.classList.remove("active"));
      $(btn.dataset.tab).classList.add("active");
    });
  });

  // ---- 文本编码 ----
  $("te-run").addEventListener("click", async () => {
    const r = await pywebview.api.encode_text($("te-in").value);
    if (!r.ok) return toast("编码失败：" + r.error, "error");
    $("te-out").value = r.data;
    $("te-hint").textContent = `${r.inLen} 字符 → ${r.outLen} 字符`;
  });
  $("te-clear").addEventListener("click", () => {
    $("te-in").value = ""; $("te-out").value = ""; $("te-hint").textContent = "";
  });
  $("te-copy").addEventListener("click", () => copyText($("te-out").value));

  // ---- 文本解码 ----
  $("td-run").addEventListener("click", async () => {
    const r = await pywebview.api.decode_text($("td-in").value);
    if (!r.ok) return toast("解码失败：" + r.error, "error");
    $("td-out").value = r.data;
    $("td-hint").textContent = r.warn ? `${r.bytes} 字节（含非 UTF-8）` : `${r.bytes} 字节`;
    if (r.warn) toast(r.warn, "error");
  });
  $("td-clear").addEventListener("click", () => {
    $("td-in").value = ""; $("td-out").value = ""; $("td-hint").textContent = "";
  });
  $("td-copy").addEventListener("click", () => copyText($("td-out").value));

  // ---- 文件编码 ----
  let fePath = "";
  $("fe-browse").addEventListener("click", async () => {
    const p = await pywebview.api.pick_open_file();
    if (!p) return;
    fePath = p;
    $("fe-path").value = p;
  });
  $("fe-run").addEventListener("click", async () => {
    if (!fePath) return toast("请先选择文件", "error");
    const r = await pywebview.api.encode_file(fePath, $("fe-wrap").checked, true);
    if (!r.ok) return toast("编码失败：" + r.error, "error");
    if (r.shown) {
      $("fe-out").value = r.data;
      $("fe-hint").textContent = `${r.size} 字节 → ${r.b64len} 字符`;
      toast("编码完成", "success");
    } else {
      $("fe-out").value = "";
      $("fe-hint").textContent = `${r.size} 字节（内容过大，未显示）`;
      toast("文件过大，请改用“保存 .b64”", "error");
    }
  });
  $("fe-save").addEventListener("click", async () => {
    if (!fePath) return toast("请先选择文件", "error");
    const r = await pywebview.api.save_encoded_file(fePath, $("fe-wrap").checked);
    if (r.canceled) return;
    if (!r.ok) return toast("保存失败：" + r.error, "error");
    toast(`已保存到 ${r.target}（原始 ${r.size} 字节）`, "success");
  });
  $("fe-copy").addEventListener("click", () => copyText($("fe-out").value));

  // ---- 文件解码 ----
  let fdPath = "";
  $("fd-browse").addEventListener("click", async () => {
    const p = await pywebview.api.pick_open_file();
    if (!p) return;
    fdPath = p;
    $("fd-path").value = p;
  });
  $("fd-run").addEventListener("click", async () => {
    if (!fdPath) return toast("请先选择文件", "error");
    const r = await pywebview.api.decode_file_to(fdPath, "");
    if (r.canceled) return;
    if (!r.ok) {
      $("fd-log").value += `✘ 解码失败：${r.error}\n`;
      return toast("解码失败：" + r.error, "error");
    }
    $("fd-log").value += `✔ 解码成功\n  源文件：${fdPath}\n  输出：  ${r.target}\n  大小：  ${r.size} 字节\n\n`;
    $("fd-hint").textContent = `已还原 ${r.size} 字节`;
    toast("解码完成", "success");
  });
</script>
</body>
</html>
"""


# ==========================================================================
# 启动
# ==========================================================================
def main():
    api = Api()
    window = webview.create_window(
        APP_TITLE,
        html=HTML,
        js_api=api,
        width=980,
        height=680,
        min_size=(860, 560),
        background_color="#F3F3F3",
    )
    api.bind(window)
    webview.start(debug=False)


if __name__ == "__main__":
    main()