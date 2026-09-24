"""读取 main.py 配置，生成四张中文标定示意图；仅在电脑端运行。"""

import ast
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.text import Text
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
SOURCE = ROOT / "code/main.py"
TREE = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
P = {}
for node in TREE.body:
    if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
        try:
            P[node.targets[0].id] = ast.literal_eval(node.value)
        except (ValueError, TypeError):
            pass

W, H = P["W"], P["H"]
MORPH_OPERATIONS = [n.args[1].attr for n in ast.walk(TREE)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "morphologyEx" and len(n.args) > 1
                    and isinstance(n.args[1], ast.Attribute)]
MORPH_TEXT = "形态学：" + " → ".join(
    {"MORPH_CLOSE": "闭运算", "MORPH_OPEN": "开运算"}.get(op, op)
    for op in MORPH_OPERATIONS) if MORPH_OPERATIONS else "形态学操作当前未启用。"
MX, MY, MW, MH = [int(v * P[k]) for v, k in zip(
    [W, H, W, H], ["M_ROI_X_RATIO", "M_ROI_Y_RATIO", "M_ROI_W_RATIO", "M_ROI_H_RATIO"])]
HY, HH = MY + int(MH * P["H_ROI_Y_RATIO"]), int(MH * P["H_ROI_H_RATIO"])
CX, HALF = int(W * P["Mark_trigger_x_ratio"]), P["MARK_TRIGGER_HALF_WIDTH"]
TY, GAP = P["Target_Y"], P["V_TO_LINE_GAP"]
LEFT = max(MX, CX - P["HEADING_SAMPLE_HALF_WIDTH"])
RIGHT = min(MX + MW - 1, CX + P["HEADING_SAMPLE_HALF_WIDTH"])
GREEN, BLUE, RED, INK = "#167044", "#145DA0", "#AC254C", "#17324D"
DPI, PREVIEW_DPI = 200, 100
EXPORTS = []
STYLE = {"font.family": "Microsoft YaHei", "font.size": 12,
         "axes.unicode_minus": False, "svg.fonttype": "path",
         "text.color": INK, "axes.labelcolor": INK}


def page(number, title, subtitle, height=7.5):
    """创建有统一标题、页脚及留白的独立图页。"""
    fig = plt.figure(figsize=(12, height), facecolor="white")
    fig.text(.045, .94, f"{number}  /  {title}", fontsize=23, weight="bold")
    fig.text(.045, .895, subtitle, fontsize=11, color="#526373")
    fig.text(.045, .035, "MaixCAM2 · main.py 参数快照 · 示意图，非相机实拍或实测结果", fontsize=10)
    return fig


def note(fig, x, y, title, body, color=INK):
    """将短说明放到图外独立区域，避免遮挡测量对象。"""
    fig.text(x, y, title, fontsize=15, weight="bold", color=color, va="top")
    fig.text(x, y-.052, body, fontsize=12, linespacing=1.65, va="top")


def rectangle(ax, values, color, style="-", fill="none"):
    """绘制用线型和颜色共同区分的矩形。"""
    ax.add_patch(Rectangle(values[:2], *values[2:], edgecolor=color,
                           facecolor=fill, linewidth=2, linestyle=style))


def image_axes(fig, rect, title, xlim, ylim):
    """创建等比例图像坐标轴；y 向下，单位均为像素。"""
    ax = fig.add_axes(rect)
    ax.set(xlim=xlim, ylim=ylim, xlabel="x / 像素", ylabel="y / 像素")
    ax.set_aspect("equal")
    ax.set_title(title, loc="left", pad=14, fontsize=14, weight="bold")
    ax.grid(alpha=.12)
    ax.tick_params(labelsize=10)
    return ax


def export(fig, stem):
    """检查文字是否越出画布，并保存高清、矢量和阅读预览版本。"""
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    for artist in fig.findobj(match=Text):
        if artist.get_visible() and artist.get_text() and not artist.get_clip_on():
            extent = artist.get_window_extent(renderer)
            if not fig.bbox.contains(extent.x0, extent.y0) or not fig.bbox.contains(extent.x1, extent.y1):
                raise ValueError(f"文字越出画布: {artist.get_text()}")
    for ext in ("png", "svg"):
        fig.savefig(OUT / f"{stem}.{ext}", dpi=DPI, facecolor="white")
    svg = OUT / f"{stem}.svg"
    svg.write_text("\n".join(line.rstrip() for line in svg.read_text(encoding="utf-8").splitlines()) + "\n", encoding="utf-8")
    fig.savefig(OUT / f"{stem}_preview.png", dpi=PREVIEW_DPI, facecolor="white")
    EXPORTS.append({"stem": stem, "pixels": [round(v * DPI) for v in fig.get_size_inches()]})
    plt.close(fig)


