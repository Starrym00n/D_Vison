from maix import camera, display, image, uart, app ,err ,pinmap ,uart
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
mark_trigger_x = int(W * H) #?

# 主 ROI 
M_ROI_X_RATIO = 0.05
M_ROI_Y_RATIO = 0.00
M_ROI_W_RATIO = 0.90
M_ROI_H_RATIO = 0.55

# 水平 ROI 
H_ROI_Y_RATIO = 0.48
H_ROI_H_RATIO = 0.35
MIN_V_ROI_HEIGHT = 24
V_TO_LINE_GAP = 3

#像素门限
L_min_area = 100
L_min_pixels = 80
L_min_length = 60
MAX_H_slope = 0.45

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
H_ROI = [
    int(main_roi[0]),
    int(main_roi[1] + int(main_roi[3] * H_ROI_Y_RATIO)),
    int(main_roi[2]),
    int(main_roi[3] * H_ROI_H_RATIO)
]

# 标定水平横线
Target_Y = 82.0

# 摄像头、串口设备初始化
cam = camera.Camera(W, H)
disp = display.Display()

# 改编自: https://wiki.sipeed.com/maixpy/doc/zh/peripheral/uart.html
err.check_raise(pinmap.set_pin_function("A21", "UART4_TX"), "UART4 TX mapping failed")
err.check_raise(pinmap.set_pin_function("A22", "UART4_RX"), "UART4 RX mapping failed")
serial_dev = uart.UART("/dev/ttyS4", 115200)


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
    lines = img.get_regression(BINARY_WHITE_THRESHOLDS, 
    roi = H_ROI,
    x_stride = 1,
    y_stride = 1,
    area_threshold = L_min_area,
    pixels_threshold = L_min_pixels,
    robust = True)


    # 直线预先值
    line = None
    length = 0


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



    blobs = img.find_blobs(thresholds, pixels_threshold=500)  
    
    # 竖线ROI
    V_ROI = {
    
    }


    # 色块标定
    for blob in blobs:
        img.draw_rect(blob[0], blob[1], blob[2], blob[3], image.COLOR_RED)

    # 串口通讯
    content = ""

    disp.show(img)


