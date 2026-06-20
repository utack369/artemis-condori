#!/Users/utano/artemis-condori/.venv/bin/python3
"""
Instagram リール動画自動生成パイプライン
バージョン：v1.0
スキル文書準拠：SKILL_リール動画制作完全プロセス.md

使い方：
    python3 pipeline_final.py '原稿テキスト' 'ロケーション名'
"""

import sys
import os
import re
import MeCab
import json
import glob
import random
import subprocess
import tempfile
import struct
import wave
import urllib.request
import urllib.error
from PIL import Image, ImageDraw, ImageFont

# config.py を読み込む
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config


NOTATION_FIX = {
    "浮腫み": "むくみ",
    "吹出物": "吹き出物",
    "罅割れ": "ひび割れ",
    "法令線": "ほうれい線",
    "倦怠感": "だるさ",
    "焦燥感": "そわそわ",
    "掻痒感": "かゆみ",
    "蕁麻疹": "じんましん",
    "肩凝り": "肩こり",
    "関節痛": "関節の痛み",
    "歯軋り": "歯ぎしり",
    "苛立ち": "イライラ",
    "抜毛": "抜け毛",
    "脱毛": "抜け毛",
    "眩暈": "めまい",
    "浮腫": "むくみ",
    "憂鬱": "ゆううつ",
    "苛々": "イライラ",
    "面皰": "ニキビ",
    "嘔気": "吐き気",
    "動悸": "どうき",
    "湿疹": "しっしん",
    "黒子": "ほくろ",
    "弛み": "たるみ",
    "窪み": "くぼみ",
    "翳り": "くすみ",
    "隈": "クマ",
    "皺": "シワ",
    "皹": "あかぎれ",
}


def fix_notation(text):
    for wrong, correct in NOTATION_FIX.items():
        text = text.replace(wrong, correct)
    return text

# テロップ/サムネ用：引用約物（「」『』・引用符）を完全除去（決定論ゲート）
_QUOTE_MARKS = ("「", "」", "『", "』", '"')
def strip_quote_marks(text):
    if not text:
        return text
    for ch in _QUOTE_MARKS:
        text = text.replace(ch, "")
    return text


# ============================================================
# STEP 1：Fish Audio TTS → 1.3倍速変換 → 無音カット
# ============================================================

def generate_tts(text, output_path):
    """Fish Audio APIでテキスト→音声変換"""
    for wrong, correct in config.TTS_READING_FIX.items():
        text = text.replace(wrong, correct)

    print("[STEP 1] Fish Audio TTSで音声生成中...")

    url = "https://api.fish.audio/v1/tts"
    payload = json.dumps({
        "text": text,
        "reference_id": config.FISH_MODEL_ID,
        "format": "wav",
        "latency": "normal"
    }).encode("utf-8")

    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Authorization", f"Bearer {config.FISH_API_KEY}")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            with open(output_path, "wb") as f:
                while True:
                    chunk = resp.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)
        print(f"  → TTS生成完了: {output_path}")
    except urllib.error.HTTPError as e:
        print(f"  ✗ Fish Audio APIエラー: {e.code} {e.reason}")
        body = e.read().decode("utf-8", errors="replace")
        print(f"    詳細: {body[:300]}")
        sys.exit(1)
    except Exception as e:
        print(f"  ✗ TTS生成失敗: {e}")
        sys.exit(1)


def speed_up_audio(input_path, output_path, speed=None):
    """FFmpegで音声を倍速変換"""
    if speed is None:
        speed = config.TTS_SPEED
    print(f"  → {speed}倍速に変換中...")
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-filter:a", f"atempo={speed}",
        "-vn", output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ✗ 倍速変換失敗: {result.stderr[:300]}")
        sys.exit(1)
    print(f"  → 倍速変換完了: {output_path}")


def remove_silence(input_path, output_path):
    """FFmpegで無音部分をカット"""
    print("  → 無音カット中...")
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-af", "silenceremove=stop_periods=-1:stop_duration=0.3:stop_threshold=-40dB",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ✗ 無音カット失敗: {result.stderr[:300]}")
        sys.exit(1)
    print(f"  → 無音カット完了: {output_path}")


def generate_tts_per_sentence(sentences, work_dir):
    """文ごとにTTSを生成し、結合したtts_final.wavと各文のdurationリストを返す"""
    print("[STEP 1] 文ごとにTTS生成中...")
    durations = []
    processed_paths = []

    for i, sentence in enumerate(sentences):
        raw = os.path.join(work_dir, f"tts_sentence_{i}_raw.wav")
        sped = os.path.join(work_dir, f"tts_sentence_{i}_sped.wav")
        final = os.path.join(work_dir, f"tts_sentence_{i}.wav")

        print(f"  [{i+1}/{len(sentences)}] {sentence[:30]}...")
        generate_tts(sentence, raw)
        speed_up_audio(raw, sped)
        remove_silence(sped, final)

        duration = get_audio_duration(final)
        durations.append(duration)
        processed_paths.append(final)
        print(f"    → duration: {duration:.3f}秒")

    # 全音声をffmpegで結合
    final_audio = os.path.join(work_dir, "tts_final.wav")
    list_file = os.path.join(work_dir, "tts_concat_list.txt")
    with open(list_file, "w") as f:
        for p in processed_paths:
            f.write(f"file '{p}'\n")

    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", list_file, "-c", "copy", final_audio
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ✗ 音声結合失敗: {result.stderr[:300]}")
        sys.exit(1)
    print(f"  → 全文結合完了: {final_audio}")

    return durations, final_audio


