#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${ROOT_DIR}"

SPEC2CASE_REGION="${SPEC2CASE_REGION:-cn}"

if [ "${SPEC2CASE_REGION}" = "cn" ]; then
    DEFAULT_BASE_IMAGE_FALLBACK="docker.1ms.run/library/python:3.11-slim-bookworm"
    DEFAULT_PIP_INDEX_URL="https://pypi.tuna.tsinghua.edu.cn/simple"
    DEFAULT_APT_MIRROR="https://mirrors.tuna.tsinghua.edu.cn/debian"
    DEFAULT_APT_SECURITY_MIRROR="https://mirrors.tuna.tsinghua.edu.cn/debian-security"
else
    DEFAULT_BASE_IMAGE_FALLBACK=""
    DEFAULT_PIP_INDEX_URL=""
    DEFAULT_APT_MIRROR=""
    DEFAULT_APT_SECURITY_MIRROR=""
fi

SPEC2CASE_PORT="${SPEC2CASE_PORT:-5002}"
SPEC2CASE_DATA_DIR="${SPEC2CASE_DATA_DIR:-./runtime}"
SPEC2CASE_SKIP_DOCKER_START="${SPEC2CASE_SKIP_DOCKER_START:-0}"
SPEC2CASE_BASE_IMAGE="${SPEC2CASE_BASE_IMAGE:-python:3.11-slim-bookworm}"
SPEC2CASE_BASE_IMAGE_FALLBACK="${SPEC2CASE_BASE_IMAGE_FALLBACK:-${DEFAULT_BASE_IMAGE_FALLBACK}}"
SPEC2CASE_PIP_INDEX_URL="${SPEC2CASE_PIP_INDEX_URL:-${DEFAULT_PIP_INDEX_URL}}"
SPEC2CASE_APT_MIRROR="${SPEC2CASE_APT_MIRROR:-${DEFAULT_APT_MIRROR}}"
SPEC2CASE_APT_SECURITY_MIRROR="${SPEC2CASE_APT_SECURITY_MIRROR:-${DEFAULT_APT_SECURITY_MIRROR}}"
export SPEC2CASE_PORT SPEC2CASE_DATA_DIR SPEC2CASE_BASE_IMAGE
export SPEC2CASE_PIP_INDEX_URL SPEC2CASE_APT_MIRROR SPEC2CASE_APT_SECURITY_MIRROR

DOCKER_WITH_SUDO=0
DOCKER_COMPOSE_IMPL=""

log() {
    printf '\n==> %s\n' "$1"
}

warn() {
    printf '\n[WARN] %s\n' "$1" >&2
}

die() {
    printf '\n[ERROR] %s\n' "$1" >&2
    exit 1
}

need_sudo() {
    if [ "$(id -u)" -eq 0 ]; then
        SUDO=""
        return
    fi

    if ! command -v sudo >/dev/null 2>&1; then
        die "当前用户不是 root，且系统未安装 sudo。请安装 sudo 或使用 root 用户执行。"
    fi

    SUDO="sudo"
}

docker_cmd() {
    if [ "${DOCKER_WITH_SUDO}" = "1" ]; then
        sudo docker "$@"
    else
        docker "$@"
    fi
}

compose_cmd() {
    case "${DOCKER_COMPOSE_IMPL}" in
        plugin)
            docker_cmd compose "$@"
            ;;
        standalone)
            if [ "${DOCKER_WITH_SUDO}" = "1" ]; then
                sudo docker-compose "$@"
            else
                docker-compose "$@"
            fi
            ;;
        *)
            die "Docker Compose 未初始化。"
            ;;
    esac
}

detect_ubuntu() {
    if [ ! -f /etc/os-release ]; then
        return 1
    fi

    # shellcheck disable=SC1091
    . /etc/os-release
    [ "${ID:-}" = "ubuntu" ]
}

