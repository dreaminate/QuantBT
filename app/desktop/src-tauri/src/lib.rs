// QuantBT 桌面端核心入口（Tauri 2 惯例：lib.rs 暴露 pub fn run()）。
// main.rs 仅调用 quantbt_desktop_lib::run()，便于未来 mobile 共享入口。

use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use tauri::{Manager, RunEvent, State};

/// 内置 Python backend 子进程句柄。
/// Tauri 启动时 spawn uvicorn，退出时 kill 子进程。
struct BackendProcess(Mutex<Option<Child>>);

fn spawn_backend() -> Result<Child, String> {
    // 优先使用环境变量 QB_BACKEND_BIN（PyInstaller 单 binary 路径）
    // 退化到本仓库 python -m uvicorn (开发期)
    if let Ok(bin) = std::env::var("QB_BACKEND_BIN") {
        Command::new(bin)
            .arg("--port")
            .arg("18234")
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|e| format!("spawn backend bin failed: {}", e))
    } else {
        // 开发期: 依赖系统 python
        Command::new("python")
            .args([
                "-m",
                "uvicorn",
                "--app-dir",
                "app/backend",
                "app.main:app",
                "--port",
                "18234",
            ])
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|e| format!("spawn python failed: {} (set QB_BACKEND_BIN env to packed binary)", e))
    }
}

#[tauri::command]
fn backend_health(state: State<BackendProcess>) -> Result<String, String> {
    let guard = state.0.lock().map_err(|e| e.to_string())?;
    match &*guard {
        Some(child) => Ok(format!("backend running pid={}", child.id())),
        None => Err("backend not started".into()),
    }
}

#[tauri::command]
fn backend_restart(state: State<BackendProcess>) -> Result<String, String> {
    let mut guard = state.0.lock().map_err(|e| e.to_string())?;
    if let Some(mut child) = guard.take() {
        let _ = child.kill();
        let _ = child.wait();
    }
    let new_child = spawn_backend()?;
    let pid = new_child.id();
    *guard = Some(new_child);
    Ok(format!("backend restarted pid={}", pid))
}

/// 桌面端运行入口。被 main.rs 调用；mobile_entry_point 便于未来移动端共享。
#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let backend = match spawn_backend() {
        Ok(c) => Some(c),
        Err(e) => {
            eprintln!("WARN: backend 启动失败 ({}); 前端仍可加载但 API 不可用", e);
            None
        }
    };

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_os::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(BackendProcess(Mutex::new(backend)))
        .invoke_handler(tauri::generate_handler![backend_health, backend_restart])
        .setup(|app| {
            // 启动后弹窗到主窗口
            #[cfg(debug_assertions)]
            {
                let window = app.get_webview_window("main").unwrap();
                window.open_devtools();
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Tauri application")
        .run(|app_handle, event| {
            if let RunEvent::Exit = event {
                // 应用退出时清理 backend 子进程。
                // 先把 child 从锁里取出来（锁守卫在内层块结束即释放），
                // 再 kill/wait，避免 State 借用与锁临时量的生命周期冲突。
                let state: State<BackendProcess> = app_handle.state();
                let child = state
                    .0
                    .lock()
                    .ok()
                    .and_then(|mut guard| guard.take());
                if let Some(mut child) = child {
                    eprintln!("INFO: killing backend pid={}", child.id());
                    let _ = child.kill();
                    let _ = child.wait();
                }
            }
        });
}
