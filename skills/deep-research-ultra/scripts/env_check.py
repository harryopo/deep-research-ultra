"""
env_check.py — 调研环境分级清单 + 验证器

按调研场景（profile）声明所需环境，逐项验证（命令 / 环境变量 / 全局 skill / Python 模块 / 网络连通），
输出「就绪 / 缺失」报告与修复建议，作为调研启动前的原子门（exit 0=就绪，1=缺失）。

环境分级（profile）：
  minimal    — 任何调研的最小底子（Python + 内置引擎 + 网络）
  opensource — 开源项目调研（Gitee/ModelScope/arXiv 免费 API 直连，基本零配置；
               可选 GITHUB_TOKEN 提升 GitHub 深搜速率）
  academic   — 学术论文调研（arXiv 直连免费；可选 UNPAYWALL_EMAIL / Semantic Scholar key）
  full       — 全量深调研（在 academic 上加 MCP / Tavily / Firecrawl / Crawl4AI 反爬）

设计约束：
- 纯确定性检查（which / env / 目录存在 / import / TCP 连通），无 LLM
- 网络探测默认开启但可选禁用（--no-net），单项失败不中断、全部汇总
- 跨平台（Windows PowerShell 亦可用：命令探测走 shutil.which）
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import socket
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# 环境分级定义
# ---------------------------------------------------------------------------

PROFILES: Dict[str, Dict[str, Any]] = {
    'minimal': {
        'desc': '任何调研的最小底子',
        'commands': ['python'],
        'modules': ['engines'],
        'skills': [],
        'envs': [],
        'net': [],
    },
    'opensource': {
        'desc': '开源项目调研（Gitee/ModelScope/arXiv 免费直连，基本零配置）',
        'commands': ['python'],
        'modules': ['engines'],
        'skills': ['oss-finder', 'agent-reach', 'sciverse'],
        'envs': ['GITHUB_TOKEN'],  # 可选（提升 GitHub 深搜速率）
        'net': ['github.com', 'gitee.com', 'modelscope.cn', 'arxiv.org'],
    },
    'academic': {
        'desc': '学术论文调研（arXiv 免费直连；可选 key 解锁增强）',
        'commands': ['python'],
        'modules': ['engines'],
        'skills': ['sciverse', 'defuddle'],
        'envs': ['UNPAYWALL_EMAIL', 'GITHUB_TOKEN', 'OPENALEX_MAILTO'],
        'net': ['arxiv.org', 'api.semanticscholar.org', 'api.openalex.org', 'doi.org'],
    },
    'full': {
        'desc': '全量深度调研（MCP + Tavily/Firecrawl + Crawl4AI 反爬）',
        'commands': ['python', 'npx', 'claude'],
        'modules': ['engines'],
        'skills': ['oss-finder', 'agent-reach', 'last30days', 'sciverse', 'defuddle', 'context7'],
        'envs': ['TAVILY_API_KEY', 'FIRECRAWL_API_KEY', 'GITHUB_TOKEN', 'UNPAYWALL_EMAIL',
                 'CRAWL4AI_URL', 'CRAWL4AI_API_TOKEN', 'OPENALEX_MAILTO'],
        'net': ['github.com', 'gitee.com', 'modelscope.cn', 'arxiv.org', 'api.semanticscholar.org',
                'api.openalex.org', 'app.tavily.com', 'www.firecrawl.dev'],
    },
}

# 可选项目（缺失只警告，不阻断启动）
OPTIONAL_ENVS = {'GITHUB_TOKEN', 'UNPAYWALL_EMAIL', 'CRAWL4AI_URL', 'CRAWL4AI_API_TOKEN',
                 'TAVILY_API_KEY', 'FIRECRAWL_API_KEY', 'OPENALEX_MAILTO'}

# 缺失时要说清后果，否则用户只在并发撞限流后才知道有这档配置
ENV_HINTS = {
    'OPENALEX_MAILTO': ('OpenAlex 匿名请求不进 polite pool，多子 Agent 并发时极易 429；'
                        '设为你的邮箱即可显著提升配额'),
}
OPTIONAL_SKILLS = {'agent-reach', 'last30days', 'sciverse', 'context7', 'defuddle',
                   'oss-finder'}
OPTIONAL_COMMANDS = {'claude', 'npx', 'uvx', 'node', 'docker'}
# 网络探测主机全部视为可选（单点不通只告警，不阻断——调研可走降级链）
OPTIONAL_NET_HOSTS = True


@dataclass
class CheckItem:
    """单项验证结果"""
    category: str            # command/env/skill/module/net
    name: str
    ok: bool
    detail: str = ''
    optional: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {'category': self.category, 'name': self.name,
                'ok': self.ok, 'detail': self.detail, 'optional': self.optional}


@dataclass
class EnvReport:
    """环境验证报告"""
    profile: str
    checks: List[CheckItem] = field(default_factory=list)
    net_skipped: bool = False

    @property
    def missing(self) -> List[CheckItem]:
        return [c for c in self.checks if not c.ok and not c.optional]

    @property
    def warnings(self) -> List[CheckItem]:
        return [c for c in self.checks if not c.ok and c.optional]

    @property
    def ready(self) -> bool:
        return len(self.missing) == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'profile': self.profile,
            'ready': self.ready,
            'missing': [c.to_dict() for c in self.missing],
            'warnings': [c.to_dict() for c in self.warnings],
            'checks': [c.to_dict() for c in self.checks],
            'net_skipped': self.net_skipped,
        }


# ---------------------------------------------------------------------------
# 单项探测
# ---------------------------------------------------------------------------

def _check_command(name: str) -> Tuple[bool, str]:
    exe = shutil.which(name)
    if exe:
        return True, exe
    return False, f'未找到命令 {name}（请安装后重试）'


def _check_module(name: str) -> Tuple[bool, str]:
    try:
        importlib.import_module(name)
        return True, f'import {name} OK'
    except Exception as e:
        return False, f'import {name} 失败：{e}'


def _check_env(name: str) -> Tuple[bool, str]:
    v = os.environ.get(name, '').strip()
    if v:
        return True, f'{name} 已配置（{v[:12]}...）' if len(v) > 12 else f'{name} 已配置'
    hint = ENV_HINTS.get(name)
    return False, (f'缺少环境变量 {name} — {hint}' if hint else f'缺少环境变量 {name}')


def _check_skill(name: str) -> Tuple[bool, str]:
    for root in (Path.home() / '.agents' / 'skills', Path.home() / '.claude' / 'skills'):
        if (root / name / 'SKILL.md').exists():
            return True, f'{root / name}'
    return False, f'全局 skill 未找到 {name}（npx skills add <owner/repo> 安装）'


def _check_net(host: str, timeout: float = 3.0) -> Tuple[bool, str]:
    try:
        with socket.create_connection((host, 443), timeout=timeout):
            return True, f'{host}:443 连通'
    except Exception as e:
        return False, f'{host}:443 不可达（{e.__class__.__name__}）'


# ---------------------------------------------------------------------------
# 主验证入口
# ---------------------------------------------------------------------------

def run_env_check(profile: str = 'full', include_net: bool = True,
                  timeout: float = 3.0) -> EnvReport:
    """执行指定 profile 的环境验证。"""
    cfg = PROFILES.get(profile, PROFILES['full'])
    report = EnvReport(profile=profile)

    for cmd in cfg.get('commands', []):
        ok, detail = _check_command(cmd)
        report.checks.append(CheckItem('command', cmd, ok, detail,
                                       optional=cmd in OPTIONAL_COMMANDS))

    for mod in cfg.get('modules', []):
        ok, detail = _check_module(mod)
        report.checks.append(CheckItem('module', mod, ok, detail))

    for env in cfg.get('envs', []):
        optional = env in OPTIONAL_ENVS
        ok, detail = _check_env(env)
        report.checks.append(CheckItem('env', env, ok, detail, optional=optional))

    for skill in cfg.get('skills', []):
        ok, detail = _check_skill(skill)
        report.checks.append(CheckItem('skill', skill, ok, detail,
                                       optional=skill in OPTIONAL_SKILLS))

    if include_net:
        for host in cfg.get('net', []):
            ok, detail = _check_net(host, timeout)
            # v6.3：网络不通只告警（降级链兜底），不阻断启动
            report.checks.append(CheckItem('net', host, ok, detail, optional=True))
    else:
        report.net_skipped = True

    return report


def format_report(report: EnvReport, verbose: bool = False) -> str:
    """格式化报告（控制台友好）。"""
    lines = [f'== 环境验证报告（profile: {report.profile}）==']
    if report.profile in PROFILES:
        lines.append(f'   {PROFILES[report.profile]["desc"]}')
    lines.append('')
    for c in report.checks:
        mark = '✅' if c.ok else ('⚠️' if c.optional else '❌')
        tag = {'command': '命令', 'env': '环境变量', 'skill': '全局skill',
               'module': '模块', 'net': '网络'}.get(c.category, c.category)
        line = f'  {mark} [{tag}] {c.name}'
        if verbose or (not c.ok):
            line += f' — {c.detail}'
        lines.append(line)
    lines.append('')
    if report.missing:
        lines.append(f'❌ 缺失 {len(report.missing)} 项，尚未就绪：')
        for c in report.missing:
            lines.append(f'    - {c.name}: {c.detail}')
        lines.append('   修复：运行 setup 或安装对应依赖后重跑 --env-check')
    elif report.warnings:
        lines.append(f'✅ 就绪（可选增强项缺失 {len(report.warnings)} 项，不影响核心调研）')
    else:
        lines.append('✅ 环境完全就绪')
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main(argv: Optional[List[str]] = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(description='调研环境分级清单 + 验证器')
    parser.add_argument('--profile', choices=list(PROFILES.keys()), default='full',
                        help='调研场景（minimal/opensource/academic/full）')
    parser.add_argument('--no-net', action='store_true', help='跳过网络连通性探测')
    parser.add_argument('--json', action='store_true', help='输出 JSON')
    parser.add_argument('--verbose', action='store_true', help='显示全部项详情')
    opts = parser.parse_args(args)

    report = run_env_check(opts.profile, include_net=not opts.no_net)
    if opts.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(format_report(report, opts.verbose))
    return 0 if report.ready else 1


if __name__ == '__main__':
    from console import force_utf8
    force_utf8()
    sys.exit(_main())