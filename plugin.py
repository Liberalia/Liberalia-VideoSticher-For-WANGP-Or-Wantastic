import os
import re
import subprocess
import time
import gradio as gr
from datetime import datetime

from shared.utils.plugins import WAN2GPPlugin

PlugIn_Name = "CPU Video Stitcher"
PlugIn_Id = "wan2gp-video-stitcher"


class ConfigTabPlugin(WAN2GPPlugin):
    def setup_ui(self):
        self.request_component("state")
        self.request_component("main_tabs")
        self.add_tab(
            tab_id=PlugIn_Id,
            label=PlugIn_Name,
            component_constructor=self.create_stitcher_ui
        )

    def create_stitcher_ui(self, api_session):
        
        def update_res_visibility(strategy):
            if strategy == "Custom Resolution":
                return gr.update(visible=True), gr.update(visible=True)
            else:
                return gr.update(visible=False), gr.update(visible=False)

        def stitch_videos_process(
            video1, video2, mode, res_strategy, custom_w, custom_h, 
            fps_strategy, audio_mode, format_ext,
            progress=gr.Progress(track_tqdm=False)
        ):
            if not video1 or not video2:
                raise gr.Error("Please select and upload both Video A and Video B.")

            progress(0.01, desc="Probing media files...")
            
            # 1. Probe video metadata
            try:
                from shared.utils.video_decode import probe_video_stream_metadata
                meta1 = probe_video_stream_metadata(video1)
                meta2 = probe_video_stream_metadata(video2)
            except Exception as e:
                raise gr.Error(f"Error probing input videos: {e}")

            if not meta1:
                raise gr.Error("Could not retrieve stream metadata for Video A.")
            if not meta2:
                raise gr.Error("Could not retrieve stream metadata for Video B.")

            # 2. Determine target width & height (sanitized to even numbers)
            if res_strategy == "Match Video A":
                W = meta1.get("display_width") or meta1.get("width") or 1280
                H = meta1.get("display_height") or meta1.get("height") or 720
            elif res_strategy == "Match Video B":
                W = meta2.get("display_width") or meta2.get("width") or 1280
                H = meta2.get("display_height") or meta2.get("height") or 720
            else:
                W = int(custom_w or 1280)
                H = int(custom_h or 720)

            # Even constraints
            W = (W // 2) * 2
            H = (H // 2) * 2

            # 3. Determine target FPS
            if fps_strategy == "Match Video A":
                FPS = meta1.get("fps_float") or meta1.get("fps") or 30.0
            elif fps_strategy == "Match Video B":
                FPS = meta2.get("fps_float") or meta2.get("fps") or 30.0
            else:
                try:
                    FPS = float(fps_strategy.split()[0])
                except Exception:
                    FPS = 30.0

            # 4. Check for audio presence
            try:
                from shared.utils.audio_video import extract_audio_tracks
                has_audio1 = extract_audio_tracks(video1, query_only=True) > 0
                has_audio2 = extract_audio_tracks(video2, query_only=True) > 0
            except Exception:
                has_audio1 = False
                has_audio2 = False

            dur1 = float(meta1.get("duration") or 0.0)
            dur2 = float(meta2.get("duration") or 0.0)

            # 5. Resolve FFmpeg binary
            try:
                from shared.utils.audio_video import _ffmpeg_binary
                ffmpeg_bin = _ffmpeg_binary()
            except Exception:
                ffmpeg_bin = "ffmpeg"

            # 6. Resolve Output Paths
            plugin_dir = os.path.dirname(os.path.abspath(__file__))
            outputs_dir = os.path.abspath(os.path.join(plugin_dir, "..", "..", "outputs"))
            os.makedirs(outputs_dir, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_filename = f"stitched_{timestamp}.{format_ext}"
            out_path = os.path.join(outputs_dir, out_filename)

            inputs = ["-i", video1, "-i", video2]
            filter_complex = []
            
            # Construct standard scale & pad filters to keep original aspect ratios (with black padding)
            vfilter0 = f"[0:v]scale='2*trunc(min({W},{H}*(iw/ih))/2)':'2*trunc(min({H},{W}/(iw/ih))/2)',pad={W}:{H}:'({W}-iw)/2':'({H}-ih)/2':color=black,fps={FPS}[v0]"
            vfilter1 = f"[1:v]scale='2*trunc(min({W},{H}*(iw/ih))/2)':'2*trunc(min({H},{W}/(iw/ih))/2)',pad={W}:{H}:'({W}-iw)/2':'({H}-ih)/2':color=black,fps={FPS}[v1]"

            filter_complex.append(vfilter0)
            filter_complex.append(vfilter1)

            video_mapped = "[outv]"
            audio_mapped = None
            max_dur = 0.0

            # Stitching Modes logic
            if "Sequential" in mode:
                max_dur = dur1 + dur2
                filter_complex.append("[v0][v1]concat=n=2:v=1:a=0[outv]")

                if audio_mode == "Mute (No Audio)":
                    audio_mapped = None
                elif audio_mode == "Keep Video A Audio Only":
                    if has_audio1:
                        filter_complex.append(f"[0:a]aresample=48000,aformat=channel_layouts=stereo[a0]")
                        filter_complex.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={dur2}[a1]")
                        filter_complex.append("[a0][a1]concat=n=2:v=0:a=1[outa]")
                        audio_mapped = "[outa]"
                elif audio_mode == "Keep Video B Audio Only":
                    if has_audio2:
                        filter_complex.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={dur1}[a0]")
                        filter_complex.append(f"[1:a]aresample=48000,aformat=channel_layouts=stereo[a1]")
                        filter_complex.append("[a0][a1]concat=n=2:v=0:a=1[outa]")
                        audio_mapped = "[outa]"
                else: # Concatenate / Sequential
                    if has_audio1 and has_audio2:
                        filter_complex.append(f"[0:a]aresample=48000,aformat=channel_layouts=stereo[a0]")
                        filter_complex.append(f"[1:a]aresample=48000,aformat=channel_layouts=stereo[a1]")
                        filter_complex.append("[a0][a1]concat=n=2:v=0:a=1[outa]")
                        audio_mapped = "[outa]"
                    elif has_audio1:
                        filter_complex.append(f"[0:a]aresample=48000,aformat=channel_layouts=stereo[a0]")
                        filter_complex.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={dur2}[a1]")
                        filter_complex.append("[a0][a1]concat=n=2:v=0:a=1[outa]")
                        audio_mapped = "[outa]"
                    elif has_audio2:
                        filter_complex.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={dur1}[a0]")
                        filter_complex.append(f"[1:a]aresample=48000,aformat=channel_layouts=stereo[a1]")
                        filter_complex.append("[a0][a1]concat=n=2:v=0:a=1[outa]")
                        audio_mapped = "[outa]"

            elif "Side-by-Side" in mode:
                max_dur = max(dur1, dur2)
                W_each = (W // 4) * 2
                
                # Resize each video to half of the final width, maintaining their aspect ratios
                filter_complex[0] = f"[0:v]scale='2*trunc(min({W_each},{H}*(iw/ih))/2)':'2*trunc(min({H},{W_each}/(iw/ih))/2)',pad={W_each}:{H}:'({W_each}-iw)/2':'({H}-ih)/2':color=black,fps={FPS}[v0]"
                filter_complex[1] = f"[1:v]scale='2*trunc(min({W_each},{H}*(iw/ih))/2)':'2*trunc(min({H},{W_each}/(iw/ih))/2)',pad={W_each}:{H}:'({W_each}-iw)/2':'({H}-ih)/2':color=black,fps={FPS}[v1]"

                # Create black canvas, overlay both side-by-side
                filter_complex.append(f"color=s={W}x{H}:d={max_dur}:r={FPS}[bg]")
                filter_complex.append(f"[bg][v0]overlay=x=0:y=0:eof_action=pass[bg1]")
                filter_complex.append(f"[bg1][v1]overlay=x={W_each}:y=0:eof_action=pass[outv]")

                if audio_mode == "Mute (No Audio)":
                    audio_mapped = None
                elif audio_mode == "Keep Video A Audio Only":
                    if has_audio1:
                        audio_mapped = "0:a"
                elif audio_mode == "Keep Video B Audio Only":
                    if has_audio2:
                        audio_mapped = "1:a"
                else: # Mix Both
                    if has_audio1 and has_audio2:
                        filter_complex.append(f"[0:a]aresample=48000,aformat=channel_layouts=stereo[a0]")
                        filter_complex.append(f"[1:a]aresample=48000,aformat=channel_layouts=stereo[a1]")
                        filter_complex.append(f"[a0][a1]amix=inputs=2:duration=longest[outa]")
                        audio_mapped = "[outa]"
                    elif has_audio1:
                        audio_mapped = "0:a"
                    elif has_audio2:
                        audio_mapped = "1:a"

            else: # Top-and-Bottom
                max_dur = max(dur1, dur2)
                H_each = (H // 4) * 2
                
                # Resize each video to half of the final height, maintaining aspect ratios
                filter_complex[0] = f"[0:v]scale='2*trunc(min({W},{H_each}*(iw/ih))/2)':'2*trunc(min({H_each},{W}/(iw/ih))/2)',pad={W}:{H_each}:'({W}-iw)/2':'({H_each}-ih)/2':color=black,fps={FPS}[v0]"
                filter_complex[1] = f"[1:v]scale='2*trunc(min({W},{H_each}*(iw/ih))/2)':'2*trunc(min({H_each},{W}/(iw/ih))/2)',pad={W}:{H_each}:'({W}-iw)/2':'({H_each}-ih)/2':color=black,fps={FPS}[v1]"

                # Create black canvas, stack top and bottom
                filter_complex.append(f"color=s={W}x{H}:d={max_dur}:r={FPS}[bg]")
                filter_complex.append(f"[bg][v0]overlay=x=0:y=0:eof_action=pass[bg1]")
                filter_complex.append(f"[bg1][v1]overlay=x=0:y={H_each}:eof_action=pass[outv]")

                if audio_mode == "Mute (No Audio)":
                    audio_mapped = None
                elif audio_mode == "Keep Video A Audio Only":
                    if has_audio1:
                        audio_mapped = "0:a"
                elif audio_mode == "Keep Video B Audio Only":
                    if has_audio2:
                        audio_mapped = "1:a"
                else: # Mix Both
                    if has_audio1 and has_audio2:
                        filter_complex.append(f"[0:a]aresample=48000,aformat=channel_layouts=stereo[a0]")
                        filter_complex.append(f"[1:a]aresample=48000,aformat=channel_layouts=stereo[a1]")
                        filter_complex.append(f"[a0][a1]amix=inputs=2:duration=longest[outa]")
                        audio_mapped = "[outa]"
                    elif has_audio1:
                        audio_mapped = "0:a"
                    elif has_audio2:
                        audio_mapped = "1:a"

            # 7. Build FFmpeg subprocess arguments
            cmd = [ffmpeg_bin, "-y", "-v", "info"]
            cmd.extend(inputs)
            cmd.extend(["-filter_complex", "; ".join(filter_complex)])
            cmd.extend(["-map", video_mapped])
            if audio_mapped:
                cmd.extend(["-map", audio_mapped])

            if format_ext == "gif":
                # High-quality color palettes generation for transparent or rich GIF conversion
                gif_filter = "; ".join(filter_complex) + "; [outv]split[gif1][gif2]; [gif1]palettegen[pal]; [gif2][pal]paletteuse[outv_gif]"
                cmd = [ffmpeg_bin, "-y", "-v", "info"]
                cmd.extend(inputs)
                cmd.extend(["-filter_complex", gif_filter])
                cmd.extend(["-map", "[outv_gif]", out_path])
            else:
                cmd.extend([
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p",
                    "-preset", "medium",
                    "-crf", "23"
                ])
                if audio_mapped:
                    cmd.extend([
                        "-c:a", "aac",
                        "-b:a", "192k"
                    ])
                cmd.append(out_path)

            progress(0.05, desc="Executing FFmpeg stitching...")
            
            # Start process
            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                text=True, errors="ignore", bufsize=1
            )

            # Read stderr progress log
            while True:
                line = process.stderr.readline()
                if not line:
                    break
                match = re.search(r"time=(\d+):(\d+):(\d+\.\d+)", line)
                if match:
                    h, m, s = match.groups()
                    current_time = float(h)*3600 + float(m)*60 + float(s)
                    if max_dur > 0:
                        ratio = min(0.98, 0.05 + 0.93 * (current_time / max_dur))
                        progress(ratio, desc=f"Merging frames: {current_time:.1f}s / {max_dur:.1f}s")

            ret_code = process.wait()
            if ret_code != 0:
                err_text = process.stderr.read()
                raise gr.Error(f"FFmpeg failed with exit code {ret_code}.\nError details: {err_text}")

            progress(1.0, desc="Finished stitching!")
            gr.Info("Video successfully stitched and saved!")
            return out_path, gr.update(visible=True, value=out_path)

        # UI Layout Design (WOW Aesthetics)
        with gr.Column(elem_id="video-stitcher-tab"):
            
            # Premium Header
            gr.HTML(
                """
                <div style="background: linear-gradient(135deg, #1b2735 0%, #090a0f 100%); 
                            padding: 24px 30px; 
                            border-radius: 16px; 
                            color: white; 
                            margin-bottom: 24px; 
                            border: 1px solid rgba(255,255,255,0.08); 
                            box-shadow: 0 10px 30px rgba(0,0,0,0.4);">
                    <div style="display: flex; align-items: center; gap: 16px;">
                        <div style="background: linear-gradient(45deg, #a770ef, #cf8bf3, #fdbb2d); 
                                    padding: 12px; 
                                    border-radius: 12px; 
                                    display: flex; 
                                    align-items: center; 
                                    justify-content: center; 
                                    box-shadow: 0 4px 15px rgba(207, 139, 243, 0.4);">
                            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                                <path d="M23 7a2 2 0 0 0-2.45-1.45L16 7V5a2 2 0 0 0-2-2H2a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-2l4.55 1.45A2 2 0 0 0 23 17V7z"/>
                            </svg>
                        </div>
                        <div>
                            <h2 style="margin: 0; font-family: 'Outfit', sans-serif; font-size: 1.85rem; font-weight: 600; letter-spacing: -0.5px;">CPU Video Stitcher</h2>
                            <p style="margin: 4px 0 0 0; opacity: 0.75; font-size: 1.0rem; font-family: 'Inter', sans-serif;">
                                Stitch, join, or tile your videos together sequentially, horizontally, or vertically.
                            </p>
                        </div>
                    </div>
                    <div style="margin-top: 16px; padding: 10px 14px; background: rgba(255, 255, 255, 0.05); border-radius: 8px; border-left: 4px solid #fdbb2d; font-size: 0.88rem; opacity: 0.95;">
                        ⚡ <b>100% CPU Processing:</b> This plugin runs completely in the background using your CPU. Your GPU remains free to generate videos continuously!
                    </div>
                </div>
                """
            )

            # Upload Panel
            with gr.Row():
                with gr.Column(variant="panel"):
                    gr.HTML("<h3 style='margin: 0 0 10px 0; font-weight:600; color:#cf8bf3;'>Video A (First Input)</h3>")
                    video_a = gr.Video(label="Select Video A", sources=["upload"], interactive=True)
                with gr.Column(variant="panel"):
                    gr.HTML("<h3 style='margin: 0 0 10px 0; font-weight:600; color:#cf8bf3;'>Video B (Second Input)</h3>")
                    video_b = gr.Video(label="Select Video B", sources=["upload"], interactive=True)

            # Settings Panel
            with gr.Group(elem_id="stitcher_settings_group"):
                gr.HTML("<div style='padding: 12px 16px; background: rgba(255,255,255,0.03); border-bottom: 1px solid rgba(255,255,255,0.08);'><h3 style='margin:0; font-weight:600; font-size:1.15rem; color:#fdbb2d;'>Stitching Configuration</h3></div>")
                
                with gr.Row():
                    stitch_mode = gr.Dropdown(
                        choices=[
                            "Sequential (Play Video A, then Video B)",
                            "Side-by-Side (Horizontal Split-Screen)",
                            "Top-and-Bottom (Vertical Split-Screen)"
                        ],
                        value="Sequential (Play Video A, then Video B)",
                        label="Stitch Layout Mode",
                        info="Select how the videos should be merged spatially or temporally."
                    )
                    
                    out_res_strategy = gr.Dropdown(
                        choices=["Match Video A", "Match Video B", "Custom Resolution"],
                        value="Match Video A",
                        label="Output Video Resolution",
                        info="Rescales and black-pads input videos safely."
                    )

                with gr.Row():
                    custom_width = gr.Number(
                        value=1280, label="Custom Width (px)", visible=False, precision=0, minimum=64, step=2
                    )
                    custom_height = gr.Number(
                        value=720, label="Custom Height (px)", visible=False, precision=0, minimum=64, step=2
                    )

                with gr.Row():
                    fps_strat = gr.Dropdown(
                        choices=["Match Video A", "Match Video B", "30 FPS", "60 FPS", "24 FPS"],
                        value="Match Video A",
                        label="Target Framerate (FPS)",
                        info="Framerates will be smoothly aligned to match this target."
                    )
                    
                    audio_strat = gr.Dropdown(
                        choices=[
                            "Concatenate / Sequential",
                            "Mix Both Audios",
                            "Keep Video A Audio Only",
                            "Keep Video B Audio Only",
                            "Mute (No Audio)"
                        ],
                        value="Concatenate / Sequential",
                        label="Audio Mixing Options",
                        info="Configure how FFmpeg mixes or handles audio tracks."
                    )
                    
                    container_format = gr.Dropdown(
                        choices=["mp4", "mkv", "mov", "gif"],
                        value="mp4",
                        label="Output File Format",
                        info="Target file extension container."
                    )

            # Stitch Trigger
            stitch_btn = gr.Button(
                "Stitch Videos Together 🎬", 
                variant="primary",
                size="lg",
                elem_id="wgp_stitcher_action_btn"
            )
            
            # Output Panel
            with gr.Column(variant="panel", visible=False) as output_panel:
                gr.HTML("<h3 style='margin: 0 0 10px 0; font-weight:600; color:#cf8bf3;'>Stitched Output Video</h3>")
                output_video = gr.Video(label="Stitched Output", interactive=False)

            # Interactive visibilities
            out_res_strategy.change(
                fn=update_res_visibility,
                inputs=[out_res_strategy],
                outputs=[custom_width, custom_height]
            )

            # Action execution
            stitch_btn.click(
                fn=stitch_videos_process,
                inputs=[
                    video_a, video_b, stitch_mode, out_res_strategy, 
                    custom_width, custom_height, fps_strat, audio_strat, 
                    container_format
                ],
                outputs=[output_video, output_panel]
            )
