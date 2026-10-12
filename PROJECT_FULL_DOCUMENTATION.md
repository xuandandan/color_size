# 智能涂料颜色配比系统：完整逻辑与架构文档

本文档系统化说明当前项目的业务逻辑、技术架构、模块关系、数据流、训练流程与部署运维方法，用于开发、交接与持续迭代。

## 1. 项目目标与核心能力

系统目标：围绕涂料/车漆配色，实现从测色输入到配方推荐、性能预测、反馈学习闭环的数字化流程。

当前能力包括：

- 用户登录与鉴权（Token）
- 测色数据管理（光谱 + 纹理）
- 配方管理（新增、查询）
- 四大算法能力（匹配、调色、生成、渲染预览）
- 图像识别提取颜色特征、图像推荐配方
- 结果可信度评估（DeltaE/SSIM/RMSE/MAE/信任分）
- 专家编排（需求解析 -> 推荐 -> 预测 -> 工艺 -> 反馈）
- 机器学习训练与推理（模型可训练、可回退）
- **流行色**：趋势 CSV 训练 → **匹配**（`/trends/match`）→ **展望**（`/trends/forecast`）→ **展望色 RGB 回灌配方**（`/algorithms/generate-from-rgb`）；详见 **§15**
- Excel 一键导入 MySQL（含失败行报告）
- 导出 Excel / PDF 报告

---

## 2. 技术架构概览

### 2.1 后端

- 框架：FastAPI
- 数据访问：SQLAlchemy ORM
- 数据库：SQLite 或 MySQL（通过 `DATABASE_URL` 切换）
- 模型训练：scikit-learn
- 图像处理：Pillow + scikit-image
- 文档导出：openpyxl + reportlab

### 2.2 前端

- 单文件页面：`app/static/index.html`
- 通过 Fetch 调用后端 API
- 支持“后端 API 地址”切换（前后端分离部署）
- 含在线状态心跳、可视化结果区、导入导出、反馈录入等入口

---

## 3. 目录与模块职责

### 3.1 入口与基础

- `app/main.py`
  - FastAPI 应用入口
  - 路由注册
  - CORS 配置
  - 静态页面挂载

- `app/db.py`
  - 数据库连接初始化
  - ORM 表模型定义
  - 初始数据种子
  - `db_ping()` 健康检查

- `app/storage.py`
  - 数据访问层（DAL）
  - 封装 measurements/formulas/feedbacks/audit 的读写

- `app/models.py`
  - Pydantic 请求/响应模型定义

### 3.2 业务核心

- `app/services.py`
  - `ColorEngine`：匹配、调色、生成、渲染
  - `ExpertOrchestrator`：需求解析、推荐、预测、工艺参数、反馈闭环

- `app/vision.py`
  - 图片 -> 颜色特征 -> `Measurement` 转换

- `app/metrics.py`
  - 颜色相似度指标：DeltaE00、SSIM、RMSE、MAE、Trust Score

- `app/ml.py`
  - 训练样本构建、模型训练、模型持久化、在线推理

- `app/train.py`
  - 命令行训练入口

- `app/importer.py`
  - Excel 批量导入逻辑（measurements/formulas/feedbacks）

- `app/trend_preferences.py`
  - 趋势 CSV 加载、`/trends/train` 聚类与近邻、`/trends/match`、`/trends/forecast`（详见 **§15**）

- `app/formula_extended.py`
  - 生成配方扩展字段占位（填料/母色占比/基料），供后续数据接入

### 3.3 鉴权与导出

- `app/auth.py`
  - 登录校验
  - `x-token` 解析与当前用户获取

- `app/exporters.py`
  - 生成 Excel / PDF 报告字节流

### 3.4 前端页面

- `app/static/index.html`
  - 登录、测色、推荐、专家编排、反馈录入、导入导出、数据查看
  - API 基地址配置与连通性心跳

---

## 4. 数据库设计与关系

主要表：

- `users`
  - `username`、`password_hash`、`token`

- `measurements`
  - `id`、`car_model`、`color_code`
  - `angles`（JSON）
  - `texture`（JSON）

- `formulas`
  - `id`、`name`
  - `pigments`（JSON）
  - `linked_measurement_id`

- `feedbacks`
  - `formula_id`
  - `measured_performance`（JSON，含 adhesion/gloss/impact/voc）
  - `accepted`、`comment`

- `audit_logs`
  - 记录关键操作与分数

逻辑关系：

- 一个 `formula` 关联一个 `measurement`（通过 `linked_measurement_id`）
- 一个 `formula` 可对应多条 `feedback`
- `feedback` 反向进入训练集，促进模型迭代

---

## 5. 端到端业务流程

### 5.1 典型流程（在线）

1. 用户登录获取 token
2. 上传图片或录入测色数据
3. 系统提取颜色特征，写入 `measurements`
4. 进行配方匹配/生成/调色建议
5. 返回可视化结果与可导出报告
6. 试制检测后录入反馈（`feedbacks`）
7. 定期触发训练，提升后续推荐质量

### 5.2 专家编排流程

`/expert/orchestrate` 的内部步骤：

1. 解析原始需求文本为硬约束与软约束
2. 在历史配方中执行多目标排序
3. 对候选配方进行性能预测与硬约束校验
4. 生成工艺参数建议
5. 输出候选结果 + 生成配方 + 步骤解释

---

## 6. 机器学习闭环

本节描述「配方 + 测色 + 反馈 → 专家性能/排序模型」的闭环；**逐步拆解、打分公式与运维顺序**以 **§6.5** 为准。

### 6.1 训练数据来源

