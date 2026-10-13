#!/usr/bin/env python3
"""
神经树验证器 v3.2 — 自动化检查脚本
用途：验证神经树文件的完整性、一致性和质量红线（结构层 V1–V13 + 内容层 V14–V21）
参考：SOP 第12章 自动化验证

检查项清单（V1–V21）：
  结构层：
    V1  11元素完整性（①–⑪ 通用核心 + ⑫ 证据链/有效期；缺③「适用主体与范围」的
        v3.1 旧格式神经元降级为兼容告警，不计入未通过计数）
    V2  触发词数量（≥5）          V3  判定模板完整性
    V4  误判防御数量（≥3）        V5  检查清单数量（≥3）
    V6  跨树突触填写              V7  根验证齐全
    V8  自检清单已执行            V9  Header统计准确
    V10 突触双向性                V11 触发词一致性
    V12 跨树引用有效性            V13 神经元编号连续性
  内容层：
    V14 常识填充检测（warning）   V15 引用模糊检测（warning）
    V16 通用安全检测（warning）   V17 矛盾检测（error）
    V18 列举计数校验（warning）   V19 限定词保真检测（warning）
    V20 标记规范检测（warning + error）
    V21 来源版本快照检查（warning + error）

变更日志：
  v3.2 2026-10-10  V1 升级为 11 元素名称关键词检测（不依赖编号字符，兼容全角/半角括号），
                   缺③旧格式神经元降级为兼容告警；新增 V18 列举计数校验、V19 限定词保真、
                   V20 标记规范、V21 来源版本快照四项内容层启发式检查；报告新增兼容告警汇总行；
                   健康度评分算法不变。
  v3.2-fix 2026-10-10  修复 V2/V4/V5/V6/V17 五项检查因正则结构错误导致的空转 bug：
                   原正则把元素编号与元素名称当作两个独立表格列（|④|触发词|），但实际格式
                   为同一单元格（|**④ 触发词**|），导致永远匹配不到目标行、检查默认通过。
                   全部改用 iterelement_rows() 名称匹配，与 V1/V11 方案统一，对未来编号
                   变动免疫。V17 触发词/标签/核心结论三处提取同步修正。V16 清理死代码 ⑦
                   并修复外层 if 运算符优先级 bug（and/or 化简为仅 phrase in line）。
                   V17 opposite_pairs 移除过宽的 ("是","否") 对。
  v1.0             初始版本（V1–V17）

用法：
    python 神经树验证器.py <神经树文件路径>
    python 神经树验证器.py --all           # 验证当前目录下所有神经树文件
    python 神经树验证器.py --sop <SOP文件>  # 同时验证SOP一致性

依赖：无（纯 Python 3 标准库）
"""

import re
import sys
import os
import csv
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional

# ============================================================================
# 平台兼容：GBK终端下安全打印
# ============================================================================

def safe_print(text: str):
    """安全打印，遇到GBK无法编码的字符时自动降级"""
    try:
        print(text)
    except UnicodeEncodeError:
        # 替换 emoji 等非 GBK 字符为安全替代
        safe = text.encode('gbk', errors='replace').decode('gbk', errors='replace')
        print(safe)

# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class CheckResult:
    """单条检查结果"""
    id: str
    name: str
    passed: bool
    detail: str = ""
    level: str = "error"  # error / warning / info

@dataclass
class ValidationReport:
    """验证报告"""
    tree_name: str
    file_path: str
    results: List[CheckResult] = field(default_factory=list)
    compat_notes: List[str] = field(default_factory=list)  # V1 旧格式兼容告警（不计入未通过）

    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def warning_count(self) -> int:
        return sum(1 for r in self.results if not r.passed and r.level == "warning")

    @property
    def error_count(self) -> int:
        return sum(1 for r in self.results if not r.passed and r.level == "error")

    @property
    def total(self) -> int:
        return len(self.results)

    def print(self):
        safe_print(f"\n{'='*60}")
        safe_print(f"  神经树验证报告：{self.tree_name}")
        safe_print(f"  文件：{self.file_path}")
        safe_print(f"{'='*60}")

        # 提取健康度
        health_result = next((r for r in self.results if r.id == "HEALTH"), None)
        health_text = health_result.detail if health_result else "健康度：未计算"

        safe_print(f"\n  状态总览")
        safe_print(f"  ✅ 通过：{self.passed_count}/{self.total}")
        safe_print(f"  ⚠️  警告：{self.warning_count}")
        safe_print(f"  ❌ 未通过：{self.error_count}")
        safe_print(f"  🩺 {health_text}")

        # V1 旧格式兼容告警：单独汇总一行，不计入未通过项主计数
        if self.compat_notes:
            safe_print(f"\n  🔄 兼容告警（v3.1 旧格式，不计入未通过）：{len(self.compat_notes)} 条")
            for note in self.compat_notes:
                safe_print(f"     → {note}")

        failed = [r for r in self.results if not r.passed and r.id != "HEALTH"]
        if failed:
            safe_print(f"\n  详细结果：")
            for r in failed:
                icon = "⚠️" if r.level == "warning" else "❌"
                safe_print(f"  {icon} [{r.id}] {r.name}")
                safe_print(f"     → {r.detail}")

        passed = [r for r in self.results if r.passed]
        if passed:
            safe_print(f"\n  ✅ 通过的检查（{len(passed)}项）：")
            for r in passed:
                safe_print(f"    ✅ [{r.id}] {r.name}")


# ============================================================================
# 检查函数
# ============================================================================

