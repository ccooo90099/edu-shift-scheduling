#!/usr/bin/env bash
# 把这个项目推到 Hugging Face Space。
#
#   用法：deploy/huggingface/push.sh <你的HF用户名>/<space名>
#   例：  deploy/huggingface/push.sh zhangsan/edu-shift-scheduling
#
# 前提：先在 https://huggingface.co/new-space 建好 Space，SDK 选 Docker。
#
# 认证：设了 HF_TOKEN 环境变量就用它（CI 用这条路），
#       没设就让 git 交互式问你（本地用这条路）。
set -euo pipefail

SPACE="${1:-}"
if [[ -z "$SPACE" ]]; then
  echo "用法：$0 <用户名>/<space名>" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "→ 组装部署目录"
cd "$ROOT"
# 只带运行需要的东西。测试、文档、归档代码、真实配置都不上去。
for item in src tools console.py requirements.txt Dockerfile; do
  cp -r "$item" "$WORK/"
done
mkdir -p "$WORK/config"
cp config/rules.example.yaml "$WORK/config/"
# HF Space 的 README 必须带 YAML frontmatter，且要在仓库根目录
cp deploy/huggingface/README.md "$WORK/README.md"

# htmx 不在仓库里（见 src/.../static/README.md），这里补一份
HTMX="$WORK/src/scheduling/interfaces/web/static/htmx.min.js"
if [[ ! -f "$HTMX" ]]; then
  echo "→ 下载 htmx"
  curl -fsSL -o "$HTMX" \
    https://cdnjs.cloudflare.com/ajax/libs/htmx/1.9.12/htmx.min.js \
    || { echo "htmx 下载失败。手动放一份到 $HTMX 再重试" >&2; exit 1; }
fi

echo "→ 推送到 https://huggingface.co/spaces/$SPACE"
cd "$WORK"
git init -q
git add -A
git -c user.email=deploy@local -c user.name=deploy commit -qm "deploy"

if [[ -n "${HF_TOKEN:-}" ]]; then
  # token 拼在 URL 里会进 git 的错误输出和 reflog，所以走 header，
  # 并且把可能回显 token 的输出掐掉
  AUTH="$(printf 'user:%s' "$HF_TOKEN" | base64 -w0 2>/dev/null || printf 'user:%s' "$HF_TOKEN" | base64)"
  git -c "http.extraheader=Authorization: Basic $AUTH" \
      push -f "https://huggingface.co/spaces/$SPACE" HEAD:main 2>&1 \
    | sed "s/$HF_TOKEN/***/g"
else
  # 没有 token：让 git 交互式问用户名和 Access Token
  git push -f "https://huggingface.co/spaces/$SPACE" HEAD:main
fi

cat <<'DONE'

✅ 推完了。接下来在 Space 页面上：

  Settings → Variables and secrets → New secret
    SCHEDULING_PASSWORD  = 你要的口令
    SCHEDULING_SECRET    = 任意一串随机字符（重启不掉线用）
    SCHEDULING_SEED_DEMO = 1      （重启后自动灌示例数据）

  然后 Settings → Factory rebuild，等构建完成即可访问。

DONE
