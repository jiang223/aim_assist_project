import argparse
import ctypes
import math
import threading
import time
from pathlib import Path

import yaml
from simple_pid import PID


class AimController:
    """2-axis controller based on simple_pid.PID."""

    def __init__(
        self,
        kp,
        ki,
        kd,
        output_max=150.0,
        deadzone_px=0.0,
        sample_time=0.0,
        error_smoothing=1.0,
        min_pid_update_dt=0.0,
        hysteresis_enabled=False,
        hysteresis_dist_ratio=1.0,
        hysteresis_release_ratio=None,
        hysteresis_boost_ratio=0.0,
        hysteresis_suppress_ratio=0.0,
        **_ignored,
    ):
        self.output_max = abs(float(output_max))
        self.deadzone_px = max(0.0, float(deadzone_px))
        self.error_smoothing = min(1.0, max(0.0, float(error_smoothing)))
        self.min_pid_update_dt = max(0.0, float(min_pid_update_dt))
        self.hysteresis_enabled = bool(hysteresis_enabled)
        self.hysteresis_dist_ratio = max(0.0, float(hysteresis_dist_ratio))
        release_ratio = self.hysteresis_dist_ratio if hysteresis_release_ratio is None else float(hysteresis_release_ratio)
        self.hysteresis_release_ratio = max(0.0, min(self.hysteresis_dist_ratio, release_ratio))
        self.hysteresis_boost_ratio = max(0.0, float(hysteresis_boost_ratio))
        self.hysteresis_suppress_ratio = min(1.0, max(0.0, float(hysteresis_suppress_ratio)))
        self.pid_x = PID(
            float(kp),
            float(ki),
            float(kd),
            setpoint=0.0,
            sample_time=float(sample_time),
            output_limits=(-self.output_max, self.output_max),
        )
        self.pid_y = PID(
            float(kp),
            float(ki),
            float(kd),
            setpoint=0.0,
            sample_time=float(sample_time),
            output_limits=(-self.output_max, self.output_max),
        )
        self.reset()

    def update(self, raw_dx, raw_dy, current_time, target_width=None, measurement_time=None):
        _ = measurement_time
        smoothed_dx, smoothed_dy = self._smooth_error(raw_dx, raw_dy)
        adjusted_dx, adjusted_dy = self._apply_hysteresis(smoothed_dx, smoothed_dy, target_width)
        # simple_pid computes error as setpoint - input, so negate the error
        # to keep controller output aligned with screen/mouse directions.
        current_time = float(current_time)
        if self.last_pid_update_time is not None and (current_time - self.last_pid_update_time) < self.min_pid_update_dt:
            out_x = self.last_output_x
            out_y = self.last_output_y
        else:
            out_x = self.pid_x(-float(adjusted_dx))
            out_y = self.pid_y(-float(adjusted_dy))
            self.last_pid_update_time = current_time
        if self.deadzone_px > 0.0:
            if abs(out_x) < self.deadzone_px:
                out_x = 0.0
            if abs(out_y) < self.deadzone_px:
                out_y = 0.0
        self.last_output_x = float(out_x)
        self.last_output_y = float(out_y)
        return float(out_x), float(out_y)

    def _smooth_error(self, dx, dy):
        measured_dx = float(dx)
        measured_dy = float(dy)
        if self.smoothed_error_dx is None or self.smoothed_error_dy is None:
            self.smoothed_error_dx = measured_dx
            self.smoothed_error_dy = measured_dy
            return measured_dx, measured_dy

        alpha = self.error_smoothing
        if alpha <= 0.0:
            return self.smoothed_error_dx, self.smoothed_error_dy
        if alpha >= 1.0:
            self.smoothed_error_dx = measured_dx
            self.smoothed_error_dy = measured_dy
            return measured_dx, measured_dy

        self.smoothed_error_dx = self.smoothed_error_dx * (1.0 - alpha) + measured_dx * alpha
        self.smoothed_error_dy = self.smoothed_error_dy * (1.0 - alpha) + measured_dy * alpha
        return self.smoothed_error_dx, self.smoothed_error_dy

    def _apply_hysteresis(self, measured_dx, measured_dy, target_width):
        if not self.hysteresis_enabled:
            return float(measured_dx), float(measured_dy)

        width = 0.0 if target_width is None else max(0.0, float(target_width))
        if width <= 0.0:
            self.hysteresis_active = False
            return float(measured_dx), float(measured_dy)

        dist = abs(float(measured_dx))
        engage_threshold = width * self.hysteresis_dist_ratio
        release_threshold = width * self.hysteresis_release_ratio

        if self.hysteresis_active:
            if dist < release_threshold:
                self.hysteresis_active = False
        elif dist > engage_threshold:
            self.hysteresis_active = True

        if self.hysteresis_active:
            boost = width * self.hysteresis_boost_ratio
            if boost <= 0.0 or dist <= 1e-6:
                return float(measured_dx), float(measured_dy)
            direction_x = 1.0 if float(measured_dx) >= 0.0 else -1.0
            return float(measured_dx) + direction_x * boost, float(measured_dy)

        suppress = self.hysteresis_suppress_ratio
        return float(measured_dx) , float(measured_dy)

    def set_applied_output(self, move_x, move_y):
        _ = (move_x, move_y)

    def reset(self):
        self.pid_x.reset()
        self.pid_y.reset()
        self.smoothed_error_dx = None
        self.smoothed_error_dy = None
        self.last_pid_update_time = None
        self.last_output_x = 0.0
        self.last_output_y = 0.0
        self.hysteresis_active = False


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        type=str,
        default="color_aimbot/aim_assist_project/config.yaml",
    )
    return parser.parse_args()