def get_audio_duration(path):
    """FFprobeで音声の長さ（秒）を取得"""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "csv=p=0", path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ✗ 音声長取得失敗: {result.stderr[:200]}")
        sys.exit(1)
    return float(result.stdout.strip())


# ============================================================
# STEP 2：文章を「。！？」で分割
# ============================================================



def _find_particle_positions(text, tagger):
    """MeCabで助詞の直後の位置（文字インデックス）を返す"""
    node = tagger.parseToNode(text)
    # まず全単語を収集
    words = []
    char_pos = 0
    while node:
        surface = node.surface
        feature = node.feature
        if surface:
            words.append({"surface": surface, "feature": feature, "end": char_pos + len(surface)})
            char_pos += len(surface)
        node = node.next

    positions = []
    for i, w in enumerate(words):
        if not w["feature"].startswith("助詞,"):
            continue
        # 接続助詞「て」「た」は文の途中なので除外
        if w["surface"] in ("て", "た"):
            continue
        # 次の単語も助詞の場合（「では」「には」「とは」等）、この助詞の直後では切らない
        if i + 1 < len(words) and words[i + 1]["feature"].startswith("助詞,"):
            continue
        # 「の」の直後が慣用パターンで始まる場合は除外（「のせい」「のため」等を分割しない）
        if w["surface"] == "の":
            rest = text[w["end"]:]
            if rest.startswith(("せい", "ため", "よう", "まま", "はず", "ほう", "うち", "もと", "かも")):
                continue
        positions.append(w["end"])

    return positions

def _find_word_boundaries(text, tagger):
    """MeCabで単語境界の位置（文字インデックス）を返す。補助動詞・接続助詞の直前は除外"""
    node = tagger.parseToNode(text)
    # まず全単語の情報を収集
    words = []
    char_pos = 0
    while node:
        surface = node.surface
        feature = node.feature
        if surface:
            words.append({"surface": surface, "feature": feature, "start": char_pos, "end": char_pos + len(surface)})
            char_pos += len(surface)
        node = node.next
    
    # 次の単語が接続助詞「て」「で」や補助動詞「しまう」「しまっ」「た」「ない」等の場合は
    # その直前を境界候補から除外（前の動詞と一体のため）
    skip_surfaces = {"て", "で", "しまっ", "しまう", "た", "ない", "なかっ", "ちゃっ", "じゃっ", "れ", "られ", "させ", "せ", "時間", "時", "日", "月", "年", "個", "人", "回"}
    skip_features_prefix = ("助詞,接続助詞", "動詞,非自立", "助動詞", "名詞,接尾", "動詞,接尾")
    
    positions = []
    for i in range(len(words) - 1):
        boundary = words[i]["end"]
        if boundary >= len(text):
            continue
        next_word = words[i + 1]
        # 次の単語が補助的な語なら、ここでは切らない
        next_is_auxiliary = False
        for prefix in skip_features_prefix:
            if next_word["feature"].startswith(prefix):
                next_is_auxiliary = True
                break
        if next_is_auxiliary and next_word["surface"] in skip_surfaces:
            continue
        positions.append(boundary)
    
    return positions


def split_sentences(text):
    """文章を句読点・読点で分割し、1区間16文字以内に収める（v3）"""
    print("[STEP 2] 文章を分割中...")
    MAX_CHARS = 16
    MIN_CHARS = 3

    # Step 1: 句読点（。！？）で一次分割
    parts = re.split(r'(?<=[。！？])', text)
    parts = [s.strip() for s in parts if s.strip()]

    # Step 2: 16文字超の区間を読点（、）で二次分割
    segments = []
    for part in parts:
        if len(part) <= MAX_CHARS:
            segments.append(part)
        else:
            sub_parts = re.split(r'(?<=、)', part)
            sub_parts = [s.strip() for s in sub_parts if s.strip()]
            segments.extend(sub_parts)

    # Step 3: 読点分割で短くなりすぎた区間を前後と結合（ただし句点をまたぐ結合は禁止）
    merged_step3 = []
    for seg in segments:
        if (merged_step3 
            and len(merged_step3[-1]) + len(seg) <= MAX_CHARS
            and "。" not in merged_step3[-1] 
            and "！" not in merged_step3[-1] 
            and "？" not in merged_step3[-1]):
            # 前の区間が句点を含まず、結合しても16文字以内なら結合
            merged_step3[-1] = merged_step3[-1] + seg
        else:
            merged_step3.append(seg)

    # Step 4: まだ16文字超の区間をMeCab助詞判定で分割
    tagger = MeCab.Tagger()
    final = []
    for seg in merged_step3:
        if len(seg) <= MAX_CHARS:
            final.append(seg)
        else:
            positions = _find_particle_positions(seg, tagger)
            half = len(seg) / 2
            best_pos = None
            best_score = float("inf")
            for pos in positions:
                left_len = pos
                right_len = len(seg) - pos
                # 分割後の各区間が短すぎないように（5文字以上を優先）
                if left_len >= MIN_CHARS and right_len >= MIN_CHARS:
                    score = abs(pos - half)
                    # 片方が5文字未満になる分割にはペナルティ
                    if left_len < 5 or right_len < 5:
                        score += 10
                    if score < best_score:
                        best_score = score
                        best_pos = pos
            if best_pos:
                final.append(seg[:best_pos])
                final.append(seg[best_pos:])
            else:
                # 助詞がない場合はMeCab単語境界で分割
                word_boundaries = _find_word_boundaries(seg, tagger)
                best_wb = None
                best_wb_score = float("inf")
                for wb in word_boundaries:
                    if wb >= MIN_CHARS and len(seg) - wb >= MIN_CHARS:
                        sc = abs(wb - half)
                        if sc < best_wb_score:
                            best_wb_score = sc
                            best_wb = wb
                if best_wb:
                    final.append(seg[:best_wb])
                    final.append(seg[best_wb:])
                else:
                    final.append(seg)

    # Step 5: 短すぎる区間（3文字未満）を前の区間に結合
    merged = []
    for seg in final:
        if merged and len(seg) < MIN_CHARS:
            merged[-1] = merged[-1] + seg
        else:
            merged.append(seg)

    print(f"  → {len(merged)}区間に分割")
    for i, s in enumerate(merged):
        print(f"    [{i+1}] ({len(s)}字) {s}")
    return merged