- 配方特征：`formulas.pigments`
- 测色特征：`measurements.angles + texture`
- 标签来源：
  - `feedbacks.measured_performance`
  - `feedbacks.accepted`
  - 无反馈时部分使用规则伪标签兜底

### 6.2 模型类型

- 性能预测：`RandomForestRegressor`
  - 输出 adhesion/gloss/impact/voc

- 排序评分：`GradientBoostingRegressor`
  - 输出候选配方优先概率

### 6.3 训练与推理接口

- 训练：
  - CLI：`python -m app.train --min-samples 20 --save-dir models`
  - API：`POST /expert/train`

- 状态：
  - `GET /expert/model-status`

- 推理接入点：
  - `ExpertOrchestrator.recommend_formulas()`
  - `ExpertOrchestrator._predict_performance()`

### 6.4 回退机制

若模型不存在或推理异常，系统自动回退启发式规则，保证服务不中断。

### 6.5 专家编排中的机器学习链路（详述：配方库 → 特征 → 训练 → 保存 → 加载 → 在线预测）

本节对应「**专家 ML 预测性能**」在代码中的完整路径：数据来自 **配方表 + 关联测色表 + 反馈表**，特征与标签在 **`app/ml.py`** 中组装，模型由 **`MLRuntime`** 训练并落盘，由 **`ExpertOrchestrator`**（`app/services.py`）在 **`recommend_formulas` / `orchestrate`** 中在线调用；任一步失败时回退到与 **`_pseudo_performance`** 同族的启发式，保证 API 可用。

#### 6.5.0 总览（两条主线：离线训练 vs 在线推理）

```mermaid
flowchart LR
  subgraph offline["离线训练 MLRuntime.train"]
    DB[(formulas + measurements + feedbacks)]
    FEAT[_extract_feature 13维]
    YP[y_perf 四维]
    YR[y_rank 标量]
    RF[RandomForest 性能]
    GB[GradientBoosting 排序]
    PKL[(perf_model.pkl + rank_model.pkl + metadata.json)]
    DB --> FEAT
    DB --> YP
    DB --> YR
    FEAT --> RF
    FEAT --> GB
    YP --> RF
    YR --> GB
    RF --> PKL
    GB --> PKL
  end
  subgraph online["在线推理 ExpertOrchestrator"]
    REQ[解析需求 hard/soft]
    LOOP[遍历配方库]
    PRED[_predict_performance]
    RANK[predict_rank]
    SCORE[priority_score 排序]
    TOP[Top-K 输出]
    REQ --> LOOP
    LOOP --> PRED
    LOOP --> RANK
    PRED --> SCORE
    RANK --> SCORE
    SCORE --> TOP
  end
  PKL -.->|进程启动 load| PRED
  PKL -.->|进程启动 load| RANK
```

- **离线**：只依赖数据库与 `models/` 目录写权限；训练失败不覆盖已有 `pkl`。  
- **在线**：每次推荐对**每条配方**各调用一次性能预测（及在模型可用时调用排序）；复杂度约为 **O(配方条数)**，配方库很大时需考虑缓存或批推理优化（当前未做）。

#### 6.5.1 配方数据库如何进入训练集（逐步）

训练入口：`MLRuntime.train(min_samples: int)`（由 **`POST /expert/train`** 或 **`python -m app.train`** 触发）。

1. **打开 ORM Session**，查询三张表的全量行：`FormulaRow`、`MeasurementRow`、`FeedbackRow`。  
2. **构建 `measurements[id] -> row` 字典**，用于 O(1) 按 id 取测色。  
3. **构建 `feedback_by_formula[formula_id] -> [FeedbackRow, ...]`**，同一配方多条反馈全部保留。  
4. **对每条配方 `f` 循环**：  
   - 令 `m = measurements.get(f.linked_measurement_id)`。  
   - **若 `m is None`**：该配方**整行丢弃**，不进入 `X`、也不进入 `y_perf` / `y_rank`。这是当前实现里最常见的「样本丢失」原因：**配方必须关联一条已存在的测色记录**。  
   - **否则**：进入特征与标签构造（见下两节），得到一行 `x_row`、`y_perf_row`、`y_rank_scalar`，追加到列表。  
5. **样本数检查**：若 `len(x_rows) < min_samples`，抛出 `ValueError`，**不写磁盘**，避免用极少样本覆盖生产模型。  
6. **拟合**：`perf.fit(X, Y_perf)`、`rank.fit(X, y_rank)`。  
7. **训练集回测**：用同一 `X` 做 `perf.predict`、`rank.predict`，计算 MAE、R²（见 6.5.4）。  
8. **持久化**：`pickle.dump` 两个估计器；写入 `metadata.json`；**再次 `load()`** 使当前进程内对象与磁盘一致。

**运维含义**：Excel 导入或界面录入时，务必保证 **`formulas.linked_measurement_id` 与 `measurements.id` 对齐**，否则该配方永远不会成为训练样本，专家侧也只能对其使用纯启发式预测（若测色缺失，`_predict_performance` 在 ML 路径上仍会取测色——关联缺失时会在 ML 分支取数失败并回退，见 6.5.7）。

#### 6.5.2 特征构建（「做特征」）

实现函数：**`ml._extract_feature(pigments: dict, measurement: dict) -> list[float]`**。

- **输入 `pigments`**：来自 ORM 的 JSON 反序列化字典；键名未出现时 **`_safe_float` 返回 0.0**，不会抛异常。  
- **输入 `measurement`**：必须能提供 `angles` 与 `texture`；其中 **`angles["45"]`** 被假定为 **若干 `{wavelength, value}` 字典的列表**；代码用字典推导收集 `band[波长] = value`，再取 **400、500、600** 三个键；若缺某波长，该维为 **0.0**。  
- **输出**：长度 **13** 的 `list[float]`，随后 `np.asarray(..., dtype=float32)` 作为单样本行向量。

