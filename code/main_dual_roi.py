"""MaixCAM2 单主 ROI、双子 ROI 黑线识别脚本。

主 ROI 负责排除车体与画面边缘干扰；横向子 ROI 用于道路线回归，
竖向子 ROI 用于寻找库边线。每帧更新 vision_result 并显示识别结果，
通过 UART4 逐帧发送视觉数据，PID 和泊车动作由下位机处理。
协议：valid,pos,head,count\r\n（ASCII），逗号分隔，换行结束，不附加校验。
pos/head 单位为像素；valid=0 时发送 0.0 占位，下位机必须忽略误差。
按换行重组完整数据行，要求恰好 4 个字段；连接后的首个残缺行应丢弃。
count 是视觉进程累计值，阶段切换时不清零；视觉端不接收阶段或复位命令。
下位机在启动/恢复巡线后，以收到的第一条新完整数据行记录 base_count。
本阶段计数 = count - base_count；建立基准的这一帧不作为新地标事件。
泊车期间下位机仍应持续接收，但不使用计数触发动作；恢复时重新记录基准。
例如恢复时 base_count=7，之后 count=10，表示本阶段新增 3 次交点确认。
视觉进程重启会清零；发现 count 下降时，下位机应重新同步，不能计算负增量。
每帧发送一次，周期随处理速度变化；下位机可记录接收间隔供 PID 使用。
单向发送无 ACK，写入成功不代表对端收到；下位机需检测超时并停止使用旧误差。
MaixCAM2 接线：A21(TX) 接对端 RX，GND 共地；实际接线与参数需板端验证。
"""

import math

import cv2
from maix import app, camera, display, err, image, pinmap, uart


# 相机输出直接转换为 OpenCV BGR 图；分辨率升高会提高远端胶带分辨率，
# 但也会增加 OpenCV CPU 开销，640x480 方案需在目标板另行测试。
FRAME_WIDTH = 320
FRAME_HEIGHT = 240

# 黑胶带二值化起始参数。阈值越高越容易包含阴影，越低越容易因反光断裂。
BINARY_THRESHOLD = 85
BLUR_KERNEL_SIZE = 5  # 高斯核边长，正奇数；过大会模糊细线。
MORPH_KERNEL_SIZE = 3  # 形态学核边长；用于连接小缺口和去除孤立噪点。

# 主 ROI 使用画面比例定义，避免后续调整分辨率时完全重写坐标。
MAIN_ROI_X_RATIO = 0.05  # 左边界 / 图像宽度。
MAIN_ROI_Y_RATIO = 0.00  # 上边界 / 图像高度。
MAIN_ROI_W_RATIO = 0.90  # 区域宽度 / 图像宽度。
MAIN_ROI_H_RATIO = 0.55  # 区域高度 / 图像高度。

# 横线位于主 ROI 中下部；竖线检测图按本帧横线逐列裁剪。
HORIZONTAL_ROI_Y_RATIO = 0.48  # 相对主 ROI 顶部的偏移 / 主 ROI 高度。
HORIZONTAL_ROI_H_RATIO = 0.35  # 横线检测带高度 / 主 ROI 高度。
MIN_VERTICAL_ROI_HEIGHT = 24  # 竖线检测区域的最小高度，像素。
VERTICAL_TO_LINE_GAP = 3  # 竖线 ROI 在横线上方预留的间隔，像素。

# 黄色圈选竖线预计经过画面约 65% 宽度处，以窗口而非单像素触发。
MARK_TRIGGER_X_RATIO = 0.65  # 触发中心 / 整幅图宽，当前对应 x=208。
MARK_TRIGGER_HALF_WIDTH = 34  # 色块中心距触发中心的最大距离，像素。

# 视觉层直接输出像素误差，不在本文件中计算 PID 或驱动执行机构。
# TARGET_LINE_Y 来自现有实拍图的起始标定，安装位置变化后必须重新测量。
TARGET_LINE_Y = 82.0  # 理想车位姿下，横线在触发中心处的 y 坐标。
HEADING_SAMPLE_HALF_WIDTH = 60  # 左右采样点距触发中心的距离，像素。