# ============================================================
# STEP 3：タイムスタンプ計算
# ============================================================

def calculate_timestamps(sentences, total_duration, durations=None):
    """各文の開始・終了時間を算出。durationsが渡された場合は実測値を使用、Noneの場合は文字数比率で算出"""
    print("[STEP 3] タイムスタンプ計算中...")
    timestamps = []
    current_time = 0.0

    if durations is not None:
        for i, sentence in enumerate(sentences):
            duration = durations[i]
            start = current_time
            end = current_time + duration
            telop_start = max(0, start - config.TELOP_PRE_ROLL)
            timestamps.append({
                "index": i,
                "text": sentence,
                "start": round(start, 3),
                "end": round(end, 3),
                "duration": round(duration, 3),
                "telop_start": round(telop_start, 3)
            })
            current_time = end
            print(f"  [{i+1}] {start:.2f}s - {end:.2f}s ({duration:.2f}s): {sentence[:20]}...")
    else:
        total_chars = sum(len(s) for s in sentences)
        for i, sentence in enumerate(sentences):
            char_ratio = len(sentence) / total_chars
            duration = total_duration * char_ratio
            start = current_time
            end = current_time + duration
            # テロップは音声より TELOP_PRE_ROLL 秒前に表示開始
            telop_start = max(0, start - config.TELOP_PRE_ROLL)
            timestamps.append({
                "index": i,
                "text": sentence,
                "start": round(start, 3),
                "end": round(end, 3),
                "duration": round(duration, 3),
                "telop_start": round(telop_start, 3)
            })
            current_time = end
            print(f"  [{i+1}] {start:.2f}s - {end:.2f}s ({duration:.2f}s): {sentence[:20]}...")

    return timestamps


# ============================================================
# STEP 4：素材動画をランダム選択
# ============================================================