def load_config(path):
    cfg_path = Path(path).expanduser().resolve()
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    return cfg_path, data


def resolve_device(requested_device):
    try:
        import torch
    except Exception:
        return requested_device
    text = str(requested_device).strip().lower()
    if text == "cpu":
        return "cpu"
    if text in {"0", "1", "2", "3", "cuda"} and not torch.cuda.is_available():
        print("未检测到可用 CUDA，已自动回退到 CPU 推理。")
        return "cpu"
    return requested_device


def has_tensorrt():
    try:
        import tensorrt

        _ = tensorrt.__version__
        return True
    except Exception:
        return False


def select_model_for_backend(yolo_cls, model_cfg, infer_device, run_half):
    model_path = Path(model_cfg["path"])
    backend = str(model_cfg.get("backend", "auto")).lower()
    if backend in {"torch", "pt", "pytorch"}:
        return str(model_path), "torch"
    if model_path.suffix.lower() == ".engine":
        if has_tensorrt():
            return str(model_path), "trt"
        pt_path = model_path.with_suffix(".pt")
        if backend == "auto" and pt_path.exists():
            print("未检测到 tensorrt 模块，已自动回退到 PyTorch 后端。")
            return str(pt_path), "torch"
        raise RuntimeError("缺少 tensorrt 模块，请先安装: python -m pip install -U nvidia-cuda-runtime tensorrt-cu13")
    trt_engine = model_cfg.get("trt_engine", "")
    engine_path = Path(trt_engine) if trt_engine else model_path.with_suffix(".engine")
    if engine_path.exists():
        if not has_tensorrt():
            if backend == "auto":
                print("未检测到 tensorrt 模块，已自动回退到 PyTorch 后端。")
                return str(model_path), "torch"
            raise RuntimeError("缺少 tensorrt 模块，请先安装: python -m pip install -U nvidia-cuda-runtime tensorrt-cu13")
        return str(engine_path), "trt"
    if backend == "trt":
        if not has_tensorrt():
            raise RuntimeError("缺少 tensorrt 模块，请先安装: python -m pip install -U nvidia-cuda-runtime tensorrt-cu13")
        print(f"未找到 TensorRT 引擎，开始导出: {engine_path}")
        exporter = yolo_cls(str(model_path))
        exported = exporter.export(
            format="engine",
            imgsz=int(model_cfg.get("imgsz", 640)),
            device=infer_device,
            half=run_half,
        )
        if isinstance(exported, str):
            engine_path = Path(exported)
        if engine_path.exists():
            return str(engine_path), "trt"
        raise RuntimeError("TensorRT 引擎导出失败，请检查 CUDA/TensorRT 环境")
    return str(model_path), "torch"


