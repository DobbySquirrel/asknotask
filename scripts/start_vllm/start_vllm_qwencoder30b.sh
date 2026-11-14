#!/bin/bash
# 启动 N 个 vLLM 分片：Qwen3-Coder-30B-A3B-Instruct，每卡一个，TP=1
# 用法:
#   bash start_vllm_qwencoder30b.sh        # 默认 1 个，GPU 0，端口 8000
#   bash start_vllm_qwencoder30b.sh 8      # 八张卡，端口 8000 / 8100 / ... / 8700
# 兼容入口: start_vllm_qwencoder30b_1vllm.sh / start_vllm_qwencoder30b_8vllm.sh

set -e

N_SHARDS="${1:-1}"
if ! [[ "${N_SHARDS}" =~ ^[1-8]$ ]]; then
    echo "N_SHARDS 必须是 1 到 8，收到: ${N_SHARDS}" >&2
    exit 1
fi

CONDA_ENV="${CONDA_ENV:-Qwen3-32B}"
SERVED_NAME="${SERVED_NAME:-Qwen3-Coder-30B-A3B-Instruct}"
if [[ -z "${MODEL_PATH:-}" ]]; then
    echo "请设置 MODEL_PATH 为 Qwen3-Coder-30B-A3B-Instruct 模型目录" >&2
    exit 1
fi
if [[ -z "${CONDA_BASE:-}" ]]; then
    if command -v conda >/dev/null 2>&1; then
        CONDA_BASE="$(conda info --base)"
    else
        echo "请设置 CONDA_BASE 为 conda 安装目录，或把 conda 放进 PATH" >&2
        exit 1
    fi
fi
GPU_MEM_UTIL=0.85
TP_SIZE=1
MAX_MODEL_LEN=32768
WAIT_SEC=600

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${SCRIPT_DIR}/logs"
GPUS=(0 1 2 3 4 5 6 7)
PORTS=(8000 8100 8200 8300 8400 8500 8600 8700)

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

have_screen() { command -v screen >/dev/null 2>&1; }

# 单卡沿用旧会话名 vllm_a3b，多卡沿用 vllm_coder30b_shard{i}
screen_name() {
    local i="$1"
    if [[ "${N_SHARDS}" -eq 1 && "${i}" -eq 0 ]]; then
        echo "vllm_a3b"
    else
        echo "vllm_coder30b_shard${i}"
    fi
}

pid_file() {
    local i="$1"
    echo "${LOG_DIR}/vllm_a3b_shard${i}_p${PORTS[$i]}.pid"
}

log_file() {
    local i="$1"
    echo "${LOG_DIR}/vllm_a3b_shard${i}_p${PORTS[$i]}.log"
}

stop_existing() {
    mkdir -p "${LOG_DIR}"
    # 也清掉旧单卡会话，避免占着 8000
    if have_screen; then
        screen -S "vllm_a3b" -X quit 2>/dev/null || true
        for i in $(seq 0 7); do
            screen -S "vllm_coder30b_shard${i}" -X quit 2>/dev/null || true
        done
    fi
    for i in $(seq 0 $((N_SHARDS - 1))); do
        local pf old_pid
        pf="$(pid_file "$i")"
        # 兼容旧单卡 pid 文件名
        if [[ "${N_SHARDS}" -eq 1 && "${i}" -eq 0 && ! -f "${pf}" ]]; then
            pf="${LOG_DIR}/vllm_a3b_p${PORTS[$i]}.pid"
        fi
        if [[ -f "${pf}" ]]; then
            old_pid="$(cat "${pf}" 2>/dev/null || true)"
            if [[ -n "${old_pid}" ]] && kill -0 "${old_pid}" 2>/dev/null; then
                echo -e "${YELLOW}停止已有进程 PID=${old_pid} (shard ${i})${NC}"
                kill "${old_pid}" 2>/dev/null || true
                sleep 2
                kill -9 "${old_pid}" 2>/dev/null || true
            fi
            rm -f "${pf}"
        fi
        fuser -k "${PORTS[$i]}/tcp" 2>/dev/null || true
    done
    sleep 2
}

launch_one() {
    local i="$1"
    local gpu="${GPUS[$i]}"
    local port="${PORTS[$i]}"
    local name log pf inner
    name="$(screen_name "$i")"
    log="$(log_file "$i")"
    pf="$(pid_file "$i")"

    inner="
        source ${CONDA_BASE}/etc/profile.d/conda.sh
        conda activate ${CONDA_ENV}
        export CUDA_VISIBLE_DEVICES=${gpu}
        export PYTHONUNBUFFERED=1
        echo '[vLLM] 分片 ${i} 启动'
        echo '[vLLM] GPU: ${gpu}'
        echo '[vLLM] 端口: ${port}'
        echo '[vLLM] 模型: ${MODEL_PATH}'
        echo '[vLLM] served-name: ${SERVED_NAME}'
        exec vllm serve ${MODEL_PATH} \\
            --served-model-name ${SERVED_NAME} \\
            --dtype auto \\
            --host 0.0.0.0 \\
            --port ${port} \\
            --gpu-memory-utilization ${GPU_MEM_UTIL} \\
            --max-model-len ${MAX_MODEL_LEN} \\
            --enable-prefix-caching \\
            --enable-chunked-prefill \\
            --tensor-parallel-size ${TP_SIZE}
    "
    if have_screen; then
        screen -dmS "${name}" bash -c "exec >${log} 2>&1; ${inner}"
    else
        nohup bash -c "${inner}" >"${log}" 2>&1 &
        echo $! >"${pf}"
    fi
}