# 这些像素门限仅是 320x240 的起始值，必须根据实车图像重新标定。
LINE_MIN_AREA = 100  # 回归区域的最小面积门限。
LINE_MIN_PIXELS = 80  # 回归所需的最少有效白色像素数。
LINE_MIN_LENGTH = 60  # 实际限制端点水平跨度 |x2-x1|，单位像素。
MAX_HORIZONTAL_SLOPE = 0.45  # 最大 |dy/dx|，排除接近竖直的候选线。

MARK_MIN_AREA = 50  # 色块最小面积门限。
MARK_MIN_PIXELS = 35  # 色块最少有效白色像素数。
MARK_MIN_HEIGHT = 14  # 裁剪后色块外接框的最小高度，像素。
MARK_MAX_WIDTH = 28  # 色块外接框的最大宽度，像素。
MARK_MIN_ASPECT_RATIO = 1.8  # 最小高宽比，排除接近方形的干扰。
MAX_JUNCTION_GAP = 12  # 色块底部与横线的最大纵向距离，像素。
JUNCTION_CONFIRM_FRAMES = 3  # 连续满足交点条件的帧数。
# 横线有效且窗口连续无竖线时才解除锁定，短暂丢线不视为地标离开。
JUNCTION_RELEASE_FRAMES = 5

# OpenCV 二值图中黑胶带已被反相为白色，因此 MaixPy 检测白色像素。
BINARY_WHITE_THRESHOLDS = [[200, 255]]
UART_DEVICE = "/dev/ttyS4"
UART_BAUDRATE = 115200  # 默认 8 数据位、无奇偶校验、1 停止位。

# ROI 格式为 [左上角 x, 左上角 y, 宽, 高]，右/下边界不含在区域内。
main_roi = [
    int(FRAME_WIDTH * MAIN_ROI_X_RATIO),
    int(FRAME_HEIGHT * MAIN_ROI_Y_RATIO),
    int(FRAME_WIDTH * MAIN_ROI_W_RATIO),
    int(FRAME_HEIGHT * MAIN_ROI_H_RATIO),
]

horizontal_roi = [
    main_roi[0],
    main_roi[1] + int(main_roi[3] * HORIZONTAL_ROI_Y_RATIO),
    main_roi[2],
    int(main_roi[3] * HORIZONTAL_ROI_H_RATIO),
]

mark_trigger_x = int(FRAME_WIDTH * MARK_TRIGGER_X_RATIO)
morph_kernel = cv2.getStructuringElement(
    cv2.MORPH_RECT,
    (MORPH_KERNEL_SIZE, MORPH_KERNEL_SIZE),
)

cam = camera.Camera(FRAME_WIDTH, FRAME_HEIGHT, image.Format.FMT_BGR888)
disp = display.Display()
# 改编自: https://wiki.sipeed.com/maixpy/doc/zh/peripheral/uart.html
err.check_raise(pinmap.set_pin_function("A21", "UART4_TX"), "UART4 TX mapping failed")
err.check_raise(pinmap.set_pin_function("A22", "UART4_RX"), "UART4 RX mapping failed")
serial_dev = uart.UART(UART_DEVICE, UART_BAUDRATE)

junction_streak = 0  # 当前连续交点候选帧数。
junction_clear_streak = 0  # 横线有效且窗口无竖线的连续帧数。
junction_latched = False  # 已计数的地标保持锁定，防止每帧重复计数。
junction_count = 0  # 仅进程启动时清零；阶段计数由下位机减去基准得到。

