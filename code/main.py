from maix import camera, display, image, uart, app ,err ,pinmap
import cv2, math

# 参数配置
# 图像初标：pictures/20260924181420.jpeg（320×240，固定支架后）

# 分辨率
W = 320
H = 240

# 预处理参数
# 横线与竖线特征共用 LAB 阈值：[L最小, L最大, A最小, A最大, B最小, B最大]。
# L 范围 0~100，A/B 范围 -128~127；本帧内部样本可分，保留现值；待测：原始帧及多光照。
LAB_THRESHOLDS = [[0, 56, -5, 14, -128, 12]]
BLUR_KERNEL_SIZE = 5  # 待测：对比不同奇数核的降噪效果与细线保留情况。
MORPH_KERNEL_SIZE = 3  # 待测：复核远处细竖线是否消失、相邻前景是否粘连。


morph_kernel = cv2.getStructuringElement( cv2.MORPH_RECT,
(MORPH_KERNEL_SIZE, MORPH_KERNEL_SIZE),
) #？

Mark_trigger_x_ratio = 0.65  # 待测：当前触发中心 x=208，需按实际计数位置标定。
MARK_TRIGGER_HALF_WIDTH = 34  # 待测：本帧竖线中心约 x=209 在窗口内，需结合车速和有效帧率验证。
Mark_half_w = 34  # 未使用：实际窗口半宽由 MARK_TRIGGER_HALF_WIDTH 控制。
mark_trigger_x = int(W * Mark_trigger_x_ratio) # 目标竖直线

MARK_MIN_AREA = 50  # 色块最小面积门限。待测：用最远、最小地标确定下限。
MARK_MIN_PIXELS = 35  # 色块最少有效白色像素数。待测：统计弱光、反光下的最小前景像素数。
MARK_MIN_HEIGHT = 14  # 裁剪后色块外接框的最小高度，像素。待测：复核最短地标裁剪后的高度。
MARK_MAX_WIDTH = 28  # 色块外接框的最大宽度，像素。待测：本帧离线裁剪后宽约 21 px，需复核近处最大宽度。
MARK_MIN_ASPECT_RATIO = 1.8  # 最小高宽比，排除接近方形的干扰。待测：检查极限姿态下的高宽比。
MAX_JUNCTION_GAP = 12  # 待测：本帧 V_TO_LINE_GAP=10 时离线间距约 10 px；现值保留，复核板端及倾斜姿态。
JUNCTION_CONFIRM_FRAMES = 3  # 连续满足交点条件的帧数。待测：结合有效帧率、窗口停留时间与误检记录验证。
# 跟踪到已计数地标移出窗口后，连续确认离开才解锁；漏检不等于离开。
JUNCTION_RELEASE_FRAMES = 5  # 待测：验证相邻地标之间有足够的窗口清空帧数，且不会重复计数。
MARK_MAX_STEP = 16  # 相邻帧允许的位置变化，像素；待按最高车速和帧率实测。
MARK_RELEASE_MARGIN = 4  # 离开窗口的额外余量，像素，防止边界抖动解锁。

# 主 ROI 
M_ROI_X_RATIO = 0.05  # 待测：本图左界 x=16 可用，需复核横向偏移极限。
M_ROI_Y_RATIO = 0.00  # 待测：本帧竖线延伸至画面顶部，保留现值，复核运动时的俯仰变化。
M_ROI_W_RATIO = 0.90  # 待测：本图宽 288 px 可用，需复核转弯时的目标覆盖。
M_ROI_H_RATIO = 0.55  # 待测：本图高 132 px 可用，需复核俯仰极限与车体干扰。

# 水平 ROI 
H_ROI_Y_RATIO = 0.425  # 图像初标：int(132×0.425)=56；横线可见带约 y=64~82，上方留约 8 px。待测：运动上界。
H_ROI_H_RATIO = 0.27  # 图像初标：int(132×0.27)=35，H_roi=[16,56,288,35]，保留至 y=90。待测：运动下界。
MIN_V_ROI_HEIGHT = 24 # 竖线检测区域的最小高度，像素。待测：检查裁剪后最短地标的覆盖。
V_TO_LINE_GAP = 10  # 图像初标：掩膜横线厚约 12~13 px，半厚向上取整 7 加 3 px 裕量。待测：板端残留与细线保留。

