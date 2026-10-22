"""多功能网站后端应用包。

模块划分：
    config    —— 全局配置与路径
    db        —— SQLite 连接与建表
    routers   —— 博客 / 文件 / WebSocket 路由
    services  —— 聊天与画布的房间广播中心
    ext       —— C++ 扩展加载与纯 Python 回退
"""

__version__ = "1.1.0"
