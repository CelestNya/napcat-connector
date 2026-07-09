try:
    from .main import NapcatConnectorPlugin

    __all__ = ["NapcatConnectorPlugin"]
except ImportError:
    # 在 KiraAI 环境外（如测试）时静默跳过
    pass