| 维度索引 | 字段含义 | 数据来源 |
|----------|----------|----------|
| 0–6 | 七颜料量 | `base_white`, `base_black`, `base_red`, `base_green`, `base_blue`, `al_silver`, `pearl` |
| 7–9 | 45° 光谱三点 | `angles["45"]` 中 400 / 500 / 600 nm |
| 10–12 | 纹理 | `flake_intensity`, `sparkle`, `grain` |

**与业务的对齐说明**：  
- 训练与推理**必须使用同一套 `_extract_feature` 定义**；若产线升级测色仪输出更多角度/波长，应同步改此函数并**全量重训**，否则旧模型输入维度不匹配。  
- 当前 **15° / 110°** 未进入特征向量，仅 45° 三通道参与 ML；若需多角融合，可在该函数中拼接并调整 `RandomForestRegressor` 输入维。

#### 6.5.3 标签构建（监督信号，含缺省与平均规则）

对每条有效配方 `f`（已关联测色 `m`）：

**（1）性能向量 `y_perf`（4 维，顺序固定：adhesion, gloss, impact, voc）**

- 令 `base_perf = _pseudo_performance(f.pigments)`，由颜料启发式给出四个基准标量。  
- 若 **`feedback_by_formula[f.id]` 非空**：  
  - 初始化累加器 `avg` 为四元零。  
  - 对每条反馈 `fb`：读取 `mp = fb.measured_performance or {}`。对每个指标键 `k`，累加 **`_safe_float(mp.get(k, base_perf[k]))`** —— 即：**单条反馈里缺某个指标时，用该配方的 `base_perf` 该项顶替**，避免单条反馈字段不全导致无法平均。  
  - 最后 **`avg[k] /= len(fb_list)`**，得到该配方在历史上的**平均表现**。  
- 若 **无任何反馈**：`y_perf = [base_perf 四值]`，等价于「用规则面当真值」，便于 **冷启动训练**。

**（2）排序标量 `y_rank`**

- 有反馈：`sum(fb.accepted for fb in fb_list) / len(fb_list)`，即 **布尔采纳率** 在 0–1 之间。  
- 无反馈：固定 **0.5**，表示「中性排序先验」。

**数据质量建议**：反馈中应尽量填全四维性能；若长期缺某维，该维在标签里会**过度接近** `_pseudo_performance`，模型在该指标上容易学偏。

#### 6.5.4 模型训练、超参与指标含义

| 项目 | 说明 |
|------|------|
| 性能模型 | `RandomForestRegressor(n_estimators=200, random_state=42)`，**单模型多输出**（`y` 形状 `(n_samples, 4)`） |
| 排序模型 | `GradientBoostingRegressor(random_state=42)`，默认 sklearn 超参；输出一维连续值，经 `recommend_formulas` 内 `max(0, min(1, val))` 截断后参与加分 |
| 性能 MAE | `mean_absolute_error(y_perf_arr, perf.predict(X))`，对四维整体逐元素平均（sklearn 默认行为） |
| 性能 R² | `r2_score(y_perf_arr, perf_pred)`；**若样本数 < 2 或 R² 非有限数，写 0.0** |
| 排序 MAE | `mean_absolute_error(y_rank_arr, rank.predict(X))` |

训练完成后 **`metadata.json`** 中的 `model_version` 为 **`v` + UTC 时间戳**（`strftime`），便于与审计日志、发布说明对应。

#### 6.5.5 保存、原子性与部署注意

- 写入顺序：先 **`perf_model.pkl`**，再 **`rank_model.pkl`**，再 **`metadata.json`**。当前实现**非事务**：若写第二个文件时进程被杀死，可能出现**仅性能模型更新、排序模型仍为旧版**的不一致；运维上可训练到临时目录再整体替换，或接受 MVP 风险。  
- **版本共置**：推理要求 **两个 `pkl` 同时存在** 才 `has_model() == True`；只拷贝其中一个会导致一直回退启发式。  
- **多实例部署**：每个 uvicorn worker 进程各自 `load()` 一份内存模型；更新模型后需 **reload 进程** 或滚动重启以加载新 `pkl`。

#### 6.5.6 加载与运行时状态

- **`MLRuntime.__init__`**：`self.load()`。  
- **`load()`**：若 `perf_path` 与 `rank_path` 均存在则 `pickle.load`；若 **`meta_path` 存在**则读 JSON；任一模型文件缺失则 **`perf_model` / `rank_model` 保持 None**。  
- **`GET /expert/model-status`**：返回 `ready: bool`、`model_dir` 绝对路径、`metadata`（仅当 `ready` 时非空）。前端「模型状态」按钮依赖此接口判断是否能走 ML 分支。

#### 6.5.7 在线预测与回退（逐调用拆解）

**入口 A：`ExpertOrchestrator._predict_performance(formula)`**

1. 若 **`ml_runtime` 为空或 `not has_model()`**：走 **`services.py` 内联启发式**（由白/黑/彩/银/珠配方比例计算四维，与 `_pseudo_performance` 同结构但部分边界如 VOC 下限略有差异，见代码）。  
2. 否则：  
   - `measurement = store.get_measurement(formula.linked_measurement_id)`（Pydantic `Measurement`）。  
   - `payload = measurement.model_dump(mode="json")`。  
   - 调用 **`ml_runtime.predict_performance(formula.pigments, payload)`**。  
   - **任意异常**：`try/except` 吞掉后 **回退到与 (1) 相同的启发式**。

