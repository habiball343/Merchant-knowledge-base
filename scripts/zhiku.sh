#!/usr/bin/env bash
# 掌柜智库 —— macOS / Linux / WSL 启动脚本
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

usage() {
  cat <<'TEXT'
用法：scripts/zhiku.sh <命令>

  setup    首次安装：生成 .env、启动依赖服务、安装前后端依赖并构建前端
  start    启动依赖服务和后端（前台运行，Ctrl+C 结束后端）
  stop     停止依赖服务（保留全部数据）
  samples  把 samples 目录里的三份示例手册导入知识库（需要后端已启动）
  check    检查各项依赖是否就绪
  verify   端到端验收：导入示例手册并用真实模型提问（需要后端已启动）
  test     运行前后端单元测试
TEXT
}

need() {
  command -v "$1" >/dev/null 2>&1 || { echo "缺少命令 $1：$2" >&2; exit 1; }
}

# 读取 .env 中的值；没有配置时返回默认值
env_value() {
  local value=""
  if [[ -f .env ]]; then
    value="$(grep -E "^$1=" .env | tail -n 1 | cut -d= -f2- | tr -d '\r' || true)"
  fi
  echo "${value:-$2}"
}

random_secret() {
  head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n'
}

ensure_env() {
  [[ -f .env ]] && return 0
  cp .env.example .env
  sed -i.bak "s/^MONGO_PASSWORD=.*/MONGO_PASSWORD=$(random_secret)/" .env
  rm -f .env.bak
  echo "已生成 .env，数据库密码为随机值。"
}

require_env() {
  [[ -f .env ]] || { echo "还没有 .env。请先执行：scripts/zhiku.sh setup" >&2; exit 1; }
}

# wait_http <名称> <URL> <最长等待秒数>
wait_http() {
  local name="$1" url="$2" deadline=$((SECONDS + $3)) announced=0
  until curl -fsS --noproxy '*' -o /dev/null --max-time 4 "$url" 2>/dev/null; do
    if (( SECONDS >= deadline )); then
      echo "$name 在 $3 秒内没有就绪。查看日志：docker compose logs" >&2
      exit 1
    fi
    if (( announced == 0 )); then
      echo "等待 $name 就绪…"
      announced=1
    fi
    sleep 3
  done
}

start_services() {
  need docker "请先安装并启动 Docker"
  docker compose up -d --wait
  # 两个模型首次启动要下载约 2.4 GB 的权重，并在 CPU 上预热，留足时间
  wait_http "向量模型（首次启动需要下载模型，可能要十几分钟）" \
    "http://127.0.0.1:$(env_value EMBEDDING_PORT 18181)/health" 1800
  wait_http "重排序模型" "http://127.0.0.1:$(env_value RERANK_PORT 18182)/health" 1800
}

backend() {
  (cd backend && uv run "$@")
}

command="${1:-}"
case "$command" in
  setup)
    need docker "请先安装并启动 Docker"
    need uv "安装方法见 https://docs.astral.sh/uv/"
    need npm "请先安装 Node.js 20 或更高版本"
    ensure_env
    start_services
    (cd backend && uv sync --locked)
    (cd frontend && npm ci && npm run build)
    backend python -m app.scripts.check_environment
    echo
    echo "安装完成。"
    if [[ -z "$(env_value LLM_API_KEY "")" ]]; then
      echo "下一步：在 .env 中填写 LLM_API_KEY，然后执行 scripts/zhiku.sh start"
    else
      echo "下一步：执行 scripts/zhiku.sh start"
    fi
    ;;
  start)
    require_env
    need uv "安装方法见 https://docs.astral.sh/uv/"
    start_services
    [[ -f frontend/dist/index.html ]] || echo "提示：前端尚未构建（cd frontend && npm ci && npm run build），当前只提供 API。"
    echo "掌柜智库：http://127.0.0.1:$(env_value APP_PORT 18100)"
    cd backend
    exec uv run python main.py
    ;;
  stop)
    require_env
    docker compose stop
    echo "依赖服务已停止，数据卷保留。"
    ;;
  samples)
    require_env
    backend python -m app.scripts.import_samples
    ;;
  check)
    require_env
    docker compose ps
    backend python -m app.scripts.check_environment
    ;;
  verify)
    require_env
    backend python -m app.scripts.verify_live
    ;;
  test)
    backend python -m pytest -q
    (cd frontend && npm test)
    ;;
  ""|-h|--help|help)
    usage
    ;;
  *)
    echo "未知命令：$command" >&2
    usage >&2
    exit 1
    ;;
esac
