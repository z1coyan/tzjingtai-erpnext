# Hourly Payroll

台州京泰 ERPNext 工时制薪资 app。打通"打卡机 `.dat` → 员工工时 → 月度薪资 → 会计凭证"整条链路。

## 功能概览

- **考勤导入**：从 ZKTeco `attlog.dat` 批量解析导入 `Employee Checkin`，支持多打卡机、跨机混打
- **工时算法**：按上午 / 下午 / 加班三段独立计算，支持"+5 分钟 + 按 0.5h 向下截断 + 正班封顶 8h + 加班全勤奖励"
- **班次对接**：一键从配置派生 `Shift Type` + 批量绑到所有在职员工的 `default_shift`，吃通 ERPNext 原生自动考勤
- **月度薪资**：`Monthly Payroll Run` 按月聚合，支持奖金 / 补发两列，同公司同月份唯一
- **会计凭证**：提交月度薪资时自动生成 Draft `Journal Entry`（借：工资费用按员工分行 / 贷：应付工资合计），会计复核后手动提交
- **调整单**：`Payroll Adjustment` 独立 DocType 处理"已过账后补发 / 集中发奖金"，同公司同月可多条
- **汇总报表**：`Payroll Summary` Script Report 聚合 MPR + Adjustment，按员工 × 期间展示总发放
- **工作区**：`打卡考勤` 侧边栏入口，集成员工 / 考勤 / 薪资 / 报表 / 设置

## 核心 DocType

| 名称 | 作用 | submittable |
|---|---|---|
| `Hourly Payroll Settings` | 时间窗 / 计算规则 / 加班奖励 / 班次对接 / 日薪除数 | Single |
| `Attlog Import` | 上传并解析 `.dat`；可自动为未映射的设备号新建占位员工 | ✗ |
| `Monthly Payroll Run` | 月度薪资主单（公司 + 年 + 月 唯一）；生成明细 + 出凭证 | ✓ |
| `Monthly Payroll Detail` | 子表：员工 / 工日 / 日薪 / 基本工资 / 奖金 / 补发 / 金额 | (table) |
| `Payroll Adjustment` | 独立补发 / 奖金发放单，提交出独立凭证 | ✓ |
| `Payroll Adjustment Detail` | 子表：员工 / 类型（Bonus / Supplementary）/ 金额 / 备注 | (table) |

## Custom Field（fixture 自动同步）

| 所在 DocType | Fieldname | 类型 | 用途 |
|---|---|---|---|
| `Employee` | `daily_wage` | Currency | 日薪；时薪 = daily_wage / `regular_hours_per_day` |
| `Attendance` | `regular_hours` | Float | 我方算的正班工时（每日）|
| `Attendance` | `overtime_hours` | Float | 加班工时（支持全勤奖励）|
| `Attendance` | `net_work_hours` | Float | 当日总工时 = regular + overtime |

Attendance 三个字段由 `before_save` 钩子在每次 save 时从 `Employee Checkin` 重算，**薪资计算不依赖 Attendance 存在**（`wage_calc.py` 直接扫 Checkin），所以即使没配 Shift 也能出月薪。

## 工时算法（`utils/work_hours.py`）

1. 打卡按"最近窗归属"分到三个窗口（上午 / 下午 / 加班），相邻窗口容差重叠区按距离判归，不重复计数
2. 每窗内取最早 / 最晚打卡之差作为该段原始时长（少于两次打卡该段为 0）
3. 正班 = 上午段 + 下午段 → + `extra_minutes` → 按 `round_unit_hours` 向下截断 → 封顶 `regular_cap_hours`
4. 加班段若原始时长 + `overtime_full_tolerance_minutes` ≥ `overtime_full_threshold_hours` × 60，直接按 `overtime_full_credit_hours` 计（全勤奖励）；否则 + `extra_minutes` → 按 `round_unit_hours` 向下截断
5. 薪资 = `net_work_hours × (daily_wage / regular_hours_per_day)`

默认值：上午 07:00–11:00 / 下午 12:30–16:30 / 加班 17:00–20:30；buffer 30 分钟；加班做满 3.5h（± 5 分钟容差）奖励到 4h。

## 使用流程

### 首次配置

1. **Hourly Payroll Settings** → 核对 6 个时间点和计算规则
2. **Setup Shift & Assignments** 按钮 → 选公司 → 自动建 `Hourly Payroll Shift` 并绑定全部在职员工 `default_shift`
3. Employee 表里为每位员工填 `daily_wage` 和 `attendance_device_id`（考勤机里的用户号）

### 每月例行

1. **Attlog Import** → 传 `.dat`（每台机一次）→ 勾选 Auto Create Unknown Employees 可选 → 点 "Parse & Create Checkins"
2. **Monthly Payroll Run** → 新建（同公司同月只能一条）→ 选公司 + 年 + 月 → Generate → 核对明细 → 填工资费用 / 应付工资 / 成本中心 → Submit → 生成 Draft JE
3. 会计进 **Journal Entry** 复核 → 手动 Submit 过账
4. 月中临时补发 / 集中发奖金：**Payroll Adjustment** → 新建 → 填 Title + 明细 → 提交 → 出独立 Draft JE
5. **Payroll Summary** 报表 → 筛公司 / 年 / 月 → 看每员工总发放（基本 + 奖金 + 补发）

### 事后更正

- Monthly Payroll Run 已提交后发现错误：Cancel 原单（Draft JE 删掉 / Submitted JE 反冲）→ Amend → 改 bonus / supplementary → 重新提交 → 新 Draft JE
- 或走 Payroll Adjustment 追加一张调整单（推荐，原始凭证不动，审计链清晰）

## 部署

遵循 CLAUDE.md 容器化部署铁律：

```
git add apps/hourly_payroll
git commit -m "feat(hourly_payroll): ..."
git push
# Dokploy 控制台点 Deploy
```

Configurator 会自动：
- `sync_all` 把新 DocType schema 刷进每个 site
- `sync_fixtures` 把 `fixtures/custom_field.json` 里的 4 个 Custom Field 装上

**禁止容器内跑 bench** —— DocType / fixture 改动全部靠 configurator。

## 本地开发

改 Python / JS / JSON 后重启 `bench start` 即可；Workspace JSON 改动登录后强刷页面侧边栏。

工时算法模块 `utils/work_hours.py` 的 `compute_day_hours` 是纯函数，不依赖 `frappe`，可直接用 `python3` 离线跑单元测试，建议改动后都跑一遍边界场景：
- 正班 2h + 下午全到
- 加班 3h20min / 3h25min（全勤奖励边界）
- 上午多次重复打卡
- 跨下午-加班边界打卡归属（如 16:45 的单次打卡）
