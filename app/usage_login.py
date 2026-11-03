from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

LOGIN_PATHS = {
    "newapi": "/login",
    "deepseek": "https://platform.deepseek.com/sign_in",
}

BUTTON_SCRIPT = r"""
(() => {
  if (document.getElementById('atlas-usage-login')) return;
  const button = document.createElement('button');
  button.id = 'atlas-usage-login';
  button.textContent = '完成绑定';
  Object.assign(button.style, {
    position: 'fixed', right: '18px', bottom: '18px', zIndex: '2147483647',
    padding: '10px 16px', borderRadius: '8px', border: '0',
    background: '#1f6feb', color: '#fff', fontSize: '14px',
    cursor: 'pointer', boxShadow: '0 6px 20px rgba(0,0,0,.25)'
  });
  button.onclick = () => window.pywebview.api.finish();
  document.body.appendChild(button);
})();
"""


def _extract_newapi(window: Any) -> dict[str, Any]:
    script = r"""
(() => {
  function getJSON(url) {
    try {
      const xhr = new XMLHttpRequest();
      xhr.open('GET', url, false);
      xhr.withCredentials = true;
      xhr.send(null);
      return JSON.parse(xhr.responseText);
    } catch (error) {
      return null;
    }
  }
  return JSON.stringify({
    self: getJSON('/api/user/self'),
    token: getJSON('/api/user/self/token')
  });
})()
"""
    raw = window.evaluate_js(script)
    data = json.loads(raw) if isinstance(raw, str) else (raw or {})
    self_payload = data.get("self") or {}
    self_data = self_payload.get("data") or {}
    user_id = self_data.get("id") or self_data.get("user_id") or ""
    token_payload = data.get("token") or {}
    token_data = token_payload.get("data")
    if isinstance(token_data, dict):
        access_token = token_data.get("token") or token_data.get("access_token") or ""
    else:
        access_token = str(token_data or "")
    return {
        "user_id": str(user_id),
        "access_token": str(access_token),
    }


def _extract_deepseek(window: Any) -> dict[str, Any]:
    script = r"""
(() => {
  const keys = ['userToken', 'user_token', 'deepseek_user_token'];
  const values = {};
  for (const key of keys) values[key] = localStorage.getItem(key) || '';
  return JSON.stringify({values});
})()
"""
    raw = window.evaluate_js(script)
    data = json.loads(raw) if isinstance(raw, str) else (raw or {})
    values = data.get("values") or {}
    token = str(values.get("userToken") or values.get("user_token") or values.get("deepseek_user_token") or "")
    return {"platform_token": token}


def _write_result(output: Path, payload: dict[str, Any]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(output)


def _login_url(kind: str, base_url: str) -> str:
    if kind == "deepseek":
        return LOGIN_PATHS["deepseek"]
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    return base + LOGIN_PATHS["newapi"]


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Atlas usage login helper")
    parser.add_argument("--kind", choices=["newapi", "deepseek"], required=True)
    parser.add_argument("--base-url", default="")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    output = Path(args.output)
    try:
        import webview
    except Exception as exc:
        _write_result(output, {"ok": False, "error": f"无法打开登录窗口：{exc}"})
        return 1

    state: dict[str, Any] = {"done": False}
    window = webview.create_window(
        "Atlas 账户登录",
        _login_url(args.kind, args.base_url),
        width=980,
        height=760,
        min_size=(720, 520),
    )

    def inject() -> None:
        try:
            window.evaluate_js(BUTTON_SCRIPT)
        except Exception:
            pass

    def finish() -> None:
        if state["done"]:
            return
        state["done"] = True
        try:
            if args.kind == "deepseek":
                data = _extract_deepseek(window)
            else:
                data = _extract_newapi(window)
            cookies = window.get_cookies() or []
            data["session_cookies"] = [
                {"name": item.get("name"), "value": item.get("value")}
                for item in cookies
                if isinstance(item, dict) and item.get("name")
            ]
            data["ok"] = True
            _write_result(output, data)
        except Exception as exc:
            _write_result(output, {"ok": False, "error": str(exc)[:500]})
        finally:
            try:
                window.destroy()
            except Exception:
                pass

    window.events.loaded += inject
    window.expose(finish)
    try:
        webview.start()
    except Exception as exc:
        if not state["done"]:
            _write_result(output, {"ok": False, "error": f"登录窗口失败：{exc}"})
    if not state["done"]:
        _write_result(output, {"ok": False, "error": "登录窗口已关闭，未完成绑定"})
    return 0


def main() -> None:
    raise SystemExit(run(sys.argv[1:]))


if __name__ == "__main__":
    main()