install_docker_on_ubuntu() {
    need_sudo

    log "安装 Docker Engine 和 Docker Compose 插件"

    # shellcheck disable=SC1091
    . /etc/os-release
    UBUNTU_CODENAME_VALUE="${VERSION_CODENAME:-${UBUNTU_CODENAME:-}}"
    if [ -z "${UBUNTU_CODENAME_VALUE}" ]; then
        die "无法识别 Ubuntu 版本代号，请手动安装 Docker 后重试。"
    fi

    ${SUDO} apt-get update
    ${SUDO} apt-get install -y ca-certificates curl gnupg
    ${SUDO} install -m 0755 -d /etc/apt/keyrings
    ${SUDO} curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    ${SUDO} chmod a+r /etc/apt/keyrings/docker.asc

    DOCKER_ARCH="$(dpkg --print-architecture)"
    printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu %s stable\n' \
        "${DOCKER_ARCH}" \
        "${UBUNTU_CODENAME_VALUE}" | ${SUDO} tee /etc/apt/sources.list.d/docker.list >/dev/null

    ${SUDO} apt-get update
    ${SUDO} apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    if command -v systemctl >/dev/null 2>&1; then
        ${SUDO} systemctl enable --now docker || true
    fi
}

wait_for_docker_desktop() {
    log "等待 Docker Desktop 启动"

    for _ in $(seq 1 60); do
        if docker info >/dev/null 2>&1; then
            return
        fi
        sleep 2
    done

    die "Docker Desktop 未启动。请打开 Docker Desktop，确认运行后重新执行脚本。"
}

ensure_docker_on_macos() {
    if ! command -v docker >/dev/null 2>&1; then
        if command -v brew >/dev/null 2>&1; then
            log "安装 Docker Desktop"
            brew install --cask docker
        else
            die "未找到 Docker。请先安装 Docker Desktop，或安装 Homebrew 后重新执行脚本。"
        fi
    fi

    if ! docker info >/dev/null 2>&1; then
        if command -v open >/dev/null 2>&1 && open -Ra Docker >/dev/null 2>&1; then
            open -a Docker || true
        elif command -v brew >/dev/null 2>&1; then
            die "Docker CLI 已安装，但 Docker Desktop 未安装或未启动。请执行 brew install --cask docker 并启动 Docker Desktop 后重试。"
        else
            die "Docker CLI 已安装，但 Docker Desktop 未安装或未启动。请安装并启动 Docker Desktop 后重试。"
        fi
        wait_for_docker_desktop
    fi
}

ensure_docker_on_linux() {
    if ! command -v docker >/dev/null 2>&1; then
        if detect_ubuntu; then
            install_docker_on_ubuntu
        else
            die "当前 Linux 发行版不是 Ubuntu。请手动安装 Docker Engine 和 Docker Compose 插件后重试。"
        fi
    fi

    need_sudo

    if command -v systemctl >/dev/null 2>&1; then
        ${SUDO} systemctl start docker || true
    fi

    if docker info >/dev/null 2>&1; then
        DOCKER_WITH_SUDO=0
    elif [ -n "${SUDO}" ] && ${SUDO} docker info >/dev/null 2>&1; then
        DOCKER_WITH_SUDO=1
        warn "当前用户没有 Docker 权限，本次将使用 sudo 运行 Docker。"
    else
        die "Docker 服务不可用。请确认 Docker 已启动后重试。"
    fi
}

ensure_docker() {
    case "$(uname -s)" in
        Darwin)
            ensure_docker_on_macos
            ;;
        Linux)
            ensure_docker_on_linux
            ;;
        *)
            die "暂不支持当前系统。请使用 Ubuntu 或 macOS。"
            ;;
    esac

    if docker_cmd compose version >/dev/null 2>&1; then
        DOCKER_COMPOSE_IMPL="plugin"
    elif command -v docker-compose >/dev/null 2>&1; then
        if [ "${DOCKER_WITH_SUDO}" = "1" ]; then
            sudo docker-compose version >/dev/null 2>&1 || die "Docker Compose 不可用。请安装 Docker Compose v2 后重试。"
        else
            docker-compose version >/dev/null 2>&1 || die "Docker Compose 不可用。请安装 Docker Compose v2 后重试。"
        fi
        DOCKER_COMPOSE_IMPL="standalone"
    else
        die "Docker Compose 不可用。请安装 Docker Compose v2 后重试。"
    fi
}