def build_capture(config):
    capture_backend = str(config["capture"]["backend"]).lower()
    monitor_index = int(config["screen"]["monitor"])
    roi = config["screen"]["roi"]
    roi_w = int(roi["width"])
    roi_h = int(roi["height"])
    screen_w = int(config["screen"]["width"])
    screen_h = int(config["screen"]["height"])
    roi_left = (screen_w - roi_w) // 2
    roi_top = (screen_h - roi_h) // 2
    if capture_backend in {"dxgi", "auto"}:
        try:
            import dxcam

            camera = dxcam.create(output_idx=max(0, monitor_index - 1))
            if camera is None:
                raise RuntimeError("dxcam create failed")
            region = (roi_left, roi_top, roi_left + roi_w, roi_top + roi_h)
            target_fps = int(config["capture"].get("target_fps", 0))
            if target_fps > 0:
                camera.start(region=region, target_fps=target_fps, video_mode=True)
            else:
                camera.start(region=region, video_mode=True)

            def _grab():
                frame = camera.get_latest_frame()
                if frame is None:
                    return None
                return frame[:, :, :3][:, :, ::-1]

            def _close():
                camera.stop()

            return _grab, _close, roi_w, roi_h
        except Exception:
            if capture_backend == "dxgi":
                raise RuntimeError("DXGI 截屏初始化失败，请安装 dxcam")
    try:
        import mss
        import numpy as np
    except Exception:
        raise RuntimeError("缺少 mss/numpy，请先安装依赖")
    sct = mss.mss()
    region = {"left": roi_left, "top": roi_top, "width": roi_w, "height": roi_h}

    def _grab():
        return np.asarray(sct.grab(region))[:, :, :3]

    def _close():
        sct.close()

    return _grab, _close, roi_w, roi_h


def select_nearest_target(result, roi_center_x, roi_center_y, max_radius_px=None):
    if result.boxes is None or len(result.boxes) == 0:
        return None
    boxes = result.boxes.xyxy
    cls = result.boxes.cls
    conf = result.boxes.conf
    best_idx = -1
    best_dist = None
    max_radius_sq = None
    if max_radius_px is not None and max_radius_px >= 0:
        max_radius_sq = float(max_radius_px) * float(max_radius_px)
    for i in range(len(boxes)):
        x1, y1, x2, y2 = boxes[i]
        cx = float((x1 + x2) * 0.5)
        cy = float((y1 + y2) * 0.5)
        dx = cx - roi_center_x
        dy = cy - roi_center_y
        dist = dx * dx + dy * dy
        if max_radius_sq is not None and dist > max_radius_sq:
            continue
        if best_dist is None or dist < best_dist:
            best_dist = dist
            best_idx = i
    if best_idx < 0:
        return None
    x1, y1, x2, y2 = boxes[best_idx]
    return {
        "x1": float(x1),
        "y1": float(y1),
        "x2": float(x2),
        "y2": float(y2),
        "width": float(x2 - x1),
        "height": float(y2 - y1),
        "cx": float((x1 + x2) * 0.5),
        "cy": float((y1 + y2) * 0.5),
        "cls": int(cls[best_idx]),
        "conf": float(conf[best_idx]),
    }


def target_distance_to_center(target, roi_center_x, roi_center_y):
    if target is None:
        return None
    dx = float(target["cx"]) - float(roi_center_x)
    dy = float(target["cy"]) - float(roi_center_y)
    return (dx * dx + dy * dy) ** 0.5


def resolve_tracking_config(tracking_cfg):
    effective = dict(tracking_cfg or {})
    presets = effective.get("presets", {})
    active_name = str(effective.get("active_preset", "")).strip()
    if not active_name or not isinstance(presets, dict):
        return effective
    selected = presets.get(active_name)
    if not isinstance(selected, dict):
        return effective

    # Apply selected preset over base tracking config with nested merge.
    merged = dict(effective)
    for key, value in selected.items():
        if isinstance(value, dict):
            base_nested = merged.get(key, {})
            if not isinstance(base_nested, dict):
                base_nested = {}
            merged[key] = {**base_nested, **value}
        else:
            merged[key] = value
    return merged


def resolve_activation_vk(key_name):
    name = str(key_name).strip().lower()
    mouse_map = {
        "left_mouse": 0x01,
        "right_mouse": 0x02,
        "middle_mouse": 0x04,
        "x1_mouse": 0x05,
        "x2_mouse": 0x06,
    }
    if name in mouse_map:
        return mouse_map[name]
    if len(name) == 1:
        return ord(name.upper())
    if name.startswith("f") and name[1:].isdigit():
        n = int(name[1:])
        if 1 <= n <= 24:
            return 0x70 + (n - 1)
    special = {"shift": 0x10, "ctrl": 0x11, "alt": 0x12, "space": 0x20}
    if name in special:
        return special[name]
    return ord("Q")


def is_key_pressed(vk_code):
    user32 = ctypes.windll.user32
    state = user32.GetAsyncKeyState(int(vk_code))
    return (state & 0x8000) != 0


