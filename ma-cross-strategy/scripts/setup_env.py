"""
setup_env.py — 從 TOOLS.md 讀取 Binance API key 並寫入 .env
=============================================================

用途：
  每次安裝 cyqnt-trd 後、跑 live trade 前執行一次。
  自動從 TOOLS.md 的 ## Binance API 區塊解析 key，寫入 .env。

使用方式：
  python3.11 /root/.openclaw/workspace/scripts/setup_env.py

  # 指定其他路徑
  python3.11 scripts/setup_env.py \
    --tools /root/.openclaw/workspace/TOOLS.md \
    --env   /root/.openclaw/workspace/.env
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

WORKSPACE = Path("/root/.openclaw/workspace")
DEFAULT_TOOLS = WORKSPACE / "TOOLS.md"
DEFAULT_ENV   = WORKSPACE / ".env"

# 要從 TOOLS.md 抽取的 key 清單（欄位名 → 環境變數名）
KEYS_TO_EXTRACT = [
    "BINANCE_MAINNET_API_KEY",
    "BINANCE_MAINNET_API_SECRET",
    "BINANCE_TESTNET",
]


def parse_tools_md(tools_path: Path) -> dict[str, str]:
    """
    解析 TOOLS.md 裡 ## Binance API code block 內的 KEY=VALUE 行。

    支援的格式（code block 內，任一行）：
      KEY=VALUE
      KEY = VALUE
      KEY="VALUE"
      KEY='VALUE'
    """
    text = tools_path.read_text(encoding="utf-8")

    # 找 ## Binance API 區塊，取到下一個 ## 或檔尾
    section_match = re.search(
        r"##\s+Binance API.*?```(.*?)```",
        text,
        re.DOTALL | re.IGNORECASE,
    )
    if not section_match:
        print(f"[setup_env] ERROR: '## Binance API' code block not found in {tools_path}")
        sys.exit(1)

    block = section_match.group(1)
    result: dict[str, str] = {}

    for line in block.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r'^([A-Z0-9_]+)\s*=\s*["\']?([^"\']*)["\']?$', line)
        if m:
            key, value = m.group(1), m.group(2).strip()
            if key in KEYS_TO_EXTRACT:
                result[key] = value

    return result


def write_env(env_path: Path, kvs: dict[str, str]) -> None:
    """
    把 kvs 寫入 .env 檔（覆蓋），並設 chmod 600。
    已存在的其他 key 會被保留（merge 模式）。
    """
    # 讀現有 .env（若存在）
    existing: dict[str, str] = {}
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, _, v = line.partition("=")
                existing[k.strip()] = v.strip()

    # merge：新值覆蓋舊值
    existing.update(kvs)

    lines = [f"{k}={v}" for k, v in sorted(existing.items())]
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(env_path, 0o600)
    print(f"[setup_env] wrote {len(kvs)} key(s) to {env_path}  (chmod 600)")
    for k, v in kvs.items():
        masked = v[:6] + "…" + v[-4:] if len(v) > 12 else "***"
        print(f"  {k} = {masked}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap .env from TOOLS.md")
    parser.add_argument("--tools", default=str(DEFAULT_TOOLS))
    parser.add_argument("--env",   default=str(DEFAULT_ENV))
    args = parser.parse_args()

    tools_path = Path(args.tools)
    env_path   = Path(args.env)

    if not tools_path.exists():
        print(f"[setup_env] ERROR: TOOLS.md not found at {tools_path}")
        return 1

    kvs = parse_tools_md(tools_path)
    if not kvs:
        print("[setup_env] ERROR: no matching keys found in TOOLS.md")
        return 1

    write_env(env_path, kvs)
    print("[setup_env] done — .env is ready for live trade")
    return 0


if __name__ == "__main__":
    sys.exit(main())