while not app.need_exit():
    img = cam.read()

    # 使用安全的复制方式转换，避免 OpenCV 数组与 MaixPy 图像生命周期不一致。
    frame_bgr = image.image2cv(img, ensure_bgr=True, copy=True)
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(
        gray,
        (BLUR_KERNEL_SIZE, BLUR_KERNEL_SIZE),
        0,
    )

    # 黑胶带反相为白色，便于后续对二值图寻找白色 blob 和回归线。
    _, binary_cv = cv2.threshold(
        gray,
        BINARY_THRESHOLD,
        255,
        cv2.THRESH_BINARY_INV,
    )
    # 先闭运算填小缺口，再开运算去孤立噪点；大面积反光仍需现场调阈值。
    binary_cv = cv2.morphologyEx(binary_cv, cv2.MORPH_CLOSE, morph_kernel)
    binary_cv = cv2.morphologyEx(binary_cv, cv2.MORPH_OPEN, morph_kernel)

    # 主 ROI 外全部清零，防止车轮、车架、电线和场地外物体参与计算。
    main_left = main_roi[0]
    main_top = main_roi[1]
    main_right = main_roi[0] + main_roi[2]
    main_bottom = main_roi[1] + main_roi[3]
    binary_cv[:main_top, :] = 0
    binary_cv[main_bottom:, :] = 0
    binary_cv[:, :main_left] = 0
    binary_cv[:, main_right:] = 0

    binary_img = image.cv2image(binary_cv, bgr=False, copy=True)

    # 在窄横带中拟合道路/库口横线，避免竖向库边线主导回归结果。
    lines = binary_img.get_regression(
        BINARY_WHITE_THRESHOLDS,
        roi=horizontal_roi,
        x_stride=1,
        y_stride=1,
        area_threshold=LINE_MIN_AREA,
        pixels_threshold=LINE_MIN_PIXELS,
        robust=True,
    )

    # 每帧清空旧结果；找不到横线时，默认高度仅用于显示/构造 ROI。
    selected_line = None
    selected_line_length = 0
    line_angle = 0.0
    line_y_at_trigger = horizontal_roi[1] + horizontal_roi[3] // 2
    line_y_left = line_y_at_trigger
    line_y_right = line_y_at_trigger
    position_error_px = 0.0
    heading_error_px = 0.0
    line_pixel_valid = False

    # 先检查水平跨度和斜率，再选最长候选；跨度检查同时避免后续除零。
    for candidate in lines:
        line_dx = candidate.x2() - candidate.x1()
        line_dy = candidate.y2() - candidate.y1()
        candidate_length = candidate.length()

        if abs(line_dx) < LINE_MIN_LENGTH:
            continue
        if abs(line_dy) > abs(line_dx) * MAX_HORIZONTAL_SLOPE:
            continue
        if candidate_length <= selected_line_length:
            continue

        selected_line = candidate
        selected_line_length = candidate_length

    if selected_line is not None:
        line_dx = selected_line.x2() - selected_line.x1()
        line_dy = selected_line.y2() - selected_line.y1()
        # 将端点顺序不同造成的 180 度差异归一化到 (-90, 90]。
        line_angle = math.degrees(math.atan2(line_dy, line_dx))
        if line_angle > 90.0:
            line_angle -= 180.0
        elif line_angle <= -90.0:
            line_angle += 180.0
        # 根据直线方程计算固定触发横坐标处的高度，避免端点位置变化影响误差。
        line_y_at_trigger = selected_line.y1() + (
            (mark_trigger_x - selected_line.x1()) * line_dy / line_dx
        )

        # 固定宽度取样可避免检测线段长度变化导致航向误差尺度漂移。
        sample_x_left = max(
            main_left,
            mark_trigger_x - HEADING_SAMPLE_HALF_WIDTH,
        )
        sample_x_right = min(
            main_right - 1,
            mark_trigger_x + HEADING_SAMPLE_HALF_WIDTH,
        )
        line_y_left = selected_line.y1() + (
            (sample_x_left - selected_line.x1()) * line_dy / line_dx
        )
        line_y_right = selected_line.y1() + (
            (sample_x_right - selected_line.x1()) * line_dy / line_dx
        )

        # 正负号只描述图像坐标方向；后续控制端需根据舵机方向决定取反与否。
        position_error_px = line_y_at_trigger - TARGET_LINE_Y
        heading_error_px = line_y_right - line_y_left
        line_pixel_valid = True

        img.draw_line(
            selected_line.x1(), selected_line.y1(), selected_line.x2(), selected_line.y2(), image.COLOR_BLUE, 2,
        )
        img.draw_rect(sample_x_left - 2, int(line_y_left) - 2, 4, 4, image.COLOR_GREEN, 1)
        img.draw_rect(sample_x_right - 2, int(line_y_right) - 2, 4, 4, image.COLOR_GREEN, 1)

    # 独立复制二值图，按 y(x) 屏蔽横线及其下方；不能用一个水平边界裁剪斜线。
    vertical_binary_cv = binary_cv.copy()
    vertical_roi_height = MIN_VERTICAL_ROI_HEIGHT
    if line_pixel_valid:
        for column_x in range(main_left, main_right):
            line_y = selected_line.y1() + (
                (column_x - selected_line.x1()) * line_dy / line_dx
            )
            cut_y = max(main_top, min(int(line_y) - VERTICAL_TO_LINE_GAP, main_bottom))
            vertical_binary_cv[cut_y:main_bottom, column_x] = 0
            vertical_roi_height = max(vertical_roi_height, cut_y - main_top)
    vertical_roi_height = min(vertical_roi_height, main_roi[3])
    # 矩形 ROI 仅包住裁剪后的有效区域，实际下边界已随横线倾斜。
    vertical_roi = [main_roi[0], main_roi[1], main_roi[2], vertical_roi_height]
    vertical_binary_img = image.cv2image(vertical_binary_cv, bgr=False, copy=True)
    blobs = vertical_binary_img.find_blobs(
        BINARY_WHITE_THRESHOLDS,
        roi=vertical_roi,
        x_stride=1,
        y_stride=1,
        area_threshold=MARK_MIN_AREA,
        pixels_threshold=MARK_MIN_PIXELS,
        merge=True,
        margin=2,
    )

    selected_blob = None
    selected_blob_distance = FRAME_WIDTH
    mark_in_window = False  # 即使未通过交点判断，窗口内竖线仍阻止解除计数锁定。
    junction_x = 0
    junction_y = 0

    # 先检查形状、窗口和交点间隔，再在合格候选中选最近者。
    for blob in blobs:
        if blob.w() <= 0:
            continue
        if blob.h() < MARK_MIN_HEIGHT or blob.w() > MARK_MAX_WIDTH:
            continue
        if blob.h() < blob.w() * MARK_MIN_ASPECT_RATIO:
            continue

        trigger_distance = abs(blob.cx() - mark_trigger_x)
        if trigger_distance > MARK_TRIGGER_HALF_WIDTH:
            continue
        mark_in_window = True
        if not line_pixel_valid:
            continue
        candidate_junction_y = int(
            selected_line.y1() + (blob.cx() - selected_line.x1()) * line_dy / line_dx
        )
        if abs(blob.y() + blob.h() - candidate_junction_y) > MAX_JUNCTION_GAP:
            continue
        if trigger_distance >= selected_blob_distance:
            continue

        selected_blob = blob
        selected_blob_distance = trigger_distance
        junction_x = blob.cx()
        junction_y = candidate_junction_y

    junction_candidate = selected_blob is not None
    if junction_candidate:
        img.draw_rect(
            selected_blob.x(), selected_blob.y(), selected_blob.w(), selected_blob.h(), image.COLOR_RED, 2,
        )

    # 连续确认抑制单帧噪点；任何不满足交点条件的帧都会打断确认。
    if junction_candidate:
        junction_streak = min(junction_streak + 1, JUNCTION_CONFIRM_FRAMES)
    else:
        junction_streak = 0

    junction_confirmed = junction_streak >= JUNCTION_CONFIRM_FRAMES

    # event 只在确认首帧为 True；count 全程累计，包括泊车期间确认的交点。
    # 阶段切换不重置锁定状态，避免仍在窗口内的同一地标因切换阶段重复计数。
    junction_event = False
    if junction_confirmed and not junction_latched:
        junction_event = True
        junction_count += 1
        junction_latched = True

    # 丢线或仍有竖线时不解除锁定，防止一次短暂识别失败造成重复计数。
    if line_pixel_valid and not mark_in_window:
        junction_clear_streak = min(
            junction_clear_streak + 1, JUNCTION_RELEASE_FRAMES
        )
    else:
        junction_clear_streak = 0
    if junction_clear_streak >= JUNCTION_RELEASE_FRAMES:
        junction_latched = False

    # 丢线时误差无效，不能把占位值 0 当作居中；角度单位为度，误差为像素。
    # 计数仅按窗口进入/离开去重，长时间遮挡后重现仍可能被当成新地标。
    vision_result = {
        "line_valid": line_pixel_valid,
        "position_error_px": position_error_px if line_pixel_valid else None,
        "heading_error_px": heading_error_px if line_pixel_valid else None,
        "line_angle_deg": line_angle if line_pixel_valid else None,
        "junction_confirmed": junction_confirmed,
        "junction_event": junction_event,
        "junction_count": junction_count,
        "junction_xy": (junction_x, junction_y) if junction_confirmed else None,
    }

    # 第四字段始终发送累计值，不能改为阶段差值；阶段管理完全由下位机负责。
    # 示例：1,-12.5,3.2,2；丢线时仍发送 0,0.0,0.0,2，避免沿用旧误差。
    packet = "{},{:.1f},{:.1f},{}\r\n".format(
        int(line_pixel_valid),
        position_error_px if line_pixel_valid else 0.0,
        heading_error_px if line_pixel_valid else 0.0,
        junction_count,
    )
    # UART 边界失败立即报错退出，避免显示正常却已停止通信；不盲目重发残帧。
    try:
        written = serial_dev.write_str(packet)
        if written != len(packet):
            raise OSError("UART incomplete write: {}/{}".format(written, len(packet)))
    except Exception:
        serial_dev.close()
        raise

    if junction_confirmed:
        img.draw_rect(junction_x - 4, junction_y - 4, 8, 8, image.COLOR_RED, 2)

    # 绿色为主 ROI，蓝色为横线 ROI，红色为竖线 ROI 和触发窗口。
    img.draw_rect(*main_roi, image.COLOR_GREEN, 1)
    img.draw_rect(*horizontal_roi, image.COLOR_BLUE, 1)
    img.draw_rect(*vertical_roi, image.COLOR_RED, 1)
    img.draw_line(
        main_left, int(TARGET_LINE_Y), main_right - 1, int(TARGET_LINE_Y), image.COLOR_GREEN, 1,
    )
    img.draw_rect(
        mark_trigger_x - MARK_TRIGGER_HALF_WIDTH, vertical_roi[1], MARK_TRIGGER_HALF_WIDTH * 2, vertical_roi[3], image.COLOR_RED, 1,
    )

    # 底部显示：位置/方向误差、角度、交点状态/累计次数/锁定状态。
    if selected_line is not None:
        img.draw_string(
            2,
            FRAME_HEIGHT - 38,
            "angle:{:.1f} rho:{}".format(line_angle, selected_line.rho()),
            image.COLOR_BLUE,
        )
    else:
        img.draw_string(2, FRAME_HEIGHT - 38, "line:lost", image.COLOR_RED)

    img.draw_string(
        2,
        FRAME_HEIGHT - 56,
        "pos:{:.1f}px head:{:.1f}px".format(
            position_error_px,
            heading_error_px,
        )
        if line_pixel_valid
        else "pixel:invalid",
        image.COLOR_GREEN if line_pixel_valid else image.COLOR_RED,
    )

    img.draw_string(
        2,
        FRAME_HEIGHT - 20,
        "mark:{} count:{} lock:{}".format(
            int(junction_confirmed), junction_count, int(junction_latched)
        ),
        image.COLOR_GREEN if junction_confirmed else image.COLOR_RED,
    )

    disp.show(img)

# 用户正常退出时释放串口；异常停止时下位机依靠接收超时停止使用旧数据。
serial_dev.close()