def draw_overlay(frame, cv2, fps_app, fps_infer, target, roi_w, roi_h, active, lock_active, lock_miss_count):
    vis = frame.copy()
    cx = roi_w // 2
    cy = roi_h // 2
    cv2.circle(vis, (cx, cy), 5, (0, 255, 255), -1)
    cv2.putText(
        vis,
        f"APP FPS: {fps_app:.1f} | INFER FPS: {fps_infer:.1f}",
        (10, 24),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        (0, 255, 0),
        2,
        cv2.LINE_AA,
    )
    state_text = "ACTIVE" if active else "IDLE"
    state_color = (0, 255, 0) if active else (100, 100, 255)
    cv2.putText(
        vis,
        f"STATE: {state_text}",
        (10, 80),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        state_color,
        2,
        cv2.LINE_AA,
    )
    lock_text = "LOCKED" if lock_active else "UNLOCKED"
    lock_color = (0, 200, 255) if lock_active else (180, 180, 180)
    cv2.putText(
        vis,
        f"LOCK: {lock_text} miss={lock_miss_count}",
        (10, 108),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.65,
        lock_color,
        2,
        cv2.LINE_AA,
    )
    if target is not None:
        pt = (int(target["cx"]), int(target["cy"]))
        cv2.rectangle(
            vis,
            (int(target["x1"]), int(target["y1"])),
            (int(target["x2"]), int(target["y2"])),
            (0, 200, 255),
            2,
        )
        cv2.circle(vis, pt, 4, (0, 0, 255), -1)
        cv2.line(vis, (cx, cy), pt, (255, 180, 0), 1)
        cv2.putText(
            vis,
            f"cls={target['cls']} conf={target['conf']:.2f}",
            (10, 52),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (255, 220, 180),
            2,
            cv2.LINE_AA,
        )
    return vis


def display_worker(window_name, frame_store, frame_lock, stop_event):
    import cv2

    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    try:
        cv2.setWindowProperty(window_name, cv2.WND_PROP_TOPMOST, 1)
    except Exception:
        pass
    while not stop_event.is_set():
        frame = None
        with frame_lock:
            if frame_store["frame"] is not None:
                frame = frame_store["frame"]
        if frame is not None:
            cv2.imshow(window_name, frame)
        key = cv2.waitKey(1) & 0xFF
        if key == 27:
            stop_event.set()
            break
        time.sleep(0.001)
    cv2.destroyWindow(window_name)


def control_worker(
    controller,
    target_state,
    target_lock,
    control_state,
    control_lock,
    stop_event,
    kma,
    kma_enabled,
    max_step_px,
    aim_y_offset_ratio,
    unlock_after_misses,
):
    last_seq = -1
    lock_active = False
    lock_miss_count = 0
    while not stop_event.is_set():
        with target_lock:
            seq = int(target_state["seq"])
            active = bool(target_state["active"])
            target = target_state["target"]
            roi_cx = float(target_state["roi_cx"])
            roi_cy = float(target_state["roi_cy"])
            frame_timestamp = target_state["frame_timestamp"]

        if seq == last_seq:
            time.sleep(0.001)
            continue
        last_seq = seq

        if not active:
            if lock_active:
                lock_active = False
                lock_miss_count = 0
                controller.reset()
            with control_lock:
                control_state["lock_active"] = lock_active
                control_state["lock_miss_count"] = lock_miss_count
            continue

        if not lock_active and target is not None:
            lock_active = True
            lock_miss_count = 0
            controller.reset()

        if lock_active:
            if target is None:
                lock_miss_count += 1
                controller.set_applied_output(0, 0)
            else:
                lock_miss_count = 0
                aim_cx = float(target["cx"])
                aim_cy = float(target["y1"] + (target["y2"] - target["y1"]) * aim_y_offset_ratio)
                err_x = aim_cx - roi_cx
                err_y = aim_cy - roi_cy
                target_width = float(target.get("width", 0.0))
                control_time = time.time()
                out_x, out_y = controller.update(
                    err_x,
                    err_y,
                    control_time,
                    target_width=target_width,
                    measurement_time=frame_timestamp,
                )
                out_x = max(-max_step_px, min(max_step_px, out_x))
                out_y = max(-max_step_px, min(max_step_px, out_y))
                move_x = int(round(out_x))
                move_y = int(round(out_y))
                applied_x = 0
                applied_y = 0
                if kma_enabled and kma is not None and (move_x != 0 or move_y != 0):
                    kma.move(move_x, move_y)
                    applied_x = move_x
                    applied_y = move_y
                controller.set_applied_output(applied_x, applied_y)

            if lock_miss_count >= unlock_after_misses:
                lock_active = False
                lock_miss_count = 0
                controller.reset()

        with control_lock:
            control_state["lock_active"] = lock_active
            control_state["lock_miss_count"] = lock_miss_count


