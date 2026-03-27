import argparse
import ctypes
import signal
import sys
import time
from pathlib import Path

# 全局变量，允许外部注入 DD 模块
_DD_MODULE = None

def set_dd_module(dd_module):
    global _DD_MODULE
    _DD_MODULE = dd_module

# 尝试自动导入 DD（如果没有注入）
try:
    from dd import DD as AutoDD
    _DD_MODULE = AutoDD
except ImportError:
    try:
        from aim_assist_project.dd.DD import DD as AutoDD
        _DD_MODULE = AutoDD
    except ImportError:
        pass # 等待外部注入或后续手动导入

from ctypes import wintypes


RIM_TYPEMOUSE = 0
RID_INPUT = 0x10000003
RIDI_DEVICENAME = 0x20000007
RIDEV_INPUTSINK = 0x00000100
RI_MOUSE_LEFT_BUTTON_DOWN = 0x0001
RI_MOUSE_LEFT_BUTTON_UP = 0x0002
RI_MOUSE_RIGHT_BUTTON_DOWN = 0x0004
RI_MOUSE_RIGHT_BUTTON_UP = 0x0008
RI_MOUSE_MIDDLE_BUTTON_DOWN = 0x0010
RI_MOUSE_MIDDLE_BUTTON_UP = 0x0020
RI_MOUSE_BUTTON_4_DOWN = 0x0040
RI_MOUSE_BUTTON_4_UP = 0x0080
RI_MOUSE_BUTTON_5_DOWN = 0x0100
RI_MOUSE_BUTTON_5_UP = 0x0200
RI_MOUSE_WHEEL = 0x0400
RI_MOUSE_HWHEEL = 0x0800
WM_INPUT = 0x00FF
WH_MOUSE_LL = 14
HC_ACTION = 0
LLMHF_INJECTED = 0x00000001
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_MOUSEWHEEL = 0x020A
WM_XBUTTONDOWN = 0x020B
WM_XBUTTONUP = 0x020C
WM_MOUSEHWHEEL = 0x020E
HWND_MESSAGE = -3
HRAWINPUT = getattr(wintypes, "HRAWINPUT", wintypes.HANDLE)
LRESULT = getattr(wintypes, "LRESULT", ctypes.c_ssize_t)
HICON = getattr(wintypes, "HICON", wintypes.HANDLE)
HCURSOR = getattr(wintypes, "HCURSOR", wintypes.HANDLE)
HBRUSH = getattr(wintypes, "HBRUSH", wintypes.HANDLE)
ATOM = getattr(wintypes, "ATOM", wintypes.WORD)
HHOOK = getattr(wintypes, "HHOOK", wintypes.HANDLE)

# 结构体定义
class RAWINPUTDEVICELIST(ctypes.Structure):
    _fields_ = [("hDevice", wintypes.HANDLE), ("dwType", wintypes.DWORD)]


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [
        ("usUsagePage", wintypes.USHORT),
        ("usUsage", wintypes.USHORT),
        ("dwFlags", wintypes.DWORD),
        ("hwndTarget", wintypes.HWND),
    ]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [
        ("dwType", wintypes.DWORD),
        ("dwSize", wintypes.DWORD),
        ("hDevice", wintypes.HANDLE),
        ("wParam", wintypes.WPARAM),
    ]


class RAWMOUSE(ctypes.Structure):
    class _U(ctypes.Union):
        class _S(ctypes.Structure):
            _fields_ = [
                ("usButtonFlags", wintypes.USHORT),
                ("usButtonData", wintypes.USHORT),
            ]
        _fields_ = [("ulButtons", wintypes.DWORD), ("s", _S)]

    _anonymous_ = ("u",)
    _fields_ = [
        ("usFlags", wintypes.USHORT),
        ("u", _U),
        ("ulRawButtons", wintypes.DWORD),
        ("lLastX", wintypes.LONG),
        ("lLastY", wintypes.LONG),
        ("ulExtraInformation", wintypes.DWORD),
    ]


class RAWINPUT(ctypes.Structure):
    _fields_ = [("header", RAWINPUTHEADER), ("data", RAWMOUSE)]

class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", wintypes.POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


# 辅助函数
def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", type=str, default="list", choices=["list", "run"])
    parser.add_argument("--device_index", type=int, default=-1)
    parser.add_argument("--debug", action="store_true")
    return parser.parse_args()