**入口 B：`ml_runtime.predict_performance` / `predict_rank`**

- 内部均为 **`x = [_extract_feature(...)]`** 后 **`model.predict(x)`**。  
- `predict_rank` 返回值 **`clip` 到 [0, 1]**。

**入口 C：`recommend_formulas` 中的 `priority_score`（与专家排序强相关）**

对每条配方，在已有 **`predicted`** 与 **`passed = _check_hard_constraints(...)`** 后，**初始 `score = 0`**，再按代码实际顺序叠加（**除 +70 外，其余项均不判断 `passed`**）：

| 条件 | 加分规则（代码级摘要） |
|------|------------------------|
| 硬约束通过 | **`if passed`：`+70.0`** |
| 模型可用 | **`if ml_runtime.has_model()`**：取关联测色，`+ rank_prob * 20.0`，`rank_prob = clip(predict_rank(...), 0, 1)`；**与是否通过硬约束无关** |
| `adhesion_min`（键存在于 `hard` 时） | `+ min(10, max(0, predicted.adhesion - hard.adhesion_min))`；**与 `passed` 无关** |
| `gloss_min` | `+ min(10, max(0, (predicted.gloss - hard.gloss_min) / 2))` |
| `impact_min` | `+ min(10, max(0, (predicted.impact - hard.impact_min) / 2))` |
| `voc_max` | `+ min(10, max(0, (hard.voc_max - predicted.voc) / 2))` |
| 软约束 | 对**所有配方**均加：`production_stability * 5`、`speed_priority * 3`、`cost_priority * 2`（缺省由 `parse_requirement` 填充） |

最后 **`recommendations.sort(..., reverse=True)`** 取前 **`payload.top_k`** 条。

**注意**：**`pass_hard_constraints == false` 的配方仍会进入列表**；其总分仍可能含 **`rank_prob*20`、余量分、软约束分**，仅**缺少 +70**，多数情况下会靠后排，但不能从数学上保证「未通过一定垫底」。若产品要求「仅输出可行解」，应在服务层对结果 **`if r.pass_hard_constraints` 再过滤**。

**入口 D：`/expert/orchestrate`**

- 先 **`parse_requirement`** → **`recommend_formulas`**（内部已含上述 ML 与打分）→ 再 **`ColorEngine.smart_generate`** 基于合成测色生成一条 **`generated_formula`**。编排文案中的「性能预测代理」即指 **`_predict_performance` 对每条历史配方的批量调用**。

#### 6.5.8 触发训练与再训练的推荐操作顺序

1. 通过 **`POST /measurements`、`POST /formulas`、`POST /expert/feedback`** 或 **`POST /import/excel`** 积累数据。  
2. **`GET /expert/model-status`** 确认当前 `ready` 与 `sample_count` 预期。  
3. **`POST /expert/train`**，body 示例：`{"min_samples": 20}`。若有效配方条数不足，`train()` 会抛错；当前路由**未包装为 400**，前端可能看到 **HTTP 500**，但磁盘上旧模型不会被覆盖。  
4. 再次 **`model-status`** 核对新版本 `model_version` 与 `perf_mae` / `perf_r2`。  
5. **`POST /expert/recommend` 或 `POST /expert/orchestrate`** 验证推荐列表中 `predicted_performance` 与 `priority_score` 是否符合业务直觉。

CLI 等价：`python -m app.train --min-samples 20 --save-dir models`（参数以 `app/train.py` 为准）。

#### 6.5.9 与「流行色」模块的边界

- **专家 ML（本节）**：对象为本库 **配方 + 测色 + 反馈**，预测 **附着力/光泽/冲击/VOC** 及排序分；模型文件为 **`perf_model.pkl` / `rank_model.pkl`**。  
- **流行色**（`trend_preferences.py` + `trend_preference_bundle.pkl`）：对象为 **外部趋势 CSV**，做聚类、近邻、展望；**不参与** `_extract_feature` 与专家性能模型训练。  
- 产品层可将「趋势偏好分」与「预测性能」并列展示，但**训练数据与权重不应混写进同一 pickle**，以免版本与可解释性混乱。

#### 6.5.10 已知局限（文档级约定）

- 标签在「无反馈」时与启发式强相关，模型可能主要学到 **自洽的颜料—规则** 映射，而非真实检测。  
- 未做时间序列或配方版本维度；**多次训练覆盖同一 `formula_id` 的历史反馈时，当前实现为简单平均**，未加权近期。  
- 未提供 SHAP / 特征重要性 API；若需合规审计，可在 `RandomForestRegressor` 上补充 `feature_importances_` 导出接口。  
- 推理未做输入校验 beyond `_safe_float`；恶意超大 JSON 可能影响 Session 查询性能，生产环境应加分页与鉴权配额。

#### 6.5.11 HTTP API 与鉴权契约（专家 ML 专用）

以下接口均需 **`POST /auth/login`** 获取 token，并在请求头携带 **`x-token: <token>`**（与前端 `index.html` 中 `call()` 一致）。

| 方法 | 路径 | 请求体（Pydantic） | 成功响应要点 |
|------|------|-------------------|--------------|
| `POST` | `/expert/train` | `TrainRequest`：`min_samples: int`，**≥ 1**（默认 20） | `TrainResult`：`trained_at`、`sample_count`、`perf_mae`、`perf_r2`、`rank_mae`、`model_version` |
| `GET` | `/expert/model-status` | 无 body | `ModelStatusResult`：`ready`、`model_dir`、`metadata`（未就绪时 `metadata` 多为空对象） |

**服务端副作用**：

