#!/usr/bin/env python3
"""
Unified C64 AI Proxy Server with tkinter GUI.
Supports Claude, Gemini, OpenAI, Ollama, and LM Studio backends with dynamic model discovery.
Single port 6464, bind 0.0.0.0.
Pure Python stdlib + tkinter — no pip installs needed.
"""

import socket
import threading
import json
import urllib.request
import urllib.error
import os
import textwrap
import re
import tkinter as tk
from tkinter import scrolledtext
from datetime import datetime

# ---------------------------------------------------------------------------
# Utility functions (from existing proxies)
# ---------------------------------------------------------------------------

def clean_for_c64(text):
    """
    Strips complex unicode characters and normalizes for standard
    retro terminal displays (such as ASCII over CCGMS or PETSCII).
    We use standard ASCII. Most C64 WiFi modem setups translate standard ASCII to PETSCII.
    """
    cleaned = text.encode('ascii', 'ignore').decode('ascii')
    cleaned = cleaned.replace('**', '')
    cleaned = cleaned.replace('```', '---')
    # Collapse multiple spaces into one
    cleaned = re.sub(r' {2,}', ' ', cleaned)
    cleaned = cleaned.upper()
    return cleaned


def wrap_text(text, width=39):
    """
    Word-wrap text to 39/40 columns for the C64 screen.
    """
    lines = []
    for paragraph in text.split('\n'):
        if not paragraph.strip():
            lines.append('')
        else:
            lines.extend(textwrap.wrap(paragraph, width=width))
    return lines


# ---------------------------------------------------------------------------
# Provider classes
# ---------------------------------------------------------------------------

class ClaudeProvider:
    name = "Claude"
    env_key = "ANTHROPIC_API_KEY"

    @staticmethod
    def probe_models(api_key):
        url = "https://api.anthropic.com/v1/models"
        req = urllib.request.Request(url, headers={
            'x-api-key': api_key,
            'anthropic-version': '2023-06-01',
        })
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
        models = []
        for m in data.get("data", []):
            mid = m.get("id", "")
            if "claude" in mid:
                models.append(mid)
        models.sort()
        return models

    @staticmethod
    def build_request(prompt, history, model, api_key):
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            'Content-Type': 'application/json',
            'x-api-key': api_key,
            'anthropic-version': '2023-06-01',
        }
        messages = []
        for msg in history:
            role = "assistant" if msg["role"] == "model" else msg["role"]
            messages.append({"role": role, "content": msg["text"]})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": model,
            "max_tokens": 2048,
            "messages": messages,
        }
        return url, headers, payload

    @staticmethod
    def parse_response(result):
        return result['content'][0]['text']

    @staticmethod
    def history_roles():
        return "user", "assistant"


class GeminiProvider:
    name = "Gemini"
    env_key = "GEMINI_API_KEY"

    @staticmethod
    def probe_models(api_key):
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
        models = []
        for m in data.get("models", []):
            methods = m.get("supportedGenerationMethods", [])
            if "generateContent" in methods:
                mid = m.get("name", "")
                if mid.startswith("models/"):
                    mid = mid[len("models/"):]
                models.append(mid)
        models.sort()
        return models

    @staticmethod
    def build_request(prompt, history, model, api_key):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        headers = {'Content-Type': 'application/json'}
        contents = []
        for msg in history:
            # Normalize role: map "assistant" to "model" for Gemini
            role = "model" if msg["role"] in ("assistant",) else msg["role"]
            contents.append({"role": role, "parts": [{"text": msg["text"]}]})
        contents.append({"role": "user", "parts": [{"text": prompt}]})
        payload = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": 2048,
                "temperature": 0.7,
            },
        }
        return url, headers, payload

    @staticmethod
    def parse_response(result):
        return result['candidates'][0]['content']['parts'][0]['text']

    @staticmethod
    def history_roles():
        return "user", "model"


