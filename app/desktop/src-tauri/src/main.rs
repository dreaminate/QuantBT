// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

// 全部逻辑在 lib.rs（Tauri 2 惯例 [lib] name=quantbt_desktop_lib）。
// main.rs 只是桌面端的瘦入口，调用 quantbt_desktop_lib::run()。
fn main() {
    quantbt_desktop_lib::run()
}