def send_input(dx, dy, button_flags, button_data):
    user32 = ctypes.windll.user32

    MOUSEEVENTF_MOVE = 0x0001
    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004
    MOUSEEVENTF_RIGHTDOWN = 0x0008
    MOUSEEVENTF_RIGHTUP = 0x0010
    MOUSEEVENTF_MIDDLEDOWN = 0x0020
    MOUSEEVENTF_MIDDLEUP = 0x0040
    MOUSEEVENTF_XDOWN = 0x0080
    MOUSEEVENTF_XUP = 0x0100
    MOUSEEVENTF_WHEEL = 0x0800
    MOUSEEVENTF_HWHEEL = 0x1000

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", wintypes.LONG),
            ("dy", wintypes.LONG),
            ("mouseData", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_size_t),
        ]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("mi", MOUSEINPUT)]

    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT

    inputs = []
    if dx or dy:
        inputs.append(INPUT(0, MOUSEINPUT(int(dx), int(dy), 0, MOUSEEVENTF_MOVE, 0, 0)))
    if button_flags & RI_MOUSE_LEFT_BUTTON_DOWN:
        inputs.append(INPUT(0, MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN, 0, 0)))
    if button_flags & RI_MOUSE_LEFT_BUTTON_UP:
        inputs.append(INPUT(0, MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTUP, 0, 0)))
    if button_flags & RI_MOUSE_RIGHT_BUTTON_DOWN:
        inputs.append(INPUT(0, MOUSEINPUT(0, 0, 0, MOUSEEVENTF_RIGHTDOWN, 0, 0)))
    if button_flags & RI_MOUSE_RIGHT_BUTTON_UP:
        inputs.append(INPUT(0, MOUSEINPUT(0, 0, 0, MOUSEEVENTF_RIGHTUP, 0, 0)))
    if button_flags & RI_MOUSE_MIDDLE_BUTTON_DOWN:
        inputs.append(INPUT(0, MOUSEINPUT(0, 0, 0, MOUSEEVENTF_MIDDLEDOWN, 0, 0)))
    if button_flags & RI_MOUSE_MIDDLE_BUTTON_UP:
        inputs.append(INPUT(0, MOUSEINPUT(0, 0, 0, MOUSEEVENTF_MIDDLEUP, 0, 0)))
    if button_flags & RI_MOUSE_BUTTON_4_DOWN:
        inputs.append(INPUT(0, MOUSEINPUT(0, 0, 1, MOUSEEVENTF_XDOWN, 0, 0)))
    if button_flags & RI_MOUSE_BUTTON_4_UP:
        inputs.append(INPUT(0, MOUSEINPUT(0, 0, 1, MOUSEEVENTF_XUP, 0, 0)))
    if button_flags & RI_MOUSE_BUTTON_5_DOWN:
        inputs.append(INPUT(0, MOUSEINPUT(0, 0, 2, MOUSEEVENTF_XDOWN, 0, 0)))
    if button_flags & RI_MOUSE_BUTTON_5_UP:
        inputs.append(INPUT(0, MOUSEINPUT(0, 0, 2, MOUSEEVENTF_XUP, 0, 0)))
    if button_flags & RI_MOUSE_WHEEL:
        wheel = ctypes.c_short(button_data).value
        inputs.append(INPUT(0, MOUSEINPUT(0, 0, wheel, MOUSEEVENTF_WHEEL, 0, 0)))
    if button_flags & RI_MOUSE_HWHEEL:
        wheel = ctypes.c_short(button_data).value
        inputs.append(INPUT(0, MOUSEINPUT(0, 0, wheel, MOUSEEVENTF_HWHEEL, 0, 0)))

    if not inputs:
        return

    arr_type = INPUT * len(inputs)
    arr = arr_type(*inputs)
    user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def get_raw_mouse_devices():
    user32 = ctypes.windll.user32
    count = wintypes.UINT(0)
    elem_size = ctypes.sizeof(RAWINPUTDEVICELIST)
    
    # 第一次调用获取数量
    res = user32.GetRawInputDeviceList(None, ctypes.byref(count), elem_size)
    if res == -1:
        raise RuntimeError(f"GetRawInputDeviceList 失败 err={ctypes.get_last_error()}")
        
    if count.value == 0:
        return []

    # 第二次调用获取列表
    arr_type = RAWINPUTDEVICELIST * count.value
    arr = arr_type()
    got = user32.GetRawInputDeviceList(arr, ctypes.byref(count), elem_size)
    if got == -1:
        raise RuntimeError("读取原始输入设备失败")

    devices = []
    for item in arr[:got]:
        if item.dwType != RIM_TYPEMOUSE:
            continue
            
        # 获取设备名
        name_size = wintypes.UINT(0)
        user32.GetRawInputDeviceInfoW(item.hDevice, RIDI_DEVICENAME, None, ctypes.byref(name_size))
        if name_size.value > 0:
            buf = ctypes.create_unicode_buffer(name_size.value + 1)
            user32.GetRawInputDeviceInfoW(item.hDevice, RIDI_DEVICENAME, buf, ctypes.byref(name_size))
            dev_name = buf.value
        else:
            dev_name = "Unknown"
            
        devices.append({"handle": int(item.hDevice), "name": dev_name})
    return devices


