# Aim Assist Project
.\.venv\Scripts\Activate.ps1 
```bash
pip install simple-pid
```
python aim_assist_project/main.py --config aim_assist_project/config.yaml

## PID 配置

- 当前使用 `simple-pid` 作为标准 PID 控制器。
- `tracking.pid` 和各预设内的 `pid` 仅保留这些字段：`kp`、`ki`、`kd`、`output_max`、`deadzone_px`、`sample_time`。
- `tracking.hysteresis` 和各预设内的 `hysteresis` 用于基于目标框宽度的 X 轴滞环误差整形，先处理 X 轴误差，再交给 PID。

## 滞环控制配置

- `enable`: 是否启用滞环控制。
- `dist_ratio`: X 轴进入增强区间的阈值倍数，实际阈值为 `目标宽度 * dist_ratio`。
- `release_ratio`: X 轴退出增强区间的阈值倍数，通常小于等于 `dist_ratio`，用于形成滞环，减少抖动切换。
- `boost_ratio`: 当 `abs(dx)` 大于阈值时增加的 X 轴误差量，增加值为 `目标宽度 * boost_ratio`，方向跟随 `dx`，Y 轴不参与。
- `suppress_ratio`: 当 `abs(dx)` 小于释放阈值时对 X 轴误差的抑制比例，`0.0` 表示完全抑制，`1.0` 表示不抑制，Y 轴不参与。

## 功能

- 扫描屏幕中心 640x640 区域并检测最近目标。
- 可选显示可视化窗口，展示推理 FPS、程序 FPS、推理画面和目标信息。
- 默认使用 DXGI 截屏。
- 支持 TensorRT 推理加速，可在配置中设置 `model.backend: trt` 与 `model.trt_engine`。
- 支持按键触发模式，仅在按住触发键时执行推理（`activation.key`）。
