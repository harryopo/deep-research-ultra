#!/usr/bin/env bash
# ============================================================
# Deep Research Ultra v4.0 — MCP 服务器一键配置脚本
# ============================================================
# 功能：配置深度调研所需的 5 个核心 MCP 服务器
#   1. Tavily MCP          — AI 搜索引擎（1000 次/月免费）
#   2. Firecrawl MCP       — 网页抓取与爬取（500 credits/月免费）
#   3. open-websearch MCP  — 免费多引擎搜索（无需 API Key）
#   4. arxiv MCP           — arXiv 论文搜索（完全免费）
#   5. paper-search MCP    — 14 学术平台聚合（完全免费）
#
# 使用方式：
#   bash scripts/setup-mcp.sh              # 交互式配置全部
#   bash scripts/setup-mcp.sh --core       # 仅配置免费 MCP（open-websearch + arxiv + paper-search）
#   bash scripts/setup-mcp.sh --tavily KEY # 配置 Tavily 并指定 Key
#   bash scripts/setup-mcp.sh --check      # 仅检查现有配置
#   bash scripts/setup-mcp.sh --uninstall  # 移除所有已配置的 MCP
#
# 写到哪里（默认不依赖任何宿主 CLI）：
#   配置写进当前目录的 .mcp.json —— 这正是 research.py 的 McpClient 会读的文件。
#   装了 Claude Code CLI 且想让它接管，加 --via-claude（原先只有这一条路，
#   结果是没有 claude 命令的宿主照 --probe 的提示跑本脚本必然失败）。
#
# 前置条件：
#   - 已安装 Node.js（npx 命令可用）
#   - 已安装 Python（脚本用它写配置；uvx 仅 arxiv MCP 需要）
#   - --via-claude 时才需要 Claude Code CLI
# ============================================================

set -e

# ---------- 颜色定义 ----------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# ---------- 全局变量 ----------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CONFIG_LOG="$PROJECT_DIR/.mcp-setup.log"
MCP_JSON="${MCP_JSON:-$PWD/.mcp.json}"     # 默认写当前工作目录；--out 可改
USE_CLAUDE=0                                # 1＝改走 claude mcp add（宿主 CLI 路线）
PY_BIN="$(command -v python3 || command -v python || echo python)"
WRITER="$SCRIPT_DIR/mcp_config_writer.py"