def create_message_window():
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    
    # 定义窗口过程
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    
    def wnd_proc(hwnd, msg, w_param, l_param):
        return user32.DefWindowProcW(hwnd, msg, w_param, l_param)
        
    wnd_proc_fn = WNDPROC(wnd_proc)
    
    # 注册窗口类
    class WNDCLASS(ctypes.Structure):
        _fields_ = [
            ("style", wintypes.UINT),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", HICON),
            ("hCursor", HCURSOR),
            ("hbrBackground", HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
        ]
        
    h_inst = kernel32.GetModuleHandleW(None)
    class_name = "RawInputReceiver"
    
    wc = WNDCLASS()
    wc.lpfnWndProc = wnd_proc_fn
    wc.hInstance = h_inst
    wc.lpszClassName = class_name
    
    user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASS)]
    user32.RegisterClassW.restype = ATOM
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        wintypes.HMENU,
        wintypes.HINSTANCE,
        wintypes.LPVOID,
    ]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = LRESULT

    if not user32.RegisterClassW(ctypes.byref(wc)):
        # 如果已注册则忽略错误
        if kernel32.GetLastError() != 1410: # ERROR_CLASS_ALREADY_EXISTS
            err = kernel32.GetLastError()
            raise RuntimeError(f"注册窗口类失败 err={err} {ctypes.FormatError(err).strip()}")

    # 创建消息窗口
    hwnd_parent = wintypes.HWND(ctypes.c_void_p(HWND_MESSAGE).value)
    hwnd = user32.CreateWindowExW(
        0,
        class_name,
        "RawInputMsgWindow",
        0, 0, 0, 0, 0,
        hwnd_parent,
        None,
        h_inst,
        None
    )
    if not hwnd:
        err = kernel32.GetLastError()
        raise RuntimeError(f"创建消息窗口失败 err={err} {ctypes.FormatError(err).strip()}")
    
    # 保持引用防止回收
    create_message_window.keep_alive = (wnd_proc_fn, wc)
    return hwnd


