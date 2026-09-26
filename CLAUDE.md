# CLAUDE.md

本文件为 Claude Code 在本仓库工作时的指引。面向“具有自动泊车功能的电动车”电赛 D 题，仓库只包含 **MaixCAM2 视觉端**程序；电机、舵机、PID、任务阶段与停车执行全部由下位机负责，本仓库没有这些控制代码。

## 语言与文件约定

- 所有回复、注释、文档、提交信息使用**简体中文**。
- 编码：所有 Python 文件均为 **UTF-8 无 BOM**。工具链统一用 `encoding='utf-8-sig'` 读取（对无 BOM 文件同样正确，且能容错 BOM），**写文件时不要写入 BOM**。
- 行尾：仓库内存放的是 **LF**（无 `.gitattributes`，靠 system 级 `core.autocrlf=true` 转换）。工作区中 `tests/`、`docs/` 为 LF，而 `code/main.py` 是 **CRLF 317 行 + LF 82 行的混合状态**（历史遗留）。新增或改动 `main.py` 时保持现有行的行尾不要整体重排，否则会产生整文件 diff。
- 不要动 `code/main.py` 顶部的参数区排版（见下文“测试与源码结构强耦合”）。
- 提交信息遵循历史风格：Conventional Commits 前缀 + 中文描述，scope 常用 `vision` / `repo`。例：`docs(vision): 核对视觉框架并同步标定资料`。

## 常用命令

在项目根目录执行：

```powershell
# 逻辑测试（13 项，需要 cv2 与 numpy）
python -m unittest discover -s tests -v

# 语法检查；预期输出 syntax PASS
python -c "import ast,pathlib; ast.parse(pathlib.Path('code/main.py').read_text(encoding='utf-8-sig')); print('syntax PASS')"
```

**以下命令当前不可用，不要照抄：**

```powershell
# 损坏：NameError: name 'junction_x' is not defined
python docs/images/draw_roi_calibration.py
```

`docs/images/draw_roi_calibration.py` 在 `timing_values()` 处崩溃（脚本第 242 行的 `exec(code, state)`）。根因是 d82be91 改写 `code/main.py` 计数逻辑时新增了 `junction_x`、`junction_y`、`tracked_x`，并把位置连续性判断改成 `max(abs(...))`，而脚本的准备状态只放行了 `min`：

```python
state = {**P, '__builtins__': {'min': min}}   # 缺 abs / max，且未注入上述三个变量
```

由于崩溃点在 `main()` 的第四张图，**前三张图与 SVG 已被重写、`manifest.json` 未更新**，所以现在重跑会同时产生“图已改、清单未改”的不一致状态。修复方向是补齐 `state` 中缺失的变量与内置函数（或在脚本内同步计数片段）；修复前请勿执行该命令，改动参数后也只能手工更新正文。

绘图脚本恢复可用后的预期输出：`Exported 4 figures: PNG / SVG / preview; layout bounds PASS`。

## 开发环境

- **解释器有坑**：VS Code 的 `.vscode/settings.json` 指向 conda（`D:\Anaconda3`），但该环境的 python **没有 cv2**；PATH 中的 `D:\python\python.exe`（Python 3.14）才有 cv2 5.0.0、numpy 2.4.1、matplotlib 3.11.0。在 VS Code 里跑测试若报 `ModuleNotFoundError: No module named 'cv2'`，先切换解释器，而不是装包。
- 电脑端**不能**运行完整的 `code/main.py`（需要相机、显示器、UART 与板端 `maix` 模块），只能做语法与逻辑检查。
- 仓库没有 CI、没有 lint/format 配置、没有测试运行器配置，全部靠手工执行上面的命令。

## 架构

单文件视觉程序：`code/main.py`（399 行）是整个项目的唯一运行入口。

- **没有函数、没有 `if __name__` 保护**：顶层顺序为「参数常量 → 计算 ROI → 初始化相机/显示/UART 与计数状态 → `while not app.need_exit()` 主循环 → 关闭串口」。导入该文件即触发设备初始化。
- 每帧流水线：取图 → 高斯滤波 → LAB 二值化 → 闭运算 → 开运算 → 主 ROI 外清零 → 横线 ROI 内 `get_regression` 回归 → 斜率/跨度/像素支撑筛选 → 算 `pos`/`head` → 沿拟合线逐列裁掉横线及下方 → 动态 V_roi 内 `find_blobs` → 形状与交点间距筛选 → 连续帧确认与计数去重 → 发串口 → 叠加标注显示。
- 参数全部集中在文件顶部常量，改参数必须**停止旧程序后重新运行**，热改无效。
- UART：A21→`UART4_TX`、A22→`UART4_RX`，`/dev/ttyS4` @115200，只发送不接收。每帧一行 ASCII：`valid,pos,head,count\r\n`。`valid=0` 时两个 `0.0` 是占位值，**不能**当作居中结果；`count` 是进程启动以来的累计值，下位机必须做差分，不能逐行累加。
- 地标计数是**无身份跟踪**的状态机：候选连续 `JUNCTION_CONFIRM_FRAMES=3` 帧确认后加一，锁定后需跟踪该地标越过触发窗口再累计 `JUNCTION_RELEASE_FRAMES=5` 帧有效横线才解锁。已计数地标若在被跟踪到出窗前完全消失（遮挡、漏检、单帧位移超过 `MARK_MAX_STEP`），锁定**可能一直不释放**并漏计后续地标——这是已知限制，`tests/test_main_logic.py` 中有两个用例专门固化该行为，不要随手“修好”它们。

