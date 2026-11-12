fn main() {
    tauri_build::build();

    #[cfg(target_os = "windows")]
    {
        if let Ok(out_dir) = std::env::var("OUT_DIR") {
            let manifest_path = std::path::PathBuf::from(out_dir).join("test-common-controls.manifest");
            let manifest = r#"<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<assembly xmlns="urn:schemas-microsoft-com:asm.v1" manifestVersion="1.0">
  <dependency>
    <dependentAssembly>
      <assemblyIdentity type="win32" name="Microsoft.Windows.Common-Controls" version="6.0.0.0" processorArchitecture="*" publicKeyToken="6595b64144ccf1df" language="*"/>
    </dependentAssembly>
  </dependency>
</assembly>
"#;
            if std::fs::write(&manifest_path, manifest).is_ok() {
                println!("cargo:rustc-link-arg-tests=/MANIFEST:EMBED");
                println!(
                    "cargo:rustc-link-arg-tests=/MANIFESTINPUT:{}",
                    manifest_path.display()
                );
            }
        }
    }
}