def inference_worker(
    grab_frame,
    model,
    predict_kwargs,
    target_state,
    target_lock,
    control_state,
    control_lock,
    frame_store,
    frame_lock,
    stop_event,
    activation_enabled,
    activation_vk,
    lock_radius_px,
    visualize,
    cfg,
    cv2,
):
    infer_fps_smooth = 0.0
    app_fps_smooth = 0.0
    roi_w = int(target_state["roi_w"])
    roi_h = int(target_state["roi_h"])
    while not stop_event.is_set():
        loop_t0 = time.perf_counter()
        frame = grab_frame()
        if frame is None:
            continue
        frame_timestamp = time.time()
        active = (not activation_enabled) or is_key_pressed(activation_vk)

        result = None
        target = None
        if active:
            infer_t0 = time.perf_counter()
            result = model.predict(source=frame, **predict_kwargs)[0]
            infer_dt = max(1e-6, time.perf_counter() - infer_t0)
            infer_fps = 1.0 / infer_dt
            if infer_fps_smooth == 0.0:
                infer_fps_smooth = infer_fps
            else:
                infer_fps_smooth = infer_fps_smooth * 0.9 + infer_fps * 0.1
            with control_lock:
                lock_active = bool(control_state["lock_active"])
            target = select_nearest_target(
                result,
                roi_w * 0.5,
                roi_h * 0.5,
                max_radius_px=lock_radius_px if lock_active else None,
            )
        else:
            infer_fps_smooth *= 0.95

        with target_lock:
            target_state["seq"] += 1
            target_state["active"] = active
            target_state["target"] = target
            target_state["frame_timestamp"] = frame_timestamp

        app_dt = max(1e-6, time.perf_counter() - loop_t0)
        app_fps = 1.0 / app_dt
        if app_fps_smooth == 0.0:
            app_fps_smooth = app_fps
        else:
            app_fps_smooth = app_fps_smooth * 0.9 + app_fps * 0.1

        if visualize:
            with control_lock:
                lock_active = bool(control_state["lock_active"])
                lock_miss_count = int(control_state["lock_miss_count"])
            vis = (
                result.plot(
                    labels=bool(cfg["visualization"].get("show_labels", True)),
                    conf=bool(cfg["visualization"].get("show_conf", True)),
                )
                if result is not None and bool(cfg["visualization"].get("show_infer_frame", True))
                else frame
            )
            vis = draw_overlay(
                vis,
                cv2,
                app_fps_smooth,
                infer_fps_smooth,
                target,
                roi_w,
                roi_h,
                active,
                lock_active,
                lock_miss_count,
            )
            with frame_lock:
                frame_store["frame"] = vis


