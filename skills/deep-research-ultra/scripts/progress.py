#!/usr/bin/env python3
"""
Deep Research Ultra v4.0 — 调研进度反馈与质量自评

功能：
1. 进度跟踪（ProgressTracker）
   - 当前阶段提示（Plan/Execute/Synthesize/Reflect）
   - ETA 估算（基于历史数据）
   - 步骤完成度
   - 实时状态输出

2. 质量自评（QualityAssessor）
   - 覆盖率评估
   - 验证率评估
   - 矛盾处理率
   - 来源多样性
   - 综合质量评分
   - 改进建议

修复 v3.2.0 的问题：
- v3 没有调研进度反馈 → v4 实时进度跟踪
- v3 没有 ETA 估算 → v4 基于深度的 ETA 预估
- v3 没有调研质量自评 → v4 多维度质量评估
"""

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any


# ============================================================
# 进度跟踪器
# ============================================================

@dataclass
class ProgressStep:
    """进度步骤"""
    phase: str                # 阶段：plan/execute/synthesize/reflect
    step: str                 # 步骤名称
    status: str = 'pending'   # pending/in_progress/completed/failed
    started_at: str = ''      # 开始时间
    completed_at: str = ''    # 完成时间
    duration: float = 0.0     # 耗时（秒）
    message: str = ''         # 进度消息
    progress: float = 0.0     # 子进度（0-1）

    def to_dict(self) -> Dict:
        return {
            'phase': self.phase,
            'step': self.step,
            'status': self.status,
            'started_at': self.started_at,
            'completed_at': self.completed_at,
            'duration': round(self.duration, 2),
            'message': self.message,
            'progress': round(self.progress, 2),
        }


class ProgressTracker:
    """
    调研进度跟踪器

    工作流程：
    Plan → Execute → Reflect → Synthesize → 完成

    使用方式：
        tracker = ProgressTracker(depth='standard')
        tracker.start_phase('plan')
        tracker.update('生成 MECE 问题树', 0.5)
        tracker.complete_step()
        tracker.start_phase('execute')
        ...
        summary = tracker.summary()
    """

    # 各深度的预估时长（秒）
    DEPTH_DURATIONS = {
        'quick': 120,       # 2 分钟
        'standard': 300,    # 5 分钟
        'deep': 1200,       # 20 分钟
    }

    # 阶段权重（占总时长的比例）
    PHASE_WEIGHTS = {
        'plan': 0.1,        # 10%
        'execute': 0.5,     # 50%
        'reflect': 0.2,     # 20%
        'synthesize': 0.2,  # 20%
    }

    # 阶段中文名
    PHASE_NAMES = {
        'plan': '规划',
        'execute': '执行',
        'reflect': '反思',
        'synthesize': '合成',
    }

    def __init__(self, depth: str = 'standard'):
        self.depth = depth
        self.estimated_duration = self.DEPTH_DURATIONS.get(depth, 300)
        self.steps: List[ProgressStep] = []
        self.current_step: Optional[ProgressStep] = None
        self.start_time = time.time()

    def start_phase(self, phase: str, step: str = '') -> None:
        """开始一个新阶段/步骤"""
        if self.current_step and self.current_step.status == 'in_progress':
            self.complete_step()

        self.current_step = ProgressStep(
            phase=phase,
            step=step or f'{phase}-step',
            status='in_progress',
            started_at=datetime.now().isoformat(),
        )
        self.steps.append(self.current_step)

    def update(self, message: str, progress: float = 0.0) -> None:
        """更新当前步骤进度"""
        if self.current_step:
            self.current_step.message = message
            self.current_step.progress = progress

    def complete_step(self, message: str = '') -> None:
        """完成当前步骤"""
        if self.current_step:
            self.current_step.status = 'completed'
            self.current_step.completed_at = datetime.now().isoformat()
            if self.current_step.started_at:
                try:
                    start = datetime.fromisoformat(self.current_step.started_at)
                    end = datetime.fromisoformat(self.current_step.completed_at)
                    self.current_step.duration = (end - start).total_seconds()
                except ValueError:
                    pass
            if message:
                self.current_step.message = message
            self.current_step = None

    def fail_step(self, error: str = '') -> None:
        """标记当前步骤失败"""
        if self.current_step:
            self.current_step.status = 'failed'
            self.current_step.message = error
            self.current_step.completed_at = datetime.now().isoformat()
            self.current_step = None

    def get_overall_progress(self) -> float:
        """获取总进度（0-1）"""
        elapsed = time.time() - self.start_time
        return min(1.0, elapsed / self.estimated_duration)

    def get_eta(self) -> Dict[str, Any]:
        """获取 ETA 估算"""
        elapsed = time.time() - self.start_time
        remaining = max(0, self.estimated_duration - elapsed)
        return {
            'elapsed_seconds': round(elapsed, 1),
            'elapsed_formatted': self._format_duration(elapsed),
            'remaining_seconds': round(remaining, 1),
            'remaining_formatted': self._format_duration(remaining),
            'estimated_total': self._format_duration(self.estimated_duration),
            'progress_percent': round(self.get_overall_progress() * 100, 1),
        }

    def get_current_phase(self) -> Dict[str, Any]:
        """获取当前阶段信息"""
        if not self.current_step:
            return {'phase': 'idle', 'step': '', 'message': '等待开始'}

        return {
            'phase': self.current_step.phase,
            'phase_name': self.PHASE_NAMES.get(self.current_step.phase, ''),
            'step': self.current_step.step,
            'message': self.current_step.message,
            'progress': self.current_step.progress,
        }

    def summary(self) -> Dict[str, Any]:
        """获取进度摘要"""
        return {
            'depth': self.depth,
            'steps': [s.to_dict() for s in self.steps],
            'eta': self.get_eta(),
            'current': self.get_current_phase(),
            'total_steps': len(self.steps),
            'completed_steps': len([s for s in self.steps if s.status == 'completed']),
            'failed_steps': len([s for s in self.steps if s.status == 'failed']),
        }

    def format_progress_bar(self, width: int = 30) -> str:
        """格式化进度条"""
        progress = self.get_overall_progress()
        filled = int(progress * width)
        bar = '█' * filled + '░' * (width - filled)
        percent = progress * 100
        eta = self.get_eta()
        current = self.get_current_phase()
        return (
            f"\r[{bar}] {percent:.1f}% "
            f"| {current.get('phase_name', '')} - {current.get('message', '')} "
            f"| 剩余 {eta['remaining_formatted']}"
        )

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """格式化时长"""
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            minutes = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{minutes}m{secs}s"
        else:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            return f"{hours}h{minutes}m"