def select_footage(timestamps, location=None):
    """素材動画をランダム選択（各クリップに動画ファイルと開始位置をセットで返す）"""
    print("[STEP 4] 素材動画を選択中...")
    footage_dir = config.FOOTAGE_DIR

    if not os.path.exists(footage_dir):
        print(f"  ✗ 素材動画フォルダが見つかりません: {footage_dir}")
        sys.exit(1)

    # 動画ファイルを検索（.mov, .mp4, .MOV, .MP4）
    patterns = ["*.mov", "*.mp4", "*.MOV", "*.MP4"]
    videos = []
    for pattern in patterns:
        videos.extend(glob.glob(os.path.join(footage_dir, pattern)))
    videos = list(set(videos))  # 重複除去

    if not videos:
        print(f"  ✗ 素材動画が見つかりません: {footage_dir}")
        sys.exit(1)

    print(f"  → {len(videos)}本の素材動画を検出")

    # footage_history.json の読み込み（使用回数ベースの優先制御）
    history_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "footage_history.json")
    if os.path.exists(history_path):
        with open(history_path, "r", encoding="utf-8") as f:
            history = json.load(f)
    else:
        history = {"counts": {}, "episodes": {}}
    counts = history.get("counts", {})
    # 全動画が均等に使い切られていたらカウントリセット
    all_counts = [counts.get(os.path.basename(v), 0) for v in videos]
    if all_counts and len(set(all_counts)) == 1 and all_counts[0] > 0:
        print("  → 全素材の使用回数が均等になったためカウントをリセットします")
        counts = {}

    # 各動画の長さをキャッシュ
    durations = {}
    for v in videos:
        durations[v] = get_audio_duration(v)

    # 動画ごとの使用済み区間リスト
    used_intervals = {v: [] for v in videos}

    selected = []
    # 1エピソード内での同一素材の使用回数を追跡（偏り防止）
    ep_usage = {v: 0 for v in videos}
    MAX_PER_EP = 3  # 1エピソード内での同一素材の使用上限

    for i, ts in enumerate(timestamps):
        clip_duration = ts["duration"]
        # 使用回数でグループ分けし、最少グループから順に試す
        from collections import defaultdict
        count_groups = defaultdict(list)
        for v in videos:
            c = counts.get(os.path.basename(v), 0)
            count_groups[c].append(v)

        chosen_video = None
        chosen_ss = None
        for count_val in sorted(count_groups.keys()):
            group = count_groups[count_val]
            random.shuffle(group)
            # エピソード内使用上限に達していない素材を優先
            group_sorted = sorted(group, key=lambda v: (0 if ep_usage[v] < MAX_PER_EP else 1, random.random()))
            for video in group_sorted:
                if ep_usage[video] >= MAX_PER_EP:
                    continue
                vid_dur = durations[video]
                if vid_dur <= clip_duration:
                    continue
                max_start = vid_dur - clip_duration
                for _ in range(20):
                    ss = random.uniform(0, max_start)
                    overlap = False
                    for (used_start, used_dur) in used_intervals[video]:
                        if ss < used_start + used_dur and ss + clip_duration > used_start:
                            overlap = True
                            break
                    if not overlap:
                        chosen_video = video
                        chosen_ss = ss
                        break
                if chosen_video:
                    break
            if chosen_video:
                break

        # 上限付きで見つからなければ上限を無視してフォールバック
        if chosen_video is None:
            candidates = sorted(videos, key=lambda v: (counts.get(os.path.basename(v), 0), random.random()))
            for video in candidates:
                vid_dur = durations[video]
                if vid_dur <= clip_duration:
                    continue
                max_start = vid_dur - clip_duration
                for _ in range(20):
                    ss = random.uniform(0, max_start)
                    overlap = False
                    for (used_start, used_dur) in used_intervals[video]:
                        if ss < used_start + used_dur and ss + clip_duration > used_start:
                            overlap = True
                            break
                    if not overlap:
                        chosen_video = video
                        chosen_ss = ss
                        break
                if chosen_video:
                    break

        if chosen_video is None:
            chosen_video = random.choice(videos)
            chosen_ss = 0.0

        used_intervals[chosen_video].append((chosen_ss, clip_duration))
        ep_usage[chosen_video] = ep_usage.get(chosen_video, 0) + 1
        selected.append((chosen_video, chosen_ss))
        print(f"  [{i+1}] {os.path.basename(chosen_video)} (ss={chosen_ss:.2f}s)")

    # footage_history.json に使用情報を保存
    episode_key = str(int(sys.argv[4]) if len(sys.argv) > 4 else 0)
    for video_path, _ in selected:
        basename = os.path.basename(video_path)
        counts[basename] = counts.get(basename, 0) + 1
    history["counts"] = counts
    history.setdefault("episodes", {})[episode_key] = [os.path.basename(v) for v, _ in selected]
    with open(history_path, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    print(f"  → footage_history.json を更新しました ({history_path})")

    return selected


# ============================================================
# STEP 5：テロップ画像生成（意味の切れ目で改行）
# ============================================================

def create_telop_image(text, output_path, width=None, height=None):
    """FFmpegのdrawtextでテロップ画像を生成"""
    if width is None:
        width = config.RESOLUTION_W
    if height is None:
        height = config.RESOLUTION_H

    # 意味の切れ目で改行（読点、接続詞の前、15文字ごと）
    formatted = format_telop_text(text)

    # FFmpegでテロップ画像を生成（黒背景透過PNG）
    # C1-C3: フォントサイズ（1行の最大文字数に応じて縮小）
    lines = formatted.split("\n")
    max_line_len = max(len(line) for line in lines)
    if max_line_len >= 12:
        fontsize = 56
    elif max_line_len >= 9:
        fontsize = 68
    else:
        fontsize = 80
    # macOSのヒラギノフォントを使用
    font_path = "/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc"
    if not os.path.exists(font_path):
        font_path = "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"
    if not os.path.exists(font_path):
        # フォールバック
        font_path = ""

    # エスケープ処理
    escaped_text = formatted.replace("%", "％").replace("'", "'\\''").replace(":", "\\:")

    if font_path:
        drawtext = (
            f"drawtext=fontfile='{font_path}'"
            f":text='{escaped_text}'"
            f":fontsize={fontsize}"
            f":fontcolor=white"
            f":borderw=5:bordercolor=black"
            f":text_align=C:x=(w-text_w)/2:y=(h-text_h)/2"
        )
    else:
        drawtext = (
            f"drawtext=text='{escaped_text}'"
            f":fontsize={fontsize}"
            f":fontcolor=white"
            f":borderw=5:bordercolor=black"
            f":text_align=C:x=(w-text_w)/2:y=(h-text_h)/2"
        )

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i",
        f"color=c=black@0.0:s={width}x{height}:d=1,format=rgba",
        "-vf", drawtext,
        "-frames:v", "1",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ⚠ テロップ生成警告: {result.stderr[:200]}")
        # フォールバック：フォント指定なしで再試行
        drawtext_fallback = (
            f"drawtext=text='{escaped_text}'"
            f":fontsize={fontsize}"
            f":fontcolor=white"
            f":borderw=5:bordercolor=black"
            f":text_align=C:x=(w-text_w)/2:y=(h-text_h)/2"
        )
        cmd_fallback = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i",
            f"color=c=black@0.0:s={width}x{height}:d=1,format=rgba",
            "-vf", drawtext_fallback,
            "-frames:v", "1",
            output_path
        ]
        subprocess.run(cmd_fallback, capture_output=True, text=True)


def format_telop_text(text):
    """テロップ用にテキストを意味の切れ目で改行（最大2行・句読点除去・MeCab v4）"""
    # B1: 句読点を除去
    text = text.replace("、", "").replace("。", "").replace("！", "").replace("？", "")
    text = strip_quote_marks(text)
    text = text.strip()

    # B2: 8文字以下なら1行表示
    if len(text) <= 8:
        return text

    # B3-B5: MeCabで助詞の直後を改行候補に（最大2行・1行11文字以内）
    tagger = MeCab.Tagger()
    positions = _find_particle_positions(text, tagger)

    best_pos = None
    best_score = float("inf")
    half = len(text) / 2

    for pos in positions:
        upper = pos
        lower = len(text) - pos
        if upper >= 4 and lower >= 4 and upper <= 11 and lower <= 11:
            score = abs(pos - half)
            if score < best_score:
                best_score = score
                best_pos = pos

    if best_pos:
        return text[:best_pos] + "\n" + text[best_pos:]

    # B6: 助詞で切れない場合はMeCab単語境界で改行
    word_boundaries = _find_word_boundaries(text, tagger)
    # 慣用パターン直前の「の」の直後も単語境界から除外
    _IDIOM_AFTER_NO = ("せい", "ため", "よう", "まま", "はず", "ほう", "うち", "もと", "かも")
    word_boundaries = [wb for wb in word_boundaries
                       if not (wb > 0 and text[wb - 1] == "の" and text[wb:].startswith(_IDIOM_AFTER_NO))]
    best_wb = None
    best_wb_score = float("inf")
    for wb in word_boundaries:
        upper = wb
        lower = len(text) - wb
        # 上下ともに4文字以上・11文字以内でないと改行しない
        if upper >= 4 and lower >= 4 and upper <= 11 and lower <= 11:
            sc = abs(wb - half)
            if sc < best_wb_score:
                best_wb_score = sc
                best_wb = wb
    if best_wb:
        return text[:best_wb] + "\n" + text[best_wb:]

    # B7: 適切な改行位置がない場合は1行表示のまま（フォントサイズ縮小で対応）
    return text


