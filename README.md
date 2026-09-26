# 电赛 D 题：自动泊车视觉端

本项目面向“具有自动泊车功能的电动车”赛题，提供运行在 **MaixCAM2** 上的视觉程序。相机识别地面横线和与其相接的竖向地标，计算巡线所需的像素误差与累计地标数，并通过 UART 发给下位机。**电机、舵机控制、任务阶段管理和停车执行由下位机负责**，本仓库没有这些控制程序。

当前代码以 320 × 240 图像和一组工程初值运行。颜色阈值、ROI、计数窗口等参数仍需在实际车辆和场地上测定；电脑端测试通过不代表板端识别效果或停车精度已验收。

## 项目结构

| 路径 | 内容 |
| --- | --- |
| [`code/main.py`](code/main.py) | MaixCAM2 视觉程序入口；参数集中在文件顶部 |
| [`code/app.yaml`](code/app.yaml)、[`code/app.png`](code/app.png) | `code/` 应用目录内的打包配置与图标 |
| [`docs/main_README.md`](docs/main_README.md) | 程序流程、显示结果、串口协议及异常行为 |
| [`docs/MaixCAM2参数实测与ROI标定方案.md`](docs/MaixCAM2参数实测与ROI标定方案.md) | 参数表、ROI 图解、标定步骤和验收记录 |
| [`docs/maixcam2_parameter_record.xlsx`](docs/maixcam2_parameter_record.xlsx) | 参数实测记录表 |
| [`docs/pdfs/`](docs/pdfs/) | 赛题 PDF 及分页图片 |
| [`pictures/`](pictures/) | 现场参考图像 |
| [`outputs/`](outputs/) | 标定过程记录目录；按[标定方案](docs/MaixCAM2参数实测与ROI标定方案.md)新建轮次子目录存放截图与日志 |
| [`tests/test_main_logic.py`](tests/test_main_logic.py) | 电脑端逻辑测试 |

应用打包配置只在 `code/` 内维护一份：以 `code/` 为应用目录，核对 `main.py`、`app.yaml` 和 `app.png`。仓库根目录没有应用入口。`code/dist/` 保留最新的 `maix-starrymoon-v1.0.2.zip` 作为已有安装包，但不保证包含当前源码的改动，交付前须重新打包。

## 运行环境与上板

- 目标设备：MaixCAM2，使用板端 MaixPy 的 `maix` 模块和 `cv2`。仓库未指定已验证的最低固件或库版本，首次运行时应记录设备上的实际版本。
- 开发电脑：使用 MaixVision 连接设备、运行脚本；电脑上的普通 Python 环境不能直接运行需要相机、显示器和 UART 的整份 `code/main.py`。
- 串口：程序将 A21 映射为 `UART4_TX`、A22 映射为 `UART4_RX`，打开 `/dev/ttyS4`，波特率为 115200。当前只发送数据；接线前核对板卡引脚、两端电平，并共地。

首次运行建议按以下顺序进行：

1. 固定相机和车体，确保画面能看到横线及其上方的竖向地标；先保持电机停止。
2. 在 MaixVision 中打开 [`code/main.py`](code/main.py)，停止旧程序后运行当前文件，确认控制台无初始化错误、显示画面持续更新。
3. 对照画面检查拟合线、`pos`、`head` 和 `count`；若显示 `line:lost` 或 `pixel:invalid`，先按[标定方案](docs/MaixCAM2参数实测与ROI标定方案.md)检查掩膜和 ROI。
4. 手推车辆验证计数与串口数据，再进行低速联调。修改文件顶部参数后，需要保存并重新运行程序。

完整的启动、接线和显示说明见 [`docs/main_README.md`](docs/main_README.md)；现场标定按 [`docs/MaixCAM2参数实测与ROI标定方案.md`](docs/MaixCAM2参数实测与ROI标定方案.md) 执行。

## UART 输出

每处理一帧发送一行 ASCII 文本，字段依次为 `valid,pos,head,count`，以英文逗号分隔，以 `\r\n` 结尾。例如：

```text
1,-12.5,3.2,2
0,0.0,0.0,2
```

`valid=1` 时，`pos` 和 `head` 分别为位置与方向的**像素误差**，`count` 是本次程序启动以来的累计地标数。`valid=0` 表示本帧横线无效，此时两个 `0.0` 只是占位值，不能作为居中结果。下位机应按行组包、处理接收超时，并根据累计计数自行计算任务阶段的通过数量；程序重启后计数从零开始。字段定义与异常细节见[串口协议说明](docs/main_README.md#7-结果字段与串口协议)。

## 电脑端检查

在项目根目录运行以下命令；逻辑测试需要电脑端已安装 `cv2` 和 `numpy`。这些检查不连接 MaixCAM2，也不模拟相机图像算法或实际串口。

```powershell
python -m unittest discover -s tests -v
python -c "import ast,pathlib; ast.parse(pathlib.Path('code/main.py').read_text(encoding='utf-8-sig')); print('syntax PASS')"
```

第二条命令预期输出 `syntax PASS`。上板前仍须完成光照、ROI、不同车姿、最高计划车速下的连续计数、串口超时与重新上电测试。当前地标若在被跟踪到离开窗口前完全丢失，计数锁定可能无法释放；联调时应重点检查遮挡和漏检场景。