def main():
    args = parse_args()
    try:
        import cv2
    except Exception:
        print("缺少 opencv-python，请先安装依赖")
        raise SystemExit(1)
    from ultralytics import YOLO

    _, cfg = load_config(args.config)
    grab_frame, close_capture, roi_w, roi_h = build_capture(cfg)
    infer_device = resolve_device(cfg["model"].get("device", "0"))
    run_half = bool(cfg["model"].get("half", False) and str(infer_device).lower() != "cpu")
    selected_model, backend_label = select_model_for_backend(YOLO, cfg["model"], infer_device, run_half)
    model = YOLO(selected_model)
    print(f"推理后端: {backend_label} | 模型: {selected_model} | 设备: {infer_device}")
    predict_kwargs = {
        "imgsz": int(cfg["model"].get("imgsz", 640)),
        "conf": float(cfg["model"].get("conf", 0.35)),
        "iou": float(cfg["model"].get("iou", 0.5)),
        "max_det": int(cfg["model"].get("max_det", 50)),
        "classes": cfg["model"].get("classes", None),
        "device": infer_device,
        "verbose": False,
    }
    if backend_label == "torch":
        predict_kwargs["half"] = run_half

    activation_cfg = cfg.get("activation", {})
    activation_enabled = bool(activation_cfg.get("enable", True))
    activation_vk = resolve_activation_vk(activation_cfg.get("key", "right_mouse"))

    tracking_cfg = resolve_tracking_config(cfg.get("tracking", {}))
    lock_radius_px = float(tracking_cfg.get("lock_radius_px", 100.0))
    unlock_after_misses = int(tracking_cfg.get("unlock_after_misses", 4))
    deadzone_px = float(tracking_cfg.get("deadzone_px", 1.5))
    max_step_px = float(tracking_cfg.get("max_step_px", 60.0))
    aim_y_offset_ratio = float(tracking_cfg.get("aim_y_offset_ratio", 0.0))
    pid_cfg = tracking_cfg.get("pid", {})
    hysteresis_cfg = tracking_cfg.get("hysteresis", tracking_cfg.get("prediction", {}))
    kd = float(pid_cfg.get("kd", 0.04))
    sample_time = float(pid_cfg.get("sample_time", 0.0))
    default_error_smoothing = 0.35 if abs(kd) > 0.0 else 1.0
    default_min_pid_update_dt = sample_time if sample_time > 0.0 else (0.008 if abs(kd) > 0.0 else 0.0)

    controller = AimController(
        kp=float(pid_cfg.get("kp", 0.45)),
        ki=float(pid_cfg.get("ki", 0.02)),
        kd=kd,
        output_max=float(pid_cfg.get("output_max", max_step_px)),
        deadzone_px=float(pid_cfg.get("deadzone_px", deadzone_px)),
        sample_time=sample_time,
        error_smoothing=float(pid_cfg.get("error_smoothing", default_error_smoothing)),
        min_pid_update_dt=float(pid_cfg.get("min_pid_update_dt", default_min_pid_update_dt)),
        hysteresis_enabled=bool(hysteresis_cfg.get("enable", False)),
        hysteresis_dist_ratio=float(hysteresis_cfg.get("dist_ratio", 1.0)),
        hysteresis_release_ratio=hysteresis_cfg.get("release_ratio", hysteresis_cfg.get("dist_ratio", 1.0)),
        hysteresis_boost_ratio=float(hysteresis_cfg.get("boost_ratio", 0.0)),
        hysteresis_suppress_ratio=float(hysteresis_cfg.get("suppress_ratio", 0.0)),
    )

    kma = None
    kma_enabled = bool(tracking_cfg.get("mouse_move_enable", True))
    if kma_enabled:
        try:
            from kma import KeyMouseSimulation

            kma = KeyMouseSimulation()
        except Exception as exc:
            print(f"kma 初始化失败，已禁用鼠标输出: {exc}")
            kma_enabled = False

    visualize = bool(cfg["visualization"].get("enable", True))
    window_name = str(cfg["visualization"].get("window_name", "Aim Assist Debug"))

    stop_event = threading.Event()
    frame_lock = threading.Lock()
    frame_store = {"frame": None}
    display_thread = None
    if visualize:
        display_thread = threading.Thread(
            target=display_worker,
            args=(window_name, frame_store, frame_lock, stop_event),
            daemon=True,
        )
        display_thread.start()

    target_lock = threading.Lock()
    control_lock = threading.Lock()
    target_state = {
        "seq": 0,
        "active": False,
        "target": None,
        "frame_timestamp": None,
        "roi_w": roi_w,
        "roi_h": roi_h,
        "roi_cx": roi_w * 0.5,
        "roi_cy": roi_h * 0.5,
    }
    control_state = {"lock_active": False, "lock_miss_count": 0}

    infer_thread = threading.Thread(
        target=inference_worker,
        args=(
            grab_frame,
            model,
            predict_kwargs,
            target_state,
            target_lock,
            control_state,
            control_lock,
            frame_store,
            frame_lock,
            stop_event,
            activation_enabled,
            activation_vk,
            lock_radius_px,
            visualize,
            cfg,
            cv2,
        ),
        daemon=True,
    )
    control_thread = threading.Thread(
        target=control_worker,
        args=(
            controller,
            target_state,
            target_lock,
            control_state,
            control_lock,
            stop_event,
            kma,
            kma_enabled,
            max_step_px,
            aim_y_offset_ratio,
            unlock_after_misses,
        ),
        daemon=True,
    )
    infer_thread.start()
    control_thread.start()

    print("运行中：按 ESC 退出。")
    try:
        while not stop_event.is_set():
            time.sleep(0.01)
    finally:
        stop_event.set()
        infer_thread.join(timeout=1.0)
        control_thread.join(timeout=1.0)
        if display_thread is not None:
            display_thread.join(timeout=1.0)
        close_capture()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
