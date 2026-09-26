# CLAUDE.md

本文件为 Claude Code 在本仓库工作时的指引。面向“具有自动泊车功能的电动车”电赛 D 题，仓库只包含 **MaixCAM2 视觉端**程序；电机、舵机、PID、任务阶段与停车执行全部由下位机负责，本仓库没有这些控制代码。

## 语言与文件约定

- 所有回复、注释、文档、提交信息使用**简体中文**。
- `code/main.py` 为 **UTF-8 带 BOM（utf-8-sig）+ CRLF** 换行；`tests/`、`docs/` 下的 Python 文件为 UTF-8 无 BOM + LF。编辑时不要混用，读取源码一律用 `encoding='utf-8-sig'`。
- 不要动 `code/main.py` 顶部的参数区排版（见下文“测试与源码结构强耦合”）。

## 常用命令

在项目根目录执行：

```powershell
# 逻辑测试（13 项，电脑端，需要 cv2 与 numpy）
python -m unittest discover -s tests -v

# 语法检查；预期输出 syntax PASS
python -c "import ast,pathlib; ast.parse(pathlib.Path('code/main.py').read_text(encoding='utf-8-sig')); print('syntax PASS')"

# 重新生成四张标定示意图（需要 matplotlib 与“微软雅黑”字体）
python docs/images/draw_roi_calibration.py
```

绘图脚本预期输出 `Exported 4 figures: PNG / SVG / preview; layout bounds PASS`。

本机开发环境：Python 3.14、cv2 5.0.0、numpy 2.4.1。电脑端**不能**运行完整的 `code/main.py`（需要相机、显示器、UART 与板端 `maix` 模块），只能做语法与逻辑检查。

## 架构

单文件视觉程序：`code/main.py`（约 399 行）是整个项目的唯一运行入口。

- **没有函数、没有 `if __name__` 保护**：顶层顺序为「参数常量 → 计算 ROI → 初始化相机/显示/UART 与计数状态 → `while not app.need_exit()` 主循环 → 关闭串口」。导入该文件即触发设备初始化。
- 每帧流水线：取图 → 高斯滤波 → LAB 二值化 → 闭运算 → 开运算 → 主 ROI 外清零 → 横线 ROI 内 `get_regression` 回归 → 斜率/跨度/像素支撑筛选 → 算 `pos`/`head` → 沿拟合线逐列裁掉横线及下方 → 动态 V_roi 内 `find_blobs` → 形状与交点间距筛选 → 连续帧确认与计数去重 → 发串口 → 叠加标注显示。
- 参数全部集中在文件顶部常量，改参数必须**停止旧程序后重新运行**，热改无效。
- UART：A21→`UART4_TX`、A22→`UART4_RX`，`/dev/ttyS4` @115200，只发送不接收。每帧一行 ASCII：`valid,pos,head,count\r\n`。`valid=0` 时两个 `0.0` 是占位值，**不能**当作居中结果；`count` 是进程启动以来的累计值，下位机必须做差分，不能逐行累加。
- 地标计数是**无身份跟踪**的状态机：候选连续 `JUNCTION_CONFIRM_FRAMES=3` 帧确认后加一，锁定后需跟踪该地标越过触发窗口再累计 `JUNCTION_RELEASE_FRAMES=5` 帧有效横线才解锁。已计数地标若在被跟踪到出窗前完全消失（遮挡、漏检、单帧位移超过 `MARK_MAX_STEP`），锁定**可能一直不释放**并漏计后续地标——这是已知限制，`tests/test_main_logic.py` 中有两个用例专门固化该行为，不要随手“修好”它们。

## 测试与源码结构强耦合

`tests/test_main_logic.py` 不做导入，而是解析 `code/main.py` 的 AST 并按**符号名切片**编译执行：

| 片段 | 切片边界 |
| --- | --- |
| `CONFIG` | 文件第 2 行 → 第一个名为 `cam` 的赋值 |
| `INITIAL` | `junction_streak` 赋值 → `while` 循环 |
| `GEOMETRY` | 循环内 `line` 赋值 → `V_binary_cv` 赋值 |
| `COUNTING` | 循环内 `blob` 赋值 → `packet` 赋值 |
| `SENDING` | `packet` 赋值起 2 条语句 |

因此：**不要删除或重命名这些锚点符号**，也不要在顶部参数区任意插删语句——`CONFIG` 的起点是硬编码的 `TREE.body` 索引 2，在 `import` 行之后插入新语句会让切片错位。改动 `code/main.py` 后必须跑一次 `python -m unittest discover -s tests -v`。

测试只覆盖计数状态机、误差计算与 UART 异常边界；它不模拟 MaixPy 图像算法、相机或串口，测试通过**不能**作为板端识别率、实时性、停车精度达标的依据。

## 文档分工与同步

| 文档 | 职责 |
| --- | --- |
| `README.md`（根） | 项目总览、目录结构、上板步骤、串口协议摘要 |
| `docs/main_README.md` | `main.py` 的流程、显示标注含义、误差定义、状态机、异常行为 |
| `docs/MaixCAM2参数实测与ROI标定方案.md` | 参数总表、ROI 图解、第 1～12 步现场标定与验收记录（含可直接粘贴的临时调试代码） |
| `docs/images/draw_roi_calibration.py` | 读取 `code/main.py` 的 AST 生成四张示意图 + `maixcam2_roi_calibration_manifest.json`（含源码 sha256） |
| `outputs/` | 标定轮次的截图与日志存放处，按日期建子目录；不是参数表 |
| `docs/pdfs/`、`pictures/` | 赛题原文与现场参考照片 |

改动 `code/main.py` 的参数或行为时，需同步：相关文档正文 → 重新生成示意图与清单 → 跑测试。四张图是**教学示意，不是板端实测**，`manifest.json` 里的 `board_validation` 恒为 `not performed`。

## 已知现状与注意事项

- 参数多为**工程初值**，代码里大量 `待测` 注释表示缺验证证据。不要把这些值当成标定结论，也不要为了让数字好看而改阈值而不说明验证条件。
- `Mark_half_w` 是未使用变量，实际窗口由 `MARK_TRIGGER_HALF_WIDTH` 控制。
- 应用打包配置只在 `code/` 内维护一份（`code/app.yaml` 当前为 `id: starrymoon`，1.0.2）。根目录没有应用入口，**打包以 `code/` 为应用目录**。
- `code/dist/` 只保留 `maix-starrymoon-v1.0.2.zip`；它是历史产物，不保证包含当前源码改动。
- `outputs/` 由标定过程按日期新建子目录填充，仓库内不带历史分析产物。
- `.gitignore` 忽略 `**/__pycache__/`、`*.py[cod]`、`*.inspect.ndjson`、`**/node_modules/`。