#像素门限
L_min_area = 100  # 待测：用最弱有效横线与背景干扰样本确定面积下限。
L_min_pixels = 80  # 待测：统计不同光照、遮挡下有效横线的最小前景像素数。
L_min_length = 60  # 待测：实际限制水平跨度 abs(dx)，需复核转弯、遮挡后的最短有效跨度。
MAX_H_slope = 0.45 # 最大斜率。待测：现值对应约 ±24.2°，需按实际最大转弯姿态验证。
LINE_SUPPORT_RADIUS = 3  # 三个误差采样点周围检查白像素的半径，像素。
LINE_MIN_SUPPORT_RATIO = 0.5  # 邻域白像素最小占比；待按胶带宽度实测。

# LAB 掩膜的白色前景阈值
BINARY_WHITE_THRESHOLDS = [[200, 255]]

# 主ROI列表
main_roi = [
    int(W * M_ROI_X_RATIO),
    int(H * M_ROI_Y_RATIO),
    int(W * M_ROI_W_RATIO),
    int(H * M_ROI_H_RATIO),
]

# 水平ROI列表
H_roi = [
    int(main_roi[0]),
    int(main_roi[1] + int(main_roi[3] * H_ROI_Y_RATIO)),
    int(main_roi[2]),
    int(main_roi[3] * H_ROI_H_RATIO)
]

# 标定水平横线
Target_Y = 73.0  # 待测：本帧离线 y(208)≈73.3 px；尚未确认理想巡线姿态，保留原零点，需板端正确拟合后多帧标零。
HEADING_SAMPLE_HALF_WIDTH = 60  # 待测：本帧 x=148、268 均落在横线跨度内；保留现值，复核极限姿态和拟合外推。

# 摄像头、串口设备初始化
cam = camera.Camera(W, H)
disp = display.Display()

# 改编自: https://wiki.sipeed.com/maixpy/doc/zh/peripheral/uart.html
err.check_raise(pinmap.set_pin_function("A21", "UART4_TX"), "UART4 TX mapping failed")
err.check_raise(pinmap.set_pin_function("A22", "UART4_RX"), "UART4 RX mapping failed")
serial_dev = uart.UART("/dev/ttyS4", 115200)

junction_streak = 0
junction_latched = False
junction_count = 0
junction_clear_streak = 0
junction_previous_xy = None
latched_x = None  # 已计数地标的最近可见位置；识别失败时保留，不推测其离开。

