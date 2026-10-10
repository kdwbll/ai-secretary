#!/bin/zsh
set -u

script_dir="${0:A:h}"
project_dir="${script_dir:h}"
python_bin="$project_dir/.venv/bin/python"
port="${SECOND_BRAIN_PORT:-8765}"
url="http://127.0.0.1:$port"
health_url="$url/api/health"
log_file="$project_dir/data/second-brain.log"
pid_file="$project_dir/data/second-brain-$port.pid"

show_error() {
  /usr/bin/osascript -e "display dialog \"$1\" with title \"第二大脑\" buttons {\"知道了\"} default button 1 with icon stop" >/dev/null 2>&1 || true
}

open_page() {
  if [[ "${SECOND_BRAIN_NO_OPEN:-0}" != "1" ]]; then
    /usr/bin/open "$url"
  fi
}

if /usr/bin/curl --silent --fail --max-time 2 "$health_url" >/dev/null 2>&1; then
  open_page
  exit 0
fi

if [[ ! -x "$python_bin" ]]; then
  show_error "缺少项目运行环境：$python_bin。请先在项目目录完成安装。"
  exit 1
fi

/bin/mkdir -p "$project_dir/data"
/usr/bin/nohup /usr/bin/env SECOND_BRAIN_ROOT="$project_dir" PYTHONUNBUFFERED=1 \
  "$python_bin" -m uvicorn core.secretary.app:app --app-dir "$project_dir" \
  --host 0.0.0.0 --port "$port" >>"$log_file" 2>&1 &
server_pid=$!
echo "$server_pid" >"$pid_file"

for _ in {1..60}; do
  if /usr/bin/curl --silent --fail --max-time 1 "$health_url" >/dev/null 2>&1; then
    open_page
    exit 0
  fi
  if ! /bin/kill -0 "$server_pid" >/dev/null 2>&1; then
    show_error "启动失败。请查看日志：$log_file"
    exit 1
  fi
  /bin/sleep 0.2
done

show_error "服务启动超时。请查看日志：$log_file"
exit 1