class OpenAIProvider:
    name = "OpenAI"
    env_key = "OPENAI_API_KEY"

    @staticmethod
    def probe_models(api_key):
        url = "https://api.openai.com/v1/models"
        req = urllib.request.Request(url, headers={
            'Authorization': f'Bearer {api_key}',
        })
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
        prefixes = ("gpt-", "chatgpt-", "o1-", "o3-")
        models = []
        for m in data.get("data", []):
            mid = m.get("id", "")
            if any(mid.startswith(p) for p in prefixes):
                models.append(mid)
        models.sort()
        return models

    @staticmethod
    def build_request(prompt, history, model, api_key):
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}',
        }
        messages = []
        for msg in history:
            role = "assistant" if msg["role"] == "model" else msg["role"]
            messages.append({"role": role, "content": msg["text"]})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": model,
            "max_tokens": 2048,
            "messages": messages,
        }
        return url, headers, payload

    @staticmethod
    def parse_response(result):
        return result['choices'][0]['message']['content']

    @staticmethod
    def history_roles():
        return "user", "assistant"


class OllamaProvider:
    name = "Ollama"
    env_key = None

    @staticmethod
    def probe_models(base_url):
        if not base_url:
            base_url = "http://localhost:11434"
        if not base_url.startswith("http"):
            base_url = f"http://{base_url}"
        url = f"{base_url.rstrip('/')}/api/tags"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        models = []
        for m in data.get("models", []):
            mid = m.get("name", "")
            if mid:
                models.append(mid)
        models.sort()
        return models

    @staticmethod
    def build_request(prompt, history, model, base_url):
        if not base_url:
            base_url = "http://localhost:11434"
        if not base_url.startswith("http"):
            base_url = f"http://{base_url}"
        url = f"{base_url.rstrip('/')}/api/chat"
        headers = {'Content-Type': 'application/json'}
        messages = []
        for msg in history:
            role = "assistant" if msg["role"] == "model" else msg["role"]
            messages.append({"role": role, "content": msg["text"]})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
        }
        return url, headers, payload

    @staticmethod
    def parse_response(result):
        return result['message']['content']

    @staticmethod
    def history_roles():
        return "user", "assistant"


class LMStudioProvider:
    name = "LM Studio"
    env_key = None

    @staticmethod
    def probe_models(base_url):
        if not base_url:
            base_url = "http://localhost:1234"
        if not base_url.startswith("http"):
            base_url = f"http://{base_url}"
        url = f"{base_url.rstrip('/')}/v1/models"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        models = []
        for m in data.get("data", []):
            mid = m.get("id", "")
            if mid:
                models.append(mid)
        models.sort()
        return models

    @staticmethod
    def build_request(prompt, history, model, base_url):
        if not base_url:
            base_url = "http://localhost:1234"
        if not base_url.startswith("http"):
            base_url = f"http://{base_url}"
        url = f"{base_url.rstrip('/')}/v1/chat/completions"
        headers = {'Content-Type': 'application/json'}
        messages = []
        for msg in history:
            role = "assistant" if msg["role"] == "model" else msg["role"]
            messages.append({"role": role, "content": msg["text"]})
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": model,
            "messages": messages,
        }
        return url, headers, payload

    @staticmethod
    def parse_response(result):
        return result['choices'][0]['message']['content']

    @staticmethod
    def history_roles():
        return "user", "assistant"


PROVIDERS = {
    "Claude": ClaudeProvider,
    "Gemini": GeminiProvider,
    "OpenAI": OpenAIProvider,
    "Ollama": OllamaProvider,
    "LM Studio": LMStudioProvider,
}

# ---------------------------------------------------------------------------
# Proxy server
# ---------------------------------------------------------------------------

PORT = 6464
LOG_FILE = "c64_ai_chat.log"
CONFIG_FILE = "c64_ai_proxy_config.json"


def load_config():
    """Load saved settings from config file."""
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.loads(f.read())
    except Exception:
        return {}


def save_config(cfg):
    """Save settings to config file."""
    try:
        with open(CONFIG_FILE, 'w') as f:
            f.write(json.dumps(cfg, indent=2))
    except Exception:
        pass


