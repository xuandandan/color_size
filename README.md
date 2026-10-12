# 智能涂料颜色配比系统（MVP）

基于 `涂料颜色配比.docx` 的需求，提供一个可运行的后端系统原型，覆盖以下关键能力：

- 多角度测色数据录入（光谱 + 纹理/颗粒特征）
- 配方数据库管理
- 用户登录鉴权（`x-token`）
- 审计日志（关键操作追踪）
- 四大核心算法接口：
  - 智能匹配（历史配方检索）
  - 智能调色（基于差异给出调色建议）
  - 智能生成（无法匹配时自动给新配方）
  - 车漆渲染预览（输出可视化参数）
- 图像识别配色：
  - 上传图片提取颜色特征并生成测色数据
  - 上传图片直接输出匹配配方与自动生成配方

## 目录结构

```text
app/
  main.py        # FastAPI 入口与 API
  models.py      # 数据模型
  db.py          # SQLAlchemy 数据库模型
  auth.py        # 登录与 token 校验
  storage.py     # SQL 数据访问
  services.py    # 四大算法实现（MVP 版本）
  vision.py      # 图片识别与颜色特征提取
  static/index.html  # 简易前端页面
requirements.txt
```

## 快速启动

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

打开页面：

- 系统首页：`http://127.0.0.1:8000/`
- API 文档：`http://127.0.0.1:8000/docs`

默认账号：

- 用户名：`admin`
- 密码：`admin123`
- 登录后通过 `x-token` 调用接口

## 免费部署到 Render（公开给别人用）

> 不要用 Netlify：本项目是 FastAPI，需要常驻 Python 进程。

### 1. 推到 GitHub

仓库根目录需包含：`app/`、`models/`、`data/`、`requirements.txt`、`render.yaml`、`README.md`、`.env.example`。

```bash
git init
git add .
git commit -m "Prepare project for Render free deploy"
# 在 GitHub 新建空仓库后：
git remote add origin https://github.com/你的用户名/仓库名.git
git branch -M main
git push -u origin main
```

### 2. 在 Render 创建服务

1. 打开 https://render.com 注册并登录  
2. **New** → **Blueprint**，连接该 GitHub 仓库（会读取 `render.yaml`）  
   - 或 **New** → **Web Service**，手动填写：  
     - Build Command：`pip install -r requirements.txt`  
     - Start Command：`uvicorn app.main:app --host 0.0.0.0 --port $PORT`  
     - Instance type：选择 **Free**  
3. 环境变量（Blueprint 已带默认值，可改）：  
   - `ADMIN_USER=admin`  
   - `ADMIN_PASSWORD=admin123`（建议改成你自己的）  
   - `ADMIN_TOKEN=demo-token`  
   - `CORS_ORIGINS=*`  
4. 部署完成后，用 Render 给出的网址访问（如 `https://xxx.onrender.com`）

### 免费版注意

- 一段时间无人访问会休眠，下次打开可能要等约 30–60 秒  
- 免费盘数据不持久，重启后 SQLite 会重新初始化（够演示用）

## 切换到 MySQL（前后端联动）

1. 安装并启动 MySQL，创建数据库 `paint_system`。
2. 复制 `.env.example` 为 `.env`，修改 `DATABASE_URL`（用户名、密码、主机、端口）。
3. 重新启动后端，系统会自动建表与初始化管理员。

PowerShell 示例：

```powershell
cd d:\color_size
$env:DATABASE_URL="mysql+pymysql://root:your_password@127.0.0.1:3306/paint_system?charset=utf8mb4"
$env:CORS_ORIGINS="http://127.0.0.1:8000,http://localhost:8000,http://127.0.0.1:5173,http://localhost:5173"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

连通性检查：

- 打开 `http://127.0.0.1:8000/health`
- 返回 `db_connected: true` 即表示后端已连上 MySQL。

## 前后端分离部署

- 后端：运行 `app.main`（任意地址）
- 前端：打开页面后，在顶部“后端 API 地址”输入框填后端地址（例如 `http://127.0.0.1:8000`），点“保存后端地址”。
- 若前端和后端跨域，确保 `CORS_ORIGINS` 包含前端域名。

## 典型流程

1. `POST /auth/login` 登录获取 token
2. `POST /measurements` 录入测色数据
3. `POST /formulas` 录入已有配方并关联测色数据
4. `POST /algorithms/match` 获取最相似配方
5. `POST /algorithms/tune` 获取基于现有配方的调色建议
6. `POST /algorithms/generate` 生成新候选配方
7. `POST /algorithms/render` 获取渲染预览参数
8. `GET /audit/logs` 查看操作审计记录
9. `POST /vision/extract` 上传图片提取颜色
10. `POST /vision/recommend` 上传图片直接推荐配方
11. `POST /export/excel` 导出当前结果为 Excel
12. `POST /export/pdf` 导出当前结果为 PDF
13. `POST /metrics/compare` 对比两张图片并返回可信度指标
14. `POST /expert/parse-requirement` 解析原始需求为硬/软约束
15. `POST /expert/recommend` 多目标推荐 Top 5-10 配方
16. `POST /expert/orchestrate` 主智能体编排全流程（解析/推荐/预测/工艺）
17. `POST /expert/feedback` 回收试制检测结果进入反馈闭环
18. `POST /expert/train` 训练推荐/性能预测模型
19. `GET /expert/model-status` 查看模型状态与版本
20. `POST /import/excel` 上传 Excel 一键导入（含失败行报告）

## 训练模型

```bash
python -m app.train --min-samples 20 --save-dir models
```

或通过 API 训练：

- `POST /expert/train`，示例 body: `{"min_samples": 20}`

## Excel 批量导入 MySQL

- 上传 `.xlsx` 文件到 `POST /import/excel`
- 支持工作表名称：`measurements`、`formulas`、`feedbacks`
- 每个工作表第一行是字段名，支持 JSON 字段（如 `angles`、`pigments`、`measured_performance`）
- 接口会返回导入成功数量和失败行报告（行号 + 原因）

## 后续可扩展建议

- 将 SQLite 切换为 MySQL/PostgreSQL（通过 `DATABASE_URL`）
- 用真实模型替换 `services.py` 中的启发式算法
- 加入 BRDF/BSDF 的物理渲染模块与前端 WebGL 可视化
- 接入 IoT 设备数据流（测色仪、电子秤、扫码枪）
- 增加配方版本管理、权限管理、操作审计
