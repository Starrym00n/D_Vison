from maix import camera, display, image, uart, app ,err ,pinmap
import cv2, math

# 参数配置

# 分辨率
W = 320
H = 240

# 预处理参数
BINARY_THRESHOLD = 85
BLUR_KERNEL_SIZE = 5
MORPH_KERNEL_SIZE = 3
thresholds = [[0, 80, -120, -10, 0, 30]] # LAB阈值设定（待验证）

morph_kernel = cv2.getStructuringElement( cv2.MORPH_RECT,
(MORPH_KERNEL_SIZE, MORPH_KERNEL_SIZE),
) #？

Mark_trigger_x_ratio = 0.65
MARK_TRIGGER_HALF_WIDTH = 34
Mark_half_w = 34
mark_trigger_x = int(W * Mark_trigger_x_ratio) # 目标竖直线

MARK_MIN_AREA = 50  # 色块最小面积门限。
MARK_MIN_PIXELS = 35  # 色块最少有效白色像素数。
MARK_MIN_HEIGHT = 14  # 裁剪后色块外接框的最小高度，像素。
MARK_MAX_WIDTH = 28  # 色块外接框的最大宽度，像素。
MARK_MIN_ASPECT_RATIO = 1.8  # 最小高宽比，排除接近方形的干扰。
MAX_JUNCTION_GAP = 12  # 色块底部与横线的最大纵向距离，像素。
JUNCTION_CONFIRM_FRAMES = 3  # 连续满足交点条件的帧数。
# 横线有效且窗口连续无竖线时才解除锁定，短暂丢线不视为地标离开。
JUNCTION_RELEASE_FRAMES = 5

# 主 ROI 
M_ROI_X_RATIO = 0.05
M_ROI_Y_RATIO = 0.00
M_ROI_W_RATIO = 0.90
M_ROI_H_RATIO = 0.55

# 水平 ROI 
H_ROI_Y_RATIO = 0.48
H_ROI_H_RATIO = 0.35
MIN_V_ROI_HEIGHT = 24 # 竖线检测区域的最小高度，像素。
V_TO_LINE_GAP = 3

#像素门限
L_min_area = 100
L_min_pixels = 80
L_min_length = 60
MAX_H_slope = 0.45 # 最大斜率

# 反相阈值
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
Target_Y = 82.0
HEADING_SAMPLE_HALF_WIDTH = 60 # 左右采样点距触发中心的距离，像素。

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

while not app.need_exit():

    # 图像预处理
    img = cam.read()
    img_bgr = image.image2cv(img,ensure_bgr=True,copy=True)
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray,
        (BLUR_KERNEL_SIZE, BLUR_KERNEL_SIZE),
        0,
    )

    # 黑胶带反相为白色
    _, binary_cv = cv2.threshold(
        gray,
        BINARY_THRESHOLD,
        255,
        cv2.THRESH_BINARY_INV,
    )
    # 先闭运算填小缺口，再开运算去孤立噪点；大面积反光仍需现场调阈值。
    # 形态学处理 
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


        line = a
        length = length_temp
        
    if line is not None:
        line_dx = line.x2() - line.x1()
        line_dy = line.y2() - line.y1()

        # 将端点顺序不同造成的 180 度差异归一化到 (-90, 90] ?
        line_angle = math.degrees(math.atan2(line_dy, line_dx))
        if line_angle > 90.0:
            line_angle -= 180.0
        elif line_angle <= -90.0:
            line_angle += 180.0

         # 根据直线方程计算固定触发横坐标处的高度，避免端点位置变化影响误差
        line_y_at_trigger = line.y1() + ((mark_trigger_x - line.x1()) * line_dy / line_dx)

        # 采样点
        sample_x_left = max(
            main_left,
            mark_trigger_x - HEADING_SAMPLE_HALF_WIDTH,
        )
        sample_x_right = min(
            main_right - 1,
            mark_trigger_x + HEADING_SAMPLE_HALF_WIDTH,
        )

        line_y_left = line.y1() + (
            (sample_x_left - line.x1()) * line_dy / line_dx
        )
        line_y_right = line.y1() + (
            (sample_x_right - line.x1()) * line_dy / line_dx
        )

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

    # 裁切图片
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
    mark_in_window = False
    junction_x = 0
    junction_y = 0

    for b in blobs:
        if b.w() <= 0:
            continue
        if b.h() < MARK_MIN_HEIGHT or b.w() > MARK_MAX_WIDTH:
            continue
        if b.h() < b.w() * MARK_MIN_ASPECT_RATIO:
            continue

        trigger_distance = abs(b.cx() - mark_trigger_x)
        if trigger_distance > MARK_TRIGGER_HALF_WIDTH:
            continue
        mark_in_window = True
        if not line_pixel_valid:
            continue
        candidate_junction_y = int(
            line.y1() + (b.cx() - line.x1()) * line_dy / line_dx
        )
        if abs(b.y() + b.h() - candidate_junction_y) > MAX_JUNCTION_GAP:
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

    # 连续确认抑制单帧噪点；任何不满足交点条件的帧都会打断确认。
    if junction_candidate:
        junction_streak = min(junction_streak + 1, JUNCTION_CONFIRM_FRAMES)
    else:
        junction_streak = 0

    junction_confirmed = junction_streak >= JUNCTION_CONFIRM_FRAMES
    
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


