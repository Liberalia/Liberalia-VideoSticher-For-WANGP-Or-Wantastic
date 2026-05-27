# 🎬 CPU Video Stitcher Plugin for Wan2GP

A premium, highly optimized **Gradio-based plugin** for the **Wan2GP** generation suite that allows you to seamlessly merge, tile, or stitch two videos together using **100% CPU background processing**.

This plugin utilizes **FFmpeg** to do all of the heavy lifting. By executing entirely on the CPU, it leaves your GPU completely unburdened, allowing you to **continue generating high-fidelity AI animations and models on your GPU** while stitching operations run in the background!

---

## ✨ Key Features

*   ⚡ **GPU-Free Background Processing:** Runs asynchronously on the CPU via robust FFmpeg subprocess calls. Keep generating videos with Wan2GP without VRAM or GPU performance hits.
*   📐 **Multiple Stitching Layouts:**
    *   **Sequential (A then B):** Plays Video A in its entirety, followed immediately by Video B.
    *   **Side-by-Side (Horizontal):** Plays both videos simultaneously in a horizontal split-screen configuration.
    *   **Top-and-Bottom (Vertical):** Plays both videos simultaneously stacked vertically in a split-screen configuration.
*   🔄 **Aspect Ratio & Canvas Scaling:** Automatically handles unequal resolutions. Rescales and black-pads input videos safely to target dimensions while perfectly preserving their original aspect ratios (no stretching or distortion).
*   🔊 **Advanced Audio Engine:**
    *   Detects if input streams contain audio tracks.
    *   Resamples diverse audio tracks to a uniform `48000Hz stereo` format for seamless processing.
    *   Supports dynamic audio mapping: **Concatenate/Sequential**, **Mix Both (Simultaneous `amix`)**, **Keep A Only**, **Keep B Only**, or **Mute**.
    *   Pads missing audio tracks with silent channels so complex layout filters never fail.
*   ❄️ **Smart Length Matching:** For side-by-side or vertical layouts of different lengths, the shorter video automatically freezes on its final frame (`eof_action=pass`) instead of terminating abruptly or crashing FFmpeg.
*   📊 **Real-Time Progress Tracking:** Parsed from raw FFmpeg standard error output stream logs to update a smooth, interactive Gradio progress bar.
*   🎨 **High-Fidelity GIF Support:** Exports to standard formats (`.mp4`, `.mkv`, `.mov`) or generates highly optimized, high-fidelity `.gif` animations utilizing a custom two-pass palette map (`palettegen` / `paletteuse`) to prevent color banding.

---

## 📁 Repository Structure

```
wan2gp-video-stitcher/
├── __init__.py           # Package initialization
├── plugin_info.json      # Plugin metadata (for Wan2GP plugin manager)
├── plugin.py             # Gradio UI components and FFmpeg execution pipeline
└── README.md             # You are here!
```

---

## 🚀 Installation & Integration

### Step 1: Place the Plugin Folder
Clone or download this repository, then place the folder under the `wan2gp/plugins/` directory of your Wan2GP installation:
```bash
# Workspace path structure:
wan2gp/
└── plugins/
    └── wan2gp-video-stitcher/
        ├── __init__.py
        ├── plugin.py
        └── plugin_info.json
```

### Step 2: Register in Config
Open your project's root configuration file `wgp_config.json` and append `"wan2gp-video-stitcher"` to your `enabled_plugins` array:
```json
"enabled_plugins": [
    "wan2gp-flashvsr",
    "wan2gp-gallery",
    "wan2gp-queue-editor",
    "wan2gp-motion-designer",
    "wan2gp-models-manager",
    "wan2gp-process-full-video",
    "wan2gp-video-stitcher"
]
```

### Step 3: Launch Wan2GP
Run your normal launch script (e.g., `Launch_Wan2GP.bat`). The application will discover, compile, and seamlessly add the **CPU Video Stitcher** tab to the main interface!

---

## 🛠️ Configuration Controls

| Option | Choices | Description |
| :--- | :--- | :--- |
| **Stitch Layout Mode** | `Sequential`, `Side-by-Side`, `Top-and-Bottom` | Controls whether videos play one after another or side-by-side/stacked vertically. |
| **Output Video Resolution**| `Match Video A`, `Match Video B`, `Custom Resolution`| Determines the final target canvas size. Non-matching input dimensions are padded. |
| **Target Framerate (FPS)** | `Match Video A`, `Match Video B`, `30 FPS`, `60 FPS`, `24 FPS`| Automatically adjusts input streams to the selected FPS using a smooth filter. |
| **Audio Mixing Options** | `Concatenate`, `Mix Both`, `Keep A`, `Keep B`, `Mute`| Configures audio combining/trimming strategies based on the selected layout. |
| **Output File Format** | `mp4`, `mkv`, `mov`, `gif` | Target video/animation file extension container. |

---

## 📖 Underlying Filter Graphs

This plugin programmatically constructs complex FFmpeg filtergraphs depending on your selections. Below is an overview of how the key modes operate:

### 1. Sequential Mode (Scale & Concatenate)
Preserves aspect ratio using scaling and padding, then links the outputs:
```python
vfilter0 = "[0:v]scale='2*trunc(min(W,H*(iw/ih))/2)':'2*trunc(min(H,W/(iw/ih))/2)',pad=W:H:'(W-iw)/2':'(H-ih)/2':color=black,fps=FPS[v0]"
vfilter1 = "[1:v]scale='2*trunc(min(W,H*(iw/ih))/2)':'2*trunc(min(H,W/(iw/ih))/2)',pad=W:H:'(W-iw)/2':'(H-ih)/2':color=black,fps=FPS[v1]"
filter_complex = [vfilter0, vfilter1, "[v0][v1]concat=n=2:v=1:a=0[outv]"]
```

### 2. Side-by-Side (Split Screen Grid)
Generates a background color canvas and lays each scaled video on top:
```python
filter_complex.append("color=s=WxH:d=max_dur:r=FPS[bg]")
filter_complex.append("[bg][v0]overlay=x=0:y=0:eof_action=pass[bg1]")
filter_complex.append("[bg1][v1]overlay=x=W_each:y=0:eof_action=pass[outv]")
```

### 3. High-Quality Two-Pass GIF Conversion
For highly fidelity `.gif` files, the plugin splits the video output to generate a global color map to minimize dithering and color distortion:
```python
gif_filter = "...; [outv]split[gif1][gif2]; [gif1]palettegen[pal]; [gif2][pal]paletteuse[outv_gif]"
```

---

## 📝 License
This project is open-source and available under the Apachie 2.0 License. Feel free to copy, modify, and distribute it as needed!
