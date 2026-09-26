"""在电脑端执行 main.py 的实际逻辑片段；不模拟 MaixPy 图像算法或硬件。"""

import ast
import math
import unittest
from pathlib import Path
from unittest.mock import Mock

import cv2
import numpy as np

SOURCE = Path(__file__).resolve().parents[1] / "code/main.py"
TREE = ast.parse(SOURCE.read_text(encoding="utf-8-sig"))
LOOP = next(node for node in TREE.body if isinstance(node, ast.While))


def assignment_index(nodes, name):
    """定位生产源码赋值，源码结构改变时显式失败，避免测试旧逻辑。"""
    return next(i for i, node in enumerate(nodes)
                if isinstance(node, ast.Assign)
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == name)


def fragment(nodes, start, end):
    """编译指定边界之间的原始 AST，保留源码行号。"""
    return compile(ast.Module(body=nodes[start:end], type_ignores=[]),
                   str(SOURCE), "exec")


CONFIG = fragment(TREE.body, 2, assignment_index(TREE.body, "cam"))
INITIAL = fragment(TREE.body, assignment_index(TREE.body, "junction_streak"),
                   TREE.body.index(LOOP))
GEOMETRY = fragment(LOOP.body, assignment_index(LOOP.body, "line"),
                    assignment_index(LOOP.body, "V_binary_cv"))
COUNTING = fragment(LOOP.body, assignment_index(LOOP.body, "blob"),
                    assignment_index(LOOP.body, "packet"))
PACKET_START = assignment_index(LOOP.body, "packet")
SENDING = fragment(LOOP.body, PACKET_START, PACKET_START + 2)


def make_line(x1=16, y1=73, x2=303, y2=73):
    """提供可控的回归结果；不声称复现 get_regression。"""
    return Mock(**{f"{key}.return_value": value for key, value in {
        "x1": x1, "y1": y1, "x2": x2, "y2": y2,
        "length": math.hypot(x2 - x1, y2 - y1),
    }.items()})


def make_blob(cx, width=10, height=60, bottom=63):
    """提供已通过 find_blobs 前置门限的合成色块。"""
    return Mock(**{f"{key}.return_value": value for key, value in {
        "cx": cx, "x": cx - width // 2, "y": bottom - height,
        "w": width, "h": height,
    }.items()})