- **`/expert/train`**：调用 `ml_runtime.train(min_samples=...)`；成功则**覆盖** `models/` 下同名 `pkl` 与 `metadata.json`；并向 **`audit_logs`** 写入一条 `action=expert_train`，`target_id=model_version`，`score=perf_r2`（便于按版本检索训练质量）。  
- **`/expert/model-status`**：只读内存中已 `load()` 的元数据，不写库。

**与「流行色训练」区分**：`POST /trends/train` 写的是 **`trend_preference_bundle.pkl`**，与 **`perf_model.pkl` / `rank_model.pkl`** 完全独立；运维发布时注意两套模型文件是否同步备份。

#### 6.5.12 单次「专家推荐」在线链路（时序视角）

以 **`POST /expert/recommend`**（或编排内同一段 `recommend_formulas`）为例，在**一次 HTTP 请求**内，对数据库中**每一条** `formula` 大致执行：

```mermaid
sequenceDiagram
  participant C as Client
  participant API as FastAPI
  participant EO as ExpertOrchestrator
  participant Store as SQLStore
  participant ML as MLRuntime
  C->>API: POST /expert/recommend + x-token
  API->>EO: recommend_formulas(payload)
  loop 每条 formula
    EO->>Store: get_measurement(linked_id)
    EO->>EO: _predict_performance
    alt has_model 且推理成功
      EO->>ML: predict_performance(pigments, m_json)
      ML-->>EO: adhesion,gloss,impact,voc
    else 无模型或异常
      EO->>EO: 启发式四维
    end
    EO->>EO: _check_hard_constraints -> passed
    alt has_model
      EO->>ML: predict_rank(pigments, m_json)
      ML-->>EO: rank_prob
    end
    EO->>EO: 累加 priority_score
    EO->>EO: _process_params
  end
  EO->>EO: sort 取 top_k
  EO-->>API: List[FormulaRecommendation]
  API-->>C: JSON
```

**复杂度**：设配方条数为 \(N\)，则 `_predict_performance` 与（若启用）`predict_rank` 各约 **\(O(N)\)**；`RandomForest.predict` 单次为亚毫秒级量级时，瓶颈常在 **数据库全表列出配方** 与 **每条一次测色查询**；配方上千条时建议引入 **分页推荐** 或 **候选预筛**（当前未实现）。

#### 6.5.13 失败矩阵（训练 / 加载 / 推理）

| 场景 | 表现 | 对线上预测的影响 |
|------|------|------------------|
| 有效样本数 `< min_samples` | `train()` 抛 `ValueError`；**`main.expert_train` 当前未 try/except**，客户端通常收到 **HTTP 500**（错误体为框架默认堆栈/消息） | 旧 `pkl` **不被覆盖** |
| 仅有 `perf_model.pkl` 无 `rank_model.pkl` | `has_model()` 为 **false** | 性能、排序均走启发式；`rank` 分支不执行 |
| 测色 id 在库中缺失 | 训练时该配方跳过；推理时 `get_measurement` 失败 → `_predict_performance` **回退启发式** | 该条推荐仍返回，但 `predicted_performance` 非 ML |
| `predict_rank` 抛错 | `recommend_formulas` 内 `try/except` 吞掉 | **不加分** `rank_prob*20`，其余分数照旧 |
| `metadata.json` 损坏或缺失 | `load()` 仍可能成功加载 `pkl`；`metadata` 为空 dict | `model-status` 中元数据不完整，不影响 `predict` |
| pickle 与当前 sklearn 版本不兼容 | `pickle.load` 抛错 → 模型指针为 None（取决于异常位置） | 等效于无模型；需在同版本环境重训或导出 ONNX 等（未实现） |

#### 6.5.14 训练样本构造（伪代码级复述）

下列逻辑与 `MLRuntime.train()` 等价，便于代码评审时对照：

```
formulas <- SELECT * FROM formulas
measurements <- dict(SELECT * FROM measurements BY id)
feedbacks_by_fid <- GROUP feedbacks BY formula_id

rows_X, rows_Yperf, rows_Yrank <- empty lists

FOR each f IN formulas:
    m <- measurements.get(f.linked_measurement_id)
    IF m IS NULL: CONTINUE
    x <- _extract_feature(f.pigments, {angles: m.angles, texture: m.texture})
    base <- _pseudo_performance(f.pigments)
    fb_list <- feedbacks_by_fid.get(f.id, [])
    IF fb_list NOT empty:
        y_perf <- average over fb in fb_list of (
            for each metric k: coalesce(fb.measured[k], base[k])
        )
        y_rank <- mean(fb.accepted)
    ELSE:
        y_perf <- [base.adhesion, base.gloss, base.impact, base.voc]
        y_rank <- 0.5
    APPEND x, y_perf, y_rank to lists

IF len(rows_X) < min_samples: RAISE ValueError

X <- matrix(rows_X)
fit RandomForestRegressor on (X, Yperf)
fit GradientBoostingRegressor on (X, Yrank)
SAVE pickle + metadata; reload in-process
```

#### 6.5.15 与演示种子、Excel 导入、反馈的衔接

- **`db.py` / `reset_and_seed_demo_data`** 灌入的 `formulas` 均带 **`linked_measurement_id`**，保证冷启动下**至少若干条**可进入 `X`。若你把 `min_samples` 设得高于种子配方数，训练会失败。  
- **Excel 导入**（`importer.py`）：若某行 `linked_measurement_id` 在 `measurements` 表不存在，该配方**不会进训练集**；导入后应跑 **`GET /formulas` + 人工或脚本校验外键**。  
- **反馈闭环**：`POST /expert/feedback` 写入 `feedbacks` 后，**不会自动触发重训**；需运维或定时任务调用 **`POST /expert/train`**。重训后 `sample_count` 反映的是**当前库中有效配方条数**，不是反馈条数。

