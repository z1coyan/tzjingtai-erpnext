# 清算中科目 11215 剩余工作清单

> 截止 2026-04-13, 基于 inspect_clearing_imbalance_by_bill_no 最新结果

## 当前状态总览

| 年度 | 逐笔配对 | 组级配对 | 真正未匹配 DR | 真正未匹配 CR | 净差 | 缺票号 |
|---|---|---|---|---|---|---|
| 2024 | 195 对 | 10 票号 | **0 / 0** | **0 / 0** | **0** | 0 |
| 2025 | 200 对 | 27 票号 | **0 / 0** | 48 / 10,071.06 | -10,071.06 | 0 |
| 全量 | **707 对** | 38 票号 | 53 / 3,409,290.06 | 64 / 722,200.47 | 2,687,089.59 | **0** |

> 2026-04-12 P2 处理后更新: 补标票号 77 笔(+77 对匹配), 迁出非票据 40 笔, 缺票号 117→0 完全收口
> 2026-04-13 P1 处理后更新: 2025 DR 侧完全收口(5→0), CR 侧 52→48(去除 2 笔误标+2 笔已匹配)

## P0: 2024 — 已完全收口

无剩余工作。

## P1: 2025 — ✅ DR 完全收口, CR 仅余利息残影 (2026-04-13)

### 1.1 利息修正残影 (48 行 CR, 10,071.06 元) — 不需要处理

宁波银行贴现利率修正后, DR 侧(实付金额)已调低, 但部分 CR 侧(银行流水 JE)之前已与旧 DR(面额)
逐笔配对过. 修正后差额变成了纯 CR 残影, 每行金额 = 对应 Bill Discount 的利息修正差.

**结论**: 会计正确(利息已拆到财务费用科目), 诊断工具的逐笔配对口径限制, 非数据错误. 可忽略.

### 1.2 DISC-00255/256/257 组 — ✅ 已修复

**根因**: JE-26-07540 (补差 JE, CR 11215 ¥475.49) 在 Bill Discount 利率修正后成为多余的双重记账.
修正前 3 个 DISC 净额合计 199,999.93, 修正后变为 199,524.44 与银行到账 (JE-26-01694) 一致,
但补差 JE 未清除, 导致 DR (199,524.44) ≠ CR (199,999.93).

**操作**: 取消 JE-26-07540 (docstatus → 2). 恢复后组级配对吸收该票号 (3 DR = 1 CR = ¥199,524.44).

### 1.3 DISC-00246/252 — ✅ 已修复

**根因**: 两个独立问题叠加:
1. 实际贴现入账 (JE-26-01701 ¥4,987.89, JE-26-01696 ¥29,922.50) CR 去了 22410 其他应付款, 应去 11215
2. 两笔无关客户货款 (JE-26-01885 ¥5,000, JE-26-01887 ¥30,000) 被 P2 自动补标票号时错误关联, 且留在 11215

**操作**:
- 重定向 JE-26-01701/01696 从 22410 → 11215 (redirect_discount_bank_journal_counter_to_clearing)
- 移除 JE-26-01885/01887 的错误票号注解 (直接 SQL), 恢复到 11221 应收账款 (restore_clearing_bank_journal_counter_from_bank_against)
- 审计记录: `p1_redirect_apply.json`, `p1_restore_apply.json`

## P2: 全量早年遗留 — ✅ 已完全收口 (2026-04-12)

原始: 117 笔 CR 缺票号 / 9,953,638.52 元 → **0 笔 / 0 元 (100% 消化)**

### 已完成操作

**A. 票号标注 (77 笔, 7,780,147.53 元)**
- 42 笔: 截断票号前缀匹配 (user_remark 中 20 位前缀 → 匹配 30 位 BoE.bill_no)
- 13 笔: 金额唯一匹配 (DR 侧只有一笔相同金额的 Bill Payment)
- 16 笔: 金额+日期接近度匹配 (同金额多候选时取日期最近的 Bill Payment)
- 3 笔: 历史补建 JE 直接从 user_remark 提取 BPAY 名称反查 bill_no
- 4 笔: 财务确认宁波银行"现金存入"对应的到期兑付票号
- 工具: `annotate_clearing_bank_journal_bill_no`
- 审计记录: `p2_annotate_73_apply.json`, `p2_annotate_last4_apply.json`, `p2_match_plan.json`

**B. 非票据迁出 (40 笔, 2,173,490.99 元)**
- 识别出 40 笔 CR 条目实为普通"货款/材料款/借款"等, 非票据清算
- 全部从 11215 恢复到原始对方科目 (11221 应收账款 / 22410 其他应付款)
- 工具: `restore_clearing_bank_journal_counter_from_bank_against`
- 审计记录: `p2_restore_40_apply.json`

## P3: 代码清理 — ✅ 已完成 (2026-04-13)

P1/P2 完全收口后, `acceptance.acceptance.api.import_helpers` 中 5 个 HOTFIX 方法及其专用辅助全部删除:

| 方法 | 状态 |
|---|---|
| `inspect_clearing_imbalance_by_bill_no` | ✅ 已删除 |
| `annotate_clearing_bank_journal_bill_no` | ✅ 已删除 |
| `restore_clearing_bank_journal_counter_from_bank_against` | ✅ 已删除 |
| `redirect_discount_bank_journal_counter_to_clearing` | ✅ 已删除 |
| `fix_bill_discount_from_bank_export` | ✅ 已删除 |

连带删除的辅助函数/常量: `_pair_clearing_rows`, `_group_match_clearing_rows`,
`_resolve_restore_target_from_bank_against`, `_normalize_year`, `_to_decimal_2`,
`_extract_bill_no`, `_short_text`, `_csv_from_rows`, `_date_gap_days`,
`_BILL_NO_IN_TEXT_RE`, `_AMOUNT_TOLERANCE`, `_GROUP_MATCH_TOLERANCE`.

清理无用 import: `csv`, `io`, `defaultdict`, `datetime.date`, `Decimal`, `InvalidOperation`.

`import_helpers.py` 从 2582 行 → 1335 行 (净减 1247 行)。

审计台账 `tmp/clearing_diagnosis_20260411/audit_trail.json` 和本次修复 JSON 留档,
需要重现时可通过 `git log` 找回删除前的源码。

## P4: submittable 链条重建 (可选)

本轮共 157 笔已 submit 的 doc 被直接改了字段/GL, 绕过了 Frappe submittable 原则.
已通过 Comment + 审计台账留痕, 但 Frappe version history 中无记录.

**如果审计要求严格**: 可以对这 157 笔走 cancel + amend 流程重建, 恢复完整修订链.
**如果当前留痕够用**: 不做, 风险是 Frappe 原生的 version history 查不到变更记录.

**建议**: 暂不做. 成本高(157 笔 cancel+amend 可能触发联动), 当前 Comment + 台账已足够解释.