def overview():
    """绘制全画幅与 ROI 的真实坐标比例，参数说明放在右栏。"""
    fig = page("01", "先确定在哪里检测", "全画幅 → 主 ROI → 横线 ROI → 触发窗口；右、下边界不包含。")
    ax = image_axes(fig, [.075, .22, .49, .60], "A  全画幅与水平横线示例", (0, W), (H, 0))
    ax.axhspan(MY+MH, H, color="#EEF1F4")
    rectangle(ax, (MX, MY, MW, MH), GREEN)
    rectangle(ax, (MX, HY, MW, HH), BLUE, "--", "#EAF2FA")
    rectangle(ax, (CX-HALF, MY, 2*HALF, TY-GAP-MY), RED, ":")
    ax.plot([MX, MX+MW-1], [TY, TY], color="#222222", lw=3)
    ax.plot([CX, CX], [MY+30, TY], color="#222222", lw=5)
    ax.axvline(CX, color=RED, ls="-.", lw=1)
    ax.scatter([LEFT, RIGHT], [TY, TY], marker="s", color="#986000", s=65, zorder=5)
    ax.text(28, 25, "主 ROI", color=GREEN)
    ax.text(28, HY+HH-6, "横线 ROI", color=BLUE, fontsize=11)
    ax.text(30, MH+35, "灰区：主 ROI 外\n检测掩膜中清零", fontsize=12)
    ax.set_xticks([0, 80, 160, 240, W])
    ax.set_yticks([0, HY, MY+MH, 180, H])
    note(fig, .62, .81, "① 主 ROI / 绿色实线", f"[{MX}, {MY}, {MW}, {MH}]\n比例以整幅 {W} × {H} 为基准。", GREEN)
    note(fig, .62, .64, "② 横线 ROI / 蓝色虚线", f"[{MX}, {HY}, {MW}, {HH}]\ny 比例、高度比例以主 ROI 为基准。", BLUE)
    note(fig, .62, .47, "③ 触发窗口 / 红色点线", f"中心 x={CX}，半宽 {HALF}\n色块中心范围：{CX-HALF} ≤ cx ≤ {CX+HALF}", RED)
    note(fig, .62, .30, "④ 两个方向采样点 / 方块", f"左 x={LEFT}；右 x={RIGHT}\n位置零点：Target_Y={TY:g}")
    fig.text(.075, .115, "窗口用于筛选色块中心；find_blobs 仍搜索整个动态 V_roi。", fontsize=12)
    export(fig, "maixcam2_roi_calibration")


def lab_ranges(fig):
    """显示当前六项阈值及各 LAB 通道完整刻度。"""
    limits = P["LAB_THRESHOLDS"][0]
    for i, (name, bounds) in enumerate(zip(("L / 亮度", "A / 绿—红", "B / 蓝—黄"), ((0, 100), (-128, 127), (-128, 127)))):
        low, high = limits[2*i:2*i+2]
        ax = fig.add_axes([.10, .725-.125*i, .46, .065])
        ax.set(xlim=bounds, ylim=(-1, 1), yticks=[], xticks=sorted(set([*bounds, low, high])))
        ax.axhline(0, color="#D8E0E7", linewidth=10)
        ax.plot([low, high], [0, 0], color=BLUE, linewidth=10, solid_capstyle="butt")
        ax.text(0, 1.22, f"{name}：[{low}, {high}]", transform=ax.transAxes, fontsize=12)
        ax.tick_params(axis="x", labelsize=10)
        for spine in ax.spines.values():
            spine.set_visible(False)


def mask_examples(fig):
    """绘制三种诊断概念图，不表示这些阈值产生的真实输出。"""
    titles = ["目标断裂：检查范围是否过窄", "目标完整：继续验证背景", "背景粘连：检查范围是否过宽"]
    for i, title in enumerate(titles):
        mask = np.zeros((64, 128), dtype=np.uint8)
        mask[44:49, 8:120] = 255
        mask[12:46, 80:85] = 255
        if i == 0:
            mask[:, 48:58] = 0
            mask[24:33, :] = 0
        elif i == 2:
            mask[20:45, 28:52] = 255
            mask[8:24, 78:110] = 255
        ax = fig.add_axes([.055+.32*i, .13, .28, .20])
        ax.imshow(mask, cmap="gray", vmin=0, vmax=255, interpolation="nearest")
        ax.set_title(title, fontsize=11, pad=10)
        ax.set_axis_off()


