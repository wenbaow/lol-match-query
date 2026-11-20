"""日志配置：输出到 ~/.lol_helper/logs/app.log（滚动文件）。

设置环境变量 LOLMQ_DEBUG=1 可开启调试日志。
"""
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER_NAME = 'lol_match_query'
LOG_DIR = Path.home() / '.lol_helper' / 'logs'


def setup_logging():
    """初始化应用日志（重复调用不会重复添加 handler）"""
    logger = logging.getLogger(LOGGER_NAME)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG if os.environ.get('LOLMQ_DEBUG') else logging.INFO)
    logger.propagate = False

    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            LOG_DIR / 'app.log',
            maxBytes=2 * 1024 * 1024,
            backupCount=3,
            encoding='utf-8',
        )
    except OSError:
        # 无法创建日志文件时静默降级（GUI 仍可通过控制台输出）
        return logger

    handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(message)s'))
    logger.addHandler(handler)
    return logger


def get_logger():
    return logging.getLogger(LOGGER_NAME)