## 测试与源码结构强耦合

`tests/test_main_logic.py` 不做导入，而是解析 `code/main.py` 的 AST 并按**符号名切片**编译执行：

| 片段 | 切片边界（符号名） | 当前 AST 索引 → 源码行 |
| --- | --- | --- |
| `CONFIG` | 顶层硬编码索引 2（当前为 `W = 320`）→ 第一个名为 `cam` 的赋值 | `TREE.body[2:41]` → 第 8～81 行 |
| `INITIAL` | `junction_streak` 赋值 → `while` 循环（6 条语句） | `TREE.body[46:52]` → 第 92～97 行 |
| `GEOMETRY` | 循环内 `line` 赋值 → `V_binary_cv` 赋值 | 循环体 `[18:30]` → 第 146～214 行 |
| `COUNTING` | 循环内 `blob` 赋值 → `packet` 赋值 | 循环体 `[37:54]` → 第 247～331 行 |
| `SENDING` | `packet` 赋值起 2 条语句（含 `try` 块） | 循环体 `[54:56]` → 第 335～348 行 |

**临界约束**：`CONFIG = fragment(TREE.body, 2, ...)` 的起点是**硬编码的 AST 索引 2**（当前对应 `W = 320`，物理第 8 行），不随注释和空行移动。因此：

- **不要在两条 `import` 之后、`W` 之前插入任何顶层语句**——索引会平移，`CONFIG` 从错误位置开始，测试静默跑偏。
- 不要在 `GEOMETRY`、`COUNTING`、`SENDING` 的边界符号之间插入语句或改变其名字。
- **不要删除或重命名** `cam`、`junction_streak`、`line`、`V_binary_cv`、`blob`、`packet` 这些锚点。

上表的行号只是当前快照，会随编辑漂移；**索引才是真正被硬编码的**。改动 `code/main.py` 后必须跑一次 `python -m unittest discover -s tests -v`，13 项应全绿。

测试只覆盖计数状态机、误差计算与 UART 异常边界；它不模拟 MaixPy 图像算法、相机或串口，测试通过**不能**作为板端识别率、实时性、停车精度达标的依据。

## 文档分工与同步

| 文档 | 职责 |
| --- | --- |
| `README.md`（根） | 项目总览、目录结构、上板步骤、串口协议摘要 |
| `docs/main_README.md` | `main.py` 的流程、显示标注含义、误差定义、状态机、异常行为 |
| `docs/MaixCAM2参数实测与ROI标定方案.md` | 参数总表、ROI 图解、第 1～12 步现场标定与验收记录（含可直接粘贴的临时调试代码） |
| `docs/images/draw_roi_calibration.py` | 读取 `code/main.py` 的 AST 生成四张示意图 + `maixcam2_roi_calibration_manifest.json`（含源码 sha256）；**当前已损坏，见上** |
| `docs/maixcam2_parameter_record.xlsx` | 参数实测记录表，标定结论填这里 |
| `outputs/` | 标定轮次的截图与日志存放处，按日期建子目录；**不纳入版本控制** |
| `docs/pdfs/`、`pictures/` | 赛题原文与现场参考照片 |

改动 `code/main.py` 的参数或行为时，需同步：相关文档正文 → 重新生成示意图与清单 → 跑测试。四张图是**教学示意，不是板端实测**，`manifest.json` 里的 `board_validation` 恒为 `not performed`。

**重跑示意图会产生大量无意义 diff**：导出的 SVG 内嵌 `<dc:date>` 生成时间戳，且 matplotlib 的 clip-path id 每次随机（如 `#p5a9487a367` → `#pfd8fadc026`），单张图动辄 145 行变更。提交前先确认差异是否只含这两类噪声；必要时用 `git checkout -- docs/images/` 丢弃纯噪声重跑，只保留真正因参数变化产生的改动。

## 已知现状与注意事项

- 参数多为**工程初值**，代码里大量 `待测` 注释表示缺验证证据。不要把这些值当成标定结论，也不要为了让数字好看而改阈值而不说明验证条件。
- `Mark_half_w` 是未使用变量，实际窗口由 `MARK_TRIGGER_HALF_WIDTH` 控制。
- 应用打包配置只在 `code/` 内维护一份（`code/app.yaml` 当前为 `id: starrymoon`，1.0.2）。根目录没有应用入口，**打包以 `code/` 为应用目录**。
- `code/dist/maix-starrymoon-v1.0.2.zip` 是历史产物，**内含的 `main.py` 与当前源码不同**（md5 不一致），不保证包含当前改动，交付前必须重新打包。
- 仓库中没有 `outputs/` 目录；标定时需自行按日期创建，用于存放截图与日志。
- `.gitignore` 忽略 `**/node_modules/`、`**/__pycache__/`、`*.py[cod]`、`*.inspect.ndjson`。
- 本仓库此前误提交过 `__pycache__/*.pyc` 与软链 `node_modules`（指向本机 codex 缓存，克隆到别处必然悬空），已在提交 `61a9236` 清理；新增文件时留意 `.gitignore` 是否生效。