def lab_figure():
    """生成阈值标度、处理顺序和掩膜诊断图。"""
    fig = page("02", "LAB 标定：让目标留下，让背景退出", "范围条读取当前源码；下方掩膜为诊断概念图，不是算法实测输出。")
    lab_ranges(fig)
    note(fig, .62, .81, "六项范围必须按顺序填写", "[L下限, L上限, A下限, A上限,\n B下限, B上限]\n同一像素的三个通道需同时命中。")
    note(fig, .62, .57, "保持完整处理链", f"彩色高斯滤波（{P['BLUR_KERNEL_SIZE']} × {P['BLUR_KERNEL_SIZE']}）→ LAB 筛选\n→ 白色掩膜 → 形态学 → ROI 检测\n{MORPH_TEXT}")
    fig.text(.055, .405, "先采横线、竖线、背景；再看下面三类现象：", fontsize=13, weight="bold")
    mask_examples(fig)
    fig.text(.055, .085, "颜色相似的背景仍可能命中；阈值通过后，还要检查 ROI、形状与连续帧。", fontsize=11)
    export(fig, "maixcam2_lab_calibration")


def clipping_panel(fig):
    """逐列裁剪严格使用源码的 int、限幅及最大高度规则。"""
    ax = image_axes(fig, [.075, .57, .51, .28], "A  逐列裁剪：保留区不是矩形", (0, W), (MH+8, MY))
    xs = np.arange(MX, MX+MW)
    ys = 60 + .15*(xs-MX)
    cuts = np.clip(ys.astype(int)-GAP, MY, MY+MH)
    height = int(min(MH, max(P['MIN_V_ROI_HEIGHT'], max(cuts-MY))))
    ax.fill_between(xs, MY, cuts, color="#FBE5EB")
    ax.fill_between(xs, cuts, MY+MH, facecolor="#E7EBEF", edgecolor="#B5BDC5", hatch="///")
    rectangle(ax, (MX, MY, MW, height), RED, "--")
    ax.plot(xs, ys, color="#222222", lw=2, label="拟合横线")
    ax.plot(xs, cuts, color=RED, ls=":", lw=2, label="清零起点")
    ax.text(30, 22, "保留区", color=RED)
    ax.text(90, MH-7, "斜纹区：清零", fontsize=11)
    ax.legend(loc="upper right", fontsize=10)
    note(fig, .64, .835, "示例 y(x)=60+0.15(x−16)", f"cut_y = int(y(x)) − {GAP}\n再限制在主 ROI 上下边界内。\n左列 cut_y={cuts[0]}；右列={cuts[-1]}\nV_roi=[{MX},{MY},{MW},{height}]\n红色虚线：搜索包围矩形。")


def geometry_panels(fig):
    """分别放大色块尺寸和误差测量，保持各自坐标比例。"""
    ax = image_axes(fig, [.075, .21, .23, .24], "B  裁剪后色块 / 局部放大", (187, 237), (95, 25))
    rectangle(ax, (202, 40, 12, 39), RED, fill="#FBE5EB")
    ax.axhline(82, color="#222222", lw=2)
    ax.axhline(79, color=RED, ls=":")
    ax.annotate("", (202, 35), (214, 35), arrowprops={"arrowstyle": "<->"})
    ax.text(208, 31, "w=12", ha="center", fontsize=10)
    ax.annotate("", (221, 40), (221, 79), arrowprops={"arrowstyle": "<->"})
    ax.text(225, 60, "h=39", rotation=90, fontsize=10)
    ax.text(189, 90, "横线 y=82", fontsize=10)
    ax = image_axes(fig, [.43, .22, .50, .21], "C  位置与方向误差 / 局部放大", (130, 285), (105, 58))
    xs = np.array([140, 278])
    ys = 90+.15*(xs-CX)
    ax.plot(xs, ys, color=BLUE, lw=2.5)
    ax.axhline(TY, color=GREEN, ls="--")
    ax.scatter([LEFT, CX, RIGHT], [90+.15*(LEFT-CX), 90, 90+.15*(RIGHT-CX)], color=RED, zorder=5)
    ax.text(135, 72, f"参考线 y={TY:g}", color=GREEN, fontsize=11)
    ax.set_xticks([LEFT, CX, RIGHT])
    ax.set_yticks([65, TY, 99])
    fig.text(.075, .11, "示例底边 y+h=79；最后像素行 78\n间距 d=|79−82|=3；h/w=3.25", fontsize=11)
    fig.text(.43, .13, f"示例 y({CX})=90：pos=90−{TY:g}={90-TY:g} px\nhead=y({RIGHT})−y({LEFT})={.15*(RIGHT-LEFT):g} px；正负只表示图像方向。", fontsize=12)