#### 6.5.16 运维与可观测性建议

- **发布检查清单**：`model-status.ready` → 抽一条配方 `POST /expert/recommend` → 比对 `predicted_performance` 与业务直觉 → 查看 `audit_logs` 是否出现对应 `expert_train` 记录。  
- **版本溯源**：以 **`metadata.json` 的 `model_version`** 为发布标签；与容器镜像 tag 或 Git commit 一并记录在变更单中。  
- **回滚**：保留上一份 `perf_model.pkl.bak` / `rank_model.pkl.bak` 与对应 `metadata.json`；回滚即替换文件并重启进程。  
- **安全**：`pickle` 可执行任意对象反序列化代码；**切勿加载不可信来源的 `pkl`**；模型目录应仅服务账号可写。

#### 6.5.17 演进方向（与当前实现的差距，供产品拆分）

若需与「工业配方系统」完全对齐，可在不改变现有 API 的前提下分阶段增加：

1. **特征层**：全角光谱、多批次测色统计量、颜料批次号 one-hot、工艺窗口编码。  
2. **标签层**：按试制日期加权、分车型/基材分层模型或多任务头。  
3. **训练层**：交叉验证选参、单独校准 VOC 等非对称误差、或替换为 **LightGBM / XGBoost / 小 MLP**。  
4. **推理层**：批量 `predict`、GPU（若用深度学习）、**仅对 Top-N 相似配方**跑 ML 以控延迟。  
5. **治理层**：模型注册表、血缘（训练快照 SQL dump hash）、**特征重要性**与漂移监控。

---

## 7. 光学三原色在系统中的体现

系统采用 45° 角度光谱的三个波段近似 RGB 通道：

- 400nm -> 蓝通道 -> `base_blue`
- 500nm -> 绿通道 -> `base_green`
- 600nm -> 红通道 -> `base_red`

对应接口：`GET /knowledge/rgb-primaries`

---

## 8. 关键接口清单（按功能分组）

### 8.1 认证与基础

- `POST /auth/login`
- `GET /health`
- `GET /dashboard/summary`

### 8.2 数据管理

- `POST /measurements`
- `POST /formulas`
- `GET /formulas`
- `GET /feedbacks`

### 8.3 颜色与算法

- `POST /vision/extract`
- `POST /vision/recommend`
- `POST /algorithms/match`
- `POST /algorithms/tune`
- `POST /algorithms/generate`
- `POST /algorithms/render`

### 8.4 指标与报告

- `POST /metrics/compare`
- `POST /export/excel`
- `POST /export/pdf`

### 8.5 专家与模型

- `POST /expert/parse-requirement`
- `POST /expert/recommend`
- `POST /expert/orchestrate`
- `POST /expert/feedback`
- `POST /expert/train`
- `GET /expert/model-status`

### 8.6 导入与管理

- `POST /import/excel`
- `POST /admin/reset-demo`
- `GET /audit/logs`

### 8.7 流行色、展望与 RGB 生成配方

- `GET /trends/status`
- `POST /trends/train`
- `POST /trends/match`
- `POST /trends/forecast`
- `POST /algorithms/generate-from-rgb`（展望色或任意 RGB → 合成测色 → `smart_generate`）

流程说明见 **§15**。

---

## 9. Excel 一键导入规范

上传 `.xlsx`，支持工作表：

- `measurements`
  - 字段：`id, car_model, color_code, angles, texture`

- `formulas`
  - 字段：`id, name, pigments, linked_measurement_id`

- `feedbacks`
  - 字段：`formula_id, measured_performance, accepted, comment`

其中 `angles/pigments/measured_performance` 为 JSON 字符串。

导入返回：

- 每类成功数量
- 失败行（数据集、行号、原因、原始数据）

---

## 10. 前后端联动与部署

### 10.1 本机同源（默认）

- 后端：`http://127.0.0.1:8000`
- 前端通过同源路径调用 API

### 10.2 前后端分离

- 页面顶部配置“后端 API 地址”
- 保存后写入 `localStorage` 并立即生效
- 启动心跳，每 10 秒检测一次 `/health`

### 10.3 CORS

通过环境变量配置：

- `CORS_ORIGINS=http://127.0.0.1:8000,...`

---

## 11. 环境变量说明

- `DATABASE_URL`
  - SQLite 默认：`sqlite:///./paint_system.db`
  - MySQL 示例：`mysql+pymysql://root:password@127.0.0.1:3306/paint_system?charset=utf8mb4`

- `ADMIN_USER`
- `ADMIN_PASSWORD`
- `ADMIN_TOKEN`
- `CORS_ORIGINS`

---

## 12. 常见问题与排查

### 12.1 页面拒绝连接（ERR_CONNECTION_REFUSED）

- 后端未启动或已退出
- 检查 `uvicorn` 是否在运行

### 12.2 登录失败

- 账号密码错误
- 当前连接数据库与预期不一致（MySQL/SQLite切换）
- 前端 API 地址配置错

### 12.3 数据“丢失”

- 实际是连接到了不同数据库实例
- 检查 `DATABASE_URL`

### 12.4 mysql 命令找不到

- 未加 PATH 或客户端未安装
- 可用 `mysql.exe` 完整路径执行

---

## 13. 当前能力边界与下一步建议

已具备：

- 可运行业务闭环（输入 -> 推荐 -> 反馈 -> 训练）
- 可切换 MySQL
- 可导入/导出

尚可增强：