while not app.need_exit():

    # 图像预处理
    img = cam.read()
    img_bgr = image.image2cv(img,ensure_bgr=True,copy=True)
    img_bgr = cv2.GaussianBlur(img_bgr,
        (BLUR_KERNEL_SIZE, BLUR_KERNEL_SIZE),
        0,
    )

    # 改编自: https://wiki.sipeed.com/maixpy/api/maix/image.html#binary
    # 在 RGB 图上按 LAB 阈值提取横线和竖线特征，命中为白色，其余为黑色。
    color_img = image.cv2image(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB),bgr=False,copy=True)
    color_img = color_img.binary(LAB_THRESHOLDS)
    binary_cv = cv2.cvtColor(
        image.image2cv(color_img,ensure_bgr=False,copy=True), cv2.COLOR_RGB2GRAY,
    )
    # 先闭运算填小缺口，再开运算去孤立噪点；大面积反光仍需现场调阈值。
    # 形态学处理 ？
    binary_cv = cv2.morphologyEx(binary_cv, cv2.MORPH_CLOSE, morph_kernel)
    binary_cv = cv2.morphologyEx(binary_cv, cv2.MORPH_OPEN, morph_kernel)

    # 绘制主ROI区域
    main_left = main_roi[0]
    main_top = main_roi[1]
    main_right = main_roi[0] + main_roi[2]
    main_bottom = main_roi[1] + main_roi[3]

    # 清空主ROI外区域
    binary_cv[:main_top, :] = 0
    binary_cv[main_bottom:, :] = 0
    binary_cv[:, :main_left] = 0
    binary_cv[:, main_right:] = 0

    binary_img = image.cv2image(binary_cv,bgr=False,copy=True)

    # 查找直线
    lines = binary_img.get_regression(BINARY_WHITE_THRESHOLDS,
    roi = H_roi,
    x_stride = 1,
    y_stride = 1,
    area_threshold = L_min_area,
    pixels_threshold = L_min_pixels,
    robust = True)


    # 直线预先值
    line = None
    length = 0
    line_y_at_trigger = H_roi[1] + H_roi[3] // 2
    line_y_left = line_y_at_trigger
    line_y_right = line_y_at_trigger
    position_error_px = 0.0
    heading_error_px = 0.0
    line_pixel_valid = False
    sample_x_left = max(main_left, mark_trigger_x - HEADING_SAMPLE_HALF_WIDTH)
    sample_x_right = min(main_right - 1, mark_trigger_x + HEADING_SAMPLE_HALF_WIDTH)

    # 直线筛选与标定
    for a in lines:
        temp_dx = a.x2() - a.x1()
        temp_dy = a.y2() - a.y1()
        length_temp = a.length()

        if abs(temp_dx) < L_min_length:
            continue
        if abs(temp_dy) > abs(temp_dx) * MAX_H_slope:
            continue
        if length_temp <= length:
            continue
        # 关键采样点必须有实际白像素支持，不能仅凭拟合延长线输出控制误差。
        supported = True
        for sample_x in (sample_x_left, mark_trigger_x, sample_x_right):
            sample_y = round(a.y1() + (sample_x - a.x1()) * temp_dy / temp_dx)
            if not (main_left <= sample_x < main_right and main_top <= sample_y < main_bottom):
                supported = False
                break
            patch_top = max(main_top, sample_y - LINE_SUPPORT_RADIUS)
            patch_bottom = min(main_bottom, sample_y + LINE_SUPPORT_RADIUS + 1)
            patch_left = max(main_left, sample_x - LINE_SUPPORT_RADIUS)
            patch_right = min(main_right, sample_x + LINE_SUPPORT_RADIUS + 1)
            patch = binary_cv[patch_top:patch_bottom, patch_left:patch_right]
            if patch.size == 0 or patch.sum() < 255 * patch.size * LINE_MIN_SUPPORT_RATIO:
                supported = False
                break
        if not supported:
            continue
        line = a
        length = length_temp
        
    if line is not None:
        line_dx = line.x2() - line.x1()
        line_dy = line.y2() - line.y1()

        # 将端点顺序不同造成的 180 度差异归一化到 (-90, 90]
        line_angle = math.degrees(math.atan2(line_dy, line_dx))
        if line_angle > 90.0:
            line_angle -= 180.0
        elif line_angle <= -90.0:
            line_angle += 180.0

        # 根据直线方程计算固定触发横坐标处的高度，避免端点位置变化影响误差
        line_y_at_trigger = line.y1() + ((mark_trigger_x - line.x1()) * line_dy / line_dx)
        line_y_left = line.y1() + (sample_x_left - line.x1()) * line_dy / line_dx
        line_y_right = line.y1() + (sample_x_right - line.x1()) * line_dy / line_dx

        # 正负号只描述图像坐标方向；后续控制端需根据舵机方向决定取反与否。
        position_error_px = line_y_at_trigger - Target_Y
        heading_error_px = line_y_right - line_y_left
        line_pixel_valid = True

        img.draw_line(
            line.x1(), line.y1(), line.x2(), line.y2(), image.COLOR_BLUE, 2,
        )
        img.draw_rect(sample_x_left - 2, int(line_y_left) - 2, 4, 4, image.COLOR_GREEN, 1)
        img.draw_rect(sample_x_right - 2, int(line_y_right) - 2, 4, 4, image.COLOR_GREEN, 1)

    # 独立复制二值图，按 y(x) 屏蔽横线及其下方；不能用一个水平边界裁剪斜线。
    V_binary_cv = binary_cv.copy()
    V_roi_height = MIN_V_ROI_HEIGHT

    # 裁切图片 ？
    if line_pixel_valid:
        for column_x in range(main_left, main_right):
            line_y = line.y1() + (
                (column_x - line.x1()) * line_dy / line_dx
            )
            cut_y = max(main_top, min(int(line_y) - V_TO_LINE_GAP, main_bottom))
            V_binary_cv[cut_y:main_bottom, column_x] = 0
            V_roi_height = max(V_roi_height, cut_y - main_top)
    V_roi_height = min(V_roi_height, main_roi[3])

    # 竖线ROI
    V_roi = [main_roi[0], main_roi[1], main_roi[2], V_roi_height]
    V_binary_img = image.cv2image(V_binary_cv,bgr=False,copy=True)

    # 寻找色块
    blobs = V_binary_img.find_blobs (
    BINARY_WHITE_THRESHOLDS,
    roi = V_roi,
    x_stride=1,
    y_stride=1,
    area_threshold=MARK_MIN_AREA,
    pixels_threshold=MARK_MIN_PIXELS,
    merge=True,
    margin=2,
    )

    blob = None
    blob_distance = W
    tracked_x = None
    track_distance = MARK_MAX_STEP + 1
    junction_x = 0
    junction_y = 0

    for b in blobs:
        if b.w() <= 0 or not line_pixel_valid:
            continue
        candidate_junction_y = int(line.y1() + (b.cx() - line.x1()) * line_dy / line_dx)
        if abs(b.y() + b.h() - candidate_junction_y) > MAX_JUNCTION_GAP:
            continue
        # 已计数目标按就近位置跟踪，允许暂时变宽/变矮；悬空干扰不参与。
        if junction_latched and abs(b.cx() - latched_x) < track_distance:
            tracked_x = b.cx()
            track_distance = abs(b.cx() - latched_x)
        if b.h() < MARK_MIN_HEIGHT or b.w() > MARK_MAX_WIDTH:
            continue
        if b.h() < b.w() * MARK_MIN_ASPECT_RATIO:
            continue
        trigger_distance = abs(b.cx() - mark_trigger_x)
        if trigger_distance > MARK_TRIGGER_HALF_WIDTH:
            continue
        if trigger_distance >= blob_distance:
            continue

        blob = b
        blob_distance = trigger_distance
        junction_x = b.cx()
        junction_y = candidate_junction_y

    # 绘制色块
    junction_candidate = blob is not None
    if blob is not None :
        img.draw_rect(
            blob.x(), blob.y(), blob.w(), blob.h(), image.COLOR_RED, 2,
        )

    # 位置连续才累计确认；候选跳变从当前帧重新计起，中断则清零。
    if junction_candidate:
        if junction_previous_xy is not None and max(abs(junction_x - junction_previous_xy[0]),
                                                   abs(junction_y - junction_previous_xy[1])) <= MARK_MAX_STEP:
            junction_streak = min(junction_streak + 1, JUNCTION_CONFIRM_FRAMES)
        else:
            junction_streak = 1
        junction_previous_xy = (junction_x, junction_y)
    else:
        junction_streak = 0
        junction_previous_xy = None

    junction_confirmed = junction_streak >= JUNCTION_CONFIRM_FRAMES
    
    junction_event = False
    if junction_confirmed and not junction_latched:
        junction_event = True
        junction_count += 1
        junction_latched = True
        latched_x = junction_x

    if tracked_x is not None:
        latched_x = tracked_x
    # 只依据旧地标已观测到的出窗位置解锁；在窗内失踪时宁可保持锁定。
    if (junction_latched and line_pixel_valid
            and abs(latched_x - mark_trigger_x)
            > MARK_TRIGGER_HALF_WIDTH + MARK_RELEASE_MARGIN):
        junction_clear_streak = min(junction_clear_streak + 1, JUNCTION_RELEASE_FRAMES)
    else:
        junction_clear_streak = 0
    if junction_clear_streak >= JUNCTION_RELEASE_FRAMES:
        junction_latched = False
        latched_x = None

    # 丢线时误差无效，不能把占位值 0 当作居中；角度单位为度，误差为像素。
    # 已计数地标若未被观测到出窗就完全消失，将保持锁定，需现场验证遮挡场景。
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
    img.draw_rect(*H_roi, image.COLOR_BLUE, 1)
    img.draw_rect(*V_roi, image.COLOR_RED, 1)
    img.draw_line(
        main_left, int(Target_Y), main_right - 1, int(Target_Y), image.COLOR_GREEN, 1,
    )
    img.draw_rect(
        mark_trigger_x - MARK_TRIGGER_HALF_WIDTH, V_roi[1], MARK_TRIGGER_HALF_WIDTH * 2, V_roi[3], image.COLOR_RED, 1,
    )

    # 底部显示：位置/方向误差、角度、交点状态/累计次数/锁定状态。
    if line is not None:
        img.draw_string(
            2,
            H - 38,
            "angle:{:.1f} rho:{}".format(line_angle, line.rho()),
            image.COLOR_BLUE,
        )
    else:
        img.draw_string(2, H - 38, "line:lost", image.COLOR_RED)

    img.draw_string(
        2,
        H - 56,
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
        H - 20,
        "mark:{} count:{} lock:{}".format(
            int(junction_confirmed), junction_count, int(junction_latched)
        ),
        image.COLOR_GREEN if junction_confirmed else image.COLOR_RED,
    )

    disp.show(img)

# 用户正常退出时释放串口；异常停止时下位机依靠接收超时停止使用旧数据。
serial_dev.close()