def geometry_figure():
    """生成裁剪、色块和误差三幅分区示意图。"""
    fig = page("03", "先裁剪，再测量，最后判断交点", "A 使用合成斜线；B、C 是独立数值示例，不能当作同一帧或实测记录。", height=10)
    clipping_panel(fig)
    geometry_panels(fig)
    export(fig, "maixcam2_geometry_calibration")


def timing_values():
    """将合成输入送入源码中的纯计数片段，避免图表另写一套状态机。"""
    loop = next(n for n in TREE.body if isinstance(n, ast.While))
    start = next(i for i, n in enumerate(loop.body) if isinstance(n, ast.If) and isinstance(n.test, ast.Name) and n.test.id == 'junction_candidate')
    end = next(i for i, n in enumerate(loop.body) if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id == 'vision_result')
    fragment = ast.Module(body=loop.body[start:end], type_ignores=[])
    assert not any(isinstance(n, (ast.Import, ast.ImportFrom, ast.Attribute)) for n in ast.walk(fragment))
    code = compile(fragment, str(SOURCE), 'exec')
    state = {**P, '__builtins__': {'min': min}}
    state.update(junction_streak=0, junction_clear_streak=0, junction_count=0, junction_latched=False)
    inputs = [(1, 1, 1)]*4 + [(0, 0, 0)] + [(1, 0, 0)]*4 + [(0, 0, 0)] + [(1, 0, 0)]*5 + [(1, 1, 1)]*3
    keys = ['line_pixel_valid', 'mark_in_window', 'junction_candidate', 'junction_streak', 'junction_clear_streak', 'junction_latched', 'junction_event', 'junction_count']
    values = []
    for valid, window, candidate in inputs:
        state.update(line_pixel_valid=valid, mark_in_window=window, junction_candidate=candidate)
        exec(code, state)
        values.append([int(state[k]) for k in keys])
    return np.array(values).T


def timing_figure():
    """用逐帧数字表区分确认、锁定、丢线和连续清空。"""
    fig = page("04", "计数看连续帧，也看锁定状态", f"当前确认 {P['JUNCTION_CONFIRM_FRAMES']} 帧；解除 {P['JUNCTION_RELEASE_FRAMES']} 帧。合成输入逐帧执行源码计数逻辑。")
    values = timing_values()
    ax = fig.add_axes([.19, .31, .76, .49])
    ax.set(xlim=(.5, 18.5), ylim=(7.5, -.5), xticks=range(1, 19), yticks=range(8))
    ax.set_yticklabels(['横线有效', '窗口有竖线', '合格交点', '连续确认数', '连续清空数', '锁定', '本帧计数事件', '累计 count'])
    ax.tick_params(length=0, pad=10, labelsize=11)
    ax.set_xlabel("帧编号（间隔不代表固定毫秒数）", labelpad=12)
    for row in range(8):
        for col in range(18):
            value = values[row, col]
            face = '#DCEAF5' if value else '#F3F5F7'
            if row == 6 and value:
                face = '#F6D7DF'
            ax.add_patch(Rectangle((col+.5, row-.5), 1, 1, facecolor=face, edgecolor='white', lw=2))
            ax.text(col+1, row, str(value), ha='center', va='center', weight='bold' if row >= 6 else 'normal')
    for edge in [4.5, 5.5, 9.5, 10.5, 15.5]:
        ax.axvline(edge, color='#7C8D9E', linewidth=1)
    note(fig, .055, .205, "读第 3、10、15、18 帧", "第 3 帧计数并锁定；第 10 帧丢线打断清空；第 15 帧才解除锁定；第 18 帧再次计数。")
    fig.text(.055, .085, "窗口有形状合格竖线但交点不合格时，也会阻止解锁；这类情况需另做现场测试。", fontsize=11)
    export(fig, "maixcam2_timing_calibration")


def main():
    """导出图页和包含源码哈希、配置、导出尺寸的溯源清单。"""
    with plt.rc_context(STYLE):
        overview()
        lab_figure()
        geometry_figure()
        timing_figure()
    manifest = {'source': 'code/main.py', 'source_sha256': hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                'generated_by': str(Path(__file__).relative_to(ROOT)), 'generated_at': datetime.now(timezone.utc).isoformat(),
                'figure_type': 'synthetic schematic; not observed data', 'parameters': P,
                'morphology_operations': MORPH_OPERATIONS,
                'matplotlib_version': matplotlib.__version__, 'dpi': DPI, 'font': STYLE['font.family'],
                'svg_text': 'glyph paths', 'exports': EXPORTS, 'board_validation': 'not performed'}
    (OUT / 'maixcam2_roi_calibration_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"Exported {len(EXPORTS)} figures: PNG / SVG / preview; layout bounds PASS")


if __name__ == '__main__':
    main()