# ---------- 工具函数 ----------
log_info()  { echo -e "${CYAN}[INFO]${NC}  $1"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step()  { echo -e "${MAGENTA}[STEP]${NC} $1"; }

check_command() {
    if command -v "$1" &> /dev/null; then
        return 0
    else
        return 1
    fi
}

check_prerequisites() {
    log_step "检查前置依赖..."
    local missing=()

    if [ "$USE_CLAUDE" = "1" ] && ! check_command "claude"; then
        log_error "加了 --via-claude 但宿主没有 claude 命令。去掉该参数即可（配置直接写 $MCP_JSON）"
        exit 1
    fi
    if [ "$USE_CLAUDE" != "1" ] && ! check_command "$PY_BIN"; then
        missing+=("python（写 .mcp.json 要用它）")
    fi
    if ! check_command "npx"; then
        missing+=("npx (Node.js)")
    fi
    if ! check_command "uvx"; then
        log_warn "uvx 未安装，arxiv MCP 将跳过（可通过 'pip install uv' 安装）"
    fi

    if [ ${#missing[@]} -ne 0 ]; then
        log_error "缺少前置依赖："
        for m in "${missing[@]}"; do
            echo "  - $m"
        done
        echo ""
        echo "请先安装缺失的依赖后重试。"
        exit 1
    fi

    log_ok "前置依赖检查通过"
    [ "$USE_CLAUDE" = "1" ] || log_info "配置写入：$MCP_JSON"
    echo ""
}

# ---------- 注册 / 移除（两条后端：本地 .mcp.json，或宿主 claude CLI）----------
#
# 原先只有 `claude mcp add` 一条路：没装 Claude Code CLI 的宿主（Qoder / TRAE / 纯
# Python 宿主）跑本脚本必失败，而 --probe 的提示又让人来跑它。现在默认写
# McpClient 自己会读的 .mcp.json，claude 路线留成 --via-claude 可选项。

register_server() {
    local name="$1"; shift
    local env_pairs=()
    local cmd=()
    while [ $# -gt 0 ]; do
        case "$1" in
            --env) env_pairs+=("$2"); shift 2 ;;
            --) shift; cmd=("$@"); break ;;
            *) shift ;;
        esac
    done
    if [ "${#cmd[@]}" -eq 0 ]; then
        log_error "register_server $name：-- 之后没有启动命令"
        return 1
    fi

    if [ "$USE_CLAUDE" = "1" ]; then
        local pass=()
        local pair
        for pair in "${env_pairs[@]}"; do pass+=(-e "$pair"); done
        claude mcp remove "$name" 2>/dev/null || true
        claude mcp add "$name" ${pass[@]+"${pass[@]}"} -- "${cmd[@]}"
    else
        local args=(--out "$MCP_JSON" --server "$name")
        for pair in "${env_pairs[@]}"; do args+=(--env "$pair"); done
        "$PY_BIN" "$WRITER" "${args[@]}" -- "${cmd[@]}" || return 1
    fi
}

remove_server() {
    local name="$1"
    if [ "$USE_CLAUDE" = "1" ]; then
        if claude mcp list 2>/dev/null | grep -q "^$name"; then
            claude mcp remove "$name" 2>/dev/null
            return $?
        fi
        return 1
    fi
    # 不许在这里吞退出码：卸载流程靠它决定"已移除"该不该说出口
    "$PY_BIN" "$WRITER" --out "$MCP_JSON" --remove "$name" >/dev/null 2>&1
}

# ---------- 单个 MCP 配置函数 ----------

setup_tavily() {
    local api_key="${1:-}"
    log_step "配置 Tavily MCP（AI 搜索引擎）..."

    if [ -z "$api_key" ]; then
        # 从环境变量读取
        api_key="${TAVILY_API_KEY:-}"
    fi
    if [ -z "$api_key" ]; then
        # 交互式输入
        echo -e "  ${CYAN}Tavily API Key 获取：https://app.tavily.com${NC}"
        read -p "  请输入 Tavily API Key（可留空跳过）: " api_key
    fi
    if [ -z "$api_key" ]; then
        log_warn "未提供 Tavily API Key，跳过配置（可稍后手动配置）"
        return 0
    fi

    # 添加新配置（使用 stdio 传输）
    register_server tavily --env TAVILY_API_KEY="$api_key" \
        -- npx -y tavily-mcp@latest

    log_ok "Tavily MCP 配置完成"
}

setup_firecrawl() {
    local api_key="${1:-}"
    log_step "配置 Firecrawl MCP（网页抓取与爬取）..."

    if [ -z "$api_key" ]; then
        api_key="${FIRECRAWL_API_KEY:-}"
    fi
    if [ -z "$api_key" ]; then
        echo -e "  ${CYAN}Firecrawl API Key 获取：https://www.firecrawl.dev/${NC}"
        read -p "  请输入 Firecrawl API Key（可留空跳过）: " api_key
    fi
    if [ -z "$api_key" ]; then
        log_warn "未提供 Firecrawl API Key，跳过配置"
        return 0
    fi

    register_server firecrawl --env FIRECRAWL_API_KEY="$api_key" \
        -- npx -y firecrawl-mcp

    log_ok "Firecrawl MCP 配置完成"
}

setup_open_websearch() {
    log_step "配置 open-websearch MCP（免费，无需 API Key）..."

    # open-websearch 支持配置默认搜索引擎
    register_server open-websearch \
        --env DEFAULT_SEARCH_ENGINE="bing" \
        --env MODE="stdio" \
        -- npx -y open-websearch@latest

    log_ok "open-websearch MCP 配置完成（免费，无需 Key）"
}

setup_arxiv() {
    log_step "配置 arXiv MCP（学术论文搜索）..."

    if ! check_command "uvx"; then
        log_warn "uvx 未安装，跳过 arXiv MCP"
        log_info "安装 uv：pip install uv"
        return 0
    fi

    register_server arxiv -- uvx arxiv-mcp-server

    log_ok "arXiv MCP 配置完成"
}

setup_paper_search() {
    log_step "配置 paper-search MCP（14 学术平台聚合）..."

    register_server paper-search -- npx -y paper-search-mcp-nodejs

    log_ok "paper-search MCP 配置完成"
}

# ---------- 检查与卸载函数 ----------

check_mcp_status() {
    log_step "当前 MCP 配置状态："
    echo ""
    if [ "$USE_CLAUDE" = "1" ]; then
        if ! command -v claude &> /dev/null; then
            log_error "claude CLI 不可用"
            return 1
        fi
        claude mcp list 2>/dev/null || log_warn "未发现已配置的 MCP 服务器"
    else
        log_info "配置文件：$MCP_JSON"
        "$PY_BIN" "$WRITER" --out "$MCP_JSON" --list ||
            log_warn "还没有任何已配置的调研 MCP（跑一次 bash scripts/setup-mcp.sh --core）"
    fi
    echo ""
}

uninstall_all_mcp() {
    log_step "移除所有已配置的调研 MCP..."
    local mcp_names=("tavily" "firecrawl" "open-websearch" "arxiv" "paper-search")
    local removed=0
    for name in "${mcp_names[@]}"; do
        if remove_server "$name"; then
            log_ok "已移除 $name"
            removed=$((removed + 1))
        fi
    done
    log_ok "清理完成（移除 $removed 个）"
}

# ---------- 主流程 ----------

show_help() {
    cat << 'EOF'
Deep Research Ultra v4.0 — MCP 配置脚本

用法：
  bash scripts/setup-mcp.sh [选项]

选项：
  --core             仅配置免费 MCP（open-websearch + arxiv + paper-search）
  --tavily KEY       配置 Tavily 并指定 API Key
  --firecrawl KEY    配置 Firecrawl 并指定 API Key
  --check            仅检查现有配置
  --uninstall        移除所有已配置的调研 MCP
  --out PATH         配置写到指定 .mcp.json（默认：当前目录的 .mcp.json）
  --via-claude       改走 claude mcp add（需要宿主装 Claude Code CLI）
  --help, -h         显示帮助

默认不需要 Claude Code CLI：配置直接写进 research.py 会读的 .mcp.json。
不传选项则交互式配置全部 MCP。

示例：
  bash scripts/setup-mcp.sh                          # 交互式配置全部
  bash scripts/setup-mcp.sh --core                   # 仅配置免费 MCP
  bash scripts/setup-mcp.sh --core --out ~/proj/.mcp.json
  bash scripts/setup-mcp.sh --tavily tvly-xxxxx      # 配置 Tavily
  bash scripts/setup-mcp.sh --check                  # 检查配置
EOF
}

main() {
    echo -e "${MAGENTA}"
    echo "============================================================"
    echo "  Deep Research Ultra v4.0 — MCP 服务器配置"
    echo "============================================================"
    echo -e "${NC}"

    # 解析参数
    local mode="interactive"
    local tavily_key=""
    local firecrawl_key=""

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --core)
                mode="core"
                shift
                ;;
            --tavily)
                mode="tavily"
                tavily_key="$2"
                shift 2
                ;;
            --firecrawl)
                mode="firecrawl"
                firecrawl_key="$2"
                shift 2
                ;;
            --check)
                check_prerequisites
                check_mcp_status
                exit 0
                ;;
            --uninstall)
                check_prerequisites
                uninstall_all_mcp
                exit 0
                ;;
            --out)
                MCP_JSON="$2"
                shift 2
                ;;
            --via-claude)
                USE_CLAUDE=1
                shift
                ;;
            --help|-h)
                show_help
                exit 0
                ;;
            *)
                log_error "未知选项：$1"
                show_help
                exit 1
                ;;
        esac
    done

    check_prerequisites

    case "$mode" in
        interactive)
            setup_open_websearch
            setup_arxiv
            setup_paper_search
            echo ""
            setup_tavily
            echo ""
            setup_firecrawl
            ;;
        core)
            setup_open_websearch
            setup_arxiv
            setup_paper_search
            ;;
        tavily)
            setup_tavily "$tavily_key"
            ;;
        firecrawl)
            setup_firecrawl "$firecrawl_key"
            ;;
    esac

    echo ""
    log_step "配置完成，验证："
    check_mcp_status

    echo ""
    log_ok "MCP 配置完成！"
    echo ""
    echo -e "${CYAN}后续步骤：${NC}"
    echo "  1. 验证数据源（要和配置同一个目录跑——research.py 按当前目录找 .mcp.json）："
    echo "       cd \"$(dirname "$MCP_JSON")\" && python \"$SCRIPT_DIR/research.py\" \"某主题\" --probe"
    echo "  2. 开始使用：深度调研 X 主题"
    if [ "$USE_CLAUDE" != "1" ]; then
        echo ""
        echo -e "${YELLOW}提示：${NC}配置写在 $MCP_JSON，本 skill 的引擎直接读它。"
        echo -e "        宿主自己也要加载这些 MCP 的话（如 Claude Code），"
        echo -e "        把这个文件并进宿主配置，或加 --via-claude 重跑本脚本。"
    fi
    echo -e "${YELLOW}提示：${NC}未配置 Tavily/Firecrawl 也能使用，将自动降级到免费 MCP"
}

main "$@"