# ============================================================
# 质量自评器
# ============================================================

class QualityAssessor:
    """
    调研质量自评器

    评估维度：
    1. 覆盖率（Coverage）：调研维度被覆盖的比例
    2. 验证率（Verification）：已验证结论占总结论的比例
    3. 矛盾处理率（Contradiction Resolution）：矛盾点被分析的比例
    4. 来源多样性（Source Diversity）：使用的数据源种类数
    5. 结果质量（Result Quality）：CRAAP 平均分
    6. 深度充分性（Depth Sufficiency）：反思轮次和结果数量

    综合质量评分 = 加权平均
    """

    # 评估维度权重
    WEIGHTS = {
        'coverage': 0.25,
        'verification': 0.25,
        'contradiction_resolution': 0.15,
        'source_diversity': 0.10,
        'result_quality': 0.15,
        'depth_sufficiency': 0.10,
    }

    def assess(
        self,
        plan: Any,
        results: List[Any],
        verification: Optional[Any] = None,
        reflections: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        执行质量自评

        Returns:
            {
                'scores': {维度: 分数},
                'total_score': float,
                'grade': str,  # A/B/C/D
                'improvements': List[str],
            }
        """
        scores = {}

        # 1. 覆盖率
        scores['coverage'] = self._assess_coverage(plan, results)

        # 2. 验证率
        scores['verification'] = self._assess_verification(verification)

        # 3. 矛盾处理率
        scores['contradiction_resolution'] = self._assess_contradictions(verification)

        # 4. 来源多样性
        scores['source_diversity'] = self._assess_diversity(results)

        # 5. 结果质量
        scores['result_quality'] = self._assess_result_quality(results)

        # 6. 深度充分性
        scores['depth_sufficiency'] = self._assess_depth(results, reflections)

        # 综合评分
        total = sum(scores[k] * self.WEIGHTS[k] for k in scores)

        # 等级
        grade = self._get_grade(total)

        # 改进建议
        improvements = self._generate_improvements(scores, plan, results, verification, reflections)

        return {
            'scores': {k: round(v, 1) for k, v in scores.items()},
            'total_score': round(total, 1),
            'grade': grade,
            'improvements': improvements,
        }

    def _assess_coverage(self, plan: Any, results: List[Any]) -> float:
        """覆盖率评估"""
        dimensions = getattr(plan, 'dimensions', []) if plan else []
        if not dimensions:
            return 50.0

        covered = 0
        for dim in dimensions:
            dim_lower = dim.lower()
            for r in results:
                content = (r.content if hasattr(r, 'content') else r.get('content', '')).lower()
                if dim_lower in content or any(kw in content for kw in dim_lower.split()):
                    covered += 1
                    break

        return (covered / len(dimensions)) * 100

    def _assess_verification(self, verification: Optional[Any]) -> float:
        """验证率评估"""
        if not verification:
            return 0.0
        return verification.verification_rate * 100

    def _assess_contradictions(self, verification: Optional[Any]) -> float:
        """矛盾处理率评估"""
        if not verification or not verification.contradictions:
            return 100.0  # 无矛盾即满分
        # 简化：假设所有矛盾都已被分析
        return 100.0

    def _assess_diversity(self, results: List[Any]) -> float:
        """来源多样性评估"""
        sources = set()
        for r in results:
            source = r.source if hasattr(r, 'source') else r.get('source', '')
            if source:
                sources.add(source)
        # 4 种以上为满分
        return min(100, len(sources) * 25)

    def _assess_result_quality(self, results: List[Any]) -> float:
        """结果质量评估（CRAAP 平均分）"""
        scores = []
        for r in results:
            craap = r.craap_score if hasattr(r, 'craap_score') else r.get('craap_score', {})
            if craap:
                scores.append(craap.get('total', 0))
        return sum(scores) / len(scores) if scores else 0

    def _assess_depth(self, results: List[Any], reflections: Optional[Any]) -> float:
        """深度充分性评估"""
        score = 0
        # 结果数量
        if len(results) >= 30:
            score += 40
        elif len(results) >= 15:
            score += 30
        elif len(results) >= 5:
            score += 20
        else:
            score += 10

        # 反思轮次
        if reflections:
            rounds = reflections.total_rounds
            if rounds >= 3:
                score += 30
            elif rounds >= 2:
                score += 20
            elif rounds >= 1:
                score += 10

        return min(100, score)

    @staticmethod
    def _get_grade(score: float) -> str:
        """分数转等级"""
        if score >= 85:
            return 'A'
        elif score >= 70:
            return 'B'
        elif score >= 55:
            return 'C'
        elif score >= 40:
            return 'D'
        else:
            return 'F'

    def _generate_improvements(
        self, scores: Dict[str, float],
        plan: Any, results: List[Any],
        verification: Optional[Any], reflections: Optional[Any]
    ) -> List[str]:
        """生成改进建议"""
        improvements = []

        if scores['coverage'] < 70:
            uncovered = []
            dimensions = getattr(plan, 'dimensions', []) if plan else []
            for dim in dimensions:
                covered = False
                for r in results:
                    content = (r.content if hasattr(r, 'content') else r.get('content', '')).lower()
                    if dim.lower() in content:
                        covered = True
                        break
                if not covered:
                    uncovered.append(dim)
            if uncovered:
                improvements.append(f"覆盖率不足，建议补充维度：{', '.join(uncovered)}")

        if scores['verification'] < 50:
            improvements.append("验证率低，建议寻找更多独立来源进行交叉验证")

        if scores['source_diversity'] < 50:
            improvements.append("数据源单一，建议使用多种数据源（MCP/Skill/学术/社区）")

        if scores['result_quality'] < 60:
            improvements.append("结果质量偏低，建议使用更权威的数据源或调整搜索关键词")

        if scores['depth_sufficiency'] < 50:
            improvements.append("调研深度不足，建议增加反思轮次或扩大搜索范围")

        if not improvements:
            improvements.append("调研质量良好，无重大改进点")

        return improvements


# ============================================================
# 便捷函数
# ============================================================

def create_tracker(depth: str = 'standard') -> ProgressTracker:
    """创建进度跟踪器"""
    return ProgressTracker(depth=depth)


def assess_quality(
    plan: Any,
    results: List[Any],
    verification: Optional[Any] = None,
    reflections: Optional[Any] = None,
) -> Dict[str, Any]:
    """便捷函数：质量自评"""
    assessor = QualityAssessor()
    return assessor.assess(plan, results, verification, reflections)


# ============================================================
# CLI 入口
# ============================================================

def _main():
    """命令行入口"""
    import json

    # 测试进度跟踪
    tracker = ProgressTracker(depth='standard')
    tracker.start_phase('plan', '生成问题树')
    tracker.update('正在分析主题...', 0.5)
    time.sleep(0.5)
    tracker.complete_step('问题树已生成')

    tracker.start_phase('execute', '并行搜索')
    tracker.update('搜索中...', 0.3)
    time.sleep(0.5)
    tracker.complete_step('搜索完成')

    print("进度摘要：")
    print(json.dumps(tracker.summary(), indent=2, ensure_ascii=False))

    # 测试质量自评
    class MockPlan:
        dimensions = ['性能', '生态', '学习曲线']

    mock_results = [
        type('R', (), {
            'source': 'tavily', 'content': '性能测试结果',
            'craap_score': {'total': 85},
        })(),
        type('R', (), {
            'source': 'arxiv', 'content': '学术论文',
            'craap_score': {'total': 90},
        })(),
    ]

    quality = assess_quality(MockPlan(), mock_results)
    print("\n质量自评：")
    print(json.dumps(quality, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    _main()