class MainLogicTests(unittest.TestCase):
    """覆盖误差、候选连续性、锁定恢复和 UART 失败边界。"""

    def setUp(self):
        """只加载配置与纯状态，不导入会初始化设备的 main.py。"""
        self.state = {"cv2": cv2, "math": math, "img": Mock()}
        self.state["image"] = Mock()
        exec(CONFIG, self.state)
        exec(INITIAL, self.state)
        self.state.update(main_left=16, main_right=304, main_top=0,
                          main_bottom=132, line=make_line(), line_dx=287,
                          line_dy=0, line_angle=0, position_error_px=0,
                          heading_error_px=0)

    def frame(self, *positions, valid=True, blobs=None):
        """推进一帧真实候选筛选和状态机，返回本帧结果。"""
        self.state.update(line_pixel_valid=valid,
                          blobs=blobs if blobs is not None else
                          [make_blob(x) for x in positions])
        exec(COUNTING, self.state)
        return self.state["vision_result"]

    def latch(self):
        """以连续三个同位置地标建立已计数状态。"""
        for _ in range(3):
            self.frame(208)
        self.assertEqual(self.state["junction_count"], 1)

    def test_confirm_and_stay_counts_once(self):
        """前两帧不计数，第三帧计数，停留不重复。"""
        self.assertFalse(self.frame(208)["junction_event"])
        self.assertFalse(self.frame(208)["junction_event"])
        self.assertTrue(self.frame(208)["junction_event"])
        for _ in range(20):
            self.assertFalse(self.frame(208)["junction_event"])
        self.assertEqual(self.state["junction_count"], 1)

    def test_candidate_jump_restarts_confirmation(self):
        """窗口内远距离切换候选不能凑成连续三帧。"""
        for x in [180, 236] * 5:
            self.frame(x)
        self.assertEqual(self.state["junction_count"], 0)

    def test_missing_candidate_restarts_confirmation(self):
        """单帧噪点和中断不能触发计数。"""
        self.frame(208)
        self.frame()
        self.frame(208)
        self.assertEqual(self.state["junction_streak"], 1)

    def test_rejected_shapes_and_floating_mark(self):
        """宽块、矮块、悬空竖条和窗外地标不计数。"""
        for blob in [make_blob(208, width=40), make_blob(208, height=12),
                     make_blob(208, bottom=50), make_blob(250)]:
            for _ in range(3):
                self.frame(blobs=[blob])
        self.assertEqual(self.state["junction_count"], 0)

    def test_normal_passages_both_directions(self):
        """左右出窗均可解锁并计下一个地标。"""
        for direction in [-1, 1]:
            self.setUp()
            self.latch()
            for offset in [16, 32, 48, 64, 80]:
                self.frame(208 + direction * offset)
            self.frame()
            self.frame()
            self.assertFalse(self.state["junction_latched"])
            for _ in range(3):
                result = self.frame(208)
            self.assertEqual(result["junction_count"], 2)

    def test_loss_inside_window_keeps_lock(self):
        """已知限制：窗内消失不能凭空窗恢复计数。"""
        self.latch()
        for _ in range(20):
            self.frame()
        for _ in range(3):
            self.frame(208)
        self.assertTrue(self.state["junction_latched"])
        self.assertEqual(self.state["junction_count"], 1)

    def test_step_limit_can_prevent_exit_tracking(self):
        """已知限制：旧目标一步跳过跟踪门限会持续锁定。"""
        self.latch()
        for _ in range(10):
            self.frame(260)
        self.assertEqual(self.state["latched_x"], 208)
        self.assertTrue(self.state["junction_latched"])

    def test_exit_margin_and_lost_line(self):
        """出窗余量是严格大于38，丢横线打断释放连续数。"""
        self.latch()
        for x in [224, 240, 246]:
            self.frame(x)
        self.assertEqual(self.state["junction_clear_streak"], 0)
        self.frame(247)
        self.assertEqual(self.state["junction_clear_streak"], 1)
        result = self.frame(valid=False)
        self.assertEqual(self.state["junction_clear_streak"], 0)
        self.assertIsNone(result["position_error_px"])
        for _ in range(4):
            self.frame()
        self.assertTrue(self.state["junction_latched"])
        self.frame()
        self.assertFalse(self.state["junction_latched"])

    def test_temporarily_wide_old_mark_is_tracked(self):
        """已锁地标允许暂时变宽，但仍受交点间距约束。"""
        self.latch()
        self.frame(blobs=[make_blob(224, width=40)])
        self.assertEqual(self.state["latched_x"], 224)
        self.frame(blobs=[make_blob(240, bottom=50)])
        self.assertEqual(self.state["latched_x"], 224)

    def test_geometry_and_reversed_endpoints(self):
        """相同斜线反转端点后误差与角度不变。"""
        mask = np.full((240, 320), 255, dtype=np.uint8)
        results = []
        for line in [make_line(16, 60, 296, 88), make_line(296, 88, 16, 60)]:
            self.state.update(lines=[line], binary_cv=mask)
            exec(GEOMETRY, self.state)
            self.assertTrue(self.state["line_pixel_valid"])
            results.append([self.state[k] for k in
                            ["position_error_px", "heading_error_px", "line_angle"]])
        np.testing.assert_allclose(results[0], [6.2, 12, math.degrees(math.atan(.1))])
        np.testing.assert_allclose(results[0], results[1])

    def test_no_line_or_no_pixel_support_is_invalid(self):
        """无候选、竖线、短线或采样无白像素时误差无效。"""
        for lines in [[], [make_line()], [make_line(208, 0, 208, 80)],
                      [make_line(190, 73, 220, 73)]]:
            self.state.update(lines=lines, binary_cv=np.zeros((240, 320), np.uint8))
            exec(GEOMETRY, self.state)
            self.assertFalse(self.state["line_pixel_valid"])

    def test_uart_lost_line_preserves_count(self):
        """无效帧发送零占位和保留的累计数，不能复用旧误差。"""
        self.state.update(line_pixel_valid=False, junction_count=2,
                          position_error_px=99, heading_error_px=88)
        expected = "0,0.0,0.0,2\r\n"
        serial = Mock(write_str=Mock(return_value=len(expected)))
        self.state["serial_dev"] = serial
        exec(SENDING, self.state)
        serial.write_str.assert_called_once_with(expected)
        serial.close.assert_not_called()

    def test_uart_short_write_and_exception_stop(self):
        """短写和写异常关闭串口并传播错误。"""
        for writer in [Mock(return_value=1), Mock(side_effect=OSError("offline"))]:
            serial = Mock(write_str=writer)
            self.state.update(serial_dev=serial, line_pixel_valid=True)
            with self.assertRaises(OSError):
                exec(SENDING, self.state)
            serial.close.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