ensure_base_image() {
    local candidates=(
        "${SPEC2CASE_BASE_IMAGE}"
        "${SPEC2CASE_BASE_IMAGE_FALLBACK}"
    )
    local image

    for image in "${candidates[@]}"; do
        [ -n "${image}" ] || continue

        if docker_cmd image inspect "${image}" >/dev/null 2>&1; then
            if [ "${SPEC2CASE_BASE_IMAGE}" != "${image}" ]; then
                warn "当前基础镜像 ${SPEC2CASE_BASE_IMAGE} 不可用，改用本地已存在的 ${image}"
                SPEC2CASE_BASE_IMAGE="${image}"
            fi
            export SPEC2CASE_BASE_IMAGE
            return 0
        fi

        if docker_cmd pull "${image}" >/dev/null 2>&1; then
            if [ "${SPEC2CASE_BASE_IMAGE}" != "${image}" ]; then
                warn "当前基础镜像 ${SPEC2CASE_BASE_IMAGE} 拉取失败，改用 ${image}"
                SPEC2CASE_BASE_IMAGE="${image}"
            fi
            export SPEC2CASE_BASE_IMAGE
            return 0
        fi
    done

    warn "未能预拉取基础镜像 ${SPEC2CASE_BASE_IMAGE} 或回退镜像 ${SPEC2CASE_BASE_IMAGE_FALLBACK}，将继续尝试构建。"
}

prepare_runtime() {
    log "准备运行目录和模型配置"

    mkdir -p \
        "${SPEC2CASE_DATA_DIR}/data" \
        "${SPEC2CASE_DATA_DIR}/uploads" \
        "${SPEC2CASE_DATA_DIR}/outputs" \
        "${SPEC2CASE_DATA_DIR}/logs" \
        "${SPEC2CASE_DATA_DIR}/config"

    CONFIG_FILE="${SPEC2CASE_DATA_DIR}/config/OAI_CONFIG_LIST"
    if [ ! -f "${CONFIG_FILE}" ]; then
        cp config/OAI_CONFIG_LIST.example "${CONFIG_FILE}"
        warn "已生成 ${CONFIG_FILE}，首次使用前请在页面“模型配置”中填写模型信息。"
    fi
}

start_service() {
    if [ "${SPEC2CASE_SKIP_DOCKER_START}" = "1" ]; then
        log "跳过 Docker 启动"
        compose_cmd config >/dev/null
        return
    fi

    ensure_base_image

    log "启动 Spec2Case"
    if ! compose_cmd up -d --build; then
        cat >&2 <<'EOF'

[ERROR] Docker 构建或启动失败。

常见原因：
- Docker Hub 匿名拉取限流，请执行 docker login 后重试。
- Docker Desktop/daemon 配置的镜像源不可用，请更换或关闭异常 registry mirror。
- 当前网络无法拉取 python:3.11-slim-bookworm 等基础镜像。
- 如不在中国大陆网络环境，可执行 SPEC2CASE_REGION=global bash scripts/quick-start.sh。

处理后重新执行：
  bash scripts/quick-start.sh
EOF
        exit 1
    fi
}

main() {
    ensure_docker
    prepare_runtime
    start_service

    log "启动完成"
    printf '访问地址: http://localhost:%s\n' "${SPEC2CASE_PORT}"
    printf '模型配置: %s/config/OAI_CONFIG_LIST\n' "${SPEC2CASE_DATA_DIR}"
}

main "$@"