def generate_telop_images(timestamps, work_dir):
    """全文のテロップ画像を一括生成"""
    print("[STEP 5] テロップ画像生成中...")
    telop_paths = []
    for ts in timestamps:
        output_path = os.path.join(work_dir, f"telop_{ts['index']:03d}.png")
        create_telop_image(ts["text"], output_path)
        telop_paths.append(output_path)
        print(f"  [{ts['index']+1}] テロップ生成: {ts['text'][:20]}...")
    return telop_paths


def generate_telop_images_b(telop_lines, total_duration, timestamps, work_dir):
    """B方式：テロップ行からPNG生成＋表示区間(Ts,Te)算出"""
    print("[STEP 5] テロップ画像生成中（B方式）...")
    n = len(telop_lines)
    if n == 0:
        return [], []

    # CTA（最終行）の開始 = 最後のナレーション文の開始時刻
    last_narr_start = timestamps[-1]["start"] if timestamps else 0.0
    cta_end = total_duration + 1.0

    telop_intervals = []
    if n == 1:
        # テロップ1行のみ = 全尺表示
        telop_intervals.append((0.0, cta_end))
    else:
        # 非CTA行: [0, last_narr_start) を均等配分
        non_cta_duration = last_narr_start if last_narr_start > 0 else total_duration * 0.8
        seg = non_cta_duration / (n - 1)
        for i in range(n - 1):
            ts_start = i * seg
            ts_end = (i + 1) * seg
            telop_intervals.append((ts_start, ts_end))
        # CTA（最終行）: 最後のナレーション開始〜動画末尾+1秒保持
        telop_intervals.append((last_narr_start, cta_end))

    telop_paths = []
    for i, line in enumerate(telop_lines):
        output_path = os.path.join(work_dir, f"telop_b_{i:03d}.png")
        create_telop_image(line, output_path)
        t_s, t_e = telop_intervals[i]
        telop_paths.append(output_path)
        print(f"  [{i+1}/{n}] テロップ: {line[:20]}... ({t_s:.1f}s〜{t_e:.1f}s)")

    return telop_paths, telop_intervals


# ============================================================
# STEP 6：1クリップずつ生成（FFmpeg）
# ============================================================

