#!/usr/bin/env python3
"""wechat-digest 入口。

用法：
    python run.py seed-demo
    python run.py run --event events/huang-renxun-lizhi.toml
"""

from wdigest.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
