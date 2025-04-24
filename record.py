import sounddevice as sd
import soundfile as sf
import tkinter as tk
from tkinter import messagebox, ttk, filedialog
import numpy as np
import os
import time
import threading
import datetime


class AudioRecorder:
    def __init__(self, root):
        self.root = root
        self.root.title("PC内部音声録音アプリ")
        self.root.geometry("420x380")  # ウィンドウサイズ
        self.is_recording = False
        self.audio_data = []
        self.stream = None
        self.volume_level = 0
        self.volume_meter_active = False
        self.recording_start_time = None
        self.recording_timer = None

        # 現在の作業ディレクトリを取得
        self.current_dir = os.getcwd()
        self.audio_dir = os.path.join(self.current_dir, 'audio_data')

        # audio_dataフォルダが存在しない場合は作成
        if not os.path.exists(self.audio_dir):
            os.makedirs(self.audio_dir)

        # file_nameはprefixのあとYYYYMMDD_HHMMSSを付与したファイル名にする
        file_name_prefix = "recorded_audio_"
        current_time = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.filename = os.path.join(self.audio_dir, f"{file_name_prefix}{current_time}.wav")

        # デバイスリストの取得
        self.devices = sd.query_devices()
        self.input_devices = []
        self.input_device_indices = []

        # 入力デバイスだけをリストアップ
        for i, device in enumerate(self.devices):
            if device['max_input_channels'] > 0:
                name = f"{device['name']} (入力ch: {device['max_input_channels']})"
                self.input_devices.append(name)
                self.input_device_indices.append(i)

        # UIの作成
        frame = tk.Frame(root)
        frame.pack(pady=10, padx=20, fill=tk.BOTH, expand=True)

        tk.Label(frame, text="録音デバイスを選択:", font=("Arial", 11)).pack(anchor="w", pady=5)

        # デバイス選択用コンボボックス
        self.device_var = tk.StringVar()
        self.device_combo = ttk.Combobox(frame, textvariable=self.device_var, values=self.input_devices, width=50)
        self.device_combo.pack(pady=5, fill=tk.X)
        self.device_combo.bind("<<ComboboxSelected>>", self.on_device_selected)

        # ステレオミキサーを自動選択（存在する場合）
        stereo_mix_found = False
        for i, device_name in enumerate(self.input_devices):
            if "ステレオ" in device_name or "Stereo Mix" in device_name:
                self.device_combo.current(i)
                stereo_mix_found = True
                break

        if not stereo_mix_found and self.input_devices:
            self.device_combo.current(0)

        # ファイル保存場所
        file_frame = tk.Frame(frame)
        file_frame.pack(fill=tk.X, pady=10)

        tk.Label(file_frame, text="保存先:", font=("Arial", 11)).pack(side=tk.LEFT, padx=(0, 5))
        self.file_path_var = tk.StringVar(value=self.filename)
        self.file_entry = tk.Entry(file_frame, textvariable=self.file_path_var, width=40)
        self.file_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.browse_btn = tk.Button(file_frame, text="参照", command=self.browse_file)
        self.browse_btn.pack(side=tk.RIGHT, padx=5)

        # 録音時間表示フレーム
        time_frame = tk.Frame(frame)
        time_frame.pack(fill=tk.X, pady=5)

        tk.Label(time_frame, text="録音時間:", font=("Arial", 11)).pack(side=tk.LEFT, padx=(0, 5))

        self.time_label = tk.Label(time_frame, text="00:00:00", font=("Arial", 12, "bold"), fg="blue")
        self.time_label.pack(side=tk.LEFT, padx=5)

        # 音量メーターフレーム
        volume_frame = tk.Frame(frame)
        volume_frame.pack(fill=tk.X, pady=10)

        tk.Label(volume_frame, text="音量レベル:", font=("Arial", 11)).pack(side=tk.LEFT, padx=(0, 5))

        # 音量メーター
        meter_frame = tk.Frame(volume_frame)
        meter_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.volume_meter = ttk.Progressbar(meter_frame, orient="horizontal", length=300, mode="determinate")
        self.volume_meter.pack(fill=tk.X, expand=True)

        self.volume_label = tk.Label(volume_frame, text="0 dB", width=6)
        self.volume_label.pack(side=tk.RIGHT, padx=5)

        # ステータス表示
        self.status_frame = tk.Frame(frame, relief=tk.SUNKEN, borderwidth=1)
        self.status_frame.pack(fill=tk.X, pady=10)
        self.status_label = tk.Label(self.status_frame, text="待機中...", font=("Arial", 12), pady=5)
        self.status_label.pack()

        # 録音状態表示
        self.record_status = tk.Label(frame, text="", fg="gray")
        self.record_status.pack(pady=5)

        # ボタンフレーム
        btn_frame = tk.Frame(frame)
        btn_frame.pack(pady=10)

        # 録音ボタン
        self.record_button = tk.Button(btn_frame, text="録音開始", command=self.toggle_recording,
                                       width=15, height=2, bg="#4CAF50", fg="white")
        self.record_button.pack(side=tk.LEFT, padx=10)

        # 再生ボタン
        self.play_button = tk.Button(btn_frame, text="再生", command=self.play_recording,
                                     width=15, height=2, state=tk.DISABLED)
        self.play_button.pack(side=tk.LEFT, padx=10)

        # 音量モニタリングを開始
        self.start_volume_monitoring()

    def on_device_selected(self, event):
        """デバイスが選択されたときに音量モニタリングを再開"""
        if self.volume_meter_active:
            self.stop_volume_monitoring()
            self.start_volume_monitoring()

    def start_volume_monitoring(self):
        """音量モニタリングを開始"""
        selected_index = self.device_combo.current()
        if selected_index < 0 or not self.input_devices:
            self.volume_meter.config(value=0)
            self.volume_label.config(text="0 dB")
            return

        device_index = self.input_device_indices[selected_index]
        device_info = self.devices[device_index]
        channels = min(2, device_info['max_input_channels'])

        try:
            # 別スレッドでモニタリングを行う
            self.volume_meter_active = True
            self.monitor_thread = threading.Thread(target=self.monitor_volume, args=(device_index, channels))
            self.monitor_thread.daemon = True  # メインスレッド終了時に自動終了
            self.monitor_thread.start()
        except Exception as e:
            print(f"音量モニタリングの開始に失敗: {e}")
            self.volume_meter_active = False

    def stop_volume_monitoring(self):
        """音量モニタリングを停止"""
        self.volume_meter_active = False
        if hasattr(self, 'monitor_stream') and self.monitor_stream is not None:
            self.monitor_stream.stop()
            self.monitor_stream.close()
            self.monitor_stream = None

    def monitor_volume(self, device_index, channels):
        """別スレッドで実行する音量モニタリング"""
        try:
            self.monitor_stream = sd.InputStream(
                device=device_index,
                channels=channels,
                callback=self.volume_callback,
                blocksize=4096,
                samplerate=44100
            )

            with self.monitor_stream:
                while self.volume_meter_active:
                    time.sleep(0.1)  # スリープ時間を短く

        except Exception as e:
            print(f"音量モニタリングエラー: {e}")
        finally:
            self.volume_meter_active = False

    def volume_callback(self, indata, frames, time, status):
        """音量レベルをメーターに表示するコールバック"""
        if status:
            print(f"音量モニタリングステータス: {status}")

        # 音量レベルの計算 (RMS)
        volume_norm = np.linalg.norm(indata) / np.sqrt(frames)

        # デシベル変換 (-60dB から 0dB)
        if volume_norm > 0:
            db = 20 * np.log10(volume_norm)
        else:
            db = -60

        # -60dB未満を-60dBに制限
        db = max(-60, db)

        # 音量メーターの更新（0-100のスケールに変換）
        # -60dB → 0%, 0dB → 100%
        meter_value = (db + 60) / 60 * 100

        # UIスレッドから安全に呼び出す
        self.root.after(0, self.update_volume_meter, meter_value, db)

    def update_volume_meter(self, meter_value, db):
        """UI更新用メソッド（メインスレッドから呼び出される）"""
        self.volume_meter.config(value=meter_value)
        self.volume_label.config(text=f"{db:.1f} dB")

        # 音量レベルに応じて色を変更
        if meter_value > 80:  # -12dB以上
            self.volume_meter.configure(style="Red.Horizontal.TProgressbar")
        elif meter_value > 60:  # -24dB以上
            self.volume_meter.configure(style="Yellow.Horizontal.TProgressbar")
        else:
            self.volume_meter.configure(style="Green.Horizontal.TProgressbar")

    def update_recording_time(self):
        """録音時間を更新するメソッド"""
        if self.is_recording and self.recording_start_time:
            # 現在の録音時間を計算
            elapsed = time.time() - self.recording_start_time
            # 時間をフォーマット (HH:MM:SS)
            formatted_time = str(datetime.timedelta(seconds=int(elapsed)))
            # 表示を更新
            self.time_label.config(text=formatted_time)
            # 1秒後に再度更新
            self.recording_timer = self.root.after(1000, self.update_recording_time)

    def browse_file(self):
        initial_dir = os.path.dirname(self.file_path_var.get())
        selected_file = filedialog.asksaveasfilename(
            initialdir=initial_dir,
            title="録音ファイルの保存先を選択",
            filetypes=(("WAV files", "*.wav"), ("All files", "*.*")),
            defaultextension=".wav"
        )
        if selected_file:
            self.file_path_var.set(selected_file)
            self.filename = selected_file

    def toggle_recording(self):
        if not self.is_recording:
            selected_index = self.device_combo.current()
            if selected_index < 0:
                messagebox.showerror("エラー", "デバイスを選択してください")
                return

            self.filename = self.file_path_var.get()
            if not self.filename:
                messagebox.showerror("エラー", "保存先ファイルを指定してください")
                return

            device_index = self.input_device_indices[selected_index]
            device_info = self.devices[device_index]
            channels = min(2, device_info['max_input_channels'])

            try:
                # 録音中は音量モニタリングを停止（リソース競合回避）
                self.stop_volume_monitoring()

                self.is_recording = True
                self.record_button.config(text="録音停止", bg="#F44336")
                self.status_label.config(text=f"録音中...")
                self.record_status.config(text=f"デバイス: {device_info['name']} / チャンネル: {channels}", fg="red")
                self.play_button.config(state=tk.DISABLED)
                self.audio_data = []

                # 録音開始時間を記録
                self.recording_start_time = time.time()
                # 録音時間の更新を開始
                self.update_recording_time()

                # 録音開始
                self.stream = sd.InputStream(
                    samplerate=fs,
                    channels=channels,
                    device=device_index,
                    callback=self.audio_callback
                )
                self.stream.start()

            except Exception as e:
                self.is_recording = False
                self.recording_start_time = None
                if self.recording_timer:
                    self.root.after_cancel(self.recording_timer)
                    self.recording_timer = None
                messagebox.showerror("録音エラー", f"録音の開始に失敗しました: {str(e)}")
                self.record_button.config(text="録音開始", bg="#4CAF50")
                self.status_label.config(text="待機中...")
                self.record_status.config(text="", fg="gray")
                self.time_label.config(text="00:00:00")
                # 音量モニタリングを再開
                self.start_volume_monitoring()
        else:
            # 録音停止
            self.stop_recording()
            # 音量モニタリングを再開
            self.start_volume_monitoring()

    def stop_recording(self):
        self.is_recording = False

        # 録音時間タイマーを停止
        if self.recording_timer:
            self.root.after_cancel(self.recording_timer)
            self.recording_timer = None

        # 録音時間を最終値に更新
        if self.recording_start_time:
            elapsed = time.time() - self.recording_start_time
            formatted_time = str(datetime.timedelta(seconds=int(elapsed)))
            self.time_label.config(text=formatted_time)
            # 録音時間を保存（ファイル名に使用するなど）
            self.recording_duration = formatted_time

        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None

        if self.audio_data:
            # 録音データの保存
            try:
                if len(self.audio_data) > 0:
                    audio_np = np.concatenate(self.audio_data, axis=0)

                    # 保存先ディレクトリが存在するか確認
                    save_dir = os.path.dirname(self.filename)
                    if save_dir and not os.path.exists(save_dir):
                        os.makedirs(save_dir)

                    # ファイル保存
                    sf.write(self.filename, audio_np, fs)

                    self.status_label.config(text="録音完了！")
                    self.record_status.config(
                        text=f"ファイル保存先: {self.filename} (録音時間: {self.recording_duration})",
                        fg="green"
                    )
                    self.play_button.config(state=tk.NORMAL)

                    messagebox.showinfo(
                        "完了",
                        f"録音が完了しました。\nファイル: {self.filename}\n録音時間: {self.recording_duration}"
                    )
                else:
                    self.status_label.config(text="録音データがありません")
                    self.record_status.config(text="", fg="gray")
            except Exception as e:
                error_msg = f"ファイルの保存に失敗しました: {str(e)}"
                self.status_label.config(text="保存エラー")
                self.record_status.config(text=error_msg, fg="red")
                messagebox.showerror("保存エラー", error_msg)
        else:
            self.status_label.config(text="録音データが取得できませんでした")

        self.record_button.config(text="録音開始", bg="#4CAF50")

    def audio_callback(self, indata, frames, time, status):
        if status:
            print(f"Status: {status}")
        if self.is_recording:
            self.audio_data.append(indata.copy())

            # 録音中も音量メーターを更新
            volume_norm = np.linalg.norm(indata) / np.sqrt(frames)
            if volume_norm > 0:
                db = 20 * np.log10(volume_norm)
            else:
                db = -60
            db = max(-60, db)
            meter_value = (db + 60) / 60 * 100
            self.root.after(0, self.update_volume_meter, meter_value, db)

    def play_recording(self):
        if os.path.exists(self.filename):
            try:
                # プラットフォームに応じた再生コマンド
                if os.name == 'nt':  # Windows
                    os.startfile(self.filename)
                elif os.name == 'posix':  # macOS, Linux
                    import subprocess
                    opener = 'open' if sys.platform == 'darwin' else 'xdg-open'
                    subprocess.call([opener, self.filename])
            except Exception as e:
                messagebox.showerror("再生エラー", f"ファイルの再生に失敗しました: {str(e)}")
        else:
            messagebox.showerror("エラー", "録音ファイルが見つかりません")

    def __del__(self):
        """オブジェクト破棄時に呼ばれるメソッド"""
        self.stop_volume_monitoring()
        if self.recording_timer:
            self.root.after_cancel(self.recording_timer)


# メイン関数
if __name__ == '__main__':
    fs = 44100  # サンプリング周波数
    try:
        import sys

        # スタイルの設定（音量メーターの色）
        root = tk.Tk()
        style = ttk.Style()
        style.configure("Green.Horizontal.TProgressbar", background='green')
        style.configure("Yellow.Horizontal.TProgressbar", background='yellow')
        style.configure("Red.Horizontal.TProgressbar", background='red')

        app = AudioRecorder(root)
        root.mainloop()
    except Exception as e:
        messagebox.showerror("アプリケーションエラー", f"エラーが発生しました: {str(e)}")