- 用户管理页面（创建/重置账号）
- 模型可观测性（在线推理来源：ML/回退）
- 配方版本管理与审批流
- BRDF/BSDF 物理渲染与 WebGL 前端
- ERP/PLM/LIMS 集成

---

## 14. 快速启动参考（MySQL）

```powershell
cd d:\color_size
$env:DATABASE_URL="mysql+pymysql://root:your_password@127.0.0.1:3306/paint_system?charset=utf8mb4"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

验证：

- `http://127.0.0.1:8000/health` -> `db_connected: true`

---

## 15. 流行色模块：匹配 → 展望 → 配方回灌（全流程详述）

本节按产品叙述顺序，把 **「当前色与趋势库的关系」**、**「按趋势外推的未来色」**、**「展望色回到配方管线」** 写完整；实现均在 **`app/trend_preferences.py`**、**`app/vision.py`**（RGB→合成测色）、**`app/main.py`**（路由）及前端 **`app/static/index.html`**（步骤 2 / 结果区）。

### 15.1 数据与训练前提（`POST /trends/train`）

- **数据源目录**：环境变量 **`TREND_DATASET_ROOT`**；未设置时默认为项目下 **`data/pantone_fashion_trends`**。  
- **主表文件**：该目录下的 **`metadata.csv`**，每行至少含有效 **`r,g,b`**（及可选 **`trend_year`**、**`tcx_code`**、**`color_name`**、`hex`、`image_rel_path` 等）。Lab 列若空，加载时用 **`skimage.color.rgb2lab`** 由 RGB 推算。  
- **训练产物**（写入 **`models/`**）：  
  - **`trend_preference_bundle.pkl`**：`StandardScaler`、`KMeans`、`NearestNeighbors`、原始 **`labs`** 矩阵、**`meta_rows`** 列表。  
  - **`trend_preference_meta.json`**：`trained_at`、`sample_count`、`n_clusters`、`model_version` 等。  
- **训练逻辑摘要**：对全体趋势色 Lab 做 **`StandardScaler.fit_transform`**；在标准化空间 **`KMeans.fit`**（簇数由样本量与参数推导，有上下界）；在同一标准化空间 **`NearestNeighbors.fit`**，训练时邻居数 **`min(15, n)`**（`n` 为 CSV 有效行数）。  
- **匹配/展望/加载**：进程内 **`TrendPreferenceRuntime._load_bundle()`** 读入上述 pickle；**无 bundle 则 `match` / `forecast` 抛错**，提示先训练。

### 15.2 流行色匹配（`POST /trends/match`）

#### 15.2.1 请求输入

- **`TrendMatchRequest`**：`r,g,b`（整数 0–255）与 **`measurement`**（Pydantic 测色对象）**二选一**；若同时传，**优先使用 `measurement`**。  
- **`top_k`**：返回的近邻条数，**1～30**；实际返回 **`min(top_k, n)`**（`n` 为趋势库行数）。

#### 15.2.2 查询色 → Lab（与识图侧「三波长」约定一致）

| 输入 | 计算路径 |
|------|----------|
| **`measurement`** | **`measurement_to_lab(m)`**：仅读 **`angles["45"]`**，用 **600nm→R、500nm→G、400nm→B** 的 `value`（0～1）乘 255 并截断到 0–255，再 **`_rgb_to_lab`**（内部 **`skimage.color.rgb2lab`**，D65 与识图管线一致）。**不使用 15°/110°，不使用 texture。** |
| **RGB** | 直接 **`_rgb_to_lab(float(r),float(g),float(b))`**。 |

得到查询 Lab 记为 **`(L, a, b)`**，响应中 **`query_lab`** 为其四舍五入展示。

#### 15.2.3 标准化空间：簇与近邻索引

1. **`q_lab`** 形状 `1×3`，**`q_scaled = scaler.transform(q_lab)`**（使用训练时在**全体趋势色**上拟合的均值方差）。  
2. **簇编号 `trend_cluster`**：**`kmeans.predict(q_scaled)[0]`**，表示查询点在**标准化 Lab** 空间中落入哪个趋势簇。  
3. **近邻检索**：**`k_use = min(top_k, len(meta_rows))`**；**`nn.kneighbors(q_scaled, n_neighbors=k_use)`**。  
   - 近邻顺序与距离定义在 **标准化后的 3 维欧氏空间**。  
   - 返回的近邻下标对应 **`meta_rows[i]`** 与 **`labs[i]`**（**原始 Lab**，未再标准化）。

#### 15.2.4 近邻列表与两种距离（易混点）

对每个近邻 `j`（对应训练行下标 `i`）：

- **`TrendNeighbor` 展示字段**：来自 **`meta_rows[i]`**（名称、TCX、hex、RGB、`trend_year`、`book_group`、`image_rel_path` 等）。  
- **`TrendNeighbor.distance`**：来自 **`kneighbors` 返回的 `dists_scaled[0][j]`**，即 **查询点与该样本在标准化 Lab 空间中的欧氏距离**（保留 6 位小数）。  
- **偏好分内部用的距离**：另算 **`d_lab = ||q_lab - labs[i]||_2`**，即 **原始 Lab 三维欧氏长度**（**不是 CIEDE2000**；字段 **`mean_delta_e_lab`** 为这批近邻 **`d_lab` 的算术平均**）。

**小结**：**谁当近邻**由 **标准化空间** 决定；**偏好分用的「平均色差」**由 **原始 Lab 欧氏** 在已选近邻上平均。

#### 15.2.5 偏好分

- **`mean_delta_e_lab = mean(d_lab 列表)`**；若列表为空（异常）则用 **50.0** 占位。  
- **`preference_score = min(100, max(0, 100 * exp(-mean_delta_e_lab / 18)))`**，再保留两位小数。  
- **含义**：近邻在 **原始 Lab** 上与查询越近，`mean_delta_e_lab` 越小，分越高；**18** 为衰减尺度常数。

