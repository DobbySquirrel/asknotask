#!/bin/bash
# 一键启动 1 个 vLLM 分片（GPU 0，端口 8000）
# 使用方法: bash start_vllm_qwencoder30b_1vllm.sh
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "${SCRIPT_DIR}/start_vllm_qwencoder30b.sh" 1
