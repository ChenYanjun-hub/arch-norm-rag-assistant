"""一次性脚本：跑评测集打分。

用法：
    cd backend && python -m scripts.run_eval --set v1_50 [--out results.json]

W4 实现。
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def main() -> None:
    # TODO(W4): 实现评测批跑：读 CSV → 过 pipeline → 7 维度打分 → 输出报告
    raise NotImplementedError("W4 实现")


if __name__ == "__main__":
    main()