### 15.3 按趋势外推的未来色（`POST /trends/forecast`）

与匹配共用 **同一 bundle**（`scaler`、`kmeans`、`labs`、`meta_rows`）。**查询 Lab 的得到方式与 §15.2.2 完全相同**。

#### 15.3.1 请求参数（`TrendForecastRequest`）

- **`horizon_years`**：展望年数，默认 **2**（例如 Y+1、Y+2）。  
- **`suggestions_per_horizon`**：每个展望年生成的 **候选色条数**，默认 **3**（前端当前写死为 2 年 × 3 条，可在 API 中改）。  
- 同样需要 **`RGB` 或 `measurement`** 二选一。

#### 15.3.2 簇与「时间速度」velocity

1. 用 **`q_scaled`** 得到 **`cluster_id`**（同匹配）。  
2. 在 **训练集所有点** 上做一次 **`kmeans.predict(scaler.transform(labs))`**，取出与 **`cluster_id`** 相同的行下标集合 **`cluster_idx`**（同簇趋势色）。  
3. **锚点年 `anchor_trend_year`**：在该簇及**全库**中，取 **`trend_year > 0`** 的最大年份；若没有任何年份字段，则用 **当前 UTC 年**。  
4. **velocity（Lab 三维，单位：Lab/年）**，按优先级三选一（`temporal_signal` 字段标明）：  
   - **`cluster_temporal_regression`**：在该簇内，按 **`trend_year`** 对样本分组，算每年 Lab **均值**，对 **L、a、b** 分别对年份做 **`numpy.polyfit` 一次线性**，斜率作为 velocity。  
   - **`global_temporal`**：簇内不足两个有年份的年时，退化为**全库**按年均值再回归。  
   - **`palette_evolution_heuristic`**：仍无足够年份时，用 **簇心 − 用户 Lab** 的单位方向 × **1.8** 作为启发式速度。  
5. **簇心 `centroid_c`**：同簇 **`labs`** 的均值；若簇为空则用全库均值。

#### 15.3.3 逐年、逐候选生成 Lab → RGB

对每个 **`h = 1 … horizon_years`**（展望第 `h` 年）：

1. **`trend_point = clamp(user + velocity * h)`**（`user` 为查询 Lab 向量；`clamp` 限制 L/a/b 在合理区间）。  
2. **融合**：**`blended = 0.42*user + 0.58*(0.55*trend_point + 0.45*centroid_c)`**，再 clamp —— 即 **保留约 42% 用户色**，其余沿「趋势外推 + 簇心」混合，避免完全漂离当前提取色。  
3. **展望公历年**：**`forecast_calendar_year = anchor + h`**。  
4. 对每个 **`k = 0 … suggestions_per_horizon-1`**：在 **`blended`** 上加 **a*b* 平面扇形扰动**（`theta = 2πk/suggestions`）及 **轻微 L 抖动**，得到 **`lab_k`**，再 **`lab2rgb`** 量化到 **RGB 与 Hex**，写入 **`TrendForecastColor`**（含 **`rationale`** 文案）。

响应 **`TrendForecastResult`** 含：**`query_lab`、`trend_cluster`、`anchor_trend_year`、`temporal_signal`、`forecasts[]`、`methodology_note`**。算法为 **启发式外推**，非市场调研结论。

### 15.4 展望色 → 配方生成（回灌）

- **接口**：**`POST /algorithms/generate-from-rgb`**，body 为 **`GenerateFromRgbRequest`**（`r,g,b`、`range_ratio`、可选 `car_model` / `color_code` / `source_label`）。  
- **实现**：**`build_measurement_from_rgb`**（`app/vision.py`）用 RGB 构造与识图一致的 **简化多角度光谱 + 纹理**，生成 **`Measurement`** 并 **`store.add_measurement`**；再调用 **`ColorEngine.smart_generate`**；在结果上附带 **`reference_rgb` / `reference_lab`** 便于与区间色对照。  
- **前端**：展望结果表中每行 **「生成配方」** 按钮 → 调用上述接口 → **`renderGenerate`** 展示七支色母表等；并把 RGB 写回步骤 2 的偏好输入，便于继续 **匹配** 或调整。

### 15.5 接口与审计一览

| 步骤 | 方法 | 路径 | 说明 |
|------|------|------|------|
| 数据集状态 | `GET` | `/trends/status` | CSV 行数、年份、`model_ready` |
| 训练趋势模型 | `POST` | `/trends/train` | 写 `trend_preference_bundle.pkl` |
| 匹配 | `POST` | `/trends/match` | 近邻 + 偏好分 + 簇 |
| 展望 | `POST` | `/trends/forecast` | 多年多候选 Lab/RGB |
| 展望色生成配方 | `POST` | `/algorithms/generate-from-rgb` | 入库测色 + 生成配方 |

审计：`trends_match`、`trends_forecast`、`generate_from_rgb` 等在 `main.py` 中写入 **`audit_logs`**（与专家 `expert_train` 独立）。

### 15.6 与专家 ML（§6.5）的关系

- **流行色**：外部 **CSV 趋势库** + **`trend_preference_bundle.pkl`**；输出为 **近邻色卡、偏好分、展望 RGB/Lab**，**不预测附着力/VOC**。  
- **专家 ML**：库内 **配方+测色+反馈** + **`perf_model.pkl` / `rank_model.pkl`**。  
- **组合方式**：产品上可同时展示「趋势偏好」与「配方性能预测」；**训练数据与 pickle 勿混用**。