class ProxyServer:
    def __init__(self, log_callback=None):
        self._server_socket = None
        self._running = False
        self._thread = None
        self._log_cb = log_callback
        # Backend config
        self.provider_name = "Claude"
        self.model = ""
        self.api_key = ""
        self.api_keys = {}  # all provider keys for C64 switching

    def _log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        print(line)
        try:
            with open(LOG_FILE, "a") as f:
                f.write(line + "\n")
        except Exception:
            pass
        if self._log_cb:
            self._log_cb(line)

    # -- chat generation (provider-agnostic) --------------------------------

    def _generate(self, prompt, history, provider_cls, model, api_key):
        user_role, assistant_role = provider_cls.history_roles()
        url, headers, payload = provider_cls.build_request(
            prompt, history, model, api_key
        )
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode('utf-8'),
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode('utf-8'))
            text = provider_cls.parse_response(result)
            # Context management
            if len(history) > 20:
                del history[:-20]
            history.append({"role": user_role, "text": prompt})
            history.append({"role": assistant_role, "text": text})
            return text
        except Exception as e:
            self._log(f"API error: {e}")
            return "API ERROR ENCOUNTERED. PLEASE SELECT A DIFFERENT MODEL WITH /MODEL"

    # -- per-connection handler (identical telnet logic to originals) --------

    def _send_c64(self, conn, text, output_lines=None):
        """Send text to C64 and optionally record lines for scrollback."""
        conn.sendall(text.encode('ascii', 'ignore'))
        if output_lines is not None:
            for line in text.split('\r\n'):
                if line:
                    output_lines.append(line)

    def _recv_key(self, conn):
        """Read a single printable keypress from the C64."""
        while True:
            try:
                b = conn.recv(1)
            except OSError:
                return None
            if not b:
                return None
            if b[0] >= 32:
                conn.sendall(b)  # echo
                return b.decode('ascii', 'ignore').upper()

    def _show_menu(self, conn, title, items, output_lines):
        """Show a lettered menu on the C64 and return the selected item."""
        self._send_c64(conn, f"\r\n{title}\r\n", output_lines)
        letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        for i, item in enumerate(items[:26]):
            self._send_c64(conn, f"  {letters[i]}) {item.upper()}\r\n", output_lines)
        self._send_c64(conn, "  Q) CANCEL\r\n", output_lines)
        self._send_c64(conn, "SELECT: ", output_lines)
        key = self._recv_key(conn)
        if not key or key == 'Q':
            self._send_c64(conn, "\r\nCANCELLED.\r\n", output_lines)
            return None
        idx = letters.find(key)
        if idx < 0 or idx >= len(items):
            self._send_c64(conn, "\r\nINVALID SELECTION.\r\n", output_lines)
            return None
        return items[idx]

    def _cmd_provider(self, conn, output_lines, chat_history):
        """Handle /provider command — switch AI backend from C64."""
        provider_names = list(PROVIDERS.keys())
        chosen = self._show_menu(conn, "SELECT PROVIDER:", provider_names, output_lines)
        if not chosen:
            return
        self.provider_name = chosen
        self.api_key = self.api_keys.get(chosen, "")
        self.model = ""
        chat_history.clear()
        self._log(f"C64 switched provider to {chosen}")
        self._send_c64(conn, f"\r\nPROVIDER SET TO {chosen.upper()}.\r\n", output_lines)
        self._send_c64(conn, "CHAT HISTORY CLEARED.\r\n", output_lines)
        self._send_c64(conn, "USE /MODEL TO SELECT A MODEL.\r\n", output_lines)

    def _cmd_model(self, conn, output_lines, chat_history):
        """Handle /model command — probe and switch model from C64."""
        provider_cls = PROVIDERS.get(self.provider_name, ClaudeProvider)
        api_key = self.api_keys.get(self.provider_name, self.api_key)
        provider_label = provider_cls.name.upper()

        self._send_c64(conn, f"\r\nPROBING {provider_label} MODELS...\r\n", output_lines)
        try:
            models = provider_cls.probe_models(api_key)
        except Exception as e:
            self._send_c64(conn, f"ERROR: {e}\r\n", output_lines)
            return
        if not models:
            self._send_c64(conn, "NO MODELS FOUND.\r\n", output_lines)
            return

        chosen = self._show_menu(conn, f"{provider_label} MODELS:", models, output_lines)
        if not chosen:
            return
        self.model = chosen
        self.api_key = api_key
        self._log(f"C64 switched model to {chosen}")
        self._send_c64(conn, f"\r\nMODEL SET TO {chosen.upper()}.\r\n", output_lines)

    def _scrollback(self, conn, output_lines):
        """Enter scrollback mode. Cursor-up/down pages, any other key exits."""
        LINES = 20
        total = len(output_lines)
        if total == 0:
            return
        total_pages = max(1, (total + LINES - 1) // LINES)
        # Start one page back from the last
        cur_page = max(1, total_pages - 1)

        while True:
            pos = (cur_page - 1) * LINES
            conn.sendall(b'\x93')  # PETSCII clear screen
            end = min(pos + LINES, total)
            for i in range(pos, end):
                conn.sendall(f"{output_lines[i]}\r\n".encode('ascii', 'ignore'))
            conn.sendall(f"[PG {cur_page}/{total_pages}] UP/DN=SCROLL Q=EXIT".encode('ascii', 'ignore'))

            try:
                key = conn.recv(1)
            except OSError:
                return
            if not key:
                return
            if key == b'\x91':  # PETSCII cursor up
                cur_page = max(1, cur_page - 1)
            elif key == b'\x11':  # PETSCII cursor down
                cur_page = min(total_pages, cur_page + 1)
            else:
                # Exit scrollback — clear and return to live view
                conn.sendall(b'\x93')
                return

    def _handle_client(self, conn, addr, provider_cls, model, api_key):
        self._log(f"[NEW CONNECTION] {addr[0]}:{addr[1]} connected.")

        output_lines = []  # scrollback buffer
        chat_history = []

        # Show initial welcome with whatever backend is active
        provider_label = provider_cls.name.upper()
        welcome = f"\r\n*** COMMODORE 64 AI CHAT ***\r\n"
        welcome += f"BACKEND: {provider_label} / {model.upper()}\r\n\r\n"
        self._send_c64(conn, welcome, output_lines)

        try:
            while self._running:
                # Read provider for prompt display
                provider_cls = PROVIDERS.get(self.provider_name, ClaudeProvider)
                provider_label = provider_cls.name.upper()

                self._send_c64(conn, f"\r\nREADY.\r\n{provider_label}> ")

                # Read input byte by byte
                data = b""
                chunk = b""
                while True:
                    try:
                        chunk = conn.recv(1)
                    except OSError:
                        chunk = b""
                    if not chunk:
                        break

                    # Backspace (0x08), delete (0x7F), or C64 Delete (0x14)
                    if chunk in (b'\x08', b'\x7f', b'\x14'):
                        if len(data) > 0:
                            data = data[:-1]
                            conn.sendall(b'\x14')
                        continue

                    # Cursor up (0x91) — enter scrollback
                    if chunk == b'\x91':
                        self._scrollback(conn, output_lines)
                        # Re-read provider in case it changed during scrollback
                        provider_cls = PROVIDERS.get(self.provider_name, ClaudeProvider)
                        provider_label = provider_cls.name.upper()
                        conn.sendall(f"{provider_label}> ".encode('ascii', 'ignore'))
                        if data:
                            conn.sendall(data)
                        continue

                    # Cursor down (0x11) — ignore during input
                    if chunk == b'\x11':
                        continue

                    conn.sendall(chunk)

                    if chunk in (b'\n', b'\r'):
                        break

                    if chunk[0] >= 32:
                        data += chunk

                if not data and not chunk:
                    break

                prompt = data.decode('ascii', 'ignore').strip()
                if not prompt:
                    continue

                # Read live settings NOW — use whatever is selected at submit time
                provider_cls = PROVIDERS.get(self.provider_name, ClaudeProvider)
                model = self.model
                api_key = self.api_key
                provider_label = provider_cls.name.upper()

                self._log(f"[{addr[0]}:{addr[1]}] [{provider_label}/{model}] USER: {prompt}")

                if prompt.upper() in ("QUIT", "EXIT", "LOGOFF", "BYE"):
                    self._send_c64(conn, "\r\n\r\nTERMINATED.\r\n", output_lines)
                    break

                if prompt.upper() in ("CLEAR", "CLS"):
                    conn.sendall(b'\x93')
                    chat_history = []
                    output_lines.clear()
                    self._send_c64(conn, "\r\nMEMORY CLEARED.\r\n", output_lines)
                    continue

                if prompt.upper() == "/PROVIDER":
                    self._cmd_provider(conn, output_lines, chat_history)
                    continue

                if prompt.upper() == "/MODEL":
                    self._cmd_model(conn, output_lines, chat_history)
                    continue

                if prompt.upper() in ("/HELP", "HELP", "?"):
                    self._send_c64(conn, "\r\n", output_lines)
                    self._send_c64(conn, "COMMANDS:\r\n", output_lines)
                    self._send_c64(conn, "  /PROVIDER - SWITCH AI BACKEND\r\n", output_lines)
                    self._send_c64(conn, "  /MODEL    - SWITCH MODEL\r\n", output_lines)
                    self._send_c64(conn, "  CLEAR     - CLEAR CHAT HISTORY\r\n", output_lines)
                    self._send_c64(conn, "  QUIT      - DISCONNECT\r\n", output_lines)
                    continue

                self._send_c64(conn, "\r\n\r\nTHINKING...\r\n", output_lines)

                response = self._generate(prompt, chat_history, provider_cls, model, api_key)
                response = clean_for_c64(response)

                self._log(f"[{addr[0]}:{addr[1]}] [{provider_label}/{model}] RESPONSE: {response}")

                lines = wrap_text(response, width=40)
                self._send_c64(conn, "\r\n", output_lines)
                for line in lines:
                    self._send_c64(conn, f"{line}\r\n", output_lines)

        except ConnectionResetError:
            pass
        except Exception as e:
            self._log(f"[ERROR] {addr[0]}:{addr[1]}: {e}")

        self._log(f"[DISCONNECTED] {addr[0]}:{addr[1]} closed.")
        try:
            conn.close()
        except Exception:
            pass

    # -- server lifecycle ---------------------------------------------------

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            srv.bind(('0.0.0.0', PORT))
        except Exception as e:
            self._log(f"FAILED TO BIND PORT {PORT}: {e}")
            self._running = False
            return
        srv.listen(5)
        srv.settimeout(1.0)
        self._server_socket = srv
        self._log(f"Server RUNNING on port {PORT}")

        while self._running:
            try:
                conn, addr = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            # Snapshot current config for this connection
            provider_cls = PROVIDERS.get(self.provider_name, ClaudeProvider)
            model = self.model
            api_key = self.api_key
            t = threading.Thread(
                target=self._handle_client,
                args=(conn, addr, provider_cls, model, api_key),
                daemon=True,
            )
            t.start()

        try:
            srv.close()
        except Exception:
            pass
        self._server_socket = None
        self._log("Server STOPPED.")

    def stop(self):
        self._running = False
        if self._server_socket:
            try:
                self._server_socket.close()
            except Exception:
                pass

    @property
    def running(self):
        return self._running


# ---------------------------------------------------------------------------
# tkinter GUI
# ---------------------------------------------------------------------------

class AIProxyGUI:
    def __init__(self, root):
        self.root = root
        root.title("C64 AI Proxy Server")
        root.resizable(True, True)
        root.minsize(520, 600)

        self.server = ProxyServer(log_callback=self._threadsafe_log)

        # Load saved config
        self._config = load_config()

        # Per-provider key storage — saved config overrides env vars
        self._api_keys = {
            "Claude": self._config.get("key_Claude", os.environ.get("ANTHROPIC_API_KEY", "")),
            "Gemini": self._config.get("key_Gemini", os.environ.get("GEMINI_API_KEY", "")),
            "OpenAI": self._config.get("key_OpenAI", os.environ.get("OPENAI_API_KEY", "")),
            "Ollama": self._config.get("key_Ollama", "localhost:11434"),
            "LM Studio": self._config.get("key_LM Studio", "localhost:1234"),
        }
        self._saved_provider = self._config.get("provider", "Claude")
        self._saved_model = self._config.get("model", "")

        self._build_ui()

        # Restore last provider
        self.provider_var.set(self._saved_provider)
        self._on_provider_change()

        # If we have a saved model, auto-probe and restore it
        if self._saved_model:
            self.root.after(100, self._restore_model)

    # -- UI construction ----------------------------------------------------

    def _build_ui(self):
        pad = dict(padx=8, pady=4)

        # --- Backend Provider ---
        frame_prov = tk.LabelFrame(self.root, text="Backend Provider")
        frame_prov.pack(fill=tk.X, **pad)

        self.provider_var = tk.StringVar(value="Claude")
        for name in ("Claude", "Gemini", "OpenAI", "Ollama", "LM Studio"):
            tk.Radiobutton(
                frame_prov, text=name, variable=self.provider_var,
                value=name, command=self._on_provider_change,
            ).pack(side=tk.LEFT, padx=6, pady=4)

        # --- API Key ---
        self.frame_key = tk.LabelFrame(self.root, text="API Key")
        self.frame_key.pack(fill=tk.X, **pad)

        self.key_entry = tk.Entry(self.frame_key, show="*", width=60)
        self.key_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4, pady=4)

        self.show_key_var = tk.BooleanVar(value=False)
        self.show_key_btn = tk.Checkbutton(
            frame_key, text="Show", variable=self.show_key_var,
            command=self._toggle_key_visibility,
        )
        self.show_key_btn.pack(side=tk.LEFT, padx=4)

        # --- Model Selection ---
        frame_model = tk.LabelFrame(self.root, text="Model Selection")
        frame_model.pack(fill=tk.BOTH, expand=True, **pad)

        btn_row = tk.Frame(frame_model)
        btn_row.pack(fill=tk.X)
        self.probe_btn = tk.Button(btn_row, text="Probe Models", command=self._probe_models)
        self.probe_btn.pack(side=tk.LEFT, padx=4, pady=4)
        self.probe_status = tk.Label(btn_row, text="")
        self.probe_status.pack(side=tk.LEFT, padx=4)

        # Scrollable model list
        model_canvas_frame = tk.Frame(frame_model)
        model_canvas_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self.model_canvas = tk.Canvas(model_canvas_frame, height=120)
        model_scrollbar = tk.Scrollbar(model_canvas_frame, orient=tk.VERTICAL,
                                       command=self.model_canvas.yview)
        self.model_inner = tk.Frame(self.model_canvas)
        self.model_inner.bind("<Configure>",
                              lambda e: self.model_canvas.configure(
                                  scrollregion=self.model_canvas.bbox("all")))
        self.model_canvas.create_window((0, 0), window=self.model_inner, anchor="nw")
        self.model_canvas.configure(yscrollcommand=model_scrollbar.set)

        self.model_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        model_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.model_var = tk.StringVar(value="")

        # --- Server Control ---
        frame_srv = tk.LabelFrame(self.root, text="Server Control")
        frame_srv.pack(fill=tk.X, **pad)

        self.start_btn = tk.Button(frame_srv, text="Start Server", width=14,
                                   command=self._toggle_server)
        self.start_btn.pack(side=tk.LEFT, padx=4, pady=4)

        self.status_label = tk.Label(frame_srv, text="STOPPED", fg="red",
                                     font=("TkDefaultFont", 10, "bold"))
        self.status_label.pack(side=tk.LEFT, padx=8)

        self.port_label = tk.Label(frame_srv, text=f"Port: {PORT}")
        self.port_label.pack(side=tk.LEFT, padx=8)

        # --- Server Log ---
        frame_log = tk.LabelFrame(self.root, text="Server Log")
        frame_log.pack(fill=tk.BOTH, expand=True, **pad)

        self.log_area = scrolledtext.ScrolledText(frame_log, height=12, state=tk.DISABLED,
                                                  wrap=tk.WORD, font=("Courier", 9))
        self.log_area.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # --- Window close ---
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # -- provider / key handling -------------------------------------------

    def _sync_server(self):
        """Push current GUI selections to the running server."""
        self._save_current_key()
        prov = self.provider_var.get()
        self.server.provider_name = prov
        self.server.model = self.model_var.get()
        self.server.api_key = self._api_keys.get(prov, "")
        self.server.api_keys = dict(self._api_keys)

    def _on_provider_change(self):
        prov = self.provider_var.get()
        # Save current key before switching
        self._save_current_key()
        # Load stored key for new provider
        self.key_entry.delete(0, tk.END)
        self.key_entry.insert(0, self._api_keys.get(prov, ""))

        # Update UI based on provider
        if prov in ("Ollama", "LM Studio"):
            self.frame_key.configure(text="Server Address (host:port)")
            self.show_key_btn.pack_forget()
            self.key_entry.configure(show="")
        else:
            self.frame_key.configure(text="API Key")
            self.show_key_btn.pack(side=tk.LEFT, padx=4)
            self._toggle_key_visibility()

        self.key_entry.configure(state=tk.NORMAL)
        # Clear model list
        self._clear_models()
        self._sync_server()

    def _save_current_key(self):
        """Persist the key entry value for the currently-selected provider."""
        prov = self.provider_var.get()
        try:
            val = self.key_entry.get()
            # Don't overwrite a saved key with empty during startup
            if val or not self._api_keys.get(prov, ""):
                self._api_keys[prov] = val
        except Exception:
            pass

    def _toggle_key_visibility(self):
        self.key_entry.configure(show="" if self.show_key_var.get() else "*")

    # -- model probing -----------------------------------------------------

    def _clear_models(self):
        for w in self.model_inner.winfo_children():
            w.destroy()
        self.model_var.set("")
        self.probe_status.configure(text="")

    def _probe_models(self):
        self._save_current_key()
        prov = self.provider_var.get()
        api_key = self._api_keys.get(prov, "")
        provider_cls = PROVIDERS[prov]

        self.probe_btn.configure(state=tk.DISABLED)
        self.probe_status.configure(text="Probing...")

        def _do_probe():
            try:
                models = provider_cls.probe_models(api_key)
                self.root.after(0, lambda: self._populate_models(models))
            except Exception as e:
                self.root.after(0, lambda: self._probe_error(str(e)))

        threading.Thread(target=_do_probe, daemon=True).start()

    def _populate_models(self, models):
        self._clear_models()
        self.probe_btn.configure(state=tk.NORMAL)
        if not models:
            self.probe_status.configure(text="No models found.")
            return
        self.probe_status.configure(text=f"{len(models)} model(s)")
        for m in models:
            tk.Radiobutton(
                self.model_inner, text=m, variable=self.model_var,
                value=m, anchor="w", command=self._sync_server,
            ).pack(fill=tk.X)
        # Auto-select first
        self.model_var.set(models[0])
        self._sync_server()

    def _probe_error(self, msg):
        self.probe_btn.configure(state=tk.NORMAL)
        self.probe_status.configure(text=f"Error: {msg[:60]}")

    # -- server control ----------------------------------------------------

    def _toggle_server(self):
        if self.server.running:
            self.server.stop()
            self.start_btn.configure(text="Start Server")
            self.status_label.configure(text="STOPPED", fg="red")
        else:
            self._save_current_key()
            prov = self.provider_var.get()
            model = self.model_var.get()
            api_key = self._api_keys.get(prov, "")
            if not model:
                self._append_log("ERROR: Select a model first (use Probe Models).")
                return
            if prov not in ("Ollama", "LM Studio") and not api_key:
                self._append_log("ERROR: API key required.")
                return
            self.server.provider_name = prov
            self.server.model = model
            self.server.api_key = api_key
            self.server.start()
            self.start_btn.configure(text="Stop Server")
            self.status_label.configure(text="RUNNING", fg="green")
            self._persist_config()

    # -- logging -----------------------------------------------------------

    def _threadsafe_log(self, msg):
        self.root.after(0, lambda: self._append_log(msg))

    def _append_log(self, msg):
        self.log_area.configure(state=tk.NORMAL)
        self.log_area.insert(tk.END, msg + "\n")
        self.log_area.see(tk.END)
        self.log_area.configure(state=tk.DISABLED)

    # -- config persistence ------------------------------------------------

    def _persist_config(self):
        """Save current keys, provider, and model to config file."""
        self._save_current_key()
        cfg = {
            "provider": self.provider_var.get(),
            "model": self.model_var.get(),
        }
        for prov in ("Claude", "Gemini", "OpenAI", "Ollama", "LM Studio"):
            cfg[f"key_{prov}"] = self._api_keys.get(prov, "")
        save_config(cfg)

    def _restore_model(self):
        """Auto-probe and restore the last selected model on startup."""
        prov = self.provider_var.get()
        api_key = self._api_keys.get(prov, "")
        provider_cls = PROVIDERS[prov]
        saved = self._saved_model

        self.probe_btn.configure(state=tk.DISABLED)
        self.probe_status.configure(text="Restoring...")

        def _do_probe():
            try:
                models = provider_cls.probe_models(api_key)
                self.root.after(0, lambda: self._restore_populate(models, saved))
            except Exception as e:
                self.root.after(0, lambda: self._probe_error(str(e)))

        threading.Thread(target=_do_probe, daemon=True).start()

    def _restore_populate(self, models, saved_model):
        self._populate_models(models)
        if saved_model and saved_model in models:
            self.model_var.set(saved_model)
            self._sync_server()

    # -- cleanup -----------------------------------------------------------

    def _on_close(self):
        self._persist_config()
        self.server.stop()
        self.root.destroy()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    root = tk.Tk()
    AIProxyGUI(root)
    root.mainloop()