def generate_clip(footage_path, telop_path, duration, output_path, ss=0.0):
    """素材動画＋テロップを合成して1クリップ生成"""

    # まず素材動画の長さを確認
    footage_duration = get_audio_duration(footage_path)

    # 素材が短い場合はループ
    loop_flag = []
    if footage_duration < duration:
        loop_flag = ["-stream_loop", "-1"]

    ss_flag = ["-ss", str(ss)] if ss > 0 else []

    if telop_path is not None:
        cmd = [
            "ffmpeg", "-y",
            *loop_flag,
            *ss_flag,
            "-i", footage_path,
            "-i", telop_path,
            "-t", str(duration),
            "-filter_complex",
            f"[0:v]scale={config.RESOLUTION_W}:{config.RESOLUTION_H}:force_original_aspect_ratio=increase,"
            f"crop={config.RESOLUTION_W}:{config.RESOLUTION_H},"
            f"fps={config.FPS}[bg];"
            f"[1:v]format=rgba[ovr];"
            f"[bg][ovr]overlay=0:0[out]",
            "-map", "[out]",
            "-an",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            output_path
        ]
    else:
        # B方式: テロップなし（素材のscale/cropのみ）
        cmd = [
            "ffmpeg", "-y",
            *loop_flag,
            *ss_flag,
            "-i", footage_path,
            "-t", str(duration),
            "-vf",
            f"scale={config.RESOLUTION_W}:{config.RESOLUTION_H}:force_original_aspect_ratio=increase,"
            f"crop={config.RESOLUTION_W}:{config.RESOLUTION_H},"
            f"fps={config.FPS}",
            "-an",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "18",
            output_path
        ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ✗ クリップ生成失敗: {result.stderr[:300]}")
        return False
    return True


def generate_all_clips(timestamps, footage_list, telop_paths, work_dir):
    """全クリップを生成"""
    print("[STEP 6] クリップ生成中...")
    clip_paths = []
    for i, ts in enumerate(timestamps):
        clip_path = os.path.join(work_dir, f"clip_{i:03d}.mp4")
        footage_path, ss = footage_list[i]
        print(f"  [{i+1}/{len(timestamps)}] クリップ生成中... ({ts['duration']:.1f}秒)")
        telop_p = telop_paths[i] if telop_paths else None
        success = generate_clip(footage_path, telop_p, ts["duration"], clip_path, ss=ss)
        if success:
            clip_paths.append(clip_path)
        else:
            print(f"  ✗ クリップ {i+1} の生成に失敗。スキップします。")
    return clip_paths


# ============================================================
# STEP 7：全クリップ結合・音声・BGM合成
# ============================================================

def apply_telop_overlay(concat_video_path, telop_paths, telop_intervals, work_dir):
    """B方式: 連結済み動画にテロップPNGを時間区間オーバーレイ"""
    print("  \u2192 テロップ時間区間オーバーレイ中...")
    n_telop = len(telop_paths)
    concat_with_telop = os.path.join(work_dir, "concat_with_telop.mp4")

    # FFmpeg入力: concat_video + 各テロップPNG
    telop_inputs = []
    for tp in telop_paths:
        telop_inputs.extend(["-i", tp])

    # filter_complex構築
    fc_parts = []
    for i in range(n_telop):
        fc_parts.append(f"[{i+1}:v]format=rgba[t{i}]")
    prev_label = "0:v"
    for i in range(n_telop):
        t_s, t_e = telop_intervals[i]
        out_label = f"v{i}" if i < n_telop - 1 else "out"
        fc_parts.append(
            f"[{prev_label}][t{i}]overlay=0:0:enable='between(t,{t_s:.3f},{t_e:.3f})'[{out_label}]"
        )
        prev_label = out_label
    fc_str = ";".join(fc_parts)

    cmd_overlay = [
        "ffmpeg", "-y",
        "-i", concat_video_path,
        *telop_inputs,
        "-filter_complex", fc_str,
        "-map", "[out]",
        "-an",
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        concat_with_telop
    ]
    result = subprocess.run(cmd_overlay, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  \u2717 テロップオーバーレイ失敗: {result.stderr[:300]}")
        sys.exit(1)
    print(f"  \u2192 テロップオーバーレイ完了（{n_telop}行）")
    return concat_with_telop


def concat_and_merge(clip_paths, audio_path, output_path, work_dir, telop_paths=None, telop_intervals=None):
    """全クリップを結合し、音声とBGMを合成"""
    print("[STEP 7] 最終結合中...")

    # concat用のファイルリスト作成
    concat_list = os.path.join(work_dir, "concat_list.txt")
    with open(concat_list, "w") as f:
        for clip in clip_paths:
            f.write(f"file '{clip}'\n")

    # クリップを結合
    concat_video = os.path.join(work_dir, "concat_video.mp4")
    cmd_concat = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", concat_list,
        "-c", "copy",
        concat_video
    ]
    result = subprocess.run(cmd_concat, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ✗ 結合失敗: {result.stderr[:300]}")
        sys.exit(1)

    # concat_videoとtts_final.wavの尺を比較し、映像が短ければ最終クリップを延長して再concat
    concat_dur = get_audio_duration(concat_video)
    audio_dur = get_audio_duration(audio_path)
    if concat_dur < audio_dur:
        diff = audio_dur - concat_dur
        print(f"  → 映像({concat_dur:.3f}秒) < 音声({audio_dur:.3f}秒)、最終クリップを{diff:.3f}秒延長して再結合...")
        last_clip = clip_paths[-1]
        extended_last = os.path.join(work_dir, "clip_last_extended.mp4")
        cmd_extend = [
            "ffmpeg", "-y",
            "-i", last_clip,
            "-vf", f"tpad=stop_mode=clone:stop_duration={diff}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            extended_last
        ]
        result = subprocess.run(cmd_extend, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  ⚠ 最終クリップ延長失敗: {result.stderr[:200]}")
        else:
            extended_paths = clip_paths[:-1] + [extended_last]
            with open(concat_list, "w") as f:
                for clip in extended_paths:
                    f.write(f"file '{clip}'\n")
            result = subprocess.run(cmd_concat, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"  ✗ 再結合失敗: {result.stderr[:300]}")
                sys.exit(1)

    # B方式: テロップ時間区間オーバーレイ
    if telop_paths and telop_intervals:
        concat_video = apply_telop_overlay(concat_video, telop_paths, telop_intervals, work_dir)

    # 音声＋BGMを合成
    bgm_path = config.BGM_PATH
    bgm_volume = config.BGM_VOLUME_DB

    # HEVCエンコード（hevc_videotoolboxを試し、失敗したらlibx265）
    codec = config.CODEC
    codec_opts = ["-c:v", codec, "-q:v", "50"]

    # 最終合成コマンド
    cmd_final = [
        "ffmpeg", "-y",
        "-i", concat_video,
        "-i", audio_path,
        "-ss", "58", "-i", bgm_path,
        "-filter_complex",
        f"[1:a]aformat=sample_rates=44100:channel_layouts=stereo[voice];"
        f"[2:a]aformat=sample_rates=44100:channel_layouts=stereo,"
        f"volume={bgm_volume}dB[bgm];"
        f"[voice][bgm]amix=inputs=2:duration=first[aout]",
        "-map", "0:v",
        "-map", "[aout]",
        *codec_opts,
        "-t", str(config.MAX_DURATION_SEC),
        output_path
    ]
    result = subprocess.run(cmd_final, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ⚠ {codec}エンコード失敗、{config.CODEC_FALLBACK}で再試行...")
        codec_opts = ["-c:v", config.CODEC_FALLBACK, "-crf", str(config.CRF)]
        cmd_final[cmd_final.index("-c:v") + 1] = config.CODEC_FALLBACK
        # コマンド再構築
        cmd_final = [
            "ffmpeg", "-y",
            "-i", concat_video,
            "-i", audio_path,
            "-ss", "58", "-i", bgm_path,
            "-filter_complex",
            f"[1:a]aformat=sample_rates=44100:channel_layouts=stereo[voice];"
            f"[2:a]aformat=sample_rates=44100:channel_layouts=stereo,"
            f"volume={bgm_volume}dB[bgm];"
            f"[voice][bgm]amix=inputs=2:duration=first[aout]",
            "-map", "0:v",
            "-map", "[aout]",
            "-c:v", config.CODEC_FALLBACK,
            "-crf", str(config.CRF),
            "-t", str(config.MAX_DURATION_SEC),
            output_path
        ]
        result = subprocess.run(cmd_final, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"  ✗ 最終合成失敗: {result.stderr[:300]}")
            sys.exit(1)

    print(f"  → 完成動画: {output_path}")


# ============================================================
# サムネイル生成
# ============================================================

def generate_thumbnail(thumbnail_text, output_path, footage_path):
    """サムネイル画像を生成（背景動画フレーム + Pillowテキスト描画）"""
    print("[THUMBNAIL] サムネイル画像生成中...")

    # 句読点除去・改行処理（現行ロジック維持）
    clean = thumbnail_text.replace("\\n", "\n").replace("。", "").replace("、", "\n").replace("！", "").replace("？", "").replace("　", "\n").replace(" ", "\n")

    lines = [seg for seg in clean.split("\n") if seg]

    print("  テキスト:")
    for line in lines:
        print(f"    {line}")

    # 背景フレームをキャプチャ（動画の20%〜80%からランダム秒数）
    tmp_bg = os.path.join(tempfile.gettempdir(), "thumbnail_bg_tmp.png")
    # 動画の長さを取得してランダムな秒数を決定
    _dur_result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", footage_path],
        capture_output=True, text=True
    )
    try:
        _duration = float(_dur_result.stdout.strip())
        _ss = round(random.uniform(_duration * 0.2, _duration * 0.8), 1)
    except (ValueError, ZeroDivisionError):
        _ss = 0.5  # フォールバック
    print(f"  → フレーム抽出: {os.path.basename(footage_path)} の {_ss}秒目")
    cmd_cap = [
        "ffmpeg", "-y",
        "-i", footage_path,
        "-ss", str(_ss),
        "-frames:v", "1",
        tmp_bg,
    ]
    result = subprocess.run(cmd_cap, capture_output=True, text=True)
    if result.returncode == 0 and os.path.exists(tmp_bg):
        bg = Image.open(tmp_bg).convert("RGB")
        bg = bg.resize((config.RESOLUTION_W, config.RESOLUTION_H), Image.LANCZOS)
    else:
        print(f"  ⚠ フレームキャプチャ失敗（黒背景にフォールバック）: {result.stderr[:200]}")
        bg = Image.new("RGB", (config.RESOLUTION_W, config.RESOLUTION_H), (0, 0, 0))

    draw = ImageDraw.Draw(bg)

    # フォントパス
    font_path = "/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc"
    if not os.path.exists(font_path):
        font_path = "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"

    # 画面幅 80% に全行が収まるようフォントサイズを自動調整
    max_width = int(config.RESOLUTION_W * 0.8)
    fontsize = 120
    font = None
    while fontsize >= 40:
        if os.path.exists(font_path):
            font = ImageFont.truetype(font_path, fontsize)
        else:
            font = ImageFont.load_default()
        max_line_w = max(
            draw.textbbox((0, 0), line, font=font)[2] - draw.textbbox((0, 0), line, font=font)[0]
            for line in lines
        )
        if max_line_w <= max_width:
            break
        fontsize -= 5

    # 行ごとの高さを計測して縦中央の開始 y を決定
    line_spacing = int(fontsize * 0.2)
    line_heights = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        line_heights.append(bbox[3] - bbox[1])
    total_h = sum(line_heights) + line_spacing * (len(lines) - 1)
    y = (config.RESOLUTION_H - total_h) // 2

    # 各行を横中央・縁取り付きで描画
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        lw = bbox[2] - bbox[0]
        x = (config.RESOLUTION_W - lw) // 2
        draw.text((x, y), line, font=font, fill=(255, 255, 255),
                  stroke_width=6, stroke_fill=(0, 0, 0))
        y += line_heights[i] + line_spacing

    bg.save(output_path)

    if os.path.exists(tmp_bg):
        os.remove(tmp_bg)

    print(f"  → サムネイル生成完了: {output_path}")
    return True


# ============================================================
# メイン処理
# ============================================================



def parse_script_blocks(raw_text):
    """【ナレーション】【テロップ】2ブロックを分離。旧形式（単一テキスト）にも対応"""
    if "【ナレーション】" in raw_text and "【テロップ】" in raw_text:
        parts = raw_text.split("【テロップ】")
        narration_block = parts[0].split("【ナレーション】", 1)[1].strip()
        telop_block = parts[1].strip()
        telop_lines = [line.strip() for line in telop_block.split("\n") if line.strip()]
        return narration_block, telop_lines
    else:
        return raw_text.strip(), []


def main():
    if len(sys.argv) < 2:
        print("使い方: python3 pipeline_final.py '原稿テキスト' ['ロケーション名'] ['サムネテキスト']")
        sys.exit(1)

    text = sys.argv[1]
    text = fix_notation(text)

    # B方式：【ナレーション】【テロップ】2ブロック分離
    narration_text, telop_lines = parse_script_blocks(text)

    if telop_lines:
        # 新形式（B方式）：ナレーション文字数チェック
        char_count = len(narration_text)
        if char_count < 40 or char_count > 80:
            print(f"エラー：ナレーションが{char_count}字です。55〜65字目安（許容40〜80字）。")
            sys.exit(1)
        print(f"  B方式: ナレーション {len(narration_text)}字 / テロップ {len(telop_lines)}行")
        text = narration_text
    else:
        # 旧形式：従来の文字数チェック
        char_count = len(text)
        if char_count < 210 or char_count > 245:
            print(f"エラー：台本の文字数が{char_count}字です。210〜245字の範囲に収めてください。")
            sys.exit(1)
    location = sys.argv[2] if len(sys.argv) > 2 else "default"
    thumbnail_text = sys.argv[3] if len(sys.argv) > 3 else None
    thumbnail_text = strip_quote_marks(thumbnail_text)
    episode_num = int(sys.argv[4]) if len(sys.argv) > 4 else 1

    print("=" * 60)
    print("Instagram リール動画自動生成パイプライン")
    print("=" * 60)
    print(f"原稿: {text[:50]}...")
    print(f"ロケーション: {location}")
    print(f"出力先: {config.OUTPUT_DIR}")
    print("=" * 60)

    # 出力ディレクトリ確認
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)

    # 作業用一時ディレクトリ
    work_dir = tempfile.mkdtemp(prefix="reel_pipeline_")
    print(f"作業ディレクトリ: {work_dir}")

    try:
        # STEP 2: 文章分割（TTS生成前に実施）
        sentences = split_sentences(text)

        # STEP 1: 文ごとにTTS → 倍速 → 無音カット → 結合
        sentence_durations, final_audio = generate_tts_per_sentence(sentences, work_dir)

        total_duration = get_audio_duration(final_audio)
        print(f"  → 最終音声: {total_duration:.2f}秒")

        if total_duration > config.MAX_DURATION_SEC:
            print(f"  ⚠ 音声が{config.MAX_DURATION_SEC}秒を超えています（{total_duration:.1f}秒）")

        # STEP 3: タイムスタンプ計算（実測durationを使用）
        timestamps = calculate_timestamps(sentences, total_duration, durations=sentence_durations)

        # STEP 4: 素材動画選択
        footage_list = select_footage(timestamps, location)

        # STEP 5: テロップ画像生成
        if telop_lines:
            telop_paths, telop_intervals = generate_telop_images_b(
                telop_lines, total_duration, timestamps, work_dir)
        else:
            telop_paths = generate_telop_images(timestamps, work_dir)
            telop_intervals = []

        # STEP 6: クリップ生成
        if telop_lines:
            # B方式: テロップなしでクリップ生成（後でオーバーレイ）
            clip_paths = generate_all_clips(timestamps, footage_list, None, work_dir)
        else:
            clip_paths = generate_all_clips(timestamps, footage_list, telop_paths, work_dir)

        if not clip_paths:
            print("✗ クリップが1つも生成されませんでした")
            sys.exit(1)

        # STEP 7: 最終結合
        output_path = os.path.join(config.OUTPUT_DIR, config.OUTPUT_FILENAME)
        if telop_lines:
            concat_and_merge(clip_paths, final_audio, output_path, work_dir,
                           telop_paths=telop_paths, telop_intervals=telop_intervals)
        else:
            concat_and_merge(clip_paths, final_audio, output_path, work_dir)

        # THUMBNAIL: サムネイル生成
        if thumbnail_text:
            thumbnail_path = os.path.join(config.OUTPUT_DIR, "thumbnail.png")
            walking_videos = sorted(glob.glob(os.path.join(config.FOOTAGE_DIR, "歩き動画*.mov")))
            walking_videos = [v for v in walking_videos if os.path.basename(v) != "歩き動画8.mov"]  # サムネは1〜7のみ
            if walking_videos:
                _th_history_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "footage_history.json")
                if os.path.exists(_th_history_path):
                    with open(_th_history_path, "r", encoding="utf-8") as _f:
                        _th_history = json.load(_f)
                else:
                    _th_history = {"counts": {}, "episodes": {}}
                _th_counts = _th_history.get("thumbnail_counts", {})
                _th_all_counts = [_th_counts.get(os.path.basename(v), 0) for v in walking_videos]
                if len(set(_th_all_counts)) == 1 and _th_all_counts[0] > 0:
                    print("  → サムネ素材の使用回数が均等になったためカウントをリセットします")
                    _th_counts = {}
                thumbnail_footage = min(walking_videos, key=lambda v: (_th_counts.get(os.path.basename(v), 0), random.random()))
                _th_counts[os.path.basename(thumbnail_footage)] = _th_counts.get(os.path.basename(thumbnail_footage), 0) + 1
                _th_history["thumbnail_counts"] = _th_counts
                with open(_th_history_path, "w", encoding="utf-8") as _f:
                    json.dump(_th_history, _f, ensure_ascii=False, indent=2)
                print(f"  → サムネ素材: {os.path.basename(thumbnail_footage)}")
            else:
                thumbnail_footage = footage_list[0][0]
            generate_thumbnail(thumbnail_text, thumbnail_path, thumbnail_footage)

        print()
        print("=" * 60)
        print("✅ 完成！")
        print(f"出力先: {output_path}")
        if thumbnail_text:
            print(f"サムネイル: {os.path.join(config.OUTPUT_DIR, 'thumbnail.png')}")
        print("=" * 60)

        # Finderで出力フォルダを開く
        subprocess.run(["open", config.OUTPUT_DIR])

    except KeyboardInterrupt:
        print("\n中断されました")
        sys.exit(1)
    finally:
        # 一時ファイルは残す（デバッグ用）
        print(f"作業ファイル: {work_dir}")


if __name__ == "__main__":
    main()
