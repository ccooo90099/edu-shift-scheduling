"""排课限界上下文。

分层（依赖方向自外向内，领域层不依赖任何外层）：

    interfaces/      web(FastAPI+HTMX) / cli
         ↓
    application/     用例编排，界面与领域之间的唯一通道
         ↓
    domain/          领域模型与业务规则，零框架依赖
         ↑
    infrastructure/  仓储实现、求解器适配、xlsx、地图
                     （实现 domain 定义的接口，依赖倒置）
"""