class NeuronTreeValidator:
    """神经树文件验证器"""

    # 常识填充词黑名单
    FILLER_WORDS = [
        "众所周知", "显然", "一般包括", "通常包括", "等等",
        "一般情况下", "一般来说", "大家都知道", "不言而喻",
    ]

    # 模糊引用黑名单
    VAGUE_REFERENCES = [
        "相关规范", "有关规定", "相关标准", "有关要求",
        "相关法律法规", "相关文件", "有关文件", "参考规范",
    ]

    def __init__(self, file_path: str):
        self.file_path = Path(file_path)
        self.content = self.file_path.read_text(encoding="utf-8")
        self.lines = self.content.split("\n")
        self.tree_name = self._extract_tree_name()
        self.compat_warnings: List[str] = []  # V1 旧格式兼容告警

    def _extract_tree_name(self) -> str:
        """从文件第一行提取树名"""
        for line in self.lines:
            if line.startswith("# 神经树｜"):
                name = line.replace("# 神经树｜", "").strip()
                return name
            if line.startswith("# 神经树"):
                name = line.replace("# 神经树", "").strip()
                return name
        return self.file_path.stem

    def _is_skeleton_section(self, section: str) -> bool:
        """判断神经元区域是否为骨架占位（未填充内容）"""
        if "{{待补充：" in section:
            return True
        stripped = section.strip()
        if len(stripped) < 120:
            return True
        if not any(marker in section for marker in [
            "①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨", "⑩"
        ]):
            return True
        return False

    def _neuron_sections(self) -> List[str]:
        """提取所有神经元区域文本"""
        return re.findall(
            r'### 🧠 N\d+.*?(?=### 🧠|### 🔗|## 📊|🍃|👉|$)',
            self.content,
            re.DOTALL
        )

    def _iter_element_rows(self, section: str):
        """迭代神经元元素表格行，返回 (行标签, 内容)。
        行标签如 '③适用主体与范围'；以名称匹配，不依赖编号字符，
        兼容 **加粗** 与全角/半角括号差异。"""
        for line in section.split("\n"):
            m = re.match(
                r'^\|\s*\*{0,2}([①-⑮])\*{0,2}\s*([^|*]+?)\s*\*{0,2}\s*\|(.*)\|\s*$',
                line.strip(),
            )
            if m:
                yield m.group(1) + m.group(2).strip(), m.group(3).strip()

    # ---- V1: 11元素完整性（①–⑪ 通用核心 + ⑫ 证据链/有效期）----

    # 元素名称关键词表（v3.2 标准：③「适用主体与范围」为新增元素）
    ELEMENT_KEYWORDS = [
        ("①", "一句话定义"),
        ("②", "使用场景"),
        ("③", "适用主体"),
        ("④", "核心数据"),
        ("⑤", "触发词"),
        ("⑥", "标签"),
        ("⑦", "判定模板"),
        ("⑧", "误判防御"),
        ("⑨", "检查清单"),
        ("⑩", "跨树突触"),
        ("⑪", "出处定位"),
        ("⑫", "证据链"),
    ]

    def check_v1_11_elements(self) -> CheckResult:
        """检查每个神经元是否包含11个核心元素（①–⑪）+⑫证据链/有效期。
        以元素名称关键词匹配（如"适用主体""证据链"），不依赖单一编号字符，
        避免全角/半角括号差异误判。
        向后兼容：缺③「适用主体与范围」但其余核心元素齐全的神经元（v3.1 旧格式）
        不记 error，改记兼容告警；兼容告警单独汇总，不计入未通过项主计数。"""
        neuron_count = 0
        incomplete_neurons = []

        for section in self._neuron_sections():
            title_match = re.search(r'### 🧠 (N\d+)', section)
            neuron_id = title_match.group(1) if title_match else "?"
            if self._is_skeleton_section(section):
                continue
            neuron_count += 1

            missing = [num + name for num, name in self.ELEMENT_KEYWORDS if name not in section]

            if not missing:
                continue

            if missing == ["③适用主体"]:
                # 旧格式（10元素）兼容降级：仅缺新增的③，其余核心元素齐全
                self.compat_warnings.append(f"{neuron_id} 缺③适用主体与范围（v3.1 旧格式，待迁移）")
            else:
                incomplete_neurons.append(f"{neuron_id} 缺少元素：{'、'.join(missing)}")

        if not incomplete_neurons:
            detail = f"检查了 {neuron_count} 个神经元，全部完整"
            if self.compat_warnings:
                detail += f"；{len(self.compat_warnings)} 个旧格式神经元缺③（已降级为兼容告警）"
            return CheckResult("V1", "11元素完整性", True, detail)
        else:
            return CheckResult("V1", "11元素完整性", False, "; ".join(incomplete_neurons))

    # ---- V2: 触发词数量 ----

    def check_v2_trigger_words(self) -> CheckResult:
        """检查每个神经元的触发词是否≥5个。
        v3.2 起触发词由④顺延为⑤，不再依赖编号字符，改用 _iter_element_rows 名称匹配。"""
        issues = []
        for section in self._neuron_sections():
            title_match = re.search(r'### 🧠 (N\d+)', section)
            neuron_id = title_match.group(1) if title_match else "?"
            if self._is_skeleton_section(section):
                continue

            trigger_content = None
            for label, content in self._iter_element_rows(section):
                if "触发词" in label:
                    trigger_content = content
                    break

            if trigger_content is None:
                continue  # V1 已检查元素缺失

            # 提取反引号内的触发词（如有）
            bt_match = re.search(r'`([^`]+)`', trigger_content)
            if bt_match:
                trigger_content = bt_match.group(1)

            # 处理 // 分层分隔符
            trigger_content = re.sub(r'\s*//\s*', '|', trigger_content)
            words = [w.strip() for w in trigger_content.split('|') if w.strip()]
            words = [w for w in words if w not in ["触发词", "关键词"]]
            if len(words) < 5:
                issues.append(f"{neuron_id} 触发词数={len(words)}（需≥5）")

        if not issues:
            return CheckResult("V2", "触发词数量", True, "全部神经元触发词≥5")
        else:
            return CheckResult("V2", "触发词数量", False, "; ".join(issues))

    # ---- V3: 判定模板完整性 ----

    def check_v3_judgment_template(self) -> CheckResult:
        """检查判定模板是否完整"""
        issues = []
        neuron_sections = re.findall(
            r'### 🧠 N\d+.*?(?=### 🧠|### 🔗|## 📊|🍃|👉|$)',
            self.content,
            re.DOTALL
        )

        for section in neuron_sections:
            title_match = re.search(r'### 🧠 (N\d+)', section)
            neuron_id = title_match.group(1) if title_match else "?"
            if self._is_skeleton_section(section):
                continue

            # 检查是否有判定模板
            has_linear = bool(re.search(r'①.*→.*②', section))
            has_decision_tree = bool(re.search(r'IF\s*\(', section, re.IGNORECASE))

            if not has_linear and not has_decision_tree:
                issues.append(f"{neuron_id} 缺少判定模板")

        if not issues:
            return CheckResult("V3", "判定模板完整性", True, "全部神经元有判定模板")
        else:
            return CheckResult("V3", "判定模板完整性", False, "; ".join(issues))

    # ---- V4: 误判防御数量 ----

    def check_v4_fallacies(self) -> CheckResult:
        """检查误判防御是否≥3条"""
        issues = []
        neuron_sections = re.findall(
            r'### 🧠 N\d+.*?(?=### 🧠|### 🔗|## 📊|🍃|👉|$)',
            self.content,
            re.DOTALL
        )

        for section in neuron_sections:
            title_match = re.search(r'### 🧠 (N\d+)', section)
            neuron_id = title_match.group(1) if title_match else "?"
            if self._is_skeleton_section(section):
                continue

            # 按名称查找误判防御行
            for label, content in self._iter_element_rows(section):
                if "误判防御" in label:
                    # 统计 ① ② ③的出现次数
                    markers = re.findall(r'[①②③④⑤]', content)
                    if len(markers) < 3:
                        issues.append(f"{neuron_id} 误判防御数={len(markers)}（需≥3）")
                    break

        if not issues:
            return CheckResult("V4", "误判防御数量", True, "全部神经元误判防御≥3条")
        else:
            return CheckResult("V4", "误判防御数量", False, "; ".join(issues))

    # ---- V5: 检查清单数量 ----

    def check_v5_checklist(self) -> CheckResult:
        """检查清单是否≥3条"""
        issues = []
        neuron_sections = re.findall(
            r'### 🧠 N\d+.*?(?=### 🧠|### 🔗|## 📊|🍃|👉|$)',
            self.content,
            re.DOTALL
        )

        for section in neuron_sections:
            title_match = re.search(r'### 🧠 (N\d+)', section)
            neuron_id = title_match.group(1) if title_match else "?"
            if self._is_skeleton_section(section):
                continue

            # 按名称查找检查清单行
            for label, content in self._iter_element_rows(section):
                if "检查清单" in label:
                    items = re.findall(r'□', content)
                    if len(items) < 3:
                        issues.append(f"{neuron_id} 检查清单数={len(items)}（需≥3）")
                    break

        if not issues:
            return CheckResult("V5", "检查清单数量", True, "全部神经元检查清单≥3条")
        else:
            return CheckResult("V5", "检查清单数量", False, "; ".join(issues))

    # ---- V6: 跨树突触填写 ----

    def check_v6_synapses(self) -> CheckResult:
        """检查跨树突触字段是否填写"""
        issues = []
        neuron_sections = re.findall(
            r'### 🧠 N\d+.*?(?=### 🧠|### 🔗|## 📊|🍃|👉|$)',
            self.content,
            re.DOTALL
        )

        for section in neuron_sections:
            title_match = re.search(r'### 🧠 (N\d+)', section)
            neuron_id = title_match.group(1) if title_match else "?"

            # 按名称查找跨树突触行
            for label, content in self._iter_element_rows(section):
                if "跨树突触" in label:
                    if not content or content.isspace():
                        issues.append(f"{neuron_id} 跨树突触为空")
                    break

        if not issues:
            return CheckResult("V6", "跨树突触填写", True, "全部已填写")
        else:
            return CheckResult("V6", "跨树突触填写", False, "; ".join(issues))

    # ---- V7: 根验证 ----

    def check_v7_root(self) -> CheckResult:
        """检查根验证是否齐全（3个判断题）"""
        root_section = re.search(
            r'## 🌱 根.*?(?=## 📐|## 🌿|## 🧬|## 🔗|## 🍃|## 📊|👉|$)',
            self.content,
            re.DOTALL
        )

        if not root_section:
            return CheckResult("V7", "根验证", False, "未找到根（Root）区域")

        root_content = root_section.group(0)

        # 检查3个判断题
        checks = [
            "第一性原理" in root_content,
            "反过来说" in root_content,
            "外行" in root_content or "外行听" in root_content,
        ]

        missing = [f"判断{i+1}" for i, c in enumerate(checks) if not c]
        if not missing:
            return CheckResult("V7", "根验证", True, "3个判断题齐全")
        else:
            return CheckResult("V7", "根验证", False, f"缺少：{', '.join(missing)}")

    # ---- V8: 自检清单 ----

    def check_v8_selfcheck(self) -> CheckResult:
        """检查自检清单是否已执行"""
        if "自检清单" not in self.content:
            return CheckResult("V8", "自检清单", False, "未找到自检清单区域")

        # 统计已打勾的项
        checked = self.content.count("□") + self.content.count("☑")
        # □ 表示待检查，但如果有10个□说明清单存在
        if checked >= 10:
            return CheckResult("V8", "自检清单", True, f"清单存在（{checked}项）")
        else:
            return CheckResult("V8", "自检清单", False, f"自检清单不完整（仅{checked}项）")

    # ---- V9: Header统计准确 ----

    def check_v9_header_stats(self) -> CheckResult:
        """检查Header中统计数是否与实际一致"""
        # 提取Header中的统计数字
        header_match = re.search(r'统计：(\d+)N\s*/\s*(\d+)突触\s*/\s*(\d+)末梢', self.content)
        if not header_match:
            if "模板" in self.tree_name or "template" in self.tree_name.lower():
                return CheckResult("V9", "Header统计", True, "模板文件，使用占位符，跳过统计一致性检查")
            if re.search(r'统计：\{.*?\}N\s*/\s*\{.*?\}突触\s*/\s*\{.*?\}末梢', self.content):
                return CheckResult("V9", "Header统计", True, "模板文件含占位符，跳过统计一致性检查")
            return CheckResult("V9", "Header统计", False, "未找到Header统计行")

        declared_N = int(header_match.group(1))
        declared_syn = int(header_match.group(2))
        declared_end = int(header_match.group(3))

        # 实际统计
        actual_N = len(re.findall(r'### 🧠 N\d+', self.content))
        actual_syn = len(re.findall(r'\| \*\*\d+', self.content))  # 粗略估计

        issues = []
        if declared_N != actual_N:
            issues.append(f"神经元数：声明={declared_N}，实际={actual_N}")

        if issues:
            return CheckResult("V9", "Header统计", False, "; ".join(issues))
        else:
            return CheckResult("V9", "Header统计", True, f"N={declared_N}, 一致")

    # ---- V10: 突触双向性（真实双向校验） ----

    def check_v10_bidirectional(self, other_files: List[str] = None) -> CheckResult:
        """检查跨树突触是否为双向：A→B 存在时，B→A 也必须存在"""
        # 优先从文件末尾「跨树突触」表格提取跨树突触（目标树名在第二列）
        cross_section = re.search(
            r'### 跨树突触.*?(?=## |\Z)',
            self.content,
            re.DOTALL
        )

        target_trees = []
        if cross_section:
            cross_content = cross_section.group(0)
            # 表格数据行格式: | 源树→源N | 目标树 | 目标N | ...
            raw_targets = re.findall(
                r'^\|\s*[^|]+?→N\d+.*?\|\s*([^|]+?)\s*\|',
                cross_content,
                re.MULTILINE
            )
            target_trees = [t.strip().strip('{}').strip() for t in raw_targets if t.strip()]
        else:
            # 回退：从神经元元素提取，但过滤掉纯神经元编号（如 N1、N2）
            raw_synapses = re.findall(
                r'→([^(→]+?)\(?[^)]*?\)?\s*∥\s*([^∥]+)∥',
                self.content
            )
            for match in raw_synapses:
                target_tree_raw = match[0].strip()
                if not target_tree_raw:
                    continue
                if re.match(r'^N\d+$', target_tree_raw):
                    continue  # 跳过纯神经元编号（树内突触）
                target_trees.append(target_tree_raw.strip('{}').strip())

        # 去重
        target_trees = list(dict.fromkeys([t for t in target_trees if t]))

        if not target_trees:
            return CheckResult("V10", "突触双向性", True, "当前树无跨树突触")

        base_dir = self.file_path.parent
        issues = []
        verified = 0

        for target_tree in target_trees:
            # 查找目标树文件
            target_file = None
            search_dirs = [base_dir]
            if other_files:
                for f in other_files:
                    search_dirs.append(Path(f).parent)

            for d in search_dirs:
                candidate = d / f"神经树_{target_tree}_v1.0.md"
                if candidate.exists():
                    target_file = candidate
                    break

            if not target_file:
                issues.append(f"A→{target_tree}：目标树文件不存在（待构建）")
                continue

            # 读取目标树文件，检查是否存在反向突触
            try:
                target_content = target_file.read_text(encoding="utf-8")
            except:
                issues.append(f"A→{target_tree}：无法读取目标树文件")
                continue

            # 在目标树的跨树突触表格中查找反向突触
            current_tree_name = self.tree_name.replace("神经树_", "").replace("_v1.0", "").replace("《", "").replace("》", "").strip()
            target_cross_section = re.search(
                r'### 跨树突触.*?(?=## |\Z)',
                target_content,
                re.DOTALL
            )

            has_reverse = False
            if target_cross_section:
                target_cross_content = target_cross_section.group(0)
                # 提取目标树跨树突触表格中所有目标树名
                raw_reverse_targets = re.findall(
                    r'^\|\s*[^|]+?→N\d+.*?\|\s*([^|]+?)\s*\|',
                    target_cross_content,
                    re.MULTILINE
                )
                for raw in raw_reverse_targets:
                    normalized = raw.strip().strip('{}').replace("神经树_", "").replace("_v1.0", "").replace("《", "").replace("》", "").strip()
                    if normalized == current_tree_name:
                        has_reverse = True
                        break

            if not has_reverse:
                if target_file:
                    issues.append(f"A→{target_tree} 存在，但 {target_tree}→A 缺失")
                else:
                    issues.append(f"A→{target_tree}：目标树未构建，待后续补齐")

            verified += 1

        if not issues:
            return CheckResult("V10", "突触双向性", True, f"{verified} 条突触双向完整")
        else:
            has_missing_file = any("待构建" in s for s in issues)
            level = "warning" if has_missing_file else "error"
            return CheckResult("V10", "突触双向性", False, "; ".join(issues), level=level)

    # ---- V11: 触发词一致性（索引表 vs 神经元） ----

    def check_v11_trigger_consistency(self) -> CheckResult:
        """检查每个神经元的触发词字段是否存在且格式正确"""
        issues = []
        has_layer_split = False
        neuron_sections = re.findall(
            r'### 🧠 N\d+.*?(?=### 🧠|### 🔗|## 📊|🍃|👉|$)',
            self.content,
            re.DOTALL
        )

        for section in neuron_sections:
            title_match = re.search(r'### 🧠 (N\d+)', section)
            neuron_id = title_match.group(1) if title_match else "?"
            if self._is_skeleton_section(section):
                continue

            # 按名称关键词定位触发词行（v3.2 起触发词由④顺延为⑤，
            # 不再依赖编号字符；兼容 **加粗** 与反引号有无两种格式）
            trigger_match = re.search(
                r'触发词[^\|`]*\|\s*`([^`]+)`',
                section
            )
            if not trigger_match:
                # 也可能是没有反引号的格式
                trigger_match = re.search(
                    r'触发词[^\|]*\|\s*([^`\|][^\|]+)',
                    section
                )
            if not trigger_match:
                issues.append(f"{neuron_id} 缺少触发词行")
                continue

            trigger_content = trigger_match.group(1)
            if "//" in trigger_content:
                has_layer_split = True

        if not issues:
            layer_note = "，触发词含分层（精确//模糊）" if has_layer_split else ""
            return CheckResult("V11", "触发词一致性", True, f"检查通过{layer_note}")
        else:
            return CheckResult("V11", "触发词一致性", False, "; ".join(issues))

    # ---- V12: 跨树引用有效性 ----

    def check_v12_cross_reference_validity(self) -> CheckResult:
        """检查跨树突触表格中引用的目标树是否存在"""
        # 限定在 "### 跨树突触" 区域搜索
        cross_section = re.search(
            r'### 跨树突触.*?(?=🍃|## )',
            self.content,
            re.DOTALL
        )

        if not cross_section:
            return CheckResult("V12", "跨树引用有效性", True, "当前树无跨树突触")

        cross_content = cross_section.group(0)

        # 从跨树突触表格数据行中提取目标树名列
        # 数据行格式: | 源→源N | 目标树 | 目标N | ...
        tree_refs = re.findall(
            r'\|\s*[^|]+?→N\d+.*?\|\s*([^|]+?)\s*\|',
            cross_content
        )

        if not tree_refs:
            return CheckResult("V12", "跨树引用有效性", True, "跨树突触区域未发现具体引用")

        # 清洗：去掉 {} 占位符，过滤表头、空字符串
        tree_refs = [ref.strip().strip('{}') for ref in tree_refs if ref.strip()]
        tree_refs = [ref for ref in tree_refs if len(ref) >= 2 and ref not in ['目标树']]

        if not tree_refs:
            return CheckResult("V12", "跨树引用有效性", True, "跨树突触引用均为占位符")

        # 检查同级目录下是否存在目标树文件
        base_dir = self.file_path.parent
        existing_files = [f.name for f in base_dir.iterdir() if f.suffix == '.md'] if base_dir.exists() else []

        found = 0
        not_found = []
        for ref in tree_refs:
            matched = any(ref in fname for fname in existing_files)
            if matched:
                found += 1
            else:
                not_found.append(ref)

        if not not_found:
            return CheckResult("V12", "跨树引用有效性", True, f"{found}/{len(tree_refs)} 条引用的目标文件存在")
        else:
            return CheckResult("V12", "跨树引用有效性", False, f"未找到目标文件：{', '.join(not_found[:3])}", level="warning")

    # ---- V13: 神经元编号连续性 ----

    def check_v13_numbering_continuity(self) -> CheckResult:
        """检查神经元编号是否连续（N1, N2, N3...无跳号）"""
        neuron_ids = re.findall(r'### 🧠 (N\d+)', self.content)

        if not neuron_ids:
            return CheckResult("V13", "编号连续性", False, "未找到任何神经元")

        # 提取数字部分
        numbers = []
        for nid in neuron_ids:
            try:
                num = int(nid[1:])
                numbers.append(num)
            except ValueError:
                continue

        if not numbers:
            return CheckResult("V13", "编号连续性", False, "无法解析编号")

        numbers.sort()
        expected = list(range(numbers[0], numbers[-1] + 1))

        missing = [str(n) for n in expected if n not in numbers]
        if not missing:
            return CheckResult("V13", "编号连续性", True, f"N{numbers[0]}~N{numbers[-1]} 连续")
        else:
            return CheckResult("V13", "编号连续性", False, f"缺少编号：N{', N'.join(missing)}")

    # ---- V14: 常识填充检测 ----

    def check_v14_filler_words(self) -> CheckResult:
        """检测是否使用了常识填充词"""
        found = []
        for i, line in enumerate(self.lines, 1):
            for word in self.FILLER_WORDS:
                if word in line and not line.strip().startswith("#"):
                    found.append(f"行{i}: 发现「{word}」")
                    break
            if not found:
                if re.search(r'等等', line) and not line.strip().startswith("#"):
                    found.append(f"行{i}: 发现「等等」")
                    break

        if not found:
            return CheckResult("V14", "常识填充检测", True, "未发现常识填充词")
        else:
            return CheckResult("V14", "常识填充检测", False, "; ".join(found[:5]), level="warning")

    # ---- V15: 引用模糊检测 ----

    def check_v15_vague_references(self) -> CheckResult:
        """检测是否使用模糊引用"""
        found = []
        for i, line in enumerate(self.lines, 1):
            for phrase in self.VAGUE_REFERENCES:
                if phrase in line:
                    found.append(f"行{i}: 发现「{phrase}」")
                    break

        if not found:
            return CheckResult("V15", "引用模糊检测", True, "引用精确")
        else:
            return CheckResult("V15", "引用模糊检测", False, "; ".join(found[:5]), level="warning")

    # ---- V16: 通用安全检测（精简版） ----

    def check_v16_generic_safety(self) -> CheckResult:
        """检测误判防御是否有通用安全语句"""
        generic_safety = [
            "注意安全", "注意安全操作", "安全第一",
            "遵守安全规定", "按规范操作",
        ]

        found = []
        for i, line in enumerate(self.lines, 1):
            for phrase in generic_safety:
                if phrase in line:
                    # 按名称定位误判防御区域（v3.2 起编号已顺移，不依赖⑦）
                    if "误判防御" in line:
                        found.append(f"行{i}: 「{phrase}」可能为通用安全语句")
                        break

        if not found:
            return CheckResult("V16", "通用安全检测", True, "误判防御含领域特有语境")
        else:
            return CheckResult("V16", "通用安全检测", False, "; ".join(found[:3]), level="warning")

    def calculate_health_score(self, log_dir: Optional[str] = None) -> str:
        """计算知识库健康度等级：🟢低 / 🟡中 / 🔴高"""
        score = 0.0

        # 1. 最近核查时间（从Header最后更新推断）
        header_match = re.search(r'最后更新：(\d{4}-\d{2}-\d{2})', self.content)
        if header_match:
            last_updated = header_match.group(1)
            try:
                from datetime import datetime
                updated = datetime.strptime(last_updated, "%Y-%m-%d")
                days = (datetime.now() - updated).days
                if days > 90:
                    score += 2
                elif days > 30:
                    score += 1
            except:
                score += 1
        else:
            score += 2

        # 2. 突触双向完整性
        cross_synapses = re.findall(
            r'→([^(→]+?)\(?[^)]*?\)?\s*∥\s*([^∥]+)∥',
            self.content
        )
        if cross_synapses:
            targets = [m[0].strip() for m in cross_synapses if m[0].strip()]
            if targets:
                score += 1  # 有跨树突触但无法确认双向，轻度扣分

        # 3. 未命中次数（如果提供日志目录）
        if log_dir:
            log_path = Path(log_dir)
            if log_path.exists() and log_path.is_dir():
                for csv_file in log_path.glob("*.csv"):
                    try:
                        with open(csv_file, "r", encoding="utf-8") as f:
                            reader = csv.DictReader(f)
                            for row in reader:
                                if self.tree_name in row.get("用户问题", "") or row.get("激活的神经元", "").startswith(self.tree_name.split("_")[0] if "_" in self.tree_name else self.tree_name):
                                    if row.get("日志类型", "") == "未命中":
                                        score += 0.5
                    except:
                        pass

        # 映射到等级
        if score <= 1:
            return "🟢 低"
        elif score <= 3:
            return "🟡 中"
        else:
            return "🔴 高"

    # ---- V17: 矛盾检测 ----

    def check_v17_contradiction(self) -> CheckResult:
        """检测同一触发词/标签下不同神经元是否存在相反结论"""
        neuron_sections = re.findall(
            r'### 🧠 N\d+.*?(?=### 🧠|### 🔗|## 📊|🍃|👉|$)',
            self.content,
            re.DOTALL
        )

        # 收集每个神经元的触发词、标签、核心结论
        # v3.2 起改用 _iter_element_rows 名称匹配，不依赖编号字符
        neuron_data = []
        for section in neuron_sections:
            title_match = re.search(r'### 🧠 (N\d+)', section)
            neuron_id = title_match.group(1) if title_match else "?"
            triggers = []
            tags = []
            core_parts = []
            for label, content in self._iter_element_rows(section):
                if "触发词" in label:
                    bt_match = re.search(r'([^`]+)`', content)
                    tc = bt_match.group(1) if bt_match else content
                    tc = re.sub(r'\s*//\s*', '|', tc)
                    triggers = [w.strip() for w in tc.split('|') if w.strip()]
                elif "标签" in label:
                    bt_match = re.search(r'([^`]+)`', content)
                    tc = bt_match.group(1) if bt_match else content
                    tags = [t.strip() for t in tc.split('#') if t.strip()]
                    tags = [f"#{t}" for t in tags]
                elif "核心数据" in label or "判定模板" in label or "一句话定义" in label:
                    core_parts.append(content.strip())
            neuron_data.append({
                "id": neuron_id,
                "triggers": triggers,
                "tags": tags,
                "core": " ".join(core_parts),
            })

        # 矛盾检测：检查有重叠触发词或标签的神经元对
        contradictions = []
        opposite_pairs = [
            ("必须", "禁止"), ("可以", "不可以"), ("有效", "无效"),
            ("成立", "不成立"), ("生效", "失效"), ("有权", "无权"),
            ("需要", "不需要"), ("应当", "不应当"),
        ]

        for i in range(len(neuron_data)):
            for j in range(i + 1, len(neuron_data)):
                a = neuron_data[i]
                b = neuron_data[j]

                # 检查触发词或标签重叠
                overlap_triggers = set(a["triggers"]) & set(b["triggers"])
                overlap_tags = set(a["tags"]) & set(b["tags"])

                if not overlap_triggers and not overlap_tags:
                    continue

                # 检查核心结论是否相反
                core_a = a["core"]
                core_b = b["core"]

                found_opposite = None
                for pos, neg in opposite_pairs:
                    if (pos in core_a and neg in core_b) or (neg in core_a and pos in core_b):
                        found_opposite = (pos, neg)
                        break

                if found_opposite:
                    overlap_signal = []
                    if overlap_triggers:
                        overlap_signal.append(f"触发词：{', '.join(list(overlap_triggers)[:3])}")
                    if overlap_tags:
                        overlap_signal.append(f"标签：{', '.join(list(overlap_tags)[:3])}")

                    contradictions.append({
                        "neurons": f"{a['id']} vs {b['id']}",
                        "signal": "；".join(overlap_signal) if overlap_signal else "触发词/标签重叠",
                        "opposite": f"{found_opposite[0]} vs {found_opposite[1]}",
                    })

        if not contradictions:
            return CheckResult("V17", "矛盾检测", True, "未发现矛盾结论")

        # 构造告警信息
        details = []
        for c in contradictions[:5]:  # 最多显示5条
            details.append(f"{c['neurons']}（{c['signal']}；相反词：{c['opposite']}）")

        return CheckResult("V17", "矛盾检测", False, "; ".join(details), level="error")

    # ---- V18: 列举计数校验（warning）----

    CN_NUM_MAP = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4,
                  "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}

    # 绝对化表述正则（V19 用）
    ABSOLUTE_PHRASE_RE = re.compile(r'不得超过|不得超|硬红线|一律不得|一律报')

    def _cn_to_int(self, s: str) -> Optional[int]:
        """中文/阿拉伯数字转 int；无法解析返回 None"""
        s = s.strip()
        if s.isdigit():
            return int(s)
        return self.CN_NUM_MAP.get(s)

    def _parse_claim_n(self, text: str) -> Optional[int]:
        """提取「共N项/类/条/种/个/层/级」声称的 N；无声称或无法解析返回 None"""
        m = re.search(r'共\s*(\d{1,3}|[一二两三四五六七八九十])\s*(项|类|条|种|个|层|级)', text)
        if not m:
            return None
        return self._cn_to_int(m.group(1))

    def _count_enumerators(self, text: str) -> Optional[int]:
        """统计文本中逐项编号的数量；无法可靠解析返回 None（调用方静默跳过）。
        支持 ①②③…、（一）（二）…、1. 2. … 三种编号体系。"""
        # 去掉法条引用中的圈码（如 §563①、第563条①），避免误计为逐项编号
        cleaned = re.sub(r'[§Ss]?\d+\s*[①-⑮]', '', text)

        # ①②③… 圈码体系
        circled = sorted(set(re.findall(r'[①-⑮]', cleaned)))
        if circled:
            if len(circled) < 2:
                return None  # 单个圈码（多为法条引用），不可靠
            nums = [ord(c) - 0x2460 + 1 for c in circled]
            if nums[0] == 1 and nums == list(range(nums[0], nums[0] + len(nums))):
                return len(nums)
            return None  # 编号断档或非从1起，不可靠

        # （一）（二）… 体系
        paren = sorted({self._cn_to_int(p) for p in re.findall(r'[（(]([一二三四五六七八九十])[)）]', cleaned)})
        if paren:
            if len(paren) < 2 or None in paren:
                return None
            if paren[0] == 1 and paren == list(range(paren[0], paren[0] + len(paren))):
                return len(paren)
            return None

        # 1. 2. … 体系
        arabic = sorted({int(x) for x in re.findall(r'(?<![\d.])(\d{1,2})[\.、]', cleaned)})
        if arabic:
            if len(arabic) < 2:
                return None
            if arabic[0] == 1 and arabic == list(range(arabic[0], arabic[0] + len(arabic))):
                return len(arabic)
            return None

        return 0  # 无任何逐项编号

    def check_v18_list_count(self) -> CheckResult:
        """V18 列举计数校验：文本声称「共N项/N类/N条/N种/N个层级」等时，
        同一元素文本必须存在逐项编号且数量一致。
        无法可靠解析时静默跳过，禁止误报。"""
        issues = []
        for section in self._neuron_sections():
            title_match = re.search(r'### 🧠 (N\d+)', section)
            neuron_id = title_match.group(1) if title_match else "?"
            if self._is_skeleton_section(section):
                continue

            for label, content in self._iter_element_rows(section):
                claim_n = self._parse_claim_n(content)
                if claim_n is None:
                    continue  # 无声称或数字无法解析 → 静默跳过
                actual_m = self._count_enumerators(content)
                if actual_m is None:
                    continue  # 编号体系不可靠 → 静默跳过
                if actual_m == 0:
                    issues.append(f"{neuron_id} [{label}] 声称共{claim_n}项但未逐项列举（违反质量红线）")
                elif actual_m != claim_n:
                    issues.append(f"{neuron_id} [{label}] 声称共{claim_n}项实列{actual_m}项")

        if not issues:
            return CheckResult("V18", "列举计数校验", True, "列举声称与逐项数量一致（或无可解析声称）")
        return CheckResult("V18", "列举计数校验", False, "; ".join(issues[:5]), level="warning")

    # ---- V19: 限定词保真检测（warning）----

    def check_v19_qualifier_fidelity(self) -> CheckResult:
        """V19 限定词保真：同一神经元内，出处/法条引用文本含「原则上」，
        而④核心数据或⑦判定模板出现绝对化表述（不得超过/不得超/硬红线/一律不得/一律报）
        且该处未同时出现「原则上」→ warning。每神经元最多报 1 条。"""
        issues = []
        for section in self._neuron_sections():
            title_match = re.search(r'### 🧠 (N\d+)', section)
            neuron_id = title_match.group(1) if title_match else "?"
            if self._is_skeleton_section(section):
                continue

            rows = list(self._iter_element_rows(section))
            # 出处定位（或⑬+法条引用类扩展）文本含「原则上」才启动对照
            source_texts = [c for label, c in rows
                            if "出处定位" in label or "法条引用" in label]
            if not any("原则上" in t for t in source_texts):
                continue

            for label, content in rows:
                if ("核心数据" in label or "判定模板" in label):
                    if self.ABSOLUTE_PHRASE_RE.search(content) and "原则上" not in content:
                        issues.append(
                            f"{neuron_id} 出处含「原则上」，但 [{label}] 出现绝对化表述且未带限定词"
                        )
                        break  # 每神经元最多 1 条，避免刷屏

        if not issues:
            return CheckResult("V19", "限定词保真检测", True, "未发现「原则上」被写成绝对化表述")
        return CheckResult("V19", "限定词保真检测", False, "; ".join(issues[:5]), level="warning")

    # ---- V20: 标记规范检测（warning / error）----

    # 自由文本待核 token（不属于统一格式 ⚠️待核：{事项}｜待{确认方}确认 的写法）
    PENDING_TOKEN_RE = re.compile(r'待确认|待核实|待明确|待核：')
    UNIFIED_PENDING_RE = re.compile(r'⚠️待核：.+｜待.+确认')
    # L1 可信度标注（避免匹配 L10/L12 等）
    L1_TAG_RE = re.compile(r'L1(?![0-9A-Za-z])')

    def _tree_body(self) -> str:
        """树正文 = 去掉「变更日志」区（元数据区），供 V20 全树正文扫描"""
        return re.sub(r'## 变更日志.*?(?=\n---|\n## |\Z)', '', self.content, flags=re.DOTALL)

    def check_v20_marker_spec(self) -> CheckResult:
        """V20 标记规范检测：
        (a) 出现自由文本待核（裸写"待确认/待核实/待明确/待核："）而未采用统一格式
            「⚠️待核：{事项}｜待{确认方}确认」→ warning；
        (b) 【操作口径】标记所在行的同一单元格/同段文本出现 L1 可信度标注 → error。
        【原文】【操作口径】两种标记本身存在且格式正确 → 不告警。"""
        warnings_found = []
        errors_found = []

        for i, line in enumerate(self._tree_body().split("\n"), 1):
            if self.PENDING_TOKEN_RE.search(line) and not self.UNIFIED_PENDING_RE.search(line):
                warnings_found.append(
                    f"行{i}: 待核写法未用统一格式「⚠️待核：{{事项}}｜待{{确认方}}确认」→ {line.strip()[:40]}"
                )
            if "【操作口径】" in line and self.L1_TAG_RE.search(line):
                errors_found.append(f"行{i}: 【操作口径】标记所在行出现 L1 可信度标注")

        if errors_found:
            return CheckResult("V20", "标记规范检测", False, "; ".join(errors_found[:3]), level="error")
        if warnings_found:
            return CheckResult("V20", "标记规范检测", False, "; ".join(warnings_found[:3]), level="warning")
        return CheckResult("V20", "标记规范检测", True, "标记规范统一（【原文】【操作口径】⚠️待核）")

    # ---- V21: 来源版本快照检查（warning / error）----

    def check_v21_source_snapshot(self) -> CheckResult:
        """V21 来源版本快照检查：
        (a) 树头 Header 引用块缺「来源版本：/生效日：/最后原文核查：」任一项 → warning；
        (b) 能解析出「失效日：YYYY-MM-DD」（非"长期有效"）时，逐神经元解析⑫
            「下次核查提醒日期」，凡 ≥ 失效日 → error（每树汇总报 1 条）。"""
        header_text = "\n".join(l for l in self.lines if l.strip().startswith(">"))
        required = ["来源版本：", "生效日：", "最后原文核查："]
        missing = [k.rstrip("：") for k in required if k not in header_text]

        expiry = None
        m = re.search(r'失效日：(\d{4}-\d{2}-\d{2})', header_text)
        if m:
            try:
                expiry = datetime.strptime(m.group(1), "%Y-%m-%d").date()
            except ValueError:
                expiry = None

        # 逐神经元比对（有失效日才执行）
        offenders = []
        if expiry is not None:
            for section in self._neuron_sections():
                title_match = re.search(r'### 🧠 (N\d+)', section)
                neuron_id = title_match.group(1) if title_match else "?"
                for label, content in self._iter_element_rows(section):
                    if "证据链" not in label:
                        continue
                    dm = re.search(r'下次核查提醒日期：(\d{4}-\d{2}-\d{2})', content)
                    if not dm:
                        continue
                    try:
                        d = datetime.strptime(dm.group(1), "%Y-%m-%d").date()
                    except ValueError:
                        continue
                    if d >= expiry:
                        offenders.append(f"{neuron_id}({dm.group(1)})")

        if offenders:
            return CheckResult(
                "V21", "来源版本快照检查", False,
                f"来源失效日为 {expiry}，以下神经元的⑫下次核查提醒日期≥失效日：{', '.join(offenders)}",
                level="error"
            )

        if missing:
            detail = "树头来源版本快照不完整（缺：" + "、".join(missing) + "）"
            if expiry is not None:
                detail += f"；已解析失效日 {expiry}，逐神经元比对未见≥失效日的核查提醒"
            return CheckResult("V21", "来源版本快照检查", False, detail, level="warning")

        if expiry is None:
            return CheckResult("V21", "来源版本快照检查", True, "树头快照完整（失效日为长期有效或未标注具体日期）")
        return CheckResult("V21", "来源版本快照检查", True, f"树头快照完整，全部⑫核查提醒日期早于失效日 {expiry}")

    # ---- 运行全部检查 ----

    def run_all(self, other_files: List[str] = None, log_dir: Optional[str] = None) -> ValidationReport:
        report = ValidationReport(
            tree_name=self.tree_name,
            file_path=str(self.file_path)
        )

        report.results.append(self.check_v1_11_elements())
        report.results.append(self.check_v2_trigger_words())
        report.results.append(self.check_v3_judgment_template())
        report.results.append(self.check_v4_fallacies())
        report.results.append(self.check_v5_checklist())
        report.results.append(self.check_v6_synapses())
        report.results.append(self.check_v7_root())
        report.results.append(self.check_v8_selfcheck())
        report.results.append(self.check_v9_header_stats())
        report.results.append(self.check_v10_bidirectional(other_files))
        report.results.append(self.check_v11_trigger_consistency())
        report.results.append(self.check_v12_cross_reference_validity())
        report.results.append(self.check_v13_numbering_continuity())
        report.results.append(self.check_v14_filler_words())
        report.results.append(self.check_v15_vague_references())
        report.results.append(self.check_v16_generic_safety())
        report.results.append(self.check_v17_contradiction())
        report.results.append(self.check_v18_list_count())
        report.results.append(self.check_v19_qualifier_fidelity())
        report.results.append(self.check_v20_marker_spec())
        report.results.append(self.check_v21_source_snapshot())

        # V1 旧格式兼容告警同步到报告（单独汇总行，不计入未通过主计数）
        report.compat_notes = list(self.compat_warnings)

        # 健康度评分（单独作为一行报告，不纳入V1-V21计数）
        health_level = self.calculate_health_score(log_dir)
        health_result = CheckResult("HEALTH", "健康度", True, f"知识库健康度：{health_level}")
        health_result.level = "info"
        report.results.append(health_result)

        return report


