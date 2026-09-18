"""口令门禁。

⚠️ **这是门禁，不是认证。** 差别要说清楚，别当成安全模块用：

- 全站**一个共享口令**，不分人。日志里查不出「谁改了这个中心」
- 口令一旦泄露（转发、截图、共享屏幕），没有吊销机制，只能换一个重启
- 它挡的是**误闯的路人**，不是有心的攻击者
- **它不会让公网部署变得安全** —— 里面的中心地址、指导员配置照样在
  一个共享口令后面

用途仅限：给测试 demo 挡一层，免得随便谁点开链接就能上传文件、跑求解。
真要上生产、真要放真实数据，得做正经的认证与权限。
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass, field

COOKIE_NAME = "scheduling_gate"
#: 口令用无歧义字符集 —— 去掉了 0/O、1/l/I，口头念或手抄不会错
_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def generate_password(length: int = 12) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


@dataclass
class PasswordGate:
    """签发和校验一张短期通行证。"""
    password: str = ""
    secret: str = ""
    ttl_seconds: int = 12 * 3600
    #: 口令是这次启动随机生成的（而非来自环境变量）时为 True
    is_ephemeral: bool = field(default=False, init=False)

    def __post_init__(self):
        if not self.password:
            env = os.environ.get("SCHEDULING_PASSWORD", "").strip()
            if env:
                self.password = env
            else:
                self.password = generate_password()
                self.is_ephemeral = True
        if not self.secret:
            # 密钥来自环境变量时，重启不会把所有人踢下线；
            # 否则每次启动换一把，重启即全部失效 —— demo 场景这样更省事
            self.secret = os.environ.get("SCHEDULING_SECRET", "") or secrets.token_urlsafe(32)

    # ------------------------------------------------------------ 校验

    def check_password(self, supplied: str) -> bool:
        """**必须用 compare_digest**：普通 == 会因为提前返回而泄露前缀，
        让人能一个字符一个字符地试出口令。"""
        return hmac.compare_digest(
            (supplied or "").encode("utf-8"), self.password.encode("utf-8"))

    def _sign(self, expiry: int) -> str:
        return hmac.new(self.secret.encode("utf-8"),
                        str(expiry).encode("ascii"),
                        hashlib.sha256).hexdigest()

    def issue(self, now: float | None = None) -> str:
        expiry = int((now if now is not None else time.time()) + self.ttl_seconds)
        return "%d.%s" % (expiry, self._sign(expiry))

    def verify(self, token: str | None, now: float | None = None) -> bool:
        if not token or "." not in token:
            return False
        head, _, sig = token.partition(".")
        try:
            expiry = int(head)
        except ValueError:
            return False
        if expiry < (now if now is not None else time.time()):
            return False
        return hmac.compare_digest(sig, self._sign(expiry))


#: 不需要口令的路径。
#:   /login   —— 不放行就没法登录
#:   /static  —— 样式和 htmx，挡住只会让登录页变成裸 HTML
#:   /healthz —— 容器探活。**不能用 /api/readiness 当探活**，
#:               那个要口令，容器会一直被判成不健康
PUBLIC_PREFIXES = ("/login", "/static", "/healthz")


def is_public(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") or path.startswith(p + "?")
               for p in PUBLIC_PREFIXES)


def safe_next(target: str | None) -> str:
    """登录后要跳去哪 —— 只允许本站的绝对路径。

    ⚠️ 光判 `startswith("/")` 不够：`//evil.com` 也以 `/` 开头，
    但浏览器会把它当**协议相对 URL**，直接跳到外站。
    这是开放重定向最常见的漏法。
    """
    t = (target or "").strip()
    if not t.startswith("/") or t.startswith("//") or t.startswith("/\\"):
        return "/"
    if ":" in t.split("/", 2)[-1][:16] and t.lower().startswith("/javascript:"):
        return "/"
    return t


def startup_banner(gate: PasswordGate) -> str:
    """启动时打给运维看的。口令不打出来就没人知道是什么。"""
    lines = ["", "=" * 56, "  排班系统已启动，访问需要口令", "",
             "    口令：%s" % gate.password, ""]
    if gate.is_ephemeral:
        lines += [
            "  ⚠ 这是本次启动随机生成的，**重启就会换一个**。",
            "    要固定下来，用环境变量：SCHEDULING_PASSWORD=你的口令",
            "",
        ]
    lines += [
        "  这是给测试 demo 挡一层的门禁，**不是认证**：",
        "  全站一个共享口令、不分人、泄露了只能换一个重启。",
        "  别拿它当保护真实数据的手段。",
        "=" * 56, ""]
    return "\n".join(lines)
