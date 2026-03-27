# How to Train NONE Class at the Conference (via MacBook)

## Overview

If the model starts producing false positives at the conference venue (e.g. misidentifying background objects as placards), you can retrain the `none` class on-site using your MacBook. This adds new images of the actual conference environment to the training data so the model learns what "no placard present" looks like in that specific setting.

---

## Step 1 — Record Video

Use QuickTime to record a 1-2 minute video of the camera view with no placard present — just the booth background, lighting, and whatever is in the scene.

Save the video to:
```
~/Documents/SummitTrainDemo/placards-lab/videos/
```

---

## Step 2 — Extract Frames

```bash
cd ~/Documents/SummitTrainDemo/placards-lab
podman run --rm -v "$PWD:/work" -w /work docker.io/jrottenberg/ffmpeg:6.0-alpine \
  -i videos/none4_room3.mov -vf fps=5 frames/none4_room3_%05d.jpg
```

This extracts one frame every 5 seconds from the video and saves them as JPEGs in the `frames/` folder. Adjust the filename to match your video.

---

## Step 3 — Add Frames to the NONE Training Folder

```bash
mv frames/none4_room3_*.jpg dataset/train/none/
```

---

## Step 4 — Check Dataset Counts Before Validation Split

Run this to confirm how many images are in each class before splitting. After the validation split you should see about 15% of images move to `val/` — this can be tricky to spot since there are already existing files, so note the before and after counts.

```bash
echo "=== TRAIN ===" && \
echo "none:    $(ls dataset/train/none/ | wc -l)" && \
echo "slow:    $(ls dataset/train/slow/ | wc -l)" && \
echo "start:   $(ls dataset/train/start/ | wc -l)" && \
echo "stop:    $(ls dataset/train/stop/ | wc -l)" && \
echo "reverse: $(ls dataset/train/reverse/ | wc -l)" && \
echo "" && \
echo "=== VAL ===" && \
echo "none:    $(ls dataset/val/none/ | wc -l)" && \
echo "slow:    $(ls dataset/val/slow/ | wc -l)" && \
echo "start:   $(ls dataset/val/start/ | wc -l)" && \
echo "stop:    $(ls dataset/val/stop/ | wc -l)" && \
echo "reverse: $(ls dataset/val/reverse/ | wc -l)"
```

> **Why validation split?** The training process splits images into two groups. The model only ever learns from the training images — validation images are kept separate and the model never sees them during training. At the end of each epoch the model is tested against validation images, and because it has never trained on them, the accuracy score reflects how well it will actually perform on new images in the real world rather than just how well it memorized the training data.

---

## Step 5 — Create Validation Split for New NONE Frames

This moves every 7th new frame into the validation set (~15%):

```bash
ls dataset/train/none/none4_room3_*.jpg | awk 'NR % 7 == 0 {print}' | xargs -I{} mv "{}" dataset/val/none/
```

---

## Step 6 — Confirm the Split

Re-run the count command from Step 4 to confirm the split looks correct.

---

## Step 7 — Retrain

```bash
cd ~/Documents/SummitTrainDemo/placards-lab
source .venv/bin/activate
python scripts/train.py \
  --data ./dataset \
  --epochs 10 \
  --batch-size 16 \
  --out-pt out/placards.pt \
  --out-labels out/labels.json \
  --use-mps
```

**Parameter explanations:**

- `--data ./dataset` — where to find training and validation images, expecting `dataset/train/` and `dataset/val/` subfolders
- `--epochs 10` — run 10 complete passes through all training images
- `--batch-size 16` — process 16 images at a time, which is faster and produces more stable weight updates
- `--out-pt out/placards.pt` — where to save the trained model weights in PyTorch format
- `--out-labels out/labels.json` — where to save the class names (none, reverse, slow, start, stop) so the inference container knows which index maps to which command
- `--use-mps` — use the Mac's Apple Silicon GPU (Metal Performance Shaders) to speed up training instead of CPU only

---

## Step 8 — Export to ONNX

```bash
python scripts/export_onnx.py \
  --weights out/placards.pt \
  --out out/placards.onnx \
  --labels out/labels.json
```

**What this does:** Converts the trained model from PyTorch format into ONNX format so it can run on the MS-01 without needing PyTorch installed.

- `--weights out/placards.pt` — the trained PyTorch model file produced by `train.py`
- `--out out/placards.onnx` — where to save the ONNX model — this is what gets copied into the inference container
- `--labels out/labels.json` — the class names file, copied alongside the ONNX model so the inference container knows what none/reverse/slow/start/stop map to

> PyTorch is a full machine learning framework needed for training but it's large and slow for inference. ONNX Runtime (what the inference container uses) is a lightweight runtime optimized purely for running a model fast — it's what makes ~30fps inference possible on the MS-01 CPU without a GPU.

---

## Step 9 — Sanity Check

Run this quick check to confirm the exported ONNX file is valid before bothering with a container rebuild:

```bash
python - <<'PY'
import onnxruntime as ort
sess = ort.InferenceSession("out/placards.onnx", providers=["CPUExecutionProvider"])
print("OK loaded ONNX")
print("Input:", sess.get_inputs()[0].name, sess.get_inputs()[0].shape)
PY
```

**Expected output:**
```
OK loaded ONNX
Input: input ['batch', 3, 224, 224]
```

**What this confirms:**
- **Model loaded successfully** — no corruption, valid ONNX graph
- **Input name:** `input` — matches what `inference_web.py` expects
- **Shape:** `['batch', 3, 224, 224]` — dynamic batch size, 3 color channels (RGB), 224×224 pixels — exactly right for MobileNetV3

If anything is wrong with the export this script will throw an exception before you waste time on a container rebuild.

---

## Step 10 — Rebuild the Inference Container

> ⚠️ **Note:** At the conference you won't have access to `rhel-util-01.lab.local` for building. You'll need an alternative build method — either a Fedora laptop (native x86_64) or the OCP cluster (OpenShift Builds). Building on the MacBook requires `--platform linux/amd64` via QEMU which is slow.

Copy the new model files into the build context and rebuild:

```bash
cp out/placards.onnx out/labels.json \
  ~/path/to/inference-web-container/models/

cd ~/path/to/inference-web-container
./build.sh
```

Then update the fleet spec in RHEM with the new image tag and let the agent roll it out to the device.