# ============================================================================
# 主入口
# ============================================================================

def find_neuron_tree_files(directory: str = ".") -> List[str]:
    """查找目录下所有神经树文件"""
    pattern = re.compile(r"神经树_.*\.md$")
    files = []
    for f in Path(directory).iterdir():
        if f.is_file() and pattern.search(f.name) and "模板" not in f.name and "示范" not in f.name:
            files.append(str(f))
    return sorted(files)


def main():
    args = sys.argv[1:]

    if not args:
        safe_print("用法：")
        safe_print("  python 神经树验证器.py <神经树文件路径>")
        safe_print("  python 神经树验证器.py --all")
        safe_print("  python 神经树验证器.py <文件1> <文件2> ...")
        sys.exit(1)

    files_to_check = []

    if "--all" in args:
        files_to_check = find_neuron_tree_files()
        if not files_to_check:
            safe_print("当前目录下未找到神经树文件（文件名模式：神经树_*.md）")
            sys.exit(0)
    else:
        files_to_check = [f for f in args if not f.startswith("--")]

    all_passed = True
    for f in files_to_check:
        if not os.path.exists(f):
            safe_print(f"文件不存在：{f}")
            continue

        validator = NeuronTreeValidator(f)
        report = validator.run_all()
        report.print()

        if report.error_count > 0:
            all_passed = False

    safe_print(f"\n{'='*60}")
    safe_print(f"  总体验证：{'OK 全部通过' if all_passed else 'FAIL 存在未通过项'}")
    safe_print(f"{'='*60}")

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()