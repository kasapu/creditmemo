"""Entry point: `python run.py` (or `uvicorn credit_memo.app:app`)."""

from __future__ import annotations

import uvicorn

from credit_memo.config import get_config


def main() -> None:
    cfg = get_config()
    uvicorn.run(
        "credit_memo.app:app",
        host=cfg.host,
        port=cfg.port,
        reload=cfg.debug,
        log_level=cfg.log_level,
    )


if __name__ == "__main__":
    main()
