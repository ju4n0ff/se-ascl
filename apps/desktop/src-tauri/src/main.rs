use tauri::Manager;

#[tauri::command]
fn greet(name: &str) -> String {
    format!("Hola, {}! Bienvenido a SeñasCL.", name)
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![greet])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