wait_ready() {
    local i="$1"
    local port="${PORTS[$i]}"
    local log pf pid
    log="$(log_file "$i")"
    pf="$(pid_file "$i")"
    echo -n "  等待分片 ${i} 就绪"
    local deadline=$((SECONDS + WAIT_SEC))
    while ! curl -s "http://127.0.0.1:${port}/v1/models" >/dev/null 2>&1; do
        if (( SECONDS >= deadline )); then
            echo -e " ${RED}超时 (${WAIT_SEC}s)${NC}"
            echo -e "${YELLOW}最近日志 ${log}:${NC}"
            tail -n 40 "${log}" 2>/dev/null || true
            exit 1
        fi
        if [[ -f "${pf}" ]]; then
            pid="$(cat "${pf}" 2>/dev/null || true)"
            if [[ -n "${pid}" ]] && ! kill -0 "${pid}" 2>/dev/null; then
                echo -e " ${RED}进程已退出 PID=${pid}${NC}"
                echo -e "${YELLOW}最近日志 ${log}:${NC}"
                tail -n 40 "${log}" 2>/dev/null || true
                exit 1
            fi
        fi
        echo -n "."
        sleep 2
    done
    echo -e " ${GREEN}✓${NC}"
}

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}启动 ${N_SHARDS} 个 vLLM 分片${NC}"
echo -e "${GREEN}环境: ${CONDA_ENV}${NC}"
echo -e "${GREEN}模型: ${MODEL_PATH}${NC}"
echo -e "${GREEN}GPU: ${GPUS[0]}$(if [[ ${N_SHARDS} -gt 1 ]]; then echo "-${GPUS[$((N_SHARDS-1))]}"; fi) (每卡一个，TP_SIZE=${TP_SIZE})${NC}"
echo -e "${GREEN}端口: ${PORTS[0]}$(if [[ ${N_SHARDS} -gt 1 ]]; then echo " / ... / ${PORTS[$((N_SHARDS-1))]}"; fi)${NC}"
echo -e "${GREEN}========================================${NC}"

if [[ ! -d "${MODEL_PATH}" ]]; then
    echo -e "${RED}[ERROR] 模型路径不存在: ${MODEL_PATH}${NC}" >&2
    exit 1
fi

if ! conda env list | grep -q "${CONDA_ENV}"; then
    echo -e "${RED}[ERROR] conda 环境不存在: ${CONDA_ENV}${NC}" >&2
    exit 1
fi

stop_existing

for i in $(seq 0 $((N_SHARDS - 1))); do
    echo -e "${YELLOW}[$((i+1))/${N_SHARDS}] 启动分片 ${i}: GPU=${GPUS[$i]}, 端口=${PORTS[$i]}${NC}"
    launch_one "$i"
    wait_ready "$i"
done

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}vLLM 分片已启动！${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "端口状态:"
for i in $(seq 0 $((N_SHARDS - 1))); do
    if curl -s "http://127.0.0.1:${PORTS[$i]}/v1/models" >/dev/null 2>&1; then
        echo -e "  ${GREEN}✅${NC} GPU ${GPUS[$i]} → port ${PORTS[$i]}: 正常"
    else
        echo -e "  ${RED}❌${NC} GPU ${GPUS[$i]} → port ${PORTS[$i]}: 异常"
    fi
done

echo ""
echo -e "${YELLOW}管理命令:${NC}"
if have_screen; then
    if [[ "${N_SHARDS}" -eq 1 ]]; then
        echo "  查看会话:   screen -ls | grep vllm_a3b"
        echo "  进入会话:   screen -r vllm_a3b"
        echo "  停止服务:   screen -S vllm_a3b -X quit"
    else
        echo "  查看会话:   screen -ls | grep vllm_coder30b"
        echo "  进入分片0:  screen -r vllm_coder30b_shard0"
        echo "  停止所有:   for i in \$(seq 0 $((N_SHARDS - 1))); do screen -S vllm_coder30b_shard\$i -X quit; done"
    fi
    echo "  退出 screen: Ctrl+A D"
else
    echo "  查看日志:   tail -f ${LOG_DIR}/vllm_a3b_shard0_p${PORTS[0]}.log"
    echo "  停止服务:   for i in \$(seq 0 $((N_SHARDS - 1))); do kill \$(cat ${LOG_DIR}/vllm_a3b_shard\$i_p\${PORTS[\$i]}.pid); done"
fi
