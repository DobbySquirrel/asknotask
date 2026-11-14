#!/bin/bash
# 一键启动 8 个 vLLM 分片（GPU 0-7，端口 8000 / 8100 / ... / 8700）
# 使用方法: bash start_vllm_qwencoder30b_8vllm.sh
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "${SCRIPT_DIR}/start_vllm_qwencoder30b.sh" 8