def run_intercept(device_index, debug=False):
    if _DD_MODULE is None:
        raise RuntimeError("DD 模块未初始化，请先调用 set_dd_module() 或确保自动导入成功")
    
    devices = get_raw_mouse_devices()
    if device_index < 0 or device_index >= len(devices):
        raise RuntimeError("device_index 超出范围，请先用 --action list 查看")
        
    target = devices[device_index]
    target_handle = target["handle"]
    
    print(f"目标设备: [{device_index}] {target['name']}")
    print(f"设备句柄: {target_handle}")
    
    # 创建接收窗口
    hwnd = create_message_window()
    if not hwnd:
        raise RuntimeError("创建消息窗口失败")
        
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    
    # 注册 RawInput
    # 使用 RIDEV_NOLEGACY 标志来阻止生成遗留的鼠标消息（WM_MOUSEMOVE等）
    # 从而实现“拦截”效果，同时依然能收到 WM_INPUT
    rid = RAWINPUTDEVICE()
    rid.usUsagePage = 0x01
    rid.usUsage = 0x02
    rid.dwFlags = RIDEV_INPUTSINK
    rid.hwndTarget = hwnd
    
    if not user32.RegisterRawInputDevices(ctypes.byref(rid), 1, ctypes.sizeof(RAWINPUTDEVICE)):
        raise RuntimeError(f"注册原始输入失败 err={ctypes.get_last_error()}")
        
    state = {"hook": None, "hook_proc": None}
    block_messages = {
        WM_MOUSEMOVE,
        WM_LBUTTONDOWN,
        WM_LBUTTONUP,
        WM_RBUTTONDOWN,
        WM_RBUTTONUP,
        WM_MBUTTONDOWN,
        WM_MBUTTONUP,
        WM_MOUSEWHEEL,
        WM_XBUTTONDOWN,
        WM_XBUTTONUP,
        WM_MOUSEHWHEEL,
    }

    HOOK_PROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
    user32.CallNextHookEx.argtypes = [HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
    user32.CallNextHookEx.restype = LRESULT
    user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOK_PROC, wintypes.HINSTANCE, wintypes.DWORD]
    user32.SetWindowsHookExW.restype = HHOOK
    user32.UnhookWindowsHookEx.argtypes = [HHOOK]
    user32.UnhookWindowsHookEx.restype = wintypes.BOOL

    def hook_callback(n_code, w_param, l_param):
        try:
            if n_code == HC_ACTION and w_param in block_messages:
                data = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                if (int(data.flags) & LLMHF_INJECTED) == 0:
                    return 1
        except Exception:
            return user32.CallNextHookEx(state["hook"], n_code, w_param, l_param)
        return user32.CallNextHookEx(state["hook"], n_code, w_param, l_param)

    state["hook_proc"] = HOOK_PROC(hook_callback)
    kernel32.SetLastError(0)
    state["hook"] = user32.SetWindowsHookExW(WH_MOUSE_LL, state["hook_proc"], None, 0)
    if not state["hook"]:
        err = kernel32.GetLastError()
        raise RuntimeError(f"安装低级钩子失败 err={err} {ctypes.FormatError(err).strip()}")

    print("已启动拦截监听... (按 Ctrl+C 退出)")
    if debug:
        print("[Debug] 调试模式已开启")
        
    running = True
    def _on_sigint(signum, frame):
        nonlocal running
        running = False
    try:
        signal.signal(signal.SIGINT, _on_sigint)
    except ValueError:
        pass # Not in main thread
    
    msg = wintypes.MSG()
    try:
        while running:
            # 使用 PeekMessage 避免阻塞，以便响应 Ctrl+C
            while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1): # PM_REMOVE
                if msg.message == WM_INPUT:
                    # 获取数据大小
                    size = wintypes.UINT(0)
                    user32.GetRawInputData(
                        HRAWINPUT(msg.lParam),
                        RID_INPUT,
                        None,
                        ctypes.byref(size),
                        ctypes.sizeof(RAWINPUTHEADER)
                    )
                    
                    if size.value > 0:
                        buf = ctypes.create_string_buffer(size.value)
                        user32.GetRawInputData(
                            HRAWINPUT(msg.lParam),
                            RID_INPUT,
                            buf,
                            ctypes.byref(size),
                            ctypes.sizeof(RAWINPUTHEADER)
                        )
                        
                        raw = ctypes.cast(buf, ctypes.POINTER(RAWINPUT)).contents
                        
                        # 仅处理目标设备
                        if raw.header.dwType == RIM_TYPEMOUSE:
                            h_dev = int(raw.header.hDevice) if raw.header.hDevice else 0
                            
                            if h_dev == target_handle:
                                dx = int(raw.data.lLastX)
                                dy = int(raw.data.lLastY)
                                flags = int(raw.data.u.s.usButtonFlags)
                                button_data = int(raw.data.u.s.usButtonData)
                                
                                if debug:
                                    print(f"[Input] dx={dx} dy={dy} flags={flags:04X}")
                                
                                if dx != 0 or dy != 0:
                                    _DD_MODULE.mouse_xy(dx, dy)
                                    
                                if flags & RI_MOUSE_LEFT_BUTTON_DOWN:
                                    _DD_MODULE.mouse_down(1)
                                if flags & RI_MOUSE_LEFT_BUTTON_UP:
                                    _DD_MODULE.mouse_up(1)
                                if flags & RI_MOUSE_RIGHT_BUTTON_DOWN:
                                    _DD_MODULE.mouse_down(2)
                                if flags & RI_MOUSE_RIGHT_BUTTON_UP:
                                    _DD_MODULE.mouse_up(2)
                                if flags & RI_MOUSE_MIDDLE_BUTTON_DOWN:
                                    _DD_MODULE.mouse_down(3)
                                if flags & RI_MOUSE_MIDDLE_BUTTON_UP:
                                    _DD_MODULE.mouse_up(3)
                                    
                            elif debug and h_dev != 0:
                                print(f"[Other] handle={h_dev}")
                            if h_dev != 0 and h_dev != target_handle:
                                dx = int(raw.data.lLastX)
                                dy = int(raw.data.lLastY)
                                flags = int(raw.data.u.s.usButtonFlags)
                                button_data = int(raw.data.u.s.usButtonData)
                                send_input(dx, dy, flags, button_data)

                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            
            time.sleep(0.0001)
            
    except KeyboardInterrupt:
        pass
    finally:
        if state.get("hook"):
            user32.UnhookWindowsHookEx(state["hook"])
        if hwnd:
            user32.DestroyWindow(hwnd)
        print("已退出")


def main():
    args = parse_args()
    
    if args.action == "list":
        devices = get_raw_mouse_devices()
        if not devices:
            print("未找到鼠标设备")
            return
        for i, d in enumerate(devices):
            print(f"[{i}] handle={d['handle']} name={d['name']}")
        return
        
    run_intercept(args.device_index, args.debug)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"执行失败: {e}")
        sys.exit(1)